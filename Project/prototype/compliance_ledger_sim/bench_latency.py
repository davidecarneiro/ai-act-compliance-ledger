#!/usr/bin/env python3
"""Measure paired, interleaved latency of the Oracle and SQLite baseline.

Protocol: docs/LATENCY_PROTOCOL_2026-09-14.md in the delivered project.
The two complete processing paths are measured. The Oracle rewrites its
JSON ledger per event, whereas the baseline inserts a SQLite row; the
difference does not isolate cryptographic cost.

Run: python3 bench_latency.py [rounds] [events_per_round]."""

from __future__ import annotations

import json
import platform
import shutil
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from baseline_logger import BaselineLogger  # noqa: E402
from paths import EXPERIMENTS_DIR  # noqa: E402
from simulator import ComplianceOracle  # noqa: E402

ROUNDS = 10
EVENTS_PER_ROUND = 200
WARMUP = 50


def _event(index: int) -> dict:
    return {
        "scenario_id": f"bench_{index}",
        "event_type": "model_validation",
        "artifact_id": f"model_v{index}",
        "artifact_type": "model",
        "pipeline_stage": "validation",
        "risk_level": "high",
        "human_approval": True,
        "metrics": {"precision": 0.85, "demographic_parity_diff": 0.02},
    }


def _run_round(round_index: int, events: int, workdir: Path) -> dict:
    ledger_file = workdir / f"ledger_{round_index}.json"
    policy_file = workdir / "policies.json"
    db_file = workdir / f"baseline_{round_index}.sqlite"
    oracle = ComplianceOracle(ledger_file=ledger_file, policy_file=policy_file)
    oracle.reset_ledger()
    baseline = BaselineLogger(db_file=db_file)

    oracle_samples: list[float] = []
    baseline_samples: list[float] = []
    growth: list[tuple[int, float]] = []

    for i in range(WARMUP + events):
        event = _event(i)
        # Alternate which arm runs first so neither is systematically warmed
        # by the other.
        oracle_first = i % 2 == 0

        if oracle_first:
            t0 = time.perf_counter()
            oracle.process_mlops_event(event)
            o_ms = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            baseline.log(event)
            b_ms = (time.perf_counter() - t0) * 1000
        else:
            t0 = time.perf_counter()
            baseline.log(event)
            b_ms = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            oracle.process_mlops_event(event)
            o_ms = (time.perf_counter() - t0) * 1000

        if i >= WARMUP:
            oracle_samples.append(o_ms)
            baseline_samples.append(b_ms)
            growth.append((i, o_ms))

    baseline.close()
    paired = [o - b for o, b in zip(oracle_samples, baseline_samples)]

    # Latency against ledger size, to expose the O(n) component.
    buckets: dict[str, list[float]] = {}
    for index, value in growth:
        bucket = f"{(index // 50) * 50}-{(index // 50) * 50 + 49}"
        buckets.setdefault(bucket, []).append(value)

    return {
        "round": round_index,
        "events": events,
        # Every paired observation is kept, so the medians below can be
        # recomputed independently and the effect of execution order can be
        # examined. Publishing only aggregates made that impossible.
        "observations": [
            {
                "event": i,
                "ledger_size_before": i,
                "oracle_first": i % 2 == 0,
                "oracle_ms": round(o, 4),
                "baseline_ms": round(b, 4),
                "difference_ms": round(o - b, 4),
            }
            for i, (o, b) in enumerate(
                zip(oracle_samples, baseline_samples), start=WARMUP
            )
        ],
        "oracle_median_ms": round(statistics.median(oracle_samples), 4),
        "baseline_median_ms": round(statistics.median(baseline_samples), 4),
        "paired_median_ms": round(statistics.median(paired), 4),
        "oracle_p95_ms": round(sorted(oracle_samples)[int(0.95 * len(oracle_samples))], 4),
        "baseline_p95_ms": round(sorted(baseline_samples)[int(0.95 * len(baseline_samples))], 4),
        "oracle_by_ledger_size": {
            k: round(statistics.median(v), 4) for k, v in sorted(buckets.items(), key=lambda kv: int(kv[0].split("-")[0]))
        },
    }


def main() -> int:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else ROUNDS
    events = int(sys.argv[2]) if len(sys.argv) > 2 else EVENTS_PER_ROUND

    workdir = Path(tempfile.mkdtemp(prefix="bench-latency-"))
    try:
        results = [_run_round(r, events, workdir) for r in range(rounds)]
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    paired = [r["paired_median_ms"] for r in results]
    oracle = [r["oracle_median_ms"] for r in results]
    base = [r["baseline_median_ms"] for r in results]
    paired_sorted = sorted(paired)

    def iqr(values: list[float]) -> list[float]:
        s = sorted(values)
        return [round(s[len(s) // 4], 4), round(s[(3 * len(s)) // 4], 4)]

    payload = {
        "protocol": "PROTOCOLO_LATENCIA_2026-09-14.md",
        "design": "paired, interleaved, alternating order; fresh stores per round",
        "independence": (
            "rounds renew ledger and SQLite stores; they run sequentially in "
            "one process on one machine, so they are not independent samples "
            "of a population of machines"
        ),
        "measures": "the two complete implemented paths, not cryptography in isolation",
        "rounds": rounds,
        "events_per_round": events,
        "warmup_per_round": WARMUP,
        "oracle_median_of_round_medians_ms": round(statistics.median(oracle), 4),
        "baseline_median_of_round_medians_ms": round(statistics.median(base), 4),
        "paired_difference_median_ms": round(statistics.median(paired), 4),
        "paired_difference_iqr_ms": iqr(paired),
        "paired_difference_min_ms": round(paired_sorted[0], 4),
        "paired_difference_max_ms": round(paired_sorted[-1], 4),
        "rounds_where_oracle_slower": sum(1 for p in paired if p > 0),
        "per_round": results,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = EXPERIMENTS_DIR / f"latency_protocol_{stamp}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in payload.items() if k != "per_round"}, indent=2))
    print(f"\nartefacto: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
