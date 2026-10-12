"""Tamper detection on the credit-scoring case (section 4.4 of the article plan).

Protocol: ``Project/protocols/tamper_detection.md``, recorded before the run.
The case's 16 events go through configurations A, B0, B and B+ of the WP3
ablation; each attack is applied to a fresh copy of the output and checked by
what a third party holding that output can verify.

    python3 tamper_experiment.py
"""

from __future__ import annotations

import base64
import copy
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

import credit_case as cc
from ablation_arms import ARM_NAMES, make_arms, verify_arm
from approvals import sign_approval
from artifact_store import ArtifactStore
from canonical import record_body_bytes
from keys import load_or_create_key
from ledger_store import GENESIS_HASH, read_ledger
from simulator import sha256_hex

ANCHOR_INTERVAL = 5
TARGET = 8                      # record 8: validation of v2, decision "rejected"
OUT_DIR = cc.EXPERIMENTS_DIR / "tamper"

ND, D, NA = "not detected", "detected", "n/a"
EXPECTED = {
    "T1": {"A": ND, "B0": D, "B": D, "Bplus": D},
    "T2": {"A": NA, "B0": NA, "B": D, "Bplus": D},
    "T3": {"A": ND, "B0": ND, "B": D, "Bplus": D},
    "T4": {"A": ND, "B0": D, "B": D, "Bplus": D},
    "T5": {"A": ND, "B0": D, "B": D, "Bplus": D},
    "T6a": {"A": ND, "B0": ND, "B": ND, "Bplus": D},
    "T6b": {"A": ND, "B0": ND, "B": ND, "Bplus": ND},
    "T7a": {"A": ND, "B0": ND, "B": ND, "Bplus": D},
    "T7b": {"A": ND, "B0": ND, "B": ND, "Bplus": ND},
    "T8": {"A": ND, "B0": ND, "B": ND, "Bplus": ND},
    "T9a": {"A": ND, "B0": ND, "B": ND, "Bplus": ND},
    "T9b": {"A": ND, "B0": ND, "B": ND, "Bplus": ND},
}
DESCRIPTIONS = {
    "T1": "alter a field of an intermediate record",
    "T2": "alter only the signature",
    "T3": "alter and recompute every hash, without the key",
    "T4": "swap two records",
    "T5": "delete an intermediate record",
    "T6a": "truncate a suffix that crosses an anchor",
    "T6b": "truncate a suffix after the last anchor",
    "T7a": "rewrite with the issuer's key, crossing an anchor",
    "T7b": "rewrite with the issuer's key, after the last anchor",
    "T8": "omit an event at the source",
    "T9a": "inject a forged event upstream",
    "T9b": "inject a forged approval upstream",
}


# ----------------------------------------------------------------------
# Producing the configurations' output
# ----------------------------------------------------------------------

def case_events(workdir: Path) -> List[dict]:
    store = ArtifactStore(workdir / "store")
    return cc.build_events(store, cc.MAIN_SEED, cc.approver_key()).events


def produce(folder: Path, events: List[dict], key) -> Dict[str, dict]:
    """Send the events through the four configurations; return what each
    decided for every event (for the gate outcome of T9)."""
    folder.mkdir(parents=True)
    policy = json.loads(cc.POLICY_FILE.read_text(encoding="utf-8"))
    policy_file = folder / "policies.json"
    policy_file.write_text(json.dumps(policy), encoding="utf-8")
    arms = make_arms(folder, policy_file, policy, key, interval=ANCHOR_INTERVAL)
    decisions = {name: [] for name in ARM_NAMES}
    for event in events:
        for name, arm in arms.items():
            out = arm.process(copy.deepcopy(event))
            decisions[name].append((out["decision"], out.get("rule_id")))
    for arm in arms.values():
        arm.close()
    return decisions


# ----------------------------------------------------------------------
# Attacks on the JSONL ledgers (B0, B, B+) and on the SQLite table (A)
# ----------------------------------------------------------------------

def _load(path: Path) -> List[dict]:
    return read_ledger(path)


def _save(path: Path, records: List[dict]) -> None:
    path.write_bytes(b"".join(
        (json.dumps(r, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
        for r in records))


def _flip(decision: str) -> str:
    return "approved" if decision != "approved" else "rejected"


def _recompute(records: List[dict], start: int, key=None) -> None:
    """Recompute hashes (and, with the key, signatures) from index start."""
    for i in range(start, len(records)):
        r = records[i]
        parent = records[i - 1]["chain_hash"] if i else GENESIS_HASH
        r["parent_hash"] = parent
        body = record_body_bytes(r)
        r["record_hash"] = sha256_hex(body)
        if key is not None and "issuer_signature" in r:
            r["issuer_signature"] = base64.b64encode(key.sign(body)).decode("ascii")
        r["chain_hash"] = sha256_hex((parent + r["record_hash"]).encode("utf-8"))


def attack_ledger(name: str, records: List[dict], key, signed: bool) -> Optional[List[dict]]:
    """Return the attacked copy, or None when the attack is n/a."""
    t = TARGET - 1
    r = copy.deepcopy(records)
    if name == "T1":
        r[t]["decision"] = "approved"
    elif name == "T2":
        if not signed:
            return None
        raw = bytearray(base64.b64decode(r[t]["issuer_signature"]))
        raw[0] ^= 0x01
        r[t]["issuer_signature"] = base64.b64encode(bytes(raw)).decode("ascii")
    elif name == "T3":
        r[t]["decision"] = "approved"
        _recompute(r, t)
    elif name == "T4":
        r[t], r[t + 1] = r[t + 1], r[t]
    elif name == "T5":
        del r[t]
    elif name == "T6a":
        r = r[:13]
    elif name == "T6b":
        r = r[:15]
    elif name == "T7a":
        r[t]["decision"] = "approved"
        _recompute(r, t, key)
    elif name == "T7b":
        r[15]["decision"] = _flip(r[15]["decision"])
        _recompute(r, 15, key)
    return r


def attack_sqlite(name: str, db_file: Path) -> bool:
    """Apply the attack to arm A's table; False when it is n/a."""
    if name == "T2":
        return False
    c = sqlite3.connect(str(db_file))
    try:
        if name in ("T1", "T3", "T7a"):
            c.execute("UPDATE events SET decision = 'approved' WHERE id = ?", (TARGET,))
        elif name == "T4":
            cols = [d[1] for d in c.execute("PRAGMA table_info(events)") if d[1] != "id"]
            rows = {i: c.execute(f"SELECT {', '.join(cols)} FROM events WHERE id = ?", (i,)).fetchone()
                    for i in (TARGET, TARGET + 1)}
            setter = ", ".join(f"{col} = ?" for col in cols)
            c.execute(f"UPDATE events SET {setter} WHERE id = ?", (*rows[TARGET + 1], TARGET))
            c.execute(f"UPDATE events SET {setter} WHERE id = ?", (*rows[TARGET], TARGET + 1))
        elif name == "T5":
            c.execute("DELETE FROM events WHERE id = ?", (TARGET,))
            last = c.execute("SELECT MAX(id) FROM events").fetchone()[0]
            for i in range(TARGET + 1, last + 1):
                c.execute("UPDATE events SET id = ? WHERE id = ?", (i - 1, i))
            c.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'events'", (last - 1,))
        elif name == "T6a":
            c.execute("DELETE FROM events WHERE id > 13")
        elif name == "T6b":
            c.execute("DELETE FROM events WHERE id > 15")
        elif name == "T7b":
            c.execute("UPDATE events SET decision = CASE decision WHEN 'approved' THEN 'rejected' "
                      "ELSE 'approved' END WHERE id = 16")
        c.commit()
    finally:
        c.close()
    return True


# ----------------------------------------------------------------------
# Upstream attacks (T8, T9): different event sequences
# ----------------------------------------------------------------------

FABRICATED = {"precision": 0.85, "demographic_parity_diff": 0.05}


def upstream_events(name: str, events: List[dict], workdir: Path) -> List[dict]:
    events = copy.deepcopy(events)
    if name == "T8":
        del events[TARGET - 1]
    elif name == "T9a":
        forged = copy.deepcopy(events[TARGET - 1])      # validation of v2
        forged["metrics"] = dict(FABRICATED)
        events.insert(TARGET, forged)
    elif name == "T9b":
        forged = copy.deepcopy(events[9])               # deployment request with approval
        forged["metrics"] = dict(FABRICATED)
        mallory = load_or_create_key("mallory", keys_dir=workdir / "mallory")
        forged["approval"] = sign_approval(mallory, cc.APPROVER_ID, forged["artifact_sha256"],
                                           forged["run_id"])
        events.insert(10, forged)
    return events


# ----------------------------------------------------------------------

def run(out_dir: Path = OUT_DIR) -> Path:
    started = datetime.now(timezone.utc)
    work = Path(tempfile.mkdtemp(prefix="tamper_"))
    try:
        key = load_or_create_key("tamper-issuer", keys_dir=work / "keys")
        events = case_events(work)
        original = work / "original"
        baseline_decisions = produce(original, events, key)
        clean = {name: verify_arm(name, original, key) for name in ARM_NAMES}

        results = {}
        for attack in ("T1", "T2", "T3", "T4", "T5", "T6a", "T6b", "T7a", "T7b"):
            folder = work / attack
            shutil.copytree(original, folder)
            row = {}
            for arm in ARM_NAMES:
                if arm == "A":
                    applicable = attack_sqlite(attack, folder / "A.sqlite")
                else:
                    path = folder / f"{arm}.jsonl"
                    attacked = attack_ledger(attack, _load(path), key, signed=arm != "B0")
                    applicable = attacked is not None
                    if applicable:
                        _save(path, attacked)
                if not applicable:
                    row[arm] = {"observed": NA, "issues": []}
                    continue
                report = verify_arm(arm, folder, key)
                row[arm] = {"observed": ND if report["valid"] else D, "issues": report["issues"][:5]}
            results[attack] = row

        for attack in ("T8", "T9a", "T9b"):
            folder = work / attack
            sequence = upstream_events(attack, events, work)
            decisions = produce(folder, sequence, key)
            row = {}
            for arm in ARM_NAMES:
                report = verify_arm(arm, folder, key)
                row[arm] = {"observed": ND if report["valid"] else D, "issues": report["issues"][:5]}
                if attack in ("T9a", "T9b"):
                    index = TARGET if attack == "T9a" else 10
                    row[arm]["gate"] = {"decision": decisions[arm][index][0],
                                        "rule_id": decisions[arm][index][1]}
            results[attack] = row

        table = []
        for attack, row in results.items():
            for arm in ARM_NAMES:
                row[arm]["expected"] = EXPECTED[attack][arm]
                row[arm]["as_expected"] = row[arm]["observed"] == EXPECTED[attack][arm]
            table.append({"attack": attack, "description": DESCRIPTIONS[attack],
                          **{arm: row[arm]["observed"] for arm in ARM_NAMES}})
        output = {
            "protocol": "Project/protocols/tamper_detection.md",
            "generated_at": started.isoformat(),
            "environment": cc.environment(),
            "anchor_interval": ANCHOR_INTERVAL,
            "target_record": TARGET,
            "original": {"records": len(events),
                         "verification": {k: v["valid"] for k, v in clean.items()},
                         "decisions": {k: [d for d, _ in v] for k, v in baseline_decisions.items()}},
            "results": results,
            "table_t7": table,
            "all_as_expected": all(row[arm]["as_expected"] for row in results.values()
                                   for arm in ARM_NAMES),
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"tamper_{started.strftime('%Y%m%dT%H%M%SZ')}.json"
        path.write_text(json.dumps(output, indent=1) + "\n", encoding="utf-8")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for line in table:
        print(f"{line['attack']:4} " + " | ".join(f"{arm}: {line[arm]}" for arm in ARM_NAMES))
    print(f"all as expected: {output['all_as_expected']}")
    print(f"saved to {path}")
    return path


if __name__ == "__main__":
    run()
    sys.exit(0)
