"""Compliance policy engine with a JSON evidence ledger.

Each record contains its policy identity, a SHA-256 digest of the canonical
body, an Ed25519 signature and a link to the preceding record. Verification
checks stored bodies and links against the issuer key. Detecting omitted
events or suffix truncation requires an external inventory or anchor.

The distributed Fabric implementation is provided separately. The included
private key is demonstration material and does not establish exclusive authorship."""

from __future__ import annotations

import contextlib
import csv
import fcntl
import hashlib
import json
import os
import math
import time
from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Tuple
from uuid import uuid4

from keys import IssuerKey, load_or_create_key, public_key_fingerprint
from pseudonymizer import Pseudonymizer

BASE_DIR = Path(__file__).parent
LEDGER_FILE = BASE_DIR / "ledger.json"
POLICY_FILE = BASE_DIR / "configs" / "policies.json"
from paths import EXPERIMENTS_DIR  # noqa: E402  (vault: 06_dados/; delivery: ./experiments)

GENESIS_HASH = "0" * 64

# Accepted values for ``risk_level``. The field is required: an event that
# does not declare its risk level is rejected rather than treated as
# low risk, so the gate fails closed.
RISK_LEVELS = {"low", "medium", "high"}

# Metrics the policy engine compares against thresholds in [0,1].
# Other metrics (a row count, for instance) must still be finite
# numbers, but carry no domain constraint.
BOUNDED_METRICS = {"precision", "demographic_parity_diff", "drift_score"}

# Marks a rejection produced by input validation rather than by a policy
# rule. Art. 12 alone is claimed for these: the event never reached the
# rules that would justify any wider coverage.
# Fields without which a record cannot be tied to an artefact or operation.
# Event types that carry a reporting obligation of their own.
INCIDENT_EVENT_TYPES = {
    "serious_incident_detected",
    "incident_reported_to_authority",
}

REQUIRED_IDENTITY_FIELDS = (
    "event_type",
    "artifact_id",
    "artifact_type",
    "pipeline_stage",
)

INVALID_INPUT_PREFIX = "invalid input: "

DEFAULT_POLICIES = {
    "min_precision": 0.80,
    "max_demographic_parity_diff": 0.05,
    "require_human_approval_for_high_risk": True,
    "drift_alert_threshold": 0.15,
}


class InvalidPolicyError(ValueError):
    """Raised when the policy file cannot be trusted to decide anything."""


def _reject_json_constant(token: str):
    raise InvalidPolicyError(
        f"policy file contains the non-finite JSON token {token}"
    )


def _validate_policies(policies: dict) -> None:
    """Fail initialisation rather than decide with a malformed policy.

    A policy is the rule the Oracle applies; if it is unusable, every
    decision taken under it is unusable too. Failing closed here is what
    keeps a silently disabled threshold from producing approvals that look
    ordinary in the ledger.
    """
    for name in ("min_precision", "max_demographic_parity_diff",
                 "drift_alert_threshold"):
        value = policies.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidPolicyError(
                f"{name} must be a number, got {type(value).__name__}"
            )
        try:
            value = float(value)
        except (OverflowError, ValueError):
            raise InvalidPolicyError(f"{name} is out of representable range")
        if math.isnan(value) or math.isinf(value):
            raise InvalidPolicyError(f"{name} must be finite, got {value}")
        if not 0.0 <= value <= 1.0:
            raise InvalidPolicyError(f"{name} must lie in [0,1], got {value}")
    flag = policies.get("require_human_approval_for_high_risk")
    if not isinstance(flag, bool):
        raise InvalidPolicyError(
            "require_human_approval_for_high_risk must be a boolean, got "
            f"{type(flag).__name__}"
        )


def _safe_metrics(metrics):
    """Return finite numeric metrics with interoperable string keys, or None.

    Valid measurements are retained for threshold rejections. This function
    checks serialisability, not confidentiality; metric names and values may
    still require data minimisation before publication."""
    if not isinstance(metrics, dict):
        return None
    for name, value in metrics.items():
        # Non-string keys cannot be ordered against string keys, so they would
        # raise inside canonical_json instead of producing a record.
        if not isinstance(name, str):
            return None
        # A name that does not encode to UTF-8, a lone surrogate for instance,
        # is not serialisable in an interoperable way, which is what this
        # function screens for. Kept as it stands, it would enter the signed
        # body and Go would rebuild a different digest.
        if not _interoperable_text(name):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            as_float = float(value)
        except (OverflowError, ValueError):
            return None
        if math.isnan(as_float) or math.isinf(as_float):
            return None
    return metrics


_UNREPRESENTABLE_MARKER = "__unrepresentable__"


def _interoperable_text(value) -> bool:
    """Is the value inside the text domain the Go destination can read back?

    `isinstance(x, str)` does not define that domain. Python admits lone
    surrogates in a `str` -- 'a\\ud800b' is a valid string -- and
    `json.dumps(ensure_ascii=True)` escapes them as `\\ud800`, which Go decodes
    differently: the body signed in Python stops rebuilding at the destination.
    RFC 8259 (§8.2) expressly acknowledges that unpaired surrogates make
    behaviour unpredictable across implementations.

    The domain is therefore that of sequences of valid Unicode scalar values,
    and the operational question is simply whether the value encodes to UTF-8.
    """
    if not isinstance(value, str):
        return True
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _without_surrogates(value) -> str:
    """Replace what does not encode, rather than copy it into the signed record.

    The rejection has to be readable at the destination. Copying the invalid
    character into another signed field would carry the rejected problem over.
    """
    # Replace only lone surrogate units; retain valid Unicode characters.
    return "".join(
        ch if not 0xD800 <= ord(ch) <= 0xDFFF else f"\\u{ord(ch):04x}"
        for ch in value
    )


def _canonical_source(value):
    """Normalise payloads for hashing, preserving well-formed event mappings.

    Mixed-type keys use a sorted envelope containing key type, key text and
    value. The reserved envelope key is also wrapped to prevent ambiguity."""
    if isinstance(value, dict):
        if all(isinstance(k, str) for k in value) and _UNREPRESENTABLE_MARKER not in value:
            return {k: _canonical_source(v) for k, v in value.items()}
        triples = [
            [type(k).__name__, k if isinstance(k, str) else repr(k), _canonical_source(v)]
            for k, v in value.items()
        ]
        triples.sort(
            key=lambda x: json.dumps(
                x, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
        )
        return {_UNREPRESENTABLE_MARKER: triples}

    if isinstance(value, (list, tuple)):
        return [_canonical_source(item) for item in value]
    if isinstance(value, str) and not _interoperable_text(value):
        return _without_surrogates(value)
    return value


def _required_text(value) -> str:
    """Represent required identity fields as interoperable strings.

    Malformed values retain their JSON rendering so rejection records remain
    readable by the Go evidence model. The reason and rule identify the rejection."""
    if isinstance(value, str):
        return value if _interoperable_text(value) else _without_surrogates(value)
    return json.dumps(
        _canonical_source(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def _optional_text(value):
    """As :func:`_required_text`, but ``None`` is a value the model allows."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if _interoperable_text(value) else _without_surrogates(value)
    return _required_text(value)


def policy_identity(policies: dict) -> Tuple[str, str]:
    """Return the policy identifier and SHA-256 digest of its canonical content.

    Identical policy content produces the same identity. Changing a policy
    changes its digest, linking each decision to a specific policy version."""
    digest = sha256_hex(canonical_json(policies))
    return f"pol-{digest[:12]}", digest


def canonical_json(payload: dict) -> bytes:
    """Deterministic JSON serialization used as the basis for hashes/signatures.

    ``ensure_ascii=True`` is the json.dumps default but is stated explicitly here
    because it is part of the canonical contract that the Go chaincode replicates
    (non-ASCII escaped to \\uXXXX). Making it explicit does not change the output.
    """

    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass
class VerificationReport:
    """Result of running ``verify_chain`` over a ledger snapshot."""

    total: int
    valid: int
    invalid: int
    first_invalid_index: int | None
    issues: List[str]

    @property
    def is_valid(self) -> bool:
        return self.invalid == 0


class ComplianceOracle:
    def __init__(
        self,
        policy_file: Path = POLICY_FILE,
        ledger_file: Path = LEDGER_FILE,
        issuer_key: IssuerKey | None = None,
        pseudonymizer: Pseudonymizer | None = None,
    ) -> None:
        self.policy_file = policy_file
        self.ledger_file = ledger_file
        self.issuer_key = issuer_key or load_or_create_key()
        # Pseudonymization is opt-in: when no instance is supplied the
        # Oracle behaves as before. When supplied, every event is passed
        # through ``apply_to_event`` before the canonical body is built,
        # so the record_hash and Ed25519 signature commit to the
        # transformed fields; other fields require separate data minimisation.
        self.pseudonymizer = pseudonymizer
        self.policies = self._load_policies()
        self._ensure_files()
        self.metrics_rows: List[dict] = []

    # ------------------------------------------------------------------
    # Filesystem helpers
    # ------------------------------------------------------------------

    def _ensure_files(self) -> None:
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.ledger_file.exists():
            self.ledger_file.write_text("[]", encoding="utf-8")
        EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)

    def set_policies(self, policies: dict) -> None:
        """Validate and archive a policy before activating it.

        Direct assignment to oracle.policies bypasses these checks."""
        _validate_policies(policies)
        self._archive_policy(policies)
        self.policies = policies

    def _archive_policy(self, policies: dict) -> None:
        """Archive a policy under its content-derived identifier.

        The archived content supports reconstruction of the rules named by a record."""
        archive = self.policy_file.parent / "policies_archive"
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / f"{policy_identity(policies)[0]}.json"
        if not target.exists():
            target.write_text(
                json.dumps(policies, indent=2, sort_keys=True), encoding="utf-8"
            )

    def _load_policies(self) -> dict:
        self.policy_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.policy_file.exists():
            self.policy_file.write_text(
                json.dumps(DEFAULT_POLICIES, indent=2), encoding="utf-8"
            )
            defaults = DEFAULT_POLICIES.copy()
            self._archive_policy(defaults)
            return defaults
        # Python's json accepts the non-standard tokens NaN, Infinity and
        # -Infinity. A threshold set to NaN compares false against every
        # metric, which silently disables the rule it belongs to, so those
        # tokens are refused at the door.
        loaded = json.loads(
            self.policy_file.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
        merged = DEFAULT_POLICIES.copy()
        merged.update(loaded)
        _validate_policies(merged)
        self._archive_policy(merged)
        return merged

    def reset_ledger(self) -> None:
        """Clear ledger contents — used by tests and reproducible runs."""

        self.ledger_file.write_text("[]", encoding="utf-8")

    def _read_ledger(self) -> List[dict]:
        return json.loads(self.ledger_file.read_text(encoding="utf-8"))

    def _write_ledger(self, ledger: List[dict]) -> None:
        # Write to a sibling temporary file and rename over the target. A plain
        # write_text truncates first, so a crash or a concurrent reader in that
        # window sees an empty or half-written ledger; os.replace is atomic on
        # POSIX, so a reader sees either the old file or the new one.
        tmp = self.ledger_file.with_suffix(self.ledger_file.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.ledger_file)

    @contextlib.contextmanager
    def _ledger_lock(self):
        """Serialise the ledger read-modify-write cycle across local processes.

        The advisory file lock prevents cooperating writers from appending to the
        same prior head and overwriting each other's records. It does not coordinate
        stores across hosts or protect writes that bypass the lock."""
        lock_path = self.ledger_file.with_suffix(self.ledger_file.suffix + ".lock")
        with open(lock_path, "a+") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    # ------------------------------------------------------------------
    # Policy evaluation
    # ------------------------------------------------------------------

    def _validate_input(self, event_data: dict) -> str | None:
        """Validate event identity, risk, approval, metrics and Unicode text.

        Malformed events are rejected before policy evaluation. The rejection is
        recorded; only logging coverage is attributed to invalid input."""
        for name in REQUIRED_IDENTITY_FIELDS:
            value = event_data.get(name)
            if not isinstance(value, str) or not value.strip():
                return f"{name} must be a non-empty string, got {value!r}"

        # scenario_id is optional, but when present it must be a string: a
        # list or object passed the gate, was signed and chained, and then
        # could not be exported at all, because the exporter groups records
        # by this value. A record nothing can read is not evidence.
        # Text boundary: see _interoperable_text. It is checked over the whole
        # event, not only over the identity fields, because artifact_hash is
        # computed over all of event_data.
        def _sweep(node, path="event"):
            if isinstance(node, dict):
                for k, v in node.items():
                    if not _interoperable_text(k):
                        return f"{path}: field name outside the interoperable text domain"
                    found = _sweep(v, f"{path}.{k if isinstance(k, str) else '?'}")
                    if found:
                        return found
            elif isinstance(node, (list, tuple)):
                for i, v in enumerate(node):
                    found = _sweep(v, f"{path}[{i}]")
                    if found:
                        return found
            elif not _interoperable_text(node):
                return (
                    f"{path} contains a lone Unicode surrogate; the domain is "
                    f"sequences of valid scalar values (RFC 8259 §8.2)"
                )
            return None

        out_of_domain = _sweep(event_data)
        if out_of_domain:
            return out_of_domain

        scenario_id = event_data.get("scenario_id")
        if scenario_id is not None and not isinstance(scenario_id, str):
            return (
                "scenario_id must be a string when present, got "
                f"{type(scenario_id).__name__}"
            )

        approval = event_data.get("human_approval")
        if approval is not None and not isinstance(approval, bool):
            return (
                "human_approval must be a boolean, got "
                f"{type(approval).__name__}"
            )

        risk = event_data.get("risk_level")
        # Compare as a string first: an unhashable value (a list, say) raises
        # TypeError on set membership, which would escape as a crash instead
        # of a recorded rejection.
        if not isinstance(risk, str) or risk not in RISK_LEVELS:
            return (
                "risk_level must be one of "
                f"{', '.join(sorted(RISK_LEVELS))}, got {risk!r}"
            )

        metrics = event_data.get("metrics", {})
        if not isinstance(metrics, dict):
            return f"metrics must be an object, got {type(metrics).__name__}"

        for name, value in metrics.items():
            # A non-string metric name cannot be ordered against a string one,
            # so it raised inside canonical_json before any decision existed.
            if not isinstance(name, str):
                return f"metric names must be strings, got {type(name).__name__}"
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return (
                    f"metric {name} must be a number, got "
                    f"{type(value).__name__}"
                )
            # An int of arbitrary magnitude overflows on conversion to float,
            # so it is bounded before math.isnan is allowed to touch it.
            try:
                value = float(value)
            except (OverflowError, ValueError):
                return f"metric {name} is out of representable range"
            if math.isnan(value) or math.isinf(value):
                return f"metric {name} must be finite, got {value}"
            if name in BOUNDED_METRICS and not 0.0 <= float(value) <= 1.0:
                return f"metric {name} must lie in [0,1], got {value}"

        return None

    def _validate_compliance(self, event_data: dict) -> Tuple[str, str, str]:
        invalid = self._validate_input(event_data)
        if invalid is not None:
            return "rejected", f"{INVALID_INPUT_PREFIX}{invalid}", "input.malformed"

        metrics = event_data.get("metrics", {})

        # An incident that already happened still has to be handled, whatever
        # the model's metrics look like. Classifying it by event type before
        # the metric rules keeps a low precision from turning a reportable
        # incident into an ordinary quality rejection.
        if event_data.get("event_type") in INCIDENT_EVENT_TYPES:
            return (
                "escalated",
                "serious incident: mandatory reporting to the market "
                "surveillance authority within the statutory deadline (Art. 73)",
                "incident.reportable",
            )

        if metrics.get("precision", 0.0) < self.policies["min_precision"]:
            return (
                "rejected",
                f"precision {metrics.get('precision')} below threshold "
                f"{self.policies['min_precision']}",
                "threshold.precision",
            )

        if (
            metrics.get("demographic_parity_diff", 1.0)
            > self.policies["max_demographic_parity_diff"]
        ):
            return (
                "rejected",
                f"demographic parity diff {metrics.get('demographic_parity_diff')} "
                f"above threshold {self.policies['max_demographic_parity_diff']}",
                "threshold.fairness",
            )

        if (
            self.policies["require_human_approval_for_high_risk"]
            and event_data.get("risk_level") == "high"
            and not event_data.get("human_approval", False)
        ):
            return (
                "rejected",
                "missing human approval for high-risk event",
                "oversight.approval_missing",
            )

        if metrics.get("drift_score", 0.0) > self.policies["drift_alert_threshold"]:
            return (
                "escalated",
                f"drift score {metrics.get('drift_score')} above threshold "
                f"{self.policies['drift_alert_threshold']}",
                "monitoring.drift_alert",
            )

        if event_data.get("event_type") in {"audit_query", "incident_audit_query"}:
            return (
                "verified",
                "audit query: integrity check requested",
                "audit.query_recorded",
            )

        return "approved", "all policy checks passed", "policy.all_checks_passed"

    def _requirement_coverage(self, event_data: dict) -> List[str]:
        covered = {"Art.12"}
        if event_data.get("human_approval") is not None:
            covered.add("Art.14")
        metrics = event_data.get("metrics", {})
        if "precision" in metrics or "demographic_parity_diff" in metrics:
            covered.add("Art.15")
        if "demographic_parity_diff" in metrics:
            covered.add("Art.10(3)")
        if "drift_score" in metrics:
            covered.add("Art.72")
        if event_data.get("event_type") in {
            "audit_query",
            "serious_incident_detected",
            "incident_reported_to_authority",
            "incident_audit_query",
        }:
            covered.add("Art.73")
        return sorted(covered)

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def process_mlops_event(self, event_data: dict) -> dict:
        start = time.perf_counter()
        # The whole read-modify-write cycle is one critical section: the
        # parent_chain_hash read here has to still be the head when the record
        # built from it is written back.
        with self._ledger_lock():
            ledger = self._read_ledger()
            parent_chain_hash = ledger[-1]["chain_hash"] if ledger else GENESIS_HASH

            # Optional pseudonymization layer (EDPB Guidelines 02/2025): if a
            # pseudonymizer was supplied at construction time, the event is
            # rewritten so that direct identifiers (subject_id, user_id, …)
            # become HMAC-SHA256 fingerprints with org and key-version metadata
            # before any hashing or signing takes place.
            if self.pseudonymizer is not None:
                event_data = self.pseudonymizer.apply_to_event(event_data)

            artifact_hash = sha256_hex(canonical_json(_canonical_source(event_data)))
            policy_id, policy_hash = policy_identity(self.policies)
            decision, reason, rule_id = self._validate_compliance(event_data)
            # Coverage is derived from field shapes, so it must not run over an
            # event already declared malformed: doing so turned a rejection that
            # should have been recorded into an uncaught exception, and nothing
            # reached the ledger at all.
            if reason.startswith(INVALID_INPUT_PREFIX):
                coverage = ["Art.12"]
            else:
                coverage = self._requirement_coverage(event_data)

            # Body fields that contribute to the record hash. Signature and
            # chain_hash are computed afterwards from this canonical body so that
            # verification is deterministic.
            body = {
                "evidence_id": f"ev-{uuid4()}",
                "scenario_id": _optional_text(event_data.get("scenario_id")),
                "event_type": _required_text(event_data.get("event_type")),
                "artifact_id": _required_text(event_data.get("artifact_id")),
                "artifact_type": _required_text(event_data.get("artifact_type")),
                "pipeline_stage": _required_text(event_data.get("pipeline_stage")),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "decision": decision,
                "reason": reason,
                "rule_id": rule_id,
                "metrics": _safe_metrics(event_data.get("metrics")),
                "policy_id": policy_id,
                "policy_hash": policy_hash,
                "artifact_hash": artifact_hash,
                "requirements_covered": coverage,
                "issuer_id": self.issuer_key.issuer_id,
                "issuer_pubkey_fingerprint": public_key_fingerprint(self.issuer_key),
                "sig_alg": "Ed25519",
                "hash_alg": "SHA-256",
                "parent_hash": parent_chain_hash,
            }

            body_bytes = canonical_json(body)
            record_hash = sha256_hex(body_bytes)
            signature = self.issuer_key.sign(body_bytes)
            chain_hash = sha256_hex((parent_chain_hash + record_hash).encode("utf-8"))

            record = dict(body)
            record["record_hash"] = record_hash
            record["issuer_signature"] = b64encode(signature).decode("ascii")
            record["chain_hash"] = chain_hash

            ledger.append(record)
            self._write_ledger(ledger)

        latency_ms = round((time.perf_counter() - start) * 1000, 4)
        self.metrics_rows.append(
            {
                "evidence_id": body["evidence_id"],
                "scenario_id": event_data.get("scenario_id"),
                "event_type": event_data.get("event_type"),
                "decision": decision,
                "latency_ms": latency_ms,
                "requirements_covered_count": len(coverage),
                "requirements_covered": ",".join(coverage),
                "chain_hash": chain_hash,
            }
        )
        # The record is already written by the time control reaches here.
        # Printing the raw value crashed on a lone surrogate and turned a
        # successful rejection into an exception: the log line must not bring
        # the gate down.
        print(
            f"[oracle] scenario={_required_text(record.get('scenario_id') or '-')} "
            f"decision={decision} latency_ms={latency_ms}"
        )
        return record

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_chain(self, ledger: List[dict] | None = None) -> VerificationReport:
        ledger = ledger if ledger is not None else self._read_ledger()
        issues: List[str] = []
        first_invalid: int | None = None
        valid = 0
        previous_chain = GENESIS_HASH

        for index, record in enumerate(ledger):
            stripped = {
                k: v
                for k, v in record.items()
                if k not in {"record_hash", "issuer_signature", "chain_hash"}
            }
            body_bytes = canonical_json(stripped)
            recomputed_hash = sha256_hex(body_bytes)

            local_issues: List[str] = []
            if record.get("parent_hash") != previous_chain:
                local_issues.append("parent_hash mismatch")
            if recomputed_hash != record.get("record_hash"):
                local_issues.append("record_hash mismatch")
            try:
                signature = b64decode(record.get("issuer_signature", ""))
                if not self.issuer_key.verify(body_bytes, signature):
                    local_issues.append("invalid signature")
            except Exception:
                local_issues.append("malformed signature")

            expected_chain = sha256_hex(
                (previous_chain + recomputed_hash).encode("utf-8")
            )
            if expected_chain != record.get("chain_hash"):
                local_issues.append("chain_hash mismatch")

            if local_issues:
                if first_invalid is None:
                    first_invalid = index
                issues.append(
                    f"#{index} ({record.get('scenario_id')}): "
                    + ", ".join(local_issues)
                )
            else:
                valid += 1

            previous_chain = record.get("chain_hash", expected_chain)

        return VerificationReport(
            total=len(ledger),
            valid=valid,
            invalid=len(ledger) - valid,
            first_invalid_index=first_invalid,
            issues=issues,
        )

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def query_by_requirement(self, article: str) -> List[dict]:
        ledger = self._read_ledger()
        return [r for r in ledger if article in r.get("requirements_covered", [])]

    def query_by_scenario(self, scenario_id: str) -> List[dict]:
        ledger = self._read_ledger()
        return [r for r in ledger if r.get("scenario_id") == scenario_id]

    # ------------------------------------------------------------------
    # Metrics export
    # ------------------------------------------------------------------

    def export_metrics(self, run_label: str) -> Tuple[Path, Path]:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        csv_path = EXPERIMENTS_DIR / f"oracle_metrics_{run_label}_{timestamp}.csv"
        json_path = EXPERIMENTS_DIR / f"oracle_summary_{run_label}_{timestamp}.json"

        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "evidence_id",
                    "scenario_id",
                    "event_type",
                    "decision",
                    "latency_ms",
                    "requirements_covered_count",
                    "requirements_covered",
                    "chain_hash",
                ],
            )
            writer.writeheader()
            writer.writerows(self.metrics_rows)

        decisions: dict = {}
        max_coverage = 0
        for row in self.metrics_rows:
            decisions[row["decision"]] = decisions.get(row["decision"], 0) + 1
            max_coverage = max(max_coverage, row["requirements_covered_count"])

        chain_report = self.verify_chain()
        avg_latency = sum(row["latency_ms"] for row in self.metrics_rows) / max(
            1, len(self.metrics_rows)
        )

        summary = {
            "run_label": run_label,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "events_processed": len(self.metrics_rows),
            "decisions": decisions,
            "avg_latency_ms": round(avg_latency, 4),
            "max_requirements_covered_in_event": max_coverage,
            "chain_verification": {
                "total": chain_report.total,
                "valid": chain_report.valid,
                "invalid": chain_report.invalid,
                "is_valid": chain_report.is_valid,
            },
            "policy_file": str(self.policy_file),
            "issuer_id": self.issuer_key.issuer_id,
            "issuer_pubkey_fingerprint": public_key_fingerprint(self.issuer_key),
            "sig_alg": "Ed25519",
            "hash_alg": "SHA-256",
        }
        json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return csv_path, json_path


def run_baseline(scenarios: Iterable[dict] | None = None) -> Tuple[Path, Path]:
    """Convenience entry point used by ``python simulator.py``."""

    from scenarios import build_scenarios

    oracle = ComplianceOracle()
    oracle.reset_ledger()
    events = list(scenarios) if scenarios is not None else build_scenarios()

    print("--- compliance oracle (baseline run) ---")
    for event in events:
        oracle.process_mlops_event(event)

    csv_path, json_path = oracle.export_metrics(run_label="oracle_baseline")
    report = oracle.verify_chain()
    print(
        f"chain_verification valid={report.valid}/{report.total} "
        f"issues={len(report.issues)}"
    )
    print(f"ledger_file={oracle.ledger_file}")
    print(f"metrics_csv={csv_path}")
    print(f"metrics_summary={json_path}")
    return csv_path, json_path


if __name__ == "__main__":
    run_baseline()
