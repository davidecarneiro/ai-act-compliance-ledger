"""Serialise the evidence ledger as an OSCAL Assessment Result document.

Implements the recommendation discussed in Chapter 2 (Section 2.10) and in
Chapter 5 of the dissertation: producing machine-readable compliance evidence
in the OSCAL (Open Security Controls Assessment Language) format defined by
NIST. The output follows the OSCAL 1.1.2 ``assessment-results`` model and is
compatible with downstream tooling that ingests OSCAL JSON, such as the NIST
oscal-cli reference validator.

Mapping from the simulator's evidence record to OSCAL primitives:

* each evidence becomes one **observation** with a stable ``uuid`` derived
  from ``evidence_id`` (UUID v5 over the URN namespace);
* every record with a recognised decision produces a **finding** that points
  back to its observation, states a technical objective, and tags the AI Act
  articles in ``requirements_covered`` as ``supports-requirement`` ``props``
  in the ``aia-`` namespace, ``aia-10-3`` among them;
* the chain and signature results go into one **assessment-log entry** that
  records each outcome and whether it was computed here or supplied;
* the issuer is an organisation-level **party** carrying the key fingerprint;
  the subject of each observation is a component derived from the artefact.

The exporter is intentionally schema-faithful: every required OSCAL field is
populated, no extension fields outside the spec are added, and timestamps
follow ISO 8601 with timezone offset as required by the NIST schema.
"""

from __future__ import annotations

import json
import sys
import uuid
from base64 import b64decode
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

BASE_DIR = Path(__file__).parent
from paths import EXPERIMENTS_DIR  # noqa: E402
from canonical import record_body_bytes  # noqa: E402
from simulator import GENESIS_HASH, LEDGER_FILE, canonical_json, sha256_hex  # noqa: E402

# Fields derived from the canonical body; excluded before recomputing it.
DERIVED_FIELDS = {"record_hash", "issuer_signature", "chain_hash"}


def verify_chain_structure(ledger: List[dict]) -> bool:
    """Recompute record hashes and parent/chain links without a signing key.

    Return whether stored hash values and links match the supplied bodies.
    This structural check does not authenticate an issuer or detect suffix
    truncation and omitted events without an external inventory or anchor."""
    previous_chain = GENESIS_HASH
    for record in ledger:
        try:
            # Recomputed in the canonical form of the record's schema_version.
            recomputed = sha256_hex(record_body_bytes(record))
        except Exception:  # unsupported version, or no canonical form
            return False
        expected_chain = sha256_hex(
            (previous_chain + recomputed).encode("utf-8")
        )
        if (
            record.get("parent_hash") != previous_chain
            or recomputed != record.get("record_hash")
            or expected_chain != record.get("chain_hash")
        ):
            return False
        previous_chain = record.get("chain_hash", expected_chain)
    return True

# Stable OSCAL UUID namespace for the dissertation. UUID v5 derivations off this
# namespace produce reproducible UUIDs per evidence/finding across runs.
OSCAL_NS = uuid.UUID("12345678-1234-5e21-9999-000000000001")

CATALOG_ID = "ai-act-2024-1689"


def _uuid_for(label: str, prefix: str) -> str:
    return str(uuid.uuid5(OSCAL_NS, f"{prefix}:{label}"))


def _control_id(article: str) -> str:
    """Map ``Art.15`` style strings to OSCAL control IDs (``aia-15``)."""

    digits = "".join(c for c in article if c.isdigit() or c == "(" or c == ")")
    return "aia-" + digits.replace("(", "-").replace(")", "")


REDACTED_PLACEHOLDER = "[REDACTED — AI Act Art. 78 confidentiality]"


def _build_observation(record: dict, redacted: bool = False) -> dict:
    full_description = (
        f"Compliance Oracle decision '{record.get('decision')}' for "
        f"artifact {record.get('artifact_id')} at stage "
        f"{record.get('pipeline_stage')}. Reason: {record.get('reason')}."
    )
    full_evidence_description = (
        f"Hash-anchored evidence in the permissioned ledger. "
        f"record_hash={record.get('record_hash')}; "
        f"chain_hash={record.get('chain_hash')}; "
        f"signature_alg={record.get('sig_alg')}."
    )
    return {
        "uuid": _uuid_for(record["evidence_id"], "obs"),
        # The title must NOT copy arbitrary text from the source. scenario_id is
        # chosen by whoever integrates the oracle and may name a client, a
        # project or a dataset; in redacted mode it is replaced by evidence_id,
        # an opaque UUID that serves the same document-linking purpose.
        "title": (
            f"Pipeline event {record['evidence_id']}"
            if redacted
            else f"Pipeline event: {record.get('scenario_id')}"
        ),
        "description": REDACTED_PLACEHOLDER if redacted else full_description,
        "methods": ["AUTOMATED"],
        "types": ["finding"],
        "subjects": [
            {
                # In redacted mode the subject is derived from artifact_hash,
                # not from artifact_id. The UUID is a uuid5 over a published
                # namespace, so anyone holding a candidate artifact_id can
                # recompute the UUID and confirm a match: the identifier the
                # redaction suppresses in the text would still be verifiable
                # from the document. artifact_hash is the digest of the event
                # payload: it is already in the record and groups by event.
                "subject-uuid": _uuid_for(
                    record.get("artifact_hash", "unknown") if redacted
                    else record.get("artifact_id", "unknown"), "subj"
                ),
                "type": "component",
            }
        ],
        "relevant-evidence": [
            {
                "href": f"urn:evidence:{record['evidence_id']}",
                # Even in redacted mode the hash chain values are kept, as
                # links to the evidence. Whether a digest may be disclosed is
                # for the party disclosing it to assess.
                "description": full_evidence_description,
            }
        ],
        "collected": record.get("timestamp"),
        "props": [
            {"name": "decision", "value": record.get("decision", "")},
            {
                "name": "reason",
                "value": (
                    REDACTED_PLACEHOLDER if redacted else record.get("reason", "")
                ),
            },
            {"name": "issuer", "value": record.get("issuer_id", "")},
            {
                "name": "issuer_pubkey_fingerprint",
                "value": record.get("issuer_pubkey_fingerprint", ""),
            },
            {
                "name": "redaction_applied",
                "value": "true" if redacted else "false",
            },
        ],
    }


# Map from the rule that fired, as named in the Oracle's own reason string, to
# the AI Act article that rule enforces. The tokens below are the stable parts
# of the f-strings produced by ``ComplianceOracle._validate_compliance``; the
# coupling is deliberate and is surfaced in the document through the
# ``objective-basis`` property, so a reader can see how the target was chosen.
# Technical objectives, versioned, each with the proposition it asserts and
# the AI Act articles it helps to assess. The separation matters: a drift
# alert above threshold means the monitoring worked, not that Art. 72 was
# breached, and a recorded rejection means the logging duty of Art. 12 was
# served, not failed. Publishing satisfied/not-satisfied against an article
# collapsed those two different propositions into one.
OBJECTIVES_VERSION = "1.0"

TECHNICAL_OBJECTIVES = {
    "policy.all_checks_passed": (
        "obj-thresholds-met",
        "Every configured threshold evaluated for this event was met.",
        True,
    ),
    "threshold.precision": (
        "obj-precision-threshold",
        "The declared precision met the configured minimum.",
        False,
    ),
    "threshold.fairness": (
        "obj-fairness-threshold",
        "The declared demographic parity difference stayed within the "
        "configured maximum.",
        False,
    ),
    "oversight.approval_missing": (
        "obj-human-approval-recorded",
        "A human approval was recorded for a high-risk event.",
        False,
    ),
    "monitoring.drift_alert": (
        "obj-drift-alert-raised",
        "A drift indicator above threshold raised an alert and was recorded.",
        True,
    ),
    "incident.reportable": (
        "obj-incident-recorded",
        "A serious incident was recorded and escalated for mandatory "
        "handling.",
        True,
    ),
    "audit.query_recorded": (
        "obj-audit-query-recorded",
        "An integrity-verification request was recorded on the chain.",
        True,
    ),
    "input.malformed": (
        "obj-input-well-formed",
        "The event satisfied the input contract of the policy engine.",
        False,
    ),
}

UNKNOWN_OBJECTIVE = (
    "obj-event-recorded",
    "The event was recorded on the chain.",
    True,
)


# Records written before rule_id existed carry the rule only in prose. This
# mapping recovers it for those, and nothing else: it is a compatibility path
# for preserved runs, marked as such in the exported document so no reader
# mistakes a recovered identifier for one the engine wrote.
LEGACY_REASON_RULES = (
    ("invalid input:", "input.malformed"),
    ("demographic parity diff", "threshold.fairness"),
    ("missing human approval", "oversight.approval_missing"),
    ("precision", "threshold.precision"),
    ("drift score", "monitoring.drift_alert"),
    ("serious incident", "incident.reportable"),
    ("audit query", "audit.query_recorded"),
    ("all policy checks passed", "policy.all_checks_passed"),
)


def _rule_id_of(record: dict) -> tuple[str, bool]:
    """Return ``(rule_id, is_legacy)`` for a record."""
    rule_id = record.get("rule_id")
    if isinstance(rule_id, str) and rule_id:
        return rule_id, False
    reason = (record.get("reason") or "").lower()
    for token, recovered in LEGACY_REASON_RULES:
        if token in reason:
            return recovered, True
    return "", True


def _objective_for(record: dict) -> tuple[str, str, bool]:
    """Resolve the technical objective from the stable rule identifier."""
    rule_id, _ = _rule_id_of(record)
    return TECHNICAL_OBJECTIVES.get(rule_id, UNKNOWN_OBJECTIVE)


def _build_finding(record: dict, redacted: bool = False) -> dict:
    # AI Act articles are attached to the finding as OSCAL ``props`` rather
    # than ``related-controls``: the ``finding`` assembly does not allow
    # ``related-controls`` (a result-level construct), so emitting it there
    # makes the document fail the NIST OSCAL 1.1.2 schema. ``props`` is the
    # schema-valid place to carry a per-finding requirement tag, and it is
    # preserved under redaction because it is an identifier, not free text.
    objective_id, proposition, satisfied = _objective_for(record)
    rule_id, legacy = _rule_id_of(record)

    props = [
        # The articles this evidence helps to assess. They are support, not
        # verdicts: no legal assessment is performed here.
        {
            "name": "supports-requirement",
            "value": _control_id(article),
            "class": "ai-act-article",
        }
        for article in record.get("requirements_covered", [])
    ]
    props.extend(
        [
            {
                "name": "objective-proposition",
                "value": proposition,
                "class": "technical-objective",
            },
            {
                "name": "objectives-version",
                "value": OBJECTIVES_VERSION,
                "class": "technical-objective",
            },
            {
                "name": "rule-id",
                "value": rule_id or "unknown",
                "class": "technical-objective",
            },
            {
                "name": "rule-id-source",
                "value": "recovered-from-reason" if legacy else "written-by-engine",
                "class": "technical-objective",
            },
            {
                "name": "legal-assessment",
                "value": "not-performed",
                "class": "technical-objective",
            },
        ]
    )
    # The policy_id is a free-form label: it can name a client or a project.
    # The policy_hash identifies the SAME policy content without revealing text.
    # Redacted mode emits the hash, which serves the audit purpose (knowing
    # which policy version produced the decision) without opening a channel.
    if redacted:
        if record.get("policy_hash"):
            props.append(
                {
                    "name": "policy-hash",
                    "value": record["policy_hash"],
                    "class": "technical-objective",
                }
            )
    elif record.get("policy_id"):
        props.append(
            {
                "name": "policy-id",
                "value": record["policy_id"],
                "class": "technical-objective",
            }
        )

    full_finding_description = (
        f"The Compliance Oracle rendered decision "
        f"'{record.get('decision')}' on {record.get('timestamp')}. "
        f"Technical objective: {proposition} "
        f"This states a technical fact about the evaluation, not a judgement "
        f"on compliance with "
        f"{', '.join(record.get('requirements_covered', [])) or 'any article'}."
    )
    return {
        "uuid": _uuid_for(record["evidence_id"], "finding"),
        # Same reason as the observation title. The objective_id and the decision
        # come from closed sets; the scenario_id is free text and leaves the document.
        "title": (
            f"Technical objective {objective_id}: {record.get('decision')}"
            if redacted
            else (
                f"Technical objective {objective_id}: {record.get('decision')} "
                f"for {record.get('scenario_id')}"
            )
        ),
        "description": (
            REDACTED_PLACEHOLDER if redacted else full_finding_description
        ),
        "props": props,
        "target": {
            "type": "objective-id",
            "target-id": objective_id,
            "status": {"state": "satisfied" if satisfied else "not-satisfied"},
        },
        "implementation-statement-uuid": _uuid_for(CATALOG_ID, "impl"),
        "related-observations": [
            {"observation-uuid": _uuid_for(record["evidence_id"], "obs")}
        ],
    }


def _strip_none(value):
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(v) for v in value]
    return value


def load_issuer_public_key(
    issuer_id: str = "compliance-oracle-v1",
    keys_dir: Path | None = None,
) -> Ed25519PublicKey | None:
    """Load only the issuer's public key, returning ``None`` when unavailable.

    Verification never needs the private key. Loading the public half alone
    keeps the exporter in the position of an external auditor, and lets a
    ledger signed elsewhere still be verified when its public key is present.
    """
    keys_dir = keys_dir or BASE_DIR / "keys"
    path = keys_dir / f"{issuer_id}.ed25519.pub.pem"
    if not path.exists():
        return None
    try:
        key = serialization.load_pem_public_key(path.read_bytes())
    except Exception:
        return None
    return key if isinstance(key, Ed25519PublicKey) else None


def _fingerprint_of(public_key: Ed25519PublicKey) -> str:
    """SHA-256 fingerprint of a public key, matching the simulator's format."""
    import hashlib

    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()


def verify_signatures(
    ledger: List[dict],
    public_key: Ed25519PublicKey | None = None,
    keys_dir: Path | None = None,
) -> bool | None:
    """Verify each record's signature against the key of *its own* issuer.

    A ledger is not necessarily single-issuer, and a key may have rotated, so
    the issuer is read from each record rather than assumed. ``None`` is
    returned when some record's key cannot be resolved: that is a different
    statement from ``False``, which asserts that a signature failed. Reporting
    the two as one would let an unknown issuer read as a forgery, or a forgery
    read as an unchecked record.
    """
    if not ledger:
        return True

    cache: dict[str, Ed25519PublicKey | None] = {}
    unresolved = False

    for record in ledger:
        issuer_id = record.get("issuer_id")
        if public_key is not None:
            key = public_key
        else:
            if issuer_id not in cache:
                cache[issuer_id] = (
                    load_issuer_public_key(issuer_id, keys_dir)
                    if isinstance(issuer_id, str)
                    else None
                )
            key = cache[issuer_id]

        if key is None:
            unresolved = True
            continue

        recorded = record.get("issuer_pubkey_fingerprint")
        if recorded and recorded != _fingerprint_of(key):
            unresolved = True
            continue

        try:
            key.verify(
                b64decode(record.get("issuer_signature", "")),
                record_body_bytes(record),
            )
        except Exception:  # InvalidSignature, malformed base64, missing field
            return False

    return None if unresolved else True


def _results_description(ledger: List[dict]) -> str:
    """Describe the ledger actually exported, not a fixed example.

    The same exporter serves the six canonical scenarios, a 1750-record
    industrial run and a three-event incident. A sentence naming one of them
    would be false in the other documents.
    """
    total = len(ledger)
    # A record written before scenario_id was constrained, or one produced
    # elsewhere, may carry a list or an object here. Counting distinct values
    # must not be what makes the whole export fail, so anything unhashable is
    # folded to its canonical serialisation for counting purposes only.
    scenarios = set()
    for record in ledger:
        value = record.get("scenario_id")
        if not value:
            continue
        try:
            scenarios.add(value)
        except TypeError:
            scenarios.add(canonical_json(value).decode("utf-8"))
    noun = "record" if total == 1 else "records"
    n_scen = len(scenarios)
    scen_noun = "identifier" if n_scen == 1 else "identifiers"
    return (
        f"{total} evidence {noun} produced by the Compliance Oracle "
        f"prototype across {n_scen} distinct scenario {scen_noun}."
    )


def _verification_narrative(
    chain_valid: bool,
    signatures_verified: bool | None,
    chain_source: str,
    signature_source: str,
) -> str:
    """Describe what the exporter actually ran, never what it assumed.

    The two checks carry their own provenance, because the caller may supply
    either independently. Deriving one from the other let a caller-supplied
    signature result be narrated as a local execution, and let a signature
    check that was never attempted be explained as an unresolvable key.
    """
    detected = "no modification was detected" if chain_valid else (
        "a modification was detected"
    )
    if chain_source == "caller":
        parts = [
            "the chain result was supplied by the caller and not recomputed "
            f"by this exporter; the caller reports that {detected}"
        ]
    else:
        parts = [
            "verify_chain_structure() recomputed each record_hash from the "
            f"canonical body and re-derived the chain links, and {detected}"
        ]
    if signature_source == "not-attempted":
        parts.append(
            "the Ed25519 signatures were not checked at all: the caller "
            "supplied a chain result without a signature result, and this "
            "exporter did not attempt to resolve any key"
        )
    elif signatures_verified is None:
        parts.append(
            "the Ed25519 signatures were not fully checked, because at least "
            "one record names an issuer whose public key the exporter could "
            "not resolve, or whose key on disk does not match the fingerprint "
            "the record carries"
        )
    elif signature_source == "caller":
        verdict = "verified" if signatures_verified else "failing verification"
        parts.append(
            f"the caller reports the Ed25519 signatures as {verdict}; this "
            "exporter did not check them"
        )
    elif signatures_verified:
        parts.append(
            "each record's Ed25519 signature was verified against the "
            "issuer's public key"
        )
    else:
        parts.append("at least one Ed25519 signature failed verification")
    parts.append(
        "suffix truncation and events that were never written lie outside "
        "both checks, because detecting them needs an anchor kept outside "
        "the file"
    )
    return "; ".join(parts) + "."


def to_oscal_sar(
    ledger: List[dict],
    chain_valid: bool | None = None,
    redacted: bool = False,
    signatures_verified: bool | None = None,
) -> dict:
    """Build an OSCAL Assessment Results document from a ledger snapshot.

    Redacted mode suppresses selected free-text fields in the export while
    retaining evidence links, hash anchors and article mappings. It does not
    change the underlying ledger or perform a legal compliance assessment.

    Chain and signature results are recorded separately, with their source."""

    # Recompute rather than assume. The two properties are reported
    # separately because they are separate checks: the chain link is
    # key-free, the signature needs the issuer's public key. A caller
    # that already ran the full verify_chain() may supply both.
    chain_source = "caller" if chain_valid is not None else "computed"
    if signatures_verified is not None:
        signature_source = "caller"
    elif chain_source == "computed":
        signature_source = "computed"
    else:
        # The caller gave a chain result and no signature result. Resolving
        # keys here would answer a question it did not ask, so nothing is
        # attempted and the document says exactly that.
        signature_source = "not-attempted"

    if chain_valid is None:
        chain_valid = verify_chain_structure(ledger)
    if signature_source == "computed":
        signatures_verified = verify_signatures(ledger)

    now = datetime.now(timezone.utc).isoformat()
    issuer_fingerprint = (
        ledger[0].get("issuer_pubkey_fingerprint") if ledger else "unknown"
    )

    observations = [_build_observation(r, redacted=redacted) for r in ledger]
    findings = [
        _build_finding(r, redacted=redacted)
        for r in ledger
        if r.get("decision") in ("approved", "rejected", "escalated", "verified")
    ]

    document = {
        "assessment-results": {
            "uuid": _uuid_for(now, "ar"),
            "metadata": {
                "title": (
                    "AI Act Compliance Assessment Results — "
                    "Compliance Oracle prototype"
                ),
                "last-modified": now,
                "version": "1.0.0",
                "oscal-version": "1.1.2",
                "parties": [
                    {
                        "uuid": _uuid_for(issuer_fingerprint, "party"),
                        "type": "organization",
                        "name": "Compliance Oracle issuer",
                        "props": [
                            {
                                "name": "ed25519-fingerprint",
                                "value": issuer_fingerprint,
                            }
                        ],
                    }
                ],
            },
            "import-ap": {
                "href": f"urn:ai-act:assessment-plan:{CATALOG_ID}",
            },
            "results": [
                {
                    "uuid": _uuid_for("results-0", "res"),
                    "title": "Compliance Oracle execution",
                    "description": _results_description(ledger),
                    "start": ledger[0]["timestamp"] if ledger else now,
                    "end": ledger[-1]["timestamp"] if ledger else now,
                    "reviewed-controls": {
                        "control-selections": [
                            {
                                "include-all": {},
                            }
                        ]
                    },
                    "observations": observations,
                    "findings": findings,
                    "assessment-log": {
                        "entries": [
                            {
                                "uuid": _uuid_for("chain-verify", "log"),
                                "title": "Ledger integrity verification",
                                "description": _verification_narrative(
                                    chain_valid,
                                    signatures_verified,
                                    chain_source,
                                    signature_source,
                                ),
                                "start": now,
                                "end": now,
                                "logged-by": [
                                    {
                                        "party-uuid": _uuid_for(
                                            issuer_fingerprint, "party"
                                        )
                                    }
                                ],
                                "props": [
                                    {
                                        "name": "chain_valid",
                                        "value": "true" if chain_valid else "false",
                                    },
                                    {
                                        "name": "signatures_verified",
                                        "value": (
                                            "not-checked"
                                            if signatures_verified is None
                                            else (
                                                "true"
                                                if signatures_verified
                                                else "false"
                                            )
                                        ),
                                    },
                                    {
                                        "name": "chain_verification_source",
                                        "value": (
                                            "computed-by-exporter"
                                            if chain_source == "computed"
                                            else "supplied-by-caller"
                                        ),
                                    },
                                    {
                                        "name": "signature_verification_source",
                                        "value": {
                                            "computed": "computed-by-exporter",
                                            "caller": "supplied-by-caller",
                                            "not-attempted": "not-attempted",
                                        }[signature_source],
                                    },
                                    {
                                        "name": "records_total",
                                        "value": str(len(ledger)),
                                    },
                                ],
                            }
                        ]
                    },
                }
            ],
        }
    }
    return _strip_none(document)


def export_oscal(
    ledger_file: Path = LEDGER_FILE,
    output_dir: Path = EXPERIMENTS_DIR,
    redacted: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
    document = to_oscal_sar(ledger, redacted=redacted)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "_redacted" if redacted else ""
    out_path = output_dir / f"oscal_assessment_results{suffix}_{timestamp}.json"
    out_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    if not LEDGER_FILE.exists():
        print(
            "[oscal] no ledger.json found; run `python3 simulator.py` first.",
            file=sys.stderr,
        )
        return 1
    full = export_oscal(redacted=False)
    redacted = export_oscal(redacted=True)
    print(f"oscal_sar={full}")
    print(f"oscal_sar_redacted={redacted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
