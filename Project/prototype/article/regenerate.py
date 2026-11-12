#!/usr/bin/env python3
"""Regenerate the dissertation's runs under schema version 2 (WP9).

    python3 regenerate.py [--multiflow DIR]

Writes ``experiments/article/wp9/run_<UTC time>/`` with four runs, each with
its ledger (append-only JSONL), OSCAL exports (complete and redacted), the
re-execution of every decision and a check of the chain:

* ``scenarios``: the six canonical scenarios;
* ``incident``: the serious-incident sequence (Art. 73);
* ``multiflow_muvu`` and ``multiflow_steel``: the two MultiFlow runs on real
  industrial data, **replayed** from the platform's CSV files through the
  bridge's own logic (``multiflow_bridge/bridge.run``), with the messages the
  injection script publishes. The live runs went through Kafka; the replay
  does not, and says so. Each replayed batch is compared with the published
  version 1 ledger of the live run: same batch, same decision, same reason
  (which carries the drift score).

The MultiFlow datasets are read from ``--multiflow`` or ``$MULTIFLOW`` (a
clone of github.com/davidecarneiro/multiflow at the commit recorded with the
published runs); without either, the repository is cloned into a cache folder
at that commit.

``summary.json`` holds the rows of Table T8 and the comparisons.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
PROTOTYPE = HERE.parent
SIM = PROTOTYPE / "compliance_ledger_sim"
BRIDGE = PROTOTYPE / "multiflow_bridge"
os.environ.setdefault("ORACLE_PATH", str(SIM))
for p in (SIM, BRIDGE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import oscal_exporter  # noqa: E402
from canonical import SCHEMA_V2  # noqa: E402
from ledger_store import read_ledger  # noqa: E402
from paths import EXPERIMENTS_DIR, PUBLISHED_DIR  # noqa: E402
from reexecution import DEFAULT_POLICY_ARCHIVE, MATCH, reexecute_ledger  # noqa: E402
from scenarios import build_incident_scenario, build_scenarios  # noqa: E402
from simulator import ComplianceOracle, requirements_of  # noqa: E402

MULTIFLOW_REPO = "https://github.com/davidecarneiro/multiflow.git"
MULTIFLOW_COMMIT = "a0a97863181eb4cc158c32bad70cf6a1d415081c"
REPLAYS = {
    "multiflow_muvu": {"files": ["Muvu_Janeiro.csv", "Muvu_Marco.csv"],
                       "published": "runs/multiflow_run_real/ledger.json"},
    "multiflow_steel": {"files": ["Steel_Industry.csv"],
                        "published": "runs/multiflow_run_steel/ledger.json"},
}
OUT_DIR = EXPERIMENTS_DIR / "wp9"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def multiflow_datasets(explicit: Path | None) -> Path:
    """The datasets folder of a MultiFlow clone at the recorded commit."""
    root = explicit or (Path(os.environ["MULTIFLOW"]) if os.environ.get("MULTIFLOW") else None)
    if root is None:
        root = Path.home() / ".cache" / "ai-act-article" / "multiflow"
        if not root.exists():
            root.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "-q", "--filter=blob:none", MULTIFLOW_REPO, str(root)],
                           check=True)
        subprocess.run(["git", "-C", str(root), "checkout", "-q", MULTIFLOW_COMMIT], check=True)
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()
    if head and head != MULTIFLOW_COMMIT:
        print(f"note: MultiFlow at {head[:7]}, not the recorded {MULTIFLOW_COMMIT[:7]}")
    return root / "datasets"


def _export(folder: Path, ledger: List[dict], chain_ok: bool) -> None:
    for redacted, name in ((False, "complete"), (True, "redacted")):
        doc = oscal_exporter.to_oscal_sar(ledger, chain_valid=chain_ok, redacted=redacted,
                                          signatures_verified=chain_ok)
        (folder / f"oscal_assessment_results_{name}.json").write_text(
            json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _row(name: str, folder: Path, oracle: ComplianceOracle, archive: Path, **extra) -> Dict:
    ledger = read_ledger(oracle.ledger_file)
    report = oracle.verify_chain()
    chain_ok = report.valid == report.total == len(ledger)
    _export(folder, ledger, chain_ok)
    rex = reexecute_ledger(ledger, archive)
    (folder / "reexecution.json").write_text(json.dumps({
        "total": rex["total"], "counts": rex["counts"],
        "results": [{"evidence_id": r.evidence_id, "status": r.status,
                     "differences": r.differences} for r in rex["results"]],
    }, indent=1) + "\n", encoding="utf-8")
    decisions = Counter(r["decision"] for r in ledger)
    return {
        "run": name,
        "events": len(ledger),
        "decisions": dict(sorted(decisions.items())),
        "chain": f"{report.valid}/{report.total}",
        "chain_valid": chain_ok,
        "reexecution": rex["counts"],
        "rules": dict(sorted(Counter(r["rule_id"] for r in ledger).items())),
        **extra,
    }


def _engine(folder: Path) -> ComplianceOracle:
    policy = json.loads((SIM / "configs" / "policies.json").read_text(encoding="utf-8"))
    (folder / "policies.json").write_text(json.dumps(policy), encoding="utf-8")
    oracle = ComplianceOracle(policy_file=folder / "policies.json",
                              ledger_file=folder / "ledger.jsonl", schema_version=SCHEMA_V2)
    oracle.reset_ledger()
    return oracle


def run_events(folder: Path, name: str, events: List[dict]) -> Dict:
    folder.mkdir(parents=True)
    oracle = _engine(folder)
    for event in events:
        oracle.process_mlops_event(event)
    extra = {}
    if name == "incident":
        ledger = read_ledger(oracle.ledger_file)
        extra["art73_supported"] = f"{sum('Art.73' in requirements_of(r) for r in ledger)}/{len(ledger)}"
    return _row(name, folder, oracle, folder / "policies_archive", **extra)


def replay(folder: Path, name: str, datasets: Path) -> Dict:
    """Replay the CSV rows through the bridge, as the injection script publishes them."""
    import bridge

    spec = REPLAYS[name]
    folder.mkdir(parents=True)
    bridge.OUT_DIR = str(folder)
    messages = []
    files = {}
    for filename in spec["files"]:
        path = datasets / filename
        files[filename] = {"sha256": _sha(path)}
        # kafka-console-producer publishes one message per line; the injection
        # script wraps each line as {"csv_data": "<line>"}.
        lines = path.read_text(encoding="utf-8").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        files[filename]["lines"] = len(lines)
        messages += [{"csv_data": line} for line in lines]
    stats: Dict = {}
    oracle = bridge.run(iter(messages), stats)

    ledger = read_ledger(oracle.ledger_file)
    published = json.loads((PUBLISHED_DIR / spec["published"]).read_text(encoding="utf-8"))
    same = [(a["scenario_id"], a["decision"], a["reason"]) ==
            (b["scenario_id"], b["decision"], b["reason"]) for a, b in zip(ledger, published)]
    comparison = {
        "published_ledger": spec["published"],
        "published_events": len(published),
        "same_length": len(ledger) == len(published),
        "batches_identical": sum(same),
        "first_difference": None if all(same) else same.index(False) + 1,
        "compared": "scenario_id, decision and reason (which carries the drift score) per batch",
    }
    return _row(name, folder, oracle, DEFAULT_POLICY_ARCHIVE, replay=True, datasets=files,
                bridge_stats=stats, comparison_with_published=comparison)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--multiflow", type=Path, default=None,
                        help="MultiFlow clone (its datasets/ folder is read)")
    parser.add_argument("--skip-multiflow", action="store_true")
    args = parser.parse_args(argv)

    started = datetime.now(timezone.utc)
    out = OUT_DIR / f"run_{started.strftime('%Y%m%dT%H%M%SZ')}"
    out.mkdir(parents=True)
    rows = [run_events(out / "scenarios", "scenarios", build_scenarios()),
            run_events(out / "incident", "incident", build_incident_scenario())]
    multiflow = None
    if not args.skip_multiflow:
        datasets = multiflow_datasets(args.multiflow)
        multiflow = {"repository": MULTIFLOW_REPO, "commit": MULTIFLOW_COMMIT}
        for name in REPLAYS:
            rows.append(replay(out / name, name, datasets))
    summary = {
        "generated_at": started.isoformat(),
        "schema_version": SCHEMA_V2,
        "environment": {"platform": platform.platform(), "python": platform.python_version()},
        "multiflow": multiflow,
        "table_t8": rows,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    for r in rows:
        line = f"{r['run']:16} {r['events']:5} events  {r['decisions']}  chain {r['chain']}  re-execution {r['reexecution']}"
        if "comparison_with_published" in r:
            c = r["comparison_with_published"]
            line += f"  identical to published: {c['batches_identical']}/{c['published_events']}"
        print(line)
    print(f"saved to {out}")
    return 0 if all(r["chain_valid"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
