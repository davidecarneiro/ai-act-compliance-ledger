"""Compare the Oracle and SQLite baseline on six shared scenarios.

Export event latency, ingestion time, audit queries, evidence fields and
a stored-decision tampering probe. Default thresholds agree for these
scenarios. The experiment compares complete implementations; it does not
establish that every database requires the same integrity mechanisms."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import List

from baseline_logger import BaselineLogger
from scenarios import build_scenarios
from simulator import ComplianceOracle

from paths import EXPERIMENTS_DIR  # noqa: E402


def percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    values_sorted = sorted(values)
    k = max(0, min(len(values_sorted) - 1, int(round(pct / 100 * (len(values_sorted) - 1)))))
    return values_sorted[k]


def run_oracle() -> dict:
    oracle = ComplianceOracle()
    oracle.reset_ledger()
    events = build_scenarios()

    start = time.perf_counter()
    for event in events:
        oracle.process_mlops_event(event)
    total_s = time.perf_counter() - start

    latencies = [row["latency_ms"] for row in oracle.metrics_rows]

    # Audit latency
    q1 = time.perf_counter()
    by_req = oracle.query_by_requirement("Art.15")
    q1_ms = (time.perf_counter() - q1) * 1000

    q2 = time.perf_counter()
    by_scenario = oracle.query_by_scenario("fairness_rejected")
    q2_ms = (time.perf_counter() - q2) * 1000

    pre_tamper = oracle.verify_chain()

    # Tamper test: silently change a stored decision. The altered copy is
    # verified in memory, which works for either ledger format and leaves the
    # stored ledger as it was.
    ledger = oracle._read_ledger()
    ledger[1]["decision"] = "approved"  # was "rejected"
    post_tamper = oracle.verify_chain(ledger)

    sample_record = oracle._read_ledger()[0]

    return {
        "events_processed": len(events),
        "total_ingestion_s": round(total_s, 4),
        "avg_latency_ms": round(mean(latencies), 4),
        "p95_latency_ms": round(percentile(latencies, 95), 4),
        "audit_query_by_requirement_ms": round(q1_ms, 4),
        "audit_query_by_scenario_ms": round(q2_ms, 4),
        "tamper_detection": {
            "before": {
                "valid": pre_tamper.valid,
                "total": pre_tamper.total,
                "detected": not pre_tamper.is_valid,
            },
            "after": {
                "valid": post_tamper.valid,
                "total": post_tamper.total,
                "detected": not post_tamper.is_valid,
                "first_invalid_index": post_tamper.first_invalid_index,
                "issues": post_tamper.issues,
            },
        },
        "evidence_field_count": len(sample_record),
        "evidence_sample_fields": sorted(sample_record.keys()),
        "by_req_count": len(by_req),
        "by_scenario_count": len(by_scenario),
    }


def run_baseline() -> dict:
    logger = BaselineLogger()
    events = build_scenarios()

    start = time.perf_counter()
    for event in events:
        logger.log(event)
    total_s = time.perf_counter() - start

    latencies = [row["latency_ms"] for row in logger.metrics_rows]

    q1 = time.perf_counter()
    by_scenario = logger.query_by_scenario("fairness_rejected")
    q1_ms = (time.perf_counter() - q1) * 1000

    q2 = time.perf_counter()
    by_artifact = logger.reconstruct_trail("credit-scoring-v2.0")
    q2_ms = (time.perf_counter() - q2) * 1000

    # This baseline checks the row count only; the change below goes unnoticed.
    pre = logger.check_integrity()
    logger.tamper("low_precision_rejected", "approved")
    post = logger.check_integrity()

    cursor = logger.connection.execute("SELECT * FROM events LIMIT 1")
    cols = [c[0] for c in cursor.description]
    sample_record = dict(zip(cols, cursor.fetchone()))

    logger.close()

    return {
        "events_processed": len(events),
        "total_ingestion_s": round(total_s, 4),
        "avg_latency_ms": round(mean(latencies), 4),
        "p95_latency_ms": round(percentile(latencies, 95), 4),
        "audit_query_by_scenario_ms": round(q1_ms, 4),
        "audit_query_by_artifact_ms": round(q2_ms, 4),
        "tamper_detection": {
            "before": {"detected": pre["tamper_detected"]},
            "after": {
                "detected": post["tamper_detected"],
                "method": post["method"],
            },
        },
        "evidence_field_count": len(sample_record),
        "evidence_sample_fields": sorted(sample_record.keys()),
        "by_scenario_count": len(by_scenario),
        "by_artifact_count": len(by_artifact),
    }


def main() -> Path:
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    print("=== Compliance Oracle ===")
    oracle_metrics = run_oracle()
    print("=== Centralised Baseline ===")
    baseline_metrics = run_baseline()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = EXPERIMENTS_DIR / f"comparison_oracle_vs_baseline_{timestamp}.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "oracle": oracle_metrics,
        "baseline": baseline_metrics,
        "delta": {
            "tamper_detection_oracle": oracle_metrics["tamper_detection"]["after"][
                "detected"
            ],
            "tamper_detection_baseline": baseline_metrics["tamper_detection"][
                "after"
            ]["detected"],
            "evidence_field_count_oracle": oracle_metrics["evidence_field_count"],
            "evidence_field_count_baseline": baseline_metrics["evidence_field_count"],
        },
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\ncomparison_summary={out_path}")
    print(json.dumps(payload, indent=2))
    return out_path


if __name__ == "__main__":
    main()
