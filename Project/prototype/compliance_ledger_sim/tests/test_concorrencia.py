"""Two processes appending to the ledger must not lose each other's records."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

FILHO = r'''
import sys, json
from pathlib import Path
sys.path.insert(0, {raiz!r})
from simulator import ComplianceOracle
oracle = ComplianceOracle(ledger_file=Path({ledger!r}))
for i in range({n}):
    oracle.process_mlops_event({{
        "scenario_id": "proc-{tag}-%d" % i,
        "event_type": "model_validation",
        "artifact_id": "m-{tag}-%d" % i,
        "artifact_type": "model",
        "pipeline_stage": "validation",
        "risk_level": "high",
        "human_approval": True,
        "metrics": {{"precision": 0.95, "demographic_parity_diff": 0.01}},
    }})
'''


def test_two_processes_do_not_lose_records(capsys):
    with tempfile.TemporaryDirectory() as d:
        ledger = str(Path(d) / "ledger.json")
        Path(ledger).write_text("[]", encoding="utf-8")
        n = 15
        procs = [
            subprocess.Popen(
                [sys.executable, "-c",
                 FILHO.format(raiz=str(RAIZ), ledger=ledger, n=n, tag=tag)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            for tag in ("a", "b")
        ]
        errors = [p.communicate()[1].decode() for p in procs]
        for e in errors:
            assert not e.strip(), f"the child process failed: {e[:800]}"

        records = json.loads(Path(ledger).read_text(encoding="utf-8"))
        assert len(records) == 2 * n, (
            f"{2 * n} events were written and the ledger holds {len(records)}: "
            "one write silently erased the other"
        )
        # the chain must link end to end, not merely survive truncated
        for previous, following in zip(records, records[1:]):
            assert following["parent_hash"] == previous["chain_hash"], (
                "the records survived but the chaining broke"
            )
        ids = {r["evidence_id"] for r in records}
        assert len(ids) == 2 * n, "there are repeated evidence_id values"
