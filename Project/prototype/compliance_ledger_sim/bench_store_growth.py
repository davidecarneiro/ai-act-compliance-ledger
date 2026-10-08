#!/usr/bin/env python3
"""Does per-event latency grow with the size of the ledger? (WP1 acceptance)

Appends N events to a fresh ledger and reports the latency of each event,
summarised per block of events, for the two stores:

* append-only JSON Lines (``.jsonl``, the article's store);
* the dissertation's whole-file JSON array (``.json``), which rewrites the
  ledger on every event.

This is an acceptance check for WP1, not the cost protocol of the article
(WP3, ``bench_ablation.py``): one machine, one run, no warm-up separation.

    python3 bench_store_growth.py [N_JSONL] [N_JSON] [BLOCK]   # 10000 2000 1000
"""
from __future__ import annotations

import json
import platform
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from paths import EXPERIMENTS_DIR
from simulator import ComplianceOracle

POLICY = {
    "min_precision": 0.80,
    "max_demographic_parity_diff": 0.05,
    "require_human_approval_for_high_risk": True,
    "drift_alert_threshold": 0.15,
}


def _event(i: int) -> dict:
    return {
        "scenario_id": f"growth-{i}",
        "event_type": "model_validation",
        "artifact_id": f"model-{i}",
        "artifact_type": "model",
        "pipeline_stage": "validation",
        "risk_level": "high",
        "human_approval": True,
        "metrics": {"precision": 0.93, "demographic_parity_diff": 0.02},
    }


def run(store_suffix: str, n: int, block: int) -> dict:
    with tempfile.TemporaryDirectory() as d:
        work = Path(d)
        (work / "policies.json").write_text(json.dumps(POLICY), encoding="utf-8")
        oracle = ComplianceOracle(
            policy_file=work / "policies.json", ledger_file=work / f"ledger{store_suffix}"
        )
        oracle.reset_ledger()
        latencies = []
        for i in range(n):
            t0 = time.perf_counter()
            oracle.process_mlops_event(_event(i))
            latencies.append((time.perf_counter() - t0) * 1000)
        report = oracle.verify_chain()
        assert report.valid == report.total == n, report.issues[:3]
        size = (work / f"ledger{store_suffix}").stat().st_size
    blocks = []
    for start in range(0, n, block):
        chunk = latencies[start:start + block]
        blocks.append({
            "records_before": start,
            "median_ms": round(statistics.median(chunk), 4),
            "p95_ms": round(sorted(chunk)[int(0.95 * (len(chunk) - 1))], 4),
        })
    first, last = blocks[0]["median_ms"], blocks[-1]["median_ms"]
    return {
        "store": store_suffix,
        "events": n,
        "block": block,
        "final_file_bytes": size,
        "blocks": blocks,
        "last_over_first_block_median": round(last / first, 3),
        "latencies_ms": [round(x, 4) for x in latencies],
    }


def main() -> int:
    n_jsonl = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    n_json = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    block = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
    import builtins
    real_print = builtins.print
    builtins.print = lambda *a, **k: None  # silence the per-event oracle line
    try:
        results = [run(".jsonl", n_jsonl, block), run(".json", n_json, max(1, block // 4))]
    finally:
        builtins.print = real_print
    out = {
        "purpose": "WP1 acceptance: per-event latency versus ledger size",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "results": results,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = EXPERIMENTS_DIR / "wp1"
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"store_growth_{stamp}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for r in results:
        real_print(f"\n{r['store']}: {r['events']} events, {r['final_file_bytes']} bytes")
        for b in r["blocks"]:
            real_print(f"  after {b['records_before']:>6} records: "
                       f"median {b['median_ms']:.3f} ms, p95 {b['p95_ms']:.3f} ms")
        real_print(f"  last/first block median: {r['last_over_first_block_median']}")
    real_print(f"\nsaved to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
