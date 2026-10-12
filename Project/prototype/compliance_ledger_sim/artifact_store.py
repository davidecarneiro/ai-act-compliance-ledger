"""Content-addressed store for artefacts kept off the ledger (WP2).

Artefacts (a trained model, a dataset, a report) never enter an evidence
record. The pipeline puts the file in this store, which names it by the
SHA-256 of its bytes, and the event it sends to the Compliance Policy Engine
carries the digest (``artifact_sha256``) and the reference (``off_chain_ref``).
The record commits to both, so a verifier holding the store can recompute
the digest from the reference and compare it with the signed value.

References have the form ``store/sha256/<64 hex digits>`` and resolve to
``<root>/sha256/<digest>``. The store is append-only by construction: a file
is written once under its digest and never replaced.

The engine does not read files: it checks the format of the digest and that
the reference names the same digest, so its decision depends on the event
alone and can be re-executed from the record (``reexecution.py``).
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

REF_PREFIX = "store/sha256/"
_HEX64 = re.compile(r"[0-9a-f]{64}")


def is_sha256_hex(value) -> bool:
    """A lowercase SHA-256 digest in hexadecimal."""
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def ref_for(digest: str) -> str:
    return REF_PREFIX + digest


def digest_of_ref(ref) -> Optional[str]:
    """The digest a ``store/sha256/...`` reference names, or None."""
    if isinstance(ref, str) and ref.startswith(REF_PREFIX):
        candidate = ref[len(REF_PREFIX):]
        if is_sha256_hex(candidate):
            return candidate
    return None


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class StoredArtifact:
    digest: str
    ref: str
    path: Path


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(self, digest: str) -> Path:
        if not is_sha256_hex(digest):
            raise ValueError(f"not a SHA-256 digest: {digest!r}")
        return self.root / "sha256" / digest

    def put(self, source: Path) -> StoredArtifact:
        """Store a file under its digest and return the digest and reference.

        The copy goes to a temporary file in the same directory and is renamed
        into place, so a reader never sees a partial artefact. Storing the same
        bytes twice is a no-op."""
        source = Path(source)
        digest = sha256_file(source)
        target = self.path_for(digest)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".incoming-")
            try:
                with os.fdopen(fd, "wb") as out, open(source, "rb") as src:
                    shutil.copyfileobj(src, out)
                    out.flush()
                    os.fsync(out.fileno())
                if sha256_file(Path(tmp)) != digest:
                    raise OSError(f"{source} changed while it was being stored")
                os.replace(tmp, target)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        return StoredArtifact(digest=digest, ref=ref_for(digest), path=target)

    def put_bytes(self, data: bytes) -> StoredArtifact:
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(data)
            name = fh.name
        try:
            return self.put(Path(name))
        finally:
            Path(name).unlink(missing_ok=True)

    def resolve(self, ref: str) -> Path:
        digest = digest_of_ref(ref)
        if digest is None:
            raise ValueError(f"not a content-addressed reference: {ref!r}")
        return self.path_for(digest)

    def verify(self, ref: str, digest: str) -> str:
        """Check a recorded (reference, digest) pair against the store.

        Returns "ok", "missing" (no file under the reference), "ref-mismatch"
        (the reference names another digest) or "content-mismatch" (the bytes
        no longer hash to the digest)."""
        named = digest_of_ref(ref)
        if named is None or named != digest:
            return "ref-mismatch"
        path = self.path_for(digest)
        if not path.is_file():
            return "missing"
        return "ok" if sha256_file(path) == digest else "content-mismatch"


def verify_ledger_artifacts(records: Iterable[dict], store: ArtifactStore) -> List[dict]:
    """Recompute, from the store, the digest of every artefact a ledger cites.

    One entry per record that carries an ``off_chain_ref``; records without an
    artefact are skipped. This checks that the stored bytes are the ones the
    signed record names; it says nothing about what the bytes mean."""
    results = []
    for index, record in enumerate(records):
        ref = record.get("off_chain_ref")
        if ref is None:
            continue
        results.append({
            "index": index,
            "evidence_id": record.get("evidence_id"),
            "off_chain_ref": ref,
            "status": store.verify(ref, record.get("artifact_hash")),
        })
    return results
