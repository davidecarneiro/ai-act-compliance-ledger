"""Signed human approvals (WP6 of the article plan).

Version 1 recorded human oversight as a boolean, ``human_approval: true``,
asserted by whoever sent the event. Version 2 accepts, in addition, an
approval statement signed by the approver: a natural person with an Ed25519
key that the policy lists as authorised. The statement names the artefact
(``artifact_sha256``), the run (``run_id``), the approver's decision and the
time, and the signature is over its RFC 8785 form. The engine checks the
statement against the event and the policy before a deployment proceeds, and
the record keeps the statement and its signature, so a third party holding the
archived policy can verify who approved what.

Event field::

    "approval": {
        "approver_id": "approver-alice",
        "statement": {
            "type": "deployment-approval",
            "artifact_sha256": "<64 hex>",
            "run_id": "run-0001" | null,
            "decision": "approve" | "deny",
            "approved_at": "2026-10-12T14:03:00+00:00"
        },
        "signature": "<base64 Ed25519 signature over JCS(statement)>"
    }

Policy fields (optional; absent keeps the dissertation's behaviour)::

    "authorised_approvers": {"approver-alice": "<64 hex raw Ed25519 public key>"},
    "signed_approval_required_for": ["deployment_request"]

What a valid approval establishes: that the holder of an authorised key signed
an approval of this artefact in this run. It does not establish who held the
key, whether the approver examined the system, or whether oversight was
effective (Art. 14(4) AI Act).
"""

from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime, timezone
from typing import Mapping, Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from artifact_store import is_sha256_hex
from canonical import canonical_v2

APPROVAL_TYPE = "deployment-approval"
APPROVAL_DECISIONS = ("approve", "deny")
_HEX64 = re.compile(r"[0-9a-f]{64}")

APPROVAL_INVALID = "oversight.approval_invalid"
APPROVAL_DENIED = "oversight.approval_denied"


def statement_bytes(statement: Mapping) -> bytes:
    """The bytes an approver signs: the RFC 8785 form of the statement."""
    return canonical_v2(dict(statement))


def sign_approval(
    key,
    approver_id: str,
    artifact_sha256: str,
    run_id: Optional[str],
    decision: str = "approve",
    approved_at: Optional[str] = None,
) -> dict:
    """Build and sign an approval statement with the approver's key.

    ``key`` is anything with ``sign(bytes) -> bytes`` (keys.IssuerKey)."""
    statement = {
        "type": APPROVAL_TYPE,
        "artifact_sha256": artifact_sha256,
        "run_id": run_id,
        "decision": decision,
        "approved_at": approved_at or datetime.now(timezone.utc).isoformat(),
    }
    signature = key.sign(statement_bytes(statement))
    return {
        "approver_id": approver_id,
        "statement": statement,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def structure_error(approval) -> Optional[str]:
    """Is the approval well formed? Returns a reason, or None.

    A malformed approval makes the event malformed (input.malformed); a well
    formed approval that does not check out is a policy matter
    (oversight.approval_invalid)."""
    if not isinstance(approval, dict):
        return f"approval must be an object, got {type(approval).__name__}"
    if set(approval) != {"approver_id", "statement", "signature"}:
        return "approval must have exactly approver_id, statement and signature"
    if not isinstance(approval["approver_id"], str) or not approval["approver_id"].strip():
        return "approval.approver_id must be a non-empty string"
    statement = approval["statement"]
    if not isinstance(statement, dict) or set(statement) != {
        "type", "artifact_sha256", "run_id", "decision", "approved_at"
    }:
        return ("approval.statement must have exactly type, artifact_sha256, run_id, "
                "decision and approved_at")
    if statement["type"] != APPROVAL_TYPE:
        return f"approval.statement.type must be {APPROVAL_TYPE!r}"
    if not is_sha256_hex(statement["artifact_sha256"]):
        return "approval.statement.artifact_sha256 must be a SHA-256 digest"
    run_id = statement["run_id"]
    if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
        return "approval.statement.run_id must be a non-empty string or null"
    if statement["decision"] not in APPROVAL_DECISIONS:
        return "approval.statement.decision must be 'approve' or 'deny'"
    if not isinstance(statement["approved_at"], str) or not statement["approved_at"]:
        return "approval.statement.approved_at must be a timestamp string"
    signature = approval["signature"]
    if not isinstance(signature, str):
        return "approval.signature must be a base64 string"
    try:
        raw = base64.b64decode(signature, validate=True)
    except (binascii.Error, ValueError):
        return "approval.signature is not valid base64"
    if len(raw) != 64:
        return "approval.signature is not an Ed25519 signature (64 bytes)"
    return None


def authorised_approvers_error(value) -> Optional[str]:
    """Policy check for ``authorised_approvers``."""
    if not isinstance(value, dict):
        return "authorised_approvers must be an object of approver_id -> public key"
    for approver_id, pubkey in value.items():
        if not isinstance(approver_id, str) or not approver_id.strip():
            return "authorised_approvers keys must be non-empty strings"
        if not isinstance(pubkey, str) or _HEX64.fullmatch(pubkey) is None:
            return (f"authorised_approvers[{approver_id!r}] must be a raw Ed25519 "
                    f"public key in 64 lowercase hex digits")
    return None


def check_approval(
    approval: Mapping,
    authorised: Mapping[str, str],
    artifact_sha256: Optional[str],
    run_id: Optional[str],
) -> Tuple[Optional[str], str]:
    """Check a well-formed approval against the policy and the event.

    Returns (rule_id, reason): rule_id is None when the approval is valid and
    approves; APPROVAL_INVALID when the approver is not authorised, the
    signature does not verify, or the statement names another artefact or
    run; APPROVAL_DENIED when a valid statement denies."""
    approver_id = approval["approver_id"]
    statement = approval["statement"]
    pubkey_hex = authorised.get(approver_id)
    if pubkey_hex is None:
        return APPROVAL_INVALID, f"approver {approver_id} is not authorised by the policy"
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))
        key.verify(base64.b64decode(approval["signature"]), statement_bytes(statement))
    except Exception:  # InvalidSignature or an unusable key
        return APPROVAL_INVALID, f"approval signature of {approver_id} does not verify"
    if statement["artifact_sha256"] != artifact_sha256:
        return APPROVAL_INVALID, "approval names another artefact"
    if statement["run_id"] != run_id:
        return APPROVAL_INVALID, "approval names another run"
    if statement["decision"] != "approve":
        return APPROVAL_DENIED, f"approver {approver_id} denied deployment"
    return None, f"approved by {approver_id}"
