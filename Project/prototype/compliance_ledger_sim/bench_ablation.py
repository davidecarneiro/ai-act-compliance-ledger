#!/usr/bin/env python3
"""Cost of verifiable evidence: the four-arm ablation of WP3.

Protocol: ``Project/protocols/wp3_ablation.md`` (recorded before any
measurement). Arms in ``ablation_arms.py``.

    python3 bench_ablation.py --label <machine> [--workdir DIR]
        [--rounds 10] [--events 200] [--warmup 50] [--growth 10000] [--block 1000]

The run that enters the article is made on the measurement machine with a
label naming it. Runs elsewhere validate the script and say so in their label.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from ablation_arms import ARM_NAMES, ANCHOR_INTERVAL, bench_key, make_arms, verify_arm  # noqa: E402
from paths import EXPERIMENTS_DIR  # noqa: E402
from scenarios import build_scenarios  # noqa: E402

POLICY_FILE = BASE_DIR / "configs" / "policies.json"
WILLIAMS = ((0, 1, 3, 2), (1, 2, 0, 3), (2, 3, 1, 0), (3, 0, 2, 1))
DIFFERENCES = (("B0", "A"), ("B", "B0"), ("B", "A"), ("Bplus", "B"))


# ----------------------------------------------------------------------
# Workloads
# ----------------------------------------------------------------------

def w1_event(i: int) -> dict:
    """The dissertation's benchmark event: an approved high-risk validation."""
    return {
        "scenario_id": f"bench_{i}",
        "event_type": "model_validation",
        "artifact_id": f"model_v{i}",
        "artifact_type": "model",
        "pipeline_stage": "validation",
        "risk_level": "high",
        "human_approval": True,
        "metrics": {"precision": 0.85, "demographic_parity_diff": 0.02},
    }


_SCENARIOS = build_scenarios()


def w2_event(i: int) -> dict:
    """The six canonical scenarios in turn."""
    return json.loads(json.dumps(_SCENARIOS[i % len(_SCENARIOS)]))


WORKLOADS = {"W1": w1_event, "W2": w2_event}


# ----------------------------------------------------------------------
# Environment
# ----------------------------------------------------------------------

def _cpu() -> str:
    try:
        if sys.platform == "darwin":
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                  capture_output=True, text=True).stdout.strip()
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "unknown"


def _filesystem(path: Path) -> str:
    """File system type of the working directory (tmpfs makes fsync free)."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["df", str(path)], capture_output=True, text=True).stdout
            device = out.splitlines()[-1].split()[0]
            mount = subprocess.run(["mount"], capture_output=True, text=True).stdout
            for line in mount.splitlines():
                if line.startswith(device + " "):
                    return line
            return device
        best, kind = "", "unknown"
        real = str(path.resolve())
        for line in Path("/proc/mounts").read_text().splitlines():
            parts = line.split()
            if real.startswith(parts[1]) and len(parts[1]) > len(best):
                best, kind = parts[1], f"{parts[2]} on {parts[1]}"
        return kind
    except Exception:
        return "unknown"


def environment(workdir: Path, settings: Dict) -> Dict:
    import cryptography
    import rfc8785

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": _cpu(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "cryptography": cryptography.__version__,
        "rfc8785": getattr(rfc8785, "__version__", "unknown"),
        "sqlite": settings,
        "workdir": str(workdir),
        "workdir_filesystem": _filesystem(workdir),
        "gc_enabled": __import__("gc").isenabled(),
    }


# ----------------------------------------------------------------------
# Measurement
# ----------------------------------------------------------------------

def _policy() -> dict:
    return json.loads(POLICY_FILE.read_text(encoding="utf-8"))


def _fresh_arms(folder: Path, interval: int):
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    policy = _policy()
    policy_file = folder / "policies.json"
    policy_file.write_text(json.dumps(policy), encoding="utf-8")
    key = bench_key(folder)
    return make_arms(folder, policy_file, policy, key, interval=interval), key


def _timed(arms: Dict, order: Sequence[int], event: dict) -> Dict[str, int]:
    out = {}
    for position in order:
        name = ARM_NAMES[position]
        arm = arms[name]
        e = json.loads(json.dumps(event))   # each arm gets its own copy, untimed
        t0 = time.perf_counter_ns()
        arm.process(e)
        out[name] = time.perf_counter_ns() - t0
    return out


def paired_rounds(workload: str, rounds: int, events: int, warmup: int,
                  workdir: Path, interval: int) -> Dict:
    make = WORKLOADS[workload]
    observations: List[List] = []      # [round, i, arm, position, ns]
    anchor_ns: List[int] = []
    decisions: Dict[str, Dict[str, int]] = {}
    verification = {}
    settings = None
    for r in range(rounds):
        folder = workdir / f"{workload}_round{r}"
        arms, key = _fresh_arms(folder, interval)
        settings = arms["A"].settings()
        for i in range(warmup + events):
            order = WILLIAMS[i % 4]
            times = _timed(arms, order, make(i))
            if i >= warmup:
                for pos, idx in enumerate(order):
                    observations.append([r, i - warmup, ARM_NAMES[idx], pos, times[ARM_NAMES[idx]]])
        anchor_ns += arms["Bplus"].anchor_ns
        for arm in arms.values():
            arm.close()
        # Same decisions in every arm, and every arm's output verifies.
        verification[r] = {n: verify_arm(n, folder, key)["valid"] for n in ARM_NAMES}
        if r == 0:
            decisions = _decisions(folder)
        shutil.rmtree(folder)
    return {"observations": observations, "anchor_ns": anchor_ns,
            "decisions_round0": decisions, "verification": verification,
            "sqlite_settings": settings}


def _decisions(folder: Path) -> Dict[str, Dict[str, int]]:
    import sqlite3

    from ledger_store import read_ledger

    out: Dict[str, Dict[str, int]] = {}
    c = sqlite3.connect(str(folder / "A.sqlite"))
    out["A"] = dict(c.execute("SELECT decision, COUNT(*) FROM events GROUP BY decision").fetchall())
    c.close()
    for name in ARM_NAMES[1:]:
        counts: Dict[str, int] = {}
        for rec in read_ledger(folder / f"{name}.jsonl"):
            counts[rec["decision"]] = counts.get(rec["decision"], 0) + 1
        out[name] = counts
    return out


def growth_run(n: int, block: int, workdir: Path, interval: int) -> Dict:
    folder = workdir / "growth"
    arms, key = _fresh_arms(folder, interval)
    series: Dict[str, List[int]] = {name: [] for name in ARM_NAMES}
    for i in range(n):
        times = _timed(arms, WILLIAMS[i % 4], w1_event(i))
        for name, ns in times.items():
            series[name].append(ns)
    for arm in arms.values():
        arm.close()
    valid = {name: verify_arm(name, folder, key)["valid"] for name in ARM_NAMES}
    shutil.rmtree(folder)
    blocks = {
        name: [round(statistics.median(values[k:k + block]) / 1e6, 4)
               for k in range(0, len(values), block)]
        for name, values in series.items()
    }
    return {"events": n, "block": block, "median_ms_per_block": blocks,
            "verification": valid, "observations_ns": series}


# ----------------------------------------------------------------------
# Summaries
# ----------------------------------------------------------------------

def _quantiles(values: Sequence[float]) -> Dict[str, float]:
    s = sorted(values)
    q = statistics.quantiles(s, n=100, method="inclusive")
    return {"q1": q[24], "median": statistics.median(s), "q3": q[74], "p95": q[94],
            "mean": statistics.fmean(s), "max": s[-1]}


def summarise(result: Dict, rounds: int) -> Dict:
    obs = result["observations"]
    by_arm: Dict[str, List[float]] = {n: [] for n in ARM_NAMES}
    by_round: Dict[str, Dict[int, List[float]]] = {n: {} for n in ARM_NAMES}
    paired: Dict[tuple, Dict[str, float]] = {}
    for r, i, name, _pos, ns in obs:
        ms = ns / 1e6
        by_arm[name].append(ms)
        by_round[name].setdefault(r, []).append(ms)
        paired.setdefault((r, i), {})[name] = ms

    def describe(values: List[float], per_round: Dict[int, List[float]]) -> Dict:
        pooled = _quantiles(values)
        return {
            "n": len(values),
            "median_of_round_medians": round(statistics.median(
                statistics.median(v) for v in per_round.values()), 4),
            **{k: round(v, 4) for k, v in pooled.items()},
        }

    arms = {n: describe(by_arm[n], by_round[n]) for n in ARM_NAMES}
    diffs = {}
    for a, b in DIFFERENCES:
        values, per_round = [], {}
        for (r, _i), row in paired.items():
            d = row[a] - row[b]
            values.append(d)
            per_round.setdefault(r, []).append(d)
        diffs[f"{a}-{b}"] = describe(values, per_round)
    anchor = result["anchor_ns"]
    return {
        "arms": arms,
        "paired_differences": diffs,
        "anchor_operation_ms": (_quantiles([x / 1e6 for x in anchor]) if len(anchor) > 1 else None),
        "anchors_measured": len(anchor),
        "position_check": _position_medians(obs),
    }


def _position_medians(obs) -> Dict[str, List[float]]:
    """Median latency per arm and position in the rotation (order effects)."""
    cells: Dict[str, Dict[int, List[float]]] = {n: {} for n in ARM_NAMES}
    for _r, _i, name, pos, ns in obs:
        cells[name].setdefault(pos, []).append(ns / 1e6)
    return {n: [round(statistics.median(cells[n][p]), 4) for p in sorted(cells[n])] for n in ARM_NAMES}


def table_t9(summaries: Dict[str, Dict]) -> List[str]:
    """Rows of Table T9: median [IQR] and P95, in ms, per workload and arm."""
    lines = ["| Workload | Arm | Median (ms) | IQR (ms) | P95 (ms) |",
             "| --- | --- | --- | --- | --- |"]
    for workload, s in summaries.items():
        for name in ARM_NAMES:
            a = s["arms"][name]
            lines.append(f"| {workload} | {name} | {a['median_of_round_medians']:.3f} | "
                         f"{a['q1']:.3f}–{a['q3']:.3f} | {a['p95']:.3f} |")
        for key, d in s["paired_differences"].items():
            lines.append(f"| {workload} | {key} | {d['median_of_round_medians']:.3f} | "
                         f"{d['q1']:.3f}–{d['q3']:.3f} | {d['p95']:.3f} |")
    return lines


# ----------------------------------------------------------------------

def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True,
                        help="names the machine; use 'validation-...' for runs that do not count")
    parser.add_argument("--workdir", type=Path, default=EXPERIMENTS_DIR / "wp3" / "_work")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--events", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--growth", type=int, default=10000)
    parser.add_argument("--block", type=int, default=1000)
    parser.add_argument("--interval", type=int, default=ANCHOR_INTERVAL)
    parser.add_argument("--workloads", default="W1,W2")
    args = parser.parse_args(argv)

    workdir = args.workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    results, summaries = {}, {}
    for workload in args.workloads.split(","):
        print(f"{workload}: {args.rounds} rounds x {args.events} events (+{args.warmup} warm-up)")
        results[workload] = paired_rounds(workload, args.rounds, args.events, args.warmup,
                                          workdir, args.interval)
        summaries[workload] = summarise(results[workload], args.rounds)
    growth = None
    if args.growth:
        print(f"growth: {args.growth} events per arm")
        growth = growth_run(args.growth, args.block, workdir, args.interval)
    settings = next(iter(results.values()))["sqlite_settings"]

    output = {
        "protocol": "Project/protocols/wp3_ablation.md",
        "label": args.label,
        "counts_for_article": not args.label.startswith("validation"),
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "parameters": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "environment": environment(workdir, settings),
        "williams_rows": WILLIAMS,
        "summaries": summaries,
        "table_t9": table_t9(summaries),
        "figure_f4": None if growth is None else {
            "block": growth["block"], "median_ms_per_block": growth["median_ms_per_block"]},
        "growth": growth,
        "runs": results,
    }
    out_dir = EXPERIMENTS_DIR / "wp3"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"ablation_{args.label}_{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(output) + "\n", encoding="utf-8")
    print("\n".join(output["table_t9"]))
    if growth:
        print(json.dumps(growth["median_ms_per_block"]))
    print(f"saved to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
