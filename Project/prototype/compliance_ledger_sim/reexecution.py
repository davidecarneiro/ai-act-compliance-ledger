"""Re-execute a recorded decision from the record and the archived policy (WP2).

A version 2 record carries everything the policy decision read: the event
identity, the metrics, ``decision_inputs`` (risk level and human approval),
the artefact commitments and the identity of the policy (``policy_id`` and
``policy_hash``). ``reexecute`` loads that policy from the archive, checks
that its content still hashes to ``policy_hash``, rebuilds the event from the
record, evaluates it with the same pure function the engine used
(``simulator.evaluate_event``) and compares decision, rule and supported
provisions with what was signed.

Two cases cannot be re-executed from the record alone, by design:

* a record of malformed input (``rule_id`` ``input.malformed``): the payload
  that failed validation is not stored, only its digest;
* a schema version 1 record: version 1 did not record the decision inputs.

Both can be re-executed when the original payload is supplied: its digest is
checked against the record before it is used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from canonical import SCHEMA_V2, canonicaliser, schema_version_of
from simulator import (
    _canonical_source,
    evaluate_event,
    policy_identity,
    requirement_support,
    requirements_of,
    sha256_hex,
)

DEFAULT_POLICY_ARCHIVE = Path(__file__).parent / "configs" / "policies_archive"

MATCH = "match"
MISMATCH = "mismatch"
PAYLOAD_REQUIRED = "payload-required"
PAYLOAD_MISMATCH = "payload-mismatch"
POLICY_MISSING = "policy-missing"
POLICY_ALTERED = "policy-altered"


@dataclass
class ReexecutionResult:
    evidence_id: Optional[str]
    status: str
    recorded: dict
    recomputed: Optional[dict] = None
    differences: List[str] = field(default_factory=list)

    @property
    def matches(self) -> bool:
        return self.status == MATCH


def _payload_digest_field(record: dict, version: int) -> str:
    return "payload_hash" if version >= SCHEMA_V2 else "artifact_hash"


def load_archived_policy(record: dict, archive: Path, version: int):
    """The archived policy a record names, checked against its policy_hash.

    Returns (policy, status): status is None when the policy is usable."""
    policy_id = record.get("policy_id")
    if not isinstance(policy_id, str) or "/" in policy_id or not policy_id:
        return None, POLICY_MISSING
    path = Path(archive) / f"{policy_id}.json"
    if not path.is_file():
        return None, POLICY_MISSING
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy_identity(policy, version) != (policy_id, record.get("policy_hash")):
        # The archive file no longer has the content the record committed to.
        return None, POLICY_ALTERED
    return policy, None


def event_from_record(record: dict) -> dict:
    """Rebuild, from a version 2 record, the event the decision was taken on.

    Fields the event did not carry were recorded as null and are left out, so
    the rebuilt event takes the same branches of the policy as the original."""
    event = {
        "event_type": record.get("event_type"),
        "artifact_id": record.get("artifact_id"),
        "artifact_type": record.get("artifact_type"),
        "pipeline_stage": record.get("pipeline_stage"),
    }
    optional = {
        "scenario_id": record.get("scenario_id"),
        "run_id": record.get("run_id"),
        "metrics": record.get("metrics"),
        "artifact_sha256": record.get("artifact_hash"),
        "off_chain_ref": record.get("off_chain_ref"),
    }
    inputs = record.get("decision_inputs") or {}
    optional["risk_level"] = inputs.get("risk_level")
    optional["human_approval"] = inputs.get("human_approval")
    event.update({k: v for k, v in optional.items() if v is not None})
    return event


def reexecute(
    record: dict,
    policy_archive: Path = DEFAULT_POLICY_ARCHIVE,
    payload: Optional[dict] = None,
) -> ReexecutionResult:
    """Re-run the policy decision a record states and compare the outcome."""
    version = schema_version_of(record)
    recorded = {
        "decision": record.get("decision"),
        "rule_id": record.get("rule_id"),
        "supports_requirements": requirements_of(record),
    }
    result = ReexecutionResult(record.get("evidence_id"), MATCH, recorded)

    policy, problem = load_archived_policy(record, policy_archive, version)
    if problem:
        result.status = problem
        return result

    if payload is not None:
        digest = sha256_hex(canonicaliser(version)(_canonical_source(payload, version)))
        if digest != record.get(_payload_digest_field(record, version)):
            result.status = PAYLOAD_MISMATCH
            return result
        event = payload
    elif version < SCHEMA_V2 or record.get("rule_id") == "input.malformed":
        result.status = PAYLOAD_REQUIRED
        return result
    else:
        event = event_from_record(record)

    decision, _reason, rule_id = evaluate_event(event, policy, version)
    malformed = rule_id == "input.malformed"
    supports = ["Art.12"] if malformed else requirement_support(event, version)
    result.recomputed = {
        "decision": decision,
        "rule_id": rule_id,
        "supports_requirements": supports,
    }
    result.differences = [
        name for name in ("decision", "rule_id", "supports_requirements")
        if result.recomputed[name] != recorded[name]
    ]
    result.status = MATCH if not result.differences else MISMATCH
    return result


def reexecute_ledger(
    records: Iterable[dict],
    policy_archive: Path = DEFAULT_POLICY_ARCHIVE,
) -> dict:
    """Re-execute every record of a ledger; summary counts and the details."""
    results = [reexecute(r, policy_archive) for r in records]
    counts: dict = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return {"total": len(results), "counts": counts, "results": results}


def main(argv: List[str]) -> int:
    """``python3 reexecution.py <ledger> [<ledger> ...] [--archive DIR] [--out FILE]``

    Re-executes every record of each ledger (.json or .jsonl) and prints the
    counts per status; --out writes the per-record results as JSON. Exits 1
    if any record re-executes to a different outcome."""
    import argparse
    from datetime import datetime, timezone

    from ledger_store import read_ledger

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("ledgers", nargs="+", type=Path)
    parser.add_argument("--archive", type=Path, default=DEFAULT_POLICY_ARCHIVE)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "ledgers": []}
    mismatched = False
    for path in args.ledgers:
        summary = reexecute_ledger(read_ledger(path), args.archive)
        mismatched |= summary["counts"].get(MISMATCH, 0) > 0
        print(f"{path}: {summary['total']} records, {summary['counts']}")
        report["ledgers"].append({
            "ledger": str(path),
            "total": summary["total"],
            "counts": summary["counts"],
            "results": [
                {"evidence_id": r.evidence_id, "status": r.status,
                 "recorded": r.recorded, "recomputed": r.recomputed,
                 "differences": r.differences}
                for r in summary["results"]
            ],
        })
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"saved to {args.out}")
    return 1 if mismatched else 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
