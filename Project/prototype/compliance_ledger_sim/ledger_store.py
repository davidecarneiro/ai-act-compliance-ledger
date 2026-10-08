"""Persistence of the evidence ledger (WP1 of the article plan).

Two stores share one interface, selected by the file suffix:

* ``JsonArrayStore`` (``*.json``): the dissertation's store. The ledger is one
  JSON array, rewritten in full on every event (temporary file, fsync,
  ``os.replace``). Kept so the published ledgers, the tests and the scripts
  that name a ``.json`` file behave exactly as before. Its cost grows with the
  size of the ledger, which is what the dissertation's latency series showed.
* ``AppendOnlyStore`` (``*.jsonl``): one record per line, appended with a
  single write and one fsync. The chain head (sequence number, last
  ``chain_hash`` and the byte offset after the last acknowledged record) lives
  in a small side file replaced atomically, so appending never reads the
  ledger. Verification and queries stream the file.

Crash consistency of the append-only store. A record line is fsynced before
the head is replaced, so the head is never ahead of the data. On the next
append (under the lock) the store compares the file with the head:

* file size equal to the head offset: consistent;
* longer: the bytes after the offset are records written but not yet
  acknowledged in the head, or a torn last line. Complete lines that link to
  the head and recompute to their ``record_hash`` and ``chain_hash`` are rolled
  forward; a final line without a newline is a torn write and is cut off; a
  complete line that does not link is corruption and is refused;
* shorter: records the head acknowledged are gone. That is truncation, not a
  crash, and the store refuses to write (fail closed).

A missing head file is rebuilt by scanning the file once. Neither store
detects a rewrite of the whole file by someone holding the issuer key: that
needs an anchor kept elsewhere (WP3, arm B+, and WP7).
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

from canonical import record_body_bytes

GENESIS_HASH = "0" * 64


class LedgerCorrupted(RuntimeError):
    """The ledger file and its head disagree in a way a crash cannot explain."""


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _links(record: dict, parent_chain_hash: str) -> bool:
    """Does the record link to the parent and recompute to its own hashes?

    The signature is not checked here: recovery only decides whether a line
    is a complete record of this chain. ``verify_chain`` checks signatures."""
    if record.get("parent_hash") != parent_chain_hash:
        return False
    try:
        record_hash = _sha256_hex(record_body_bytes(record))
    except Exception:  # unsupported version or no canonical form
        return False
    if record_hash != record.get("record_hash"):
        return False
    expected = _sha256_hex((parent_chain_hash + record_hash).encode("utf-8"))
    return expected == record.get("chain_hash")


class _Store:
    """Interface shared by both stores."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    @contextlib.contextmanager
    def _lock(self):
        """Serialise writers across local processes (advisory fcntl lock).

        It does not coordinate stores across hosts or protect writes that
        bypass the lock."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "a+") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    # Subclasses implement these.
    def ensure(self) -> None: ...
    def reset(self) -> None: ...
    def iter_records(self) -> Iterator[dict]: ...
    def append_with(self, build: Callable[[int, str], dict]) -> dict: ...

    def read_all(self) -> List[dict]:
        return list(self.iter_records())


class JsonArrayStore(_Store):
    """The dissertation's whole-file JSON array (thesis-v1.0 behaviour)."""

    def ensure(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def reset(self) -> None:
        self.path.write_text("[]", encoding="utf-8")

    def iter_records(self) -> Iterator[dict]:
        return iter(json.loads(self.path.read_text(encoding="utf-8")))

    def _write(self, ledger: List[dict]) -> None:
        # Sibling temporary file renamed over the target: a reader sees either
        # the old file or the new one, never a truncated one.
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def append_with(self, build: Callable[[int, str], dict]) -> dict:
        with self._lock():
            ledger = json.loads(self.path.read_text(encoding="utf-8"))
            parent = ledger[-1]["chain_hash"] if ledger else GENESIS_HASH
            record = build(len(ledger), parent)
            ledger.append(record)
            self._write(ledger)
            return record


class AppendOnlyStore(_Store):
    """JSON Lines, appended in place, with an atomically replaced head file."""

    def __init__(self, path: Path, fsync: bool = True) -> None:
        super().__init__(path)
        self.head_path = self.path.with_name(self.path.name + ".head")
        # fsync of each record line. Turning it off trades durability on power
        # loss for latency; it is a protocol parameter of the WP3 benchmark,
        # never a default.
        self.fsync = fsync

    # -- head ------------------------------------------------------------

    def _read_head(self) -> Optional[dict]:
        try:
            head = json.loads(self.head_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise LedgerCorrupted(f"unreadable head file {self.head_path}: {exc}")
        if not (
            isinstance(head, dict)
            and isinstance(head.get("seq"), int)
            and isinstance(head.get("offset"), int)
            and isinstance(head.get("chain_hash"), str)
        ):
            raise LedgerCorrupted(f"malformed head file {self.head_path}")
        return head

    def _write_head(self, seq: int, chain_hash: str, offset: int) -> None:
        # Replaced atomically but not fsynced: losing a head update only
        # leaves it behind the data, which recovery rolls forward.
        tmp = self.head_path.with_name(self.head_path.name + ".tmp")
        tmp.write_text(
            json.dumps({"seq": seq, "chain_hash": chain_hash, "offset": offset}),
            encoding="utf-8",
        )
        os.replace(tmp, self.head_path)

    def _scan(self, start_offset: int, seq: int, chain_hash: str,
              repair: bool) -> Tuple[int, str, int]:
        """Walk the lines after start_offset, linking each to the chain.

        Returns the head after the last complete, linking record. A torn final
        line is cut off when repair is set; any other inconsistency raises."""
        offset = start_offset
        with open(self.path, "rb") as fh:
            fh.seek(start_offset)
            for line in fh:
                if not line.endswith(b"\n"):
                    # Torn write: the final line never completed.
                    if repair:
                        os.truncate(self.path, offset)
                        return seq, chain_hash, offset
                    raise LedgerCorrupted(f"incomplete last line at byte {offset}")
                try:
                    record = json.loads(line)
                except ValueError:
                    raise LedgerCorrupted(f"unparsable record at byte {offset}")
                if not isinstance(record, dict) or not _links(record, chain_hash):
                    raise LedgerCorrupted(
                        f"record at byte {offset} does not link to the chain"
                    )
                seq += 1
                chain_hash = record["chain_hash"]
                offset += len(line)
        return seq, chain_hash, offset

    def _recover(self) -> Tuple[int, str, int]:
        """Bring the head in line with the file (called under the lock)."""
        size = self.path.stat().st_size
        head = self._read_head()
        if head is None:
            # No head: rebuild it from the whole file.
            seq, chain_hash, offset = self._scan(0, 0, GENESIS_HASH, repair=True)
        elif size < head["offset"]:
            raise LedgerCorrupted(
                f"{self.path} has {size} bytes but its head acknowledges "
                f"{head['offset']}: records are missing from the end"
            )
        elif size == head["offset"]:
            return head["seq"], head["chain_hash"], head["offset"]
        else:
            seq, chain_hash, offset = self._scan(
                head["offset"], head["seq"], head["chain_hash"], repair=True
            )
        self._write_head(seq, chain_hash, offset)
        return seq, chain_hash, offset

    # -- interface -------------------------------------------------------

    def ensure(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with self._lock():
                if not self.path.exists():
                    self.path.touch()
                    self._write_head(0, GENESIS_HASH, 0)

    def reset(self) -> None:
        with self._lock():
            self.path.write_bytes(b"")
            self._write_head(0, GENESIS_HASH, 0)

    def head(self) -> Tuple[int, str]:
        """(sequence number, chain_hash) of the last acknowledged record."""
        with self._lock():
            seq, chain_hash, _ = self._recover()
            return seq, chain_hash

    def iter_records(self) -> Iterator[dict]:
        with open(self.path, "rb") as fh:
            for line in fh:
                if line.endswith(b"\n"):
                    yield json.loads(line)
                # A torn final line is not a record; the next append removes it.

    def append_with(self, build: Callable[[int, str], dict]) -> dict:
        with self._lock():
            seq, parent, offset = self._recover()
            record = build(seq, parent)
            line = (
                json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n"
            ).encode("ascii")
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND)
            try:
                written = os.write(fd, line)
                if written != len(line):
                    raise OSError(f"short write ({written} of {len(line)} bytes)")
                if self.fsync:
                    os.fsync(fd)
            finally:
                os.close(fd)
            self._write_head(seq + 1, record["chain_hash"], offset + len(line))
            return record


def open_store(path: Path, **options) -> _Store:
    """The store for a ledger path: ``.jsonl`` is append-only, anything else
    is the dissertation's JSON array."""
    path = Path(path)
    if path.suffix == ".jsonl":
        return AppendOnlyStore(path, **options)
    return JsonArrayStore(path)


def read_ledger(path: Path) -> List[dict]:
    """All records of a ledger file in either format."""
    return open_store(path).read_all()


def main(argv: List[str]) -> int:
    """``python3 ledger_store.py to-json <in.jsonl> <out.json>``

    Writes a JSON array copy of a ledger, for tools that read the
    dissertation's format (the Ledger Explorer page, for instance)."""
    if len(argv) != 3 or argv[0] != "to-json":
        print("usage: python3 ledger_store.py to-json <in.jsonl> <out.json>")
        return 2
    records = read_ledger(Path(argv[1]))
    Path(argv[2]).write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"{len(records)} records written to {argv[2]}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
