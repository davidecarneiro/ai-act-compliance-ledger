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

Acquisition state (reference rows, the batch being filled, the batch counter,
skip counts and, from Kafka, the last offset processed per partition) is
written to OUT_DIR/bridge_state.json after every message, so a restarted
bridge resumes with the same reference instead of silently taking a new one,
and skips messages Kafka delivers again. A complete batch is written to the
state as pending before it goes to the ledger: on a restart, a pending batch
is recorded only if the ledger does not already hold it. From Kafka, offsets
are committed only after the state that includes the message is saved, so a
new run starts after the last committed message, as before.

This illustrative indicator is not a validated general-purpose drift
detector. Precision, demographic-parity difference and human approval are
configured inputs, not measurements or approvals obtained from the stream.

Configuration: KAFKA_BOOTSTRAP, STREAM_TOPIC, BATCH_SIZE, MODEL_ID,
MODEL_PRECISION, MODEL_DP_DIFF, ORACLE_PATH, OUT_DIR and LEDGER_FILE (default
ledger.jsonl, append-only, under schema version 2; ledger.json under
EVIDENCE_SCHEMA_VERSION=1, as in the dissertation)."""

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
from canonical import CURRENT_SCHEMA_VERSION  # noqa: E402
from ledger_store import read_ledger  # noqa: E402
from simulator import ComplianceOracle  # noqa: E402

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:29092")
STREAM_TOPIC = os.getenv("STREAM_TOPIC", "phd_kafka")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "20"))
MODEL_ID = os.getenv("MODEL_ID", "multiflow-stream-model")
MODEL_PRECISION = float(os.getenv("MODEL_PRECISION", "0.85"))
MODEL_DP_DIFF = float(os.getenv("MODEL_DP_DIFF", "0.03"))
OUT_DIR = os.getenv("OUT_DIR", "/out")
LEDGER_FILE = os.getenv("LEDGER_FILE") or (
    "ledger.jsonl" if CURRENT_SCHEMA_VERSION >= 2 else "ledger.json")
STATE_FILE = "bridge_state.json"
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


def _state_path() -> Path:
    return Path(OUT_DIR) / STATE_FILE


def load_state() -> dict | None:
    path = _state_path()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    """Atomic replace: a reader sees the old state or the new one."""
    path = _state_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def _recorded_batches(ledger_path: Path) -> int:
    """Highest batch number in the ledger (from its scenario_id)."""
    if not ledger_path.exists():
        return 0
    last = 0
    for record in read_ledger(ledger_path):
        scenario = str(record.get("scenario_id") or "")
        if "-batch-" in scenario:
            try:
                last = max(last, int(scenario.rsplit("-batch-", 1)[1]))
            except ValueError:
                pass
    return last


def run(consume_messages, stats: dict | None = None, on_checkpoint=None):
    """Testable core: takes an iterable of messages and processes them.

    Each item is a message, or a (position, message) pair where position is
    (topic, partition, offset), as main() passes from Kafka; on_checkpoint is
    called after each save of the state (main() commits the Kafka offset
    there). Kept separate
    from Kafka consumption so that unit tests need no broker. If a dict is
    passed as stats, it is filled with the counts of rows used, skipped and
    left in an incomplete final batch.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    ledger_path = Path(OUT_DIR) / LEDGER_FILE
    oracle = ComplianceOracle(ledger_file=ledger_path)
    state = load_state() or {"reference": [], "batch": [], "batch_n": 0, "n_cols": None,
                             "unusable": 0, "wrong_width": 0, "positions": {}, "pending": None}
    if state["batch_n"] or state["reference"]:
        print(f"[bridge] resuming: {len(state['reference'])} reference row(s), "
              f"{len(state['batch'])} row(s) in the current batch, "
              f"{state['batch_n']} batch(es) recorded", flush=True)
    reference, batch, batch_n = state["reference"], state["batch"], state["batch_n"]
    n_cols = state["n_cols"]
    unusable, wrong_width = state["unusable"], state["wrong_width"]
    positions = state["positions"]
    pending = state.get("pending")

    def checkpoint(position=None):
        if position is not None:
            positions[f"{position[0]}:{position[1]}"] = position[2]
        save_state({"reference": reference, "batch": batch, "batch_n": batch_n,
                    "n_cols": n_cols, "unusable": unusable, "wrong_width": wrong_width,
                    "positions": positions, "pending": pending})
        if on_checkpoint is not None:
            on_checkpoint()

    def record_pending():
        nonlocal pending
        record = oracle.process_mlops_event(
            build_event(pending["batch_n"], pending["score"], pending["rows"], STREAM_TOPIC))
        print(f"[bridge] batch={pending['batch_n']} rows={pending['rows']} "
              f"drift_score={pending['score']} decision={record['decision']} "
              f"chain_hash={record['chain_hash'][:12]}…", flush=True)
        pending = None

    if pending is not None:
        if _recorded_batches(ledger_path) >= pending["batch_n"]:
            print(f"[bridge] batch {pending['batch_n']} is already in the ledger", flush=True)
            pending = None
        else:
            print(f"[bridge] recording batch {pending['batch_n']}, complete before the stop",
                  flush=True)
            record_pending()
        checkpoint()

    for item in consume_messages:
        position = None
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], tuple):
            position, msg = item
            done = positions.get(f"{position[0]}:{position[1]}")
            if done is not None and position[2] <= done:
                continue                      # delivered again after a restart
        else:
            msg = item
        row = parse_csv_row(msg)
        if row is None:
            unusable += 1
            print(f"[bridge] skipped unusable message #{unusable} "
                  f"(not an object, or not comma-separated finite numbers)", flush=True)
            checkpoint(position)
            continue
        if n_cols is None:
            n_cols = len(row)  # the first usable row fixes the width
        if len(row) != n_cols:
            wrong_width += 1
            print(f"[bridge] skipped row #{wrong_width} with {len(row)} column(s); "
                  f"the reference has {n_cols}", flush=True)
            checkpoint(position)
            continue
        if len(reference) < BATCH_SIZE:
            reference.append(row)
            checkpoint(position)
            continue
        batch.append(row)
        if len(batch) >= BATCH_SIZE:
            # Written ahead: the complete batch is in the saved state before
            # it reaches the ledger, and leaves it once recorded.
            batch_n += 1
            pending = {"batch_n": batch_n, "score": drift_score(reference, batch),
                       "rows": len(batch)}
            batch = []
            checkpoint(position)
            record_pending()
        checkpoint(position)

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
                # Offsets are committed after the state is saved (on_checkpoint),
                # never ahead of it; bridge_state.json skips redelivered messages.
                enable_auto_commit=False,
            )
            break
        except Exception as exc:
            print(f"[bridge] Kafka unavailable ({exc}); retry {attempt+1}/30",
                  flush=True)
            time.sleep(5)
    else:
        sys.exit("Kafka unreachable after 30 attempts")
    print("[bridge] connected, waiting for the MultiFlow stream…", flush=True)
    run((((m.topic, m.partition, m.offset), m.value) for m in consumer),
        on_checkpoint=consumer.commit)


if __name__ == "__main__":
    main()
