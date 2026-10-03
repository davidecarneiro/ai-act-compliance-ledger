#!/usr/bin/env python3
"""Observe MultiFlow Kafka messages and generate monitoring evidence.

The first BATCH_SIZE rows define the reference distribution. Each complete
subsequent batch produces a mean column z-score, divided by three and
saturated at one, which is submitted to ComplianceOracle.

Input is checked before it reaches the indicator: a message that is not an
object, a row that is not made of finite numbers, or a row whose column count
differs from the reference rows is skipped, logged as it happens and counted.
A partial batch waits in memory for more rows; it is never submitted, and its
size is reported only when a finite stream ends (as in the tests).

This illustrative indicator is not a validated general-purpose drift
detector. Precision, demographic-parity difference and human approval are
configured inputs, not measurements or approvals obtained from the stream.

Configuration: KAFKA_BOOTSTRAP, STREAM_TOPIC, BATCH_SIZE, MODEL_ID,
MODEL_PRECISION, MODEL_DP_DIFF, ORACLE_PATH and OUT_DIR."""

from __future__ import annotations  # lazy annotations: allows `list[float] | None` on Python 3.9 (host)

import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

# The thesis prototype is copied to /oracle when the container is built.
sys.path.insert(0, os.getenv("ORACLE_PATH", "/oracle"))
from simulator import ComplianceOracle  # noqa: E402

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:29092")
STREAM_TOPIC = os.getenv("STREAM_TOPIC", "phd_kafka")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "20"))
MODEL_ID = os.getenv("MODEL_ID", "multiflow-stream-model")
MODEL_PRECISION = float(os.getenv("MODEL_PRECISION", "0.85"))
MODEL_DP_DIFF = float(os.getenv("MODEL_DP_DIFF", "0.03"))
OUT_DIR = os.getenv("OUT_DIR", "/out")
if BATCH_SIZE < 1:
    sys.exit(f"BATCH_SIZE must be a positive integer, got {BATCH_SIZE}")


def decode_message(raw: bytes):
    """Kafka payload to a Python value, or None when it is not UTF-8 JSON.

    This runs inside the consumer, before parse_csv_row: a deserializer that
    raised would stop the consumer on the first malformed message.
    """
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def parse_csv_row(message) -> list[float] | None:
    """The numeric row of a MultiFlow message, or None if it cannot be used.

    The message must be an object whose csv_data holds comma-separated finite
    numbers. NaN and infinity are refused: they would otherwise reach the
    statistics and could still yield a finite, misleading drift score.
    """
    if not isinstance(message, dict):
        return None
    csv_data = message.get("csv_data")
    if isinstance(csv_data, bool) or not isinstance(csv_data, (str, int, float)):
        return None
    try:
        row = [float(x) for x in str(csv_data).split(",")]
    except ValueError:
        return None
    if not all(math.isfinite(v) for v in row):
        return None
    return row


def drift_score(reference: list[list[float]], batch: list[list[float]]) -> float:
    """Mean per-column z-score of the batch against the reference, saturated at 1.0.

    A simple, deterministic indicator for evidence purposes; rigorous statistical
    detection belongs to the MultiFlow apps (MMD, for instance).
    """
    n_cols = min(len(reference[0]), len(batch[0]))
    zs = []
    for c in range(n_cols):
        ref_col = [r[c] for r in reference]
        bat_col = [r[c] for r in batch]
        mu, sd = statistics.mean(ref_col), statistics.pstdev(ref_col) or 1e-9
        zs.append(abs(statistics.mean(bat_col) - mu) / sd)
    return round(min(1.0, statistics.mean(zs) / 3.0), 4)  # 3σ → score 1.0


def build_event(batch_n: int, score: float, rows: int, topic: str) -> dict:
    """Canonical post-deployment monitoring event (chapters 3 and 5)."""
    return {
        "scenario_id": f"multiflow-{topic}-batch-{batch_n:04d}",
        "event_type": "stream_batch_monitoring",
        "artifact_id": MODEL_ID,
        "artifact_type": "monitoring_report",
        "pipeline_stage": "post_deploy_monitoring",
        "risk_level": "high",
        "metrics": {
            "precision": MODEL_PRECISION,
            "demographic_parity_diff": MODEL_DP_DIFF,
            "drift_score": score,
            "batch_rows": rows,
        },
        "human_approval": True,  # deployment approval for the monitored model
        "source": {"platform": "multiflow", "topic": topic},
    }


def run(consume_messages, stats: dict | None = None):
    """Testable core: takes an iterable of messages and processes them.

    Kept separate from Kafka consumption so that unit tests need no broker.
    If a dict is passed as stats, it is filled with the counts of rows used,
    skipped and left in an incomplete final batch.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    oracle = ComplianceOracle(ledger_file=Path(OUT_DIR) / "ledger.json")
    reference, batch, batch_n = [], [], 0
    n_cols = None
    unusable = wrong_width = 0

    for msg in consume_messages:
        row = parse_csv_row(msg)
        if row is None:
            unusable += 1
            print(f"[bridge] skipped unusable message #{unusable} "
                  f"(not an object, or not comma-separated finite numbers)", flush=True)
            continue
        if n_cols is None:
            n_cols = len(row)  # the first usable row fixes the width
        if len(row) != n_cols:
            wrong_width += 1
            print(f"[bridge] skipped row #{wrong_width} with {len(row)} column(s); "
                  f"the reference has {n_cols}", flush=True)
            continue
        if len(reference) < BATCH_SIZE:
            reference.append(row)
            continue
        batch.append(row)
        if len(batch) >= BATCH_SIZE:
            batch_n += 1
            score = drift_score(reference, batch)
            record = oracle.process_mlops_event(
                build_event(batch_n, score, len(batch), STREAM_TOPIC))
            print(f"[bridge] batch={batch_n} rows={len(batch)} "
                  f"drift_score={score} decision={record['decision']} "
                  f"chain_hash={record['chain_hash'][:12]}…", flush=True)
            batch = []

    if unusable or wrong_width:
        print(f"[bridge] skipped {unusable} unusable message(s) and "
              f"{wrong_width} row(s) with a column count other than {n_cols}",
              flush=True)
    if batch:
        print(f"[bridge] {len(batch)} row(s) left in an incomplete final batch, "
              f"not submitted", flush=True)
    if stats is not None:
        stats.update(batches=batch_n, unusable=unusable, wrong_width=wrong_width,
                     reference_rows=len(reference), left_over=len(batch))
    report = oracle.verify_chain()
    print(f"[bridge] chain_verification valid={report.valid}/{report.total}",
          flush=True)
    return oracle


def main():
    from kafka import KafkaConsumer  # imported here: the unit tests need no broker
    print(f"[bridge] connecting to {KAFKA_BOOTSTRAP}, topic '{STREAM_TOPIC}' "
          f"(batches of {BATCH_SIZE})", flush=True)
    for attempt in range(30):  # Kafka takes a while to come up in the compose stack
        try:
            consumer = KafkaConsumer(
                STREAM_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_deserializer=decode_message,
                auto_offset_reset="earliest",
                group_id="compliance-bridge",
            )
            break
        except Exception as exc:
            print(f"[bridge] Kafka unavailable ({exc}); retry {attempt+1}/30",
                  flush=True)
            time.sleep(5)
    else:
        sys.exit("Kafka unreachable after 30 attempts")
    print("[bridge] connected, waiting for the MultiFlow stream…", flush=True)
    run(m.value for m in consumer)


if __name__ == "__main__":
    main()
