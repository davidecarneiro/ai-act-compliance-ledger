"""SQLite baseline for the comparative experiment.

Rows contain decisions, reasons and metrics, but no hash chain, issuer
signature, content-derived policy identity or explicit article mapping.
The row-count integrity probe does not detect changes to stored decisions.
This limitation belongs to this baseline, not to every centralised database."""

from __future__ import annotations

import csv
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Tuple

BASE_DIR = Path(__file__).parent
# SQLite is kept under /tmp to avoid filesystem limitations on the host mount
# used by the development environment. The path can be overridden by tests.
import tempfile

DB_FILE = Path(tempfile.gettempdir()) / "compliance_ledger_baseline.sqlite"
from paths import EXPERIMENTS_DIR  # noqa: E402


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id TEXT,
    event_type TEXT,
    artifact_id TEXT,
    pipeline_stage TEXT,
    timestamp TEXT,
    decision TEXT,
    reason TEXT,
    metrics_json TEXT
);
"""


class BaselineLogger:
    def __init__(self, db_file: Path = DB_FILE) -> None:
        self.db_file = db_file
        if self.db_file.exists():
            try:
                self.db_file.unlink()
            except OSError:
                pass
        self.connection = sqlite3.connect(str(self.db_file))
        self.connection.execute("DROP TABLE IF EXISTS events")
        self.connection.execute(SCHEMA)
        self.connection.commit()
        self.metrics_rows: List[dict] = []

    def close(self) -> None:
        self.connection.close()

    # ------------------------------------------------------------------
    # Naive policy decision (mirrors the Oracle to keep comparisons fair)
    # ------------------------------------------------------------------

    def _decide(self, event: dict) -> Tuple[str, str]:
        metrics = event.get("metrics", {})
        if metrics.get("precision", 0.0) < 0.80:
            return "rejected", "precision below threshold"
        if metrics.get("demographic_parity_diff", 1.0) > 0.05:
            return "rejected", "fairness violation"
        if (
            event.get("risk_level") == "high"
            and not event.get("human_approval", False)
        ):
            return "rejected", "missing human approval"
        if metrics.get("drift_score", 0.0) > 0.15:
            return "escalated", "drift above threshold"
        if event.get("event_type") == "audit_query":
            return "verified", "audit query"
        return "approved", "ok"

    def log(self, event: dict) -> dict:
        start = time.perf_counter()
        decision, reason = self._decide(event)
        timestamp = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """
            INSERT INTO events (scenario_id, event_type, artifact_id,
                pipeline_stage, timestamp, decision, reason, metrics_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.get("scenario_id"),
                event.get("event_type"),
                event.get("artifact_id"),
                event.get("pipeline_stage"),
                timestamp,
                decision,
                reason,
                json.dumps(event.get("metrics", {})),
            ),
        )
        self.connection.commit()
        latency_ms = round((time.perf_counter() - start) * 1000, 4)
        self.metrics_rows.append(
            {
                "scenario_id": event.get("scenario_id"),
                "decision": decision,
                "latency_ms": latency_ms,
            }
        )
        print(
            f"[baseline] scenario={event.get('scenario_id')} "
            f"decision={decision} latency_ms={latency_ms}"
        )
        return {
            "scenario_id": event.get("scenario_id"),
            "decision": decision,
            "reason": reason,
            "timestamp": timestamp,
        }

    # ------------------------------------------------------------------
    # Integrity probes
    # ------------------------------------------------------------------

    def tamper(self, scenario_id: str, new_decision: str) -> bool:
        """Silently rewrite a stored decision. Returns True if a row changed."""

        cursor = self.connection.execute(
            "UPDATE events SET decision = ? WHERE scenario_id = ?",
            (new_decision, scenario_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def check_integrity(self) -> dict:
        """Row count only. This baseline keeps no chain and no signature, so
        it does not detect the stored-decision change that ``tamper`` makes:
        the altered row looks like any other row."""

        cursor = self.connection.execute("SELECT COUNT(*) FROM events")
        total = cursor.fetchone()[0]
        return {
            "total_records": total,
            "tamper_detected": False,
            "method": "row count only — no cryptographic anchor",
        }

    # ------------------------------------------------------------------
    # Audit query (used for performance comparison)
    # ------------------------------------------------------------------

    def query_by_scenario(self, scenario_id: str) -> List[dict]:
        cursor = self.connection.execute(
            "SELECT * FROM events WHERE scenario_id = ?", (scenario_id,)
        )
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def reconstruct_trail(self, artifact_id: str) -> List[dict]:
        cursor = self.connection.execute(
            "SELECT * FROM events WHERE artifact_id = ? ORDER BY timestamp ASC",
            (artifact_id,),
        )
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Metrics export
    # ------------------------------------------------------------------

    def export_metrics(self, run_label: str) -> Tuple[Path, Path]:
        EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        csv_path = EXPERIMENTS_DIR / f"baseline_metrics_{run_label}_{timestamp}.csv"
        json_path = EXPERIMENTS_DIR / f"baseline_summary_{run_label}_{timestamp}.json"

        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["scenario_id", "decision", "latency_ms"]
            )
            writer.writeheader()
            writer.writerows(self.metrics_rows)

        decisions: dict = {}
        for row in self.metrics_rows:
            decisions[row["decision"]] = decisions.get(row["decision"], 0) + 1

        avg_latency = sum(r["latency_ms"] for r in self.metrics_rows) / max(
            1, len(self.metrics_rows)
        )

        summary = {
            "run_label": run_label,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "events_processed": len(self.metrics_rows),
            "decisions": decisions,
            "avg_latency_ms": round(avg_latency, 4),
            "integrity_anchor": "none",
            "tamper_detection": "not supported",
            "audit_trail_reconstruction": "manual SQL queries; depends on convention",
        }
        json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return csv_path, json_path


def run_baseline_scenarios(
    scenarios: Iterable[dict] | None = None,
) -> Tuple[Path, Path]:
    from scenarios import build_scenarios

    logger = BaselineLogger()
    events = list(scenarios) if scenarios is not None else build_scenarios()
    print("--- baseline logger run ---")
    for event in events:
        logger.log(event)
    csv_path, json_path = logger.export_metrics(run_label="baseline_logger")
    integrity = logger.check_integrity()
    print(f"baseline_integrity={integrity}")
    print(f"db_file={logger.db_file}")
    print(f"metrics_csv={csv_path}")
    print(f"metrics_summary={json_path}")
    logger.close()
    return csv_path, json_path


if __name__ == "__main__":
    run_baseline_scenarios()
