"""Sensitivity analysis of the Compliance Oracle policy thresholds.

Runs the six-scenario suite repeatedly while sweeping the three policy
thresholds that drive most rejection decisions. The output supports the
discussion in Section 5.4 of the dissertation: how robust is the artefact's
behaviour to plausible variations in policy choice?

The sweep is intentionally coarse (5 precision x 3 fairness x 3 drift values
-> 45 combinations)
to keep the run reproducible in seconds while still illustrating the
qualitative impact of each parameter on the decision distribution.
"""

from __future__ import annotations

import csv
import itertools
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

from scenarios import build_scenarios
from simulator import ComplianceOracle

from paths import EXPERIMENTS_DIR  # noqa: E402

# Grid chosen to span meaningful boundaries of the six fixed scenarios:
# precision values in scenarios are {0.74, 0.85, 0.86, 0.89, 0.90, 0.99},
# demographic_parity_diff in {0.0, 0.02, 0.03, 0.09}, drift in {0.01, 0.03,
# 0.04, 0.05, 0.06, 0.22}. The grid below crosses each boundary at least once.
PRECISION_GRID = [0.70, 0.75, 0.80, 0.85, 0.90]
FAIRNESS_GRID = [0.02, 0.05, 0.10]
DRIFT_GRID = [0.05, 0.15, 0.25]


def run_one_combination(
    min_precision: float,
    max_dp_diff: float,
    drift_threshold: float,
) -> dict:
    # One ledger per combination: the sweep must not write over the canonical
    # six-scenario ledger, which is the artefact the dissertation cites.
    workdir = Path(tempfile.mkdtemp(prefix="sensitivity_"))
    oracle = ComplianceOracle(ledger_file=workdir / "ledger.json")
    oracle.set_policies({
        "min_precision": min_precision,
        "max_demographic_parity_diff": max_dp_diff,
        "require_human_approval_for_high_risk": True,
        "drift_alert_threshold": drift_threshold,
    })
    oracle.reset_ledger()
    counts = {
        "approved": 0,
        "rejected": 0,
        "escalated": 0,
        "verified": 0,
    }
    for event in build_scenarios():
        record = oracle.process_mlops_event(event)
        decision = record["decision"]
        counts[decision] = counts.get(decision, 0) + 1
    total = sum(counts.values())
    return {
        "min_precision": min_precision,
        "max_demographic_parity_diff": max_dp_diff,
        "drift_alert_threshold": drift_threshold,
        "approved": counts["approved"],
        "rejected": counts["rejected"],
        "escalated": counts["escalated"],
        "verified": counts["verified"],
        "total": total,
        "rejection_rate": round(counts["rejected"] / max(1, total), 3),
        "escalation_rate": round(counts["escalated"] / max(1, total), 3),
        "approval_rate": round(counts["approved"] / max(1, total), 3),
    }


def run() -> Path:
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    results: List[dict] = []
    print("--- sensitivity analysis (45 combinations) ---")
    combinations = itertools.product(PRECISION_GRID, FAIRNESS_GRID, DRIFT_GRID)
    for min_p, max_dp, drift in combinations:
        outcome = run_one_combination(min_p, max_dp, drift)
        results.append(outcome)
        print(
            f"min_p={min_p} max_dp={max_dp} drift={drift} "
            f"-> approved={outcome['approved']} rejected={outcome['rejected']} "
            f"escalated={outcome['escalated']}"
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = EXPERIMENTS_DIR / f"sensitivity_analysis_{timestamp}.csv"
    json_path = EXPERIMENTS_DIR / f"sensitivity_analysis_{timestamp}.json"

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "grid": {
            "min_precision": PRECISION_GRID,
            "max_demographic_parity_diff": FAIRNESS_GRID,
            "drift_alert_threshold": DRIFT_GRID,
        },
        "combinations": len(results),
        "summary": {
            "min_rejection_rate": min(r["rejection_rate"] for r in results),
            "max_rejection_rate": max(r["rejection_rate"] for r in results),
            "min_approval_rate": min(r["approval_rate"] for r in results),
            "max_approval_rate": max(r["approval_rate"] for r in results),
        },
        "results": results,
    }
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nsensitivity_csv={csv_path}")
    print(f"sensitivity_json={json_path}")

    # Restores the canonical six-scenario ledger.json with the policy in
    # configs/policies.json (pol-c3d1fc49f36e, the one Appendix A prints), but
    # with fresh evidence_id and timestamp values: the published file changes.
    # Run this only when that is intended, or restore ledger.json afterwards.
    oracle = ComplianceOracle()
    oracle.reset_ledger()
    for event in build_scenarios():
        oracle.process_mlops_event(event)
    return json_path


if __name__ == "__main__":
    run()
