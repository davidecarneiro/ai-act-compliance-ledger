#!/usr/bin/env python3
"""WP7 measurement runner (protocols/wp7_fabric_anchoring.md).

Three steps, run on the machine that hosts the Fabric test network:

    python3 run_wp7.py prepare  --out DIR             # issue records, anchors, proofs (no network)
    python3 run_wp7.py measure  --prep DIR --label L  # run the client against the live network
    python3 run_wp7.py summarise RESULT.json [...]    # rows and series of Figure F5

``prepare`` issues the evidence with the Compliance Policy Engine (schema
version 2, the engine's own key) before anything is timed. ``measure`` builds
the Go client (gateway/anchorbench) once and calls it for every step in the
protocol's order, then writes one JSON file per network bring-up to
``experiments/article/wp7/``. ``summarise`` computes latency, durable-evidence
throughput and query statistics from those files.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

HERE = Path(__file__).resolve().parent
FABRIC = HERE.parent
SIM = FABRIC.parent / "compliance_ledger_sim"
CASE = FABRIC.parent / "credit_case"
GATEWAY = FABRIC / "gateway"
for p in (SIM, CASE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import batch_anchor as ba  # noqa: E402
from canonical import SCHEMA_V2  # noqa: E402
from keys import load_or_create_key, public_key_fingerprint, public_key_hex  # noqa: E402
from paths import EXPERIMENTS_DIR  # noqa: E402
from simulator import ISSUER_ID_V2, ComplianceOracle  # noqa: E402

PROTOCOL = "Project/protocols/wp7_fabric_anchoring.md"
BATCH_SIZES = (10, 50, 100, 500)
ORDER = (1, 10, 50, 100, 500)
REPETITIONS = 3
PER_RECORD = 200
STREAM_RECORDS = 1000
INCLUSION_SAMPLE = 100
VERIFYCHAIN_CALLS = 20
OUT_DIR = EXPERIMENTS_DIR / "wp7"


# ----------------------------------------------------------------------
# prepare
# ----------------------------------------------------------------------

def _engine(folder: Path, ledger: str, policy: dict, key) -> ComplianceOracle:
    policy_file = folder / "policies.json"
    if not policy_file.exists():
        policy_file.write_text(json.dumps(policy), encoding="utf-8")
    engine = ComplianceOracle(policy_file=policy_file, ledger_file=folder / ledger,
                              issuer_key=key, schema_version=SCHEMA_V2)
    engine.reset_ledger()
    return engine


def _issue(engine: ComplianceOracle, events: Sequence[dict]) -> List[dict]:
    return [engine.store.append_with(lambda _s, parent, e=e: engine._build_record(e, parent))
            for e in events]


def _w2(n: int) -> List[dict]:
    from bench_ablation import w2_event
    return [w2_event(i) for i in range(n)]


def _jsonl(path: Path, items) -> None:
    ba.write_jsonl(path, items)


def rotated_order(rep: int) -> List[int]:
    k = (rep - 1) % len(ORDER)
    return list(ORDER[k:] + ORDER[:k])


def prepare(out: Path, small: bool = False, with_credit_case: bool = True) -> Dict:
    """Issue every record, anchor and proof the measurement needs."""
    per_record = 10 if small else PER_RECORD
    stream_n = 100 if small else STREAM_RECORDS
    sizes = (10, 50) if small else BATCH_SIZES
    out.mkdir(parents=True, exist_ok=False)
    key = load_or_create_key(ISSUER_ID_V2)
    shipped = json.loads((SIM / "configs" / "policies.json").read_text(encoding="utf-8"))

    chain_dir = out / "chain"
    chain_dir.mkdir()
    chain = _issue(_engine(chain_dir, "chain.jsonl", shipped, key), _w2(1 + REPETITIONS * per_record))
    _jsonl(out / "chain_warmup.jsonl", chain[:1])
    for r in range(1, REPETITIONS + 1):
        _jsonl(out / f"chain_r{r}.jsonl", chain[1 + (r - 1) * per_record: 1 + r * per_record])

    stream_dir = out / "stream"
    stream_dir.mkdir()
    stream = _issue(_engine(stream_dir, "stream.jsonl", shipped, key), _w2(stream_n))
    proof_sizes = {}
    for n in sizes:
        for r in range(1, REPETITIONS + 1):
            _jsonl(out / f"anchors_n{n}_r{r}.jsonl", ba.make_anchors(stream, n, f"n{n}-r{r}", key))
        sample = [ba.proof_size_bytes(ba.inclusion_proof(stream, seq, n, "x"))
                  for seq in range(1, len(stream) + 1)]
        proof_sizes[n] = {"median": statistics.median(sample), "max": max(sample)}
    proof_sizes[1] = {"median": 0, "max": 0, "note": "N = 1 submits the record itself; no proof"}
    _jsonl(out / "anchors_warmup.jsonl", ba.make_anchors(stream[:20], 10, "warmup", key))
    (out / "singleorg_anchor.json").write_text(
        json.dumps(ba.make_anchors(stream[:10], 10, "governance-check", key)[0],
                   separators=(",", ":")), encoding="utf-8")

    inclusion_n = 100 if 100 in sizes else sizes[-1]
    rng = random.Random(42)
    picked = sorted(rng.sample(range(1, len(stream) + 1), min(INCLUSION_SAMPLE, len(stream))))
    _jsonl(out / "inclusion_pairs.jsonl", (
        {"record": stream[s - 1],
         "proof": ba.inclusion_proof(stream, s, inclusion_n, f"n{inclusion_n}-r1")}
        for s in picked))

    credit = None
    if with_credit_case:
        import credit_case as cc
        from artifact_store import ArtifactStore

        case_dir = out / "credit_case"
        case_dir.mkdir()
        events = cc.build_events(ArtifactStore(case_dir / "store"), cc.MAIN_SEED,
                                 cc.approver_key()).events
        policy = json.loads(cc.POLICY_FILE.read_text(encoding="utf-8"))
        records = _issue(_engine(case_dir, "ledger.jsonl", policy, key), events)
        _jsonl(out / "anchors_credit_case.jsonl", ba.make_anchors(records, 1, "credit-case", key))
        credit = {"records": len(records), "ledger": "credit_case/ledger.jsonl"}

    (out / "pubkey.txt").write_text(public_key_hex(key) + "\n", encoding="ascii")
    shutil.copy2(SIM / "keys" / f"{ISSUER_ID_V2}.ed25519.pub.pem", out / "engine.pub.pem")
    manifest = {
        "protocol": PROTOCOL,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "small": small,
        "issuer_fingerprint": public_key_fingerprint(key),
        "per_record": {"warmup": 1, "repetitions": REPETITIONS, "records_each": per_record},
        "stream": {"records": len(stream), "batch_sizes": list(sizes),
                   "inclusion_stream": f"n{inclusion_n}-r1", "inclusion_sample": len(picked)},
        "proof_size_bytes": proof_sizes,
        "credit_case": credit,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest


# ----------------------------------------------------------------------
# measure
# ----------------------------------------------------------------------

def _samples_dir() -> Path:
    return Path(os.environ.get("FABRIC_SAMPLES",
                               Path.home() / "fabric-workspace" / "fabric-samples"))


def network_environment() -> Dict:
    env: Dict = {"platform": platform.platform(), "machine": platform.machine(),
                 "python": platform.python_version()}
    configtx = _samples_dir() / "test-network" / "configtx" / "configtx.yaml"
    try:
        m = re.search(r"^\s*BatchTimeout:\s*(\S+)", configtx.read_text(), re.M)
        env["batch_timeout"] = m.group(1) if m else "not found"
        m = re.search(r"^\s*MaxMessageCount:\s*(\S+)", configtx.read_text(), re.M)
        env["max_message_count"] = m.group(1) if m else "not found"
    except OSError:
        env["batch_timeout"] = "configtx.yaml not found"
    try:
        names = subprocess.run(["docker", "ps", "--format", "{{.Names}} {{.Image}}"],
                               capture_output=True, text=True, timeout=30).stdout
        env["containers"] = sorted(names.split("\n")) if names else []
        env["state_database"] = "CouchDB" if "couchdb" in names.lower() else "LevelDB"
        env["orderers"] = sum(1 for line in names.splitlines() if line.startswith("orderer"))
    except (OSError, subprocess.SubprocessError):
        env["state_database"] = "unknown (docker not reachable)"
    try:
        env["docker"] = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                                       capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return env


def build_client(target: Path) -> Path:
    subprocess.run(["go", "build", "-o", str(target), "./anchorbench"], cwd=GATEWAY, check=True)
    return target


def _run(client: Sequence[str], command: str, args: List[str], out: Path) -> Dict:
    subprocess.run([*client, command, *args, "-out", str(out)], check=True)
    return json.loads(out.read_text(encoding="utf-8"))


def measure(prep: Path, label: str, client: Optional[Sequence[str]] = None,
            queries_only: bool = False, out_dir: Path = OUT_DIR) -> Path:
    manifest = json.loads((prep / "manifest.json").read_text(encoding="utf-8"))
    started = datetime.now(timezone.utc)
    work = Path(tempfile.mkdtemp(prefix="wp7_"))
    client = list(client) if client else [str(build_client(work / "anchorbench"))]
    environment = network_environment()
    steps: List[Dict] = []

    def step(name: str, command: str, args: List[str], **meta) -> Dict:
        result = _run(client, command, args, work / f"{len(steps):03d}_{name}.json")
        steps.append({"name": name, "command": command, **meta, "result": result})
        failed = [c for c in result["calls"] if not c["ok"]]
        if failed and meta.get("must_succeed", True):
            raise SystemExit(f"{name}: {len(failed)} calls failed, first: {failed[0].get('error')}")
        return result

    step("register", "register", ["-pubkey", str(prep / "pubkey.txt")])
    step("warmup-submit", "submit", ["-in", str(prep / "chain_warmup.jsonl")], counted=False)
    step("warmup-anchor", "anchor", ["-in", str(prep / "anchors_warmup.jsonl")], counted=False)
    reps = [1] if queries_only else list(range(1, REPETITIONS + 1))
    sizes = manifest["stream"]["batch_sizes"]
    inclusion_n = int(manifest["stream"]["inclusion_stream"].split("-")[0][1:])
    for r in reps:
        order = [n for n in rotated_order(r) if n == 1 or n in sizes]
        if queries_only:
            order = [1, inclusion_n]
        for n in order:
            if n == 1:
                step(f"n1-r{r}", "submit", ["-in", str(prep / f"chain_r{r}.jsonl")],
                     n=1, rep=r, counted=True, records_per_call=1)
            else:
                step(f"n{n}-r{r}", "anchor", ["-in", str(prep / f"anchors_n{n}_r{r}.jsonl")],
                     n=n, rep=r, counted=True, records_per_call=n)
    step("verify-inclusion", "inclusion",
         ["-in", str(prep / "inclusion_pairs.jsonl"), "-keep-results"], query=True)
    step("verify-chain", "verifychain", ["-repeat", str(VERIFYCHAIN_CALLS)], query=True)
    exports = {}
    if not queries_only and manifest.get("credit_case"):
        step("credit-case-anchors", "anchor", ["-in", str(prep / "anchors_credit_case.jsonl")])
        export = step("credit-case-export", "anchors", ["-stream", "credit-case"])
        exports["credit_case"] = json.loads(export["calls"][0]["result"])
    governance = step("governance-single-org", "singleorg", ["-in", str(prep / "singleorg_anchor.json")],
                      must_succeed=False)

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"fabric_{label}_{stamp}.json"
    if exports.get("credit_case"):
        case_out = out_dir / f"credit_case_{label}_{stamp}"
        case_out.mkdir()
        shutil.copy2(prep / "credit_case" / "ledger.jsonl", case_out / "ledger.jsonl")
        shutil.copy2(prep / "engine.pub.pem", case_out / "engine.pub.pem")
        (case_out / "onchain_anchors.json").write_text(
            json.dumps(exports["credit_case"], indent=1) + "\n", encoding="utf-8")
    call = governance["calls"][0]
    output = {
        "protocol": PROTOCOL,
        "label": label,
        "counts_for_article": not label.startswith("validation"),
        "queries_only": queries_only,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "environment": environment,
        "manifest": manifest,
        "governance_check": {"refused": not call["ok"], "code": call.get("code"),
                             "error": call.get("error")},
        "steps": steps,
    }
    path.write_text(json.dumps(output) + "\n", encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    print(f"saved to {path}")
    return path


# ----------------------------------------------------------------------
# summarise
# ----------------------------------------------------------------------

def _q(values: Sequence[float]) -> Dict[str, float]:
    s = sorted(values)
    if len(s) == 1:
        return {"n": 1, "median": s[0], "q1": s[0], "q3": s[0], "p95": s[0]}
    q = statistics.quantiles(s, n=100, method="inclusive")
    return {"n": len(s), "median": round(statistics.median(s), 3), "q1": round(q[24], 3),
            "q3": round(q[74], 3), "p95": round(q[94], 3)}


def summarise_run(result: Dict) -> Dict:
    by_n: Dict[int, Dict] = {}
    for st in result["steps"]:
        if not st.get("counted"):
            continue
        calls = st["result"]["calls"]
        per_call = st["records_per_call"]
        latencies = [c["ms"] for c in calls]
        elapsed_s = (calls[-1]["end_unix_ns"] - calls[0]["start_unix_ns"]) / 1e9
        records = per_call * len(calls)
        entry = by_n.setdefault(st["n"], {"latency_ms": [], "throughput_rps": [],
                                          "durable_ms_per_record": []})
        entry["latency_ms"] += latencies
        entry["throughput_rps"].append(records / elapsed_s)
        entry["durable_ms_per_record"] += [ms for ms in latencies for _ in range(per_call)]
    out = {}
    for n, e in sorted(by_n.items()):
        out[n] = {
            "transaction_latency_ms": _q(e["latency_ms"]),
            "durable_latency_ms_per_record": _q(e["durable_ms_per_record"]),
            "throughput_records_per_s": {
                "per_repetition": [round(x, 3) for x in e["throughput_rps"]],
                "median": round(statistics.median(e["throughput_rps"]), 3)},
            "proof_size_bytes": result["manifest"]["proof_size_bytes"].get(str(n)),
        }
    queries = {st["name"]: _q([c["ms"] for c in st["result"]["calls"]])
               for st in result["steps"] if st.get("query")}
    inclusion = next(st for st in result["steps"] if st["name"] == "verify-inclusion")
    included = sum('"included":true' in (c.get("result") or "")
                   for c in inclusion["result"]["calls"])
    return {"label": result["label"], "environment": result["environment"],
            "per_n": out, "queries_ms": queries,
            "verify_inclusion_included": included,
            "verify_inclusion_calls": len(inclusion["result"]["calls"]),
            "governance_check": result["governance_check"]}


def batch_wait_s(n: int, events_per_s: float) -> Dict[str, float]:
    """Analytic wait for a batch of n to fill at a cadence (protocol)."""
    return {"mean": (n - 1) / (2 * events_per_s), "max": (n - 1) / events_per_s}


def summarise(paths: Sequence[Path], out_dir: Path = OUT_DIR) -> Path:
    runs = [summarise_run(json.loads(Path(p).read_text(encoding="utf-8"))) for p in paths]
    series = {}
    for run in runs:
        key = f"{run['environment'].get('batch_timeout')}/{run['environment'].get('state_database')}"
        series[key] = {str(n): {"throughput": v["throughput_records_per_s"]["median"],
                                "durable_latency_median_ms": v["durable_latency_ms_per_record"]["median"]}
                       for n, v in run["per_n"].items()}
    output = {"generated_at": datetime.now(timezone.utc).isoformat(), "protocol": PROTOCOL,
              "sources": [str(p) for p in paths], "runs": runs, "figure_f5": series}
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"summary_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(output, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(series, indent=1))
    print(f"saved to {path}")
    return path


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--small", action="store_true", help="tiny inputs, for testing the scripts")
    m = sub.add_parser("measure")
    m.add_argument("--prep", type=Path, required=True)
    m.add_argument("--label", required=True)
    m.add_argument("--queries-only", action="store_true",
                   help="CouchDB run: one repetition of N = 1 and the inclusion stream, then the queries")
    s = sub.add_parser("summarise")
    s.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        print(json.dumps(prepare(args.out, small=args.small), indent=1))
    elif args.command == "measure":
        measure(args.prep, args.label, queries_only=args.queries_only)
    else:
        summarise(args.results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
