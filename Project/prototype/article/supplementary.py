"""Generate the tables of the supplementary material from the result files.

Writes LaTeX fragments to ``Project/manuscript/supplementary/generated/``:

* ``s1_fields.tex``: the fields of a version 2 record, from the JSON Schema;
* ``s2_matrix.tex`` and ``s2_missing.tex``: the full Q1--Q14 matrix of WP5;
* ``s4_boundary.tex``: the 24 cases of the boundary matrix and their outcome;
* ``s5_complete.json`` and ``s5_redacted.json``: the finding of Figure 4, whole;
* ``s6_protocols.tex``: each protocol, when it was recorded and amended.

Every number comes from a file in the repository; run from any directory:
``python3 Project/prototype/article/supplementary.py``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
REPO = PROJECT.parent
OUT = PROJECT / "manuscript" / "supplementary" / "generated"

SCHEMA = PROJECT / "schemas" / "evidence_record_v2.schema.json"
WP5 = PROJECT / "experiments" / "article" / "wp5" / "answerability_20261119T215838Z_fabric_q12.json"
BOUNDARY = PROJECT / "prototype" / "fabric_migration" / "chaincode" / "testdata_fronteiras_v2.json"
FIGURES = PROJECT / "experiments" / "article" / "figures"

# The labels of the 24 boundary cases, in the order of the matrix
# (compliance_ledger_sim/tests/test_fronteiras.py: BOUNDARY_MATRIX, then BOUNDARY_MATRIX_V2).
BOUNDARY_LABELS = [
    "scenario named", "scenario null", "scenario absent", "scenario empty", "scenario in Unicode",
    "scenario is a list", "scenario with a lone surrogate", "metric name with a lone surrogate",
    "artefact identifier is a number", "precision below the threshold", "parity above the threshold",
    "high risk without approval", "drift above the threshold", "metric is NaN",
    "metric keys of mixed type", "metric is text",
    "run identifier (v2)", "run identifier is a list (v2)", "artefact in the store (v2)",
    "artefact digest in upper case (v2)", "store reference without a digest (v2)",
    "store reference to another digest (v2)", "integer beyond $2^{53}-1$ (v2)",
    "payload key with a lone surrogate (v2)",
]

GROUPS = [
    ("Identity", ["evidence_id", "scenario_id", "event_type", "artifact_id", "artifact_type",
                  "pipeline_stage", "timestamp", "run_id"]),
    ("Content commitments", ["payload_hash", "artifact_hash", "off_chain_ref"]),
    ("Decision", ["decision", "reason", "rule_id", "metrics", "decision_inputs", "policy_id", "policy_hash"]),
    ("Normative binding", ["supports_requirements"]),
    ("Provenance", ["issuer_id", "issuer_pubkey_fingerprint", "sig_alg", "hash_alg", "schema_version"]),
    ("Chain", ["parent_hash", "record_hash", "issuer_signature", "chain_hash"]),
]

CODE = {"yes": "Y", "partial": "P", "no": "N", "n/a": "--"}


def tex(text: str) -> str:
    """Escape plain text for LaTeX (no math, no commands)."""
    out = str(text)
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                 ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\^{}")):
        out = out.replace(a, b)
    return out


def path(name: str) -> str:
    return r"\path{" + name + "}"


def kind(spec: dict) -> str:
    if "const" in spec:
        return f"constant {json.dumps(spec['const'])}"
    if "enum" in spec:
        return "one of a closed set"
    if "anyOf" in spec:
        inner = [kind(s) for s in spec["anyOf"] if s.get("type") != "null"]
        return (inner[0] if inner else "object") + " or null"
    if spec.get("pattern", "").startswith("^[0-9a-f]{64}"):
        return "SHA-256, hex"
    if spec.get("format") == "date-time":
        return "date-time"
    return spec.get("type", "object") if isinstance(spec.get("type"), str) else "/".join(spec["type"])


def s1_fields() -> str:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    props = schema["properties"]
    rows = []
    for group, fields in GROUPS:
        for i, name in enumerate(fields):
            desc = props[name].get("description", "").split(". ", 1)[-1]
            rows.append(f"{group if i == 0 else ''} & {path(name)} & {tex(kind(props[name]))} & {tex(desc)} \\\\")
        rows.append(r"\addlinespace")
    assert {f for _, fs in GROUPS for f in fs} == set(props), "every schema field is in one group"
    return "\n".join(rows[:-1]) + "\n"


def s2_matrix(data: dict) -> tuple[str, str]:
    rows, missing = [], []
    for q, cells in data["matrix"].items():
        text = data["questions"][q]
        codes = []
        for c in ("A", "B", "C", "D"):
            cell = cells[c]
            codes.append(f"{CODE[cell['answerable']]} / {CODE[cell['verifiable']]}")
            if cell.get("missing"):
                missing.append(f"{q} & {c} & {tex('; '.join(cell['missing']))} \\\\")
        rows.append(f"{q} & {tex(text)} & " + " & ".join(codes) + r" \\")
    return "\n".join(rows) + "\n", "\n".join(missing) + "\n"


def s4_boundary() -> str:
    records = json.loads(BOUNDARY.read_text(encoding="utf-8"))
    assert len(records) == len(BOUNDARY_LABELS) == 24
    rows = []
    for i, (label, r) in enumerate(zip(BOUNDARY_LABELS, records), 1):
        kept = "yes" if r.get("metrics") else "no"
        rows.append(f"{i} & {label} & {r['decision']} & {path(r['rule_id'])} & {kept} \\\\")
    return "\n".join(rows) + "\n"


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def s6_protocols() -> str:
    names = {
        "wp3_ablation.md": "Cost ablation, arms A, B0, B, B+ (Section 6.5)",
        "wp4_credit_case.md": "Credit-scoring case (Section 6.3)",
        "wp4_supplementary_seed_stability.md": "Stability over 500 partitions, post hoc (Section 6.3)",
        "tamper_detection.md": "Tamper experiment T1--T9b (Section 6.4)",
        "wp5_answerability.md": "Audit questions Q1--Q14 (Section 6.7)",
        "wp7_fabric_anchoring.md": "Anchoring on Fabric (Section 6.6)",
        "RUNNING_MEASUREMENTS.md": "Instructions and record of the measurement machine (Sections 6.5, 6.6)",
    }
    rows = []
    for name, what in names.items():
        log = git("log", "--format=%h %ad", "--date=short", "--", f"Project/protocols/{name}").splitlines()
        first = log[-1].split()
        later = ", ".join(f"{h} ({d})" for h, d in (line.split() for line in reversed(log[:-1]))) or "none"
        rows.append(f"{path(name)} & {what} & {first[0]} ({first[1]}) & {later} \\\\")
    return "\n".join(rows) + "\n"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.loads(WP5.read_text(encoding="utf-8"))
    matrix, missing = s2_matrix(data)
    files = {
        "s1_fields.tex": s1_fields(),
        "s2_matrix.tex": matrix,
        "s2_missing.tex": missing,
        "s4_boundary.tex": s4_boundary(),
        "s6_protocols.tex": s6_protocols(),
    }
    for name, content in files.items():
        (OUT / name).write_text(content, encoding="utf-8")
    for variant in ("complete", "redacted"):
        excerpt = json.loads((FIGURES / f"F6_finding_{variant}.json").read_text(encoding="utf-8"))
        (OUT / f"s5_{variant}.json").write_text(json.dumps(excerpt, indent=1, ensure_ascii=False) + "\n",
                                                encoding="utf-8")
    (OUT / "SOURCES.txt").write_text(
        "Generated by Project/prototype/article/supplementary.py from:\n"
        + "\n".join(str(p.relative_to(REPO)) for p in (SCHEMA, WP5, BOUNDARY, FIGURES)) + "\n",
        encoding="utf-8")
    print(f"wrote {len(files) + 2} files to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
