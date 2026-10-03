#!/usr/bin/env python3
"""Measure input-validation latency on the first canonical scenario.

After warm-up, record repeated timings of _validate_input, summary
statistics and the execution environment. These timings do not isolate
all validation costs for every possible event shape.

Run: python3 bench_validation.py [repetitions]."""

from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from paths import EXPERIMENTS_DIR  # noqa: E402
from scenarios import build_scenarios  # noqa: E402
from simulator import ComplianceOracle  # noqa: E402


def measure(repetitions: int = 20000) -> dict:
    oracle = ComplianceOracle()
    event = build_scenarios()[0]

    # A short warm-up keeps first-call import and branch-prediction effects
    # out of the sample.
    for _ in range(1000):
        oracle._validate_input(event)

    samples = []
    for _ in range(repetitions):
        start = time.perf_counter()
        oracle._validate_input(event)
        samples.append((time.perf_counter() - start) * 1000)

    samples.sort()
    return {
        "measurement": "input validation per event",
        "target": "ComplianceOracle._validate_input",
        "event": build_scenarios()[0]["scenario_id"],
        "repetitions": repetitions,
        "warmup": 1000,
        "unit": "ms",
        "mean_ms": round(statistics.mean(samples), 6),
        "median_ms": round(statistics.median(samples), 6),
        "p95_ms": round(samples[int(0.95 * len(samples))], 6),
        "min_ms": round(samples[0], 6),
        "max_ms": round(samples[-1], 6),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    repetitions = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    payload = measure(repetitions)
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = EXPERIMENTS_DIR / f"validation_cost_{timestamp}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"\nartefacto: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
