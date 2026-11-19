#!/usr/bin/env python3
"""Data figures of the article, drawn from the results JSON (WP9).

    python3 figures.py [--wp3 FILE] [--wp7 FILE] [--allow-validation]

* F4: latency per event against ledger size, per arm of the ablation
  (``experiments/article/wp3/ablation_<label>_*.json``, growth run).
* F5: anchoring on Fabric, three panels against records per anchor N, one
  line per orderer BatchTimeout (``experiments/article/wp7/summary_*.json``):
  (a) durable-evidence throughput, with the event rate of the live MultiFlow
  Steel_Industry run as a reference line; (b) the measured anchor latency
  (saturated mode); (c) the expected time from emission to durable evidence
  at that rate, the measured latency plus the analytic mean wait for the
  batch to fill, (N - 1)/(2 rate), omitted where serial anchoring is slower
  than the stream (protocol WP7, estimands).
* F6: the same OSCAL finding, complete and redacted, as two JSON excerpts for
  the article to typeset side by side (from the credit case's exports).

By default only runs that count for the article are used (their label does
not start with "validation"); ``--allow-validation`` draws validation runs
too, and stamps the figure as such. Output: ``experiments/article/figures/``
with PDF and PNG, and ``figures_manifest.json`` naming each figure's sources.

Colours: the first four slots of the validated categorical palette, in fixed
order (A, B0, B, B+), each with its own marker and dash and a direct label,
so identity never rests on colour alone and survives greyscale print.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
SIM = HERE.parent / "compliance_ledger_sim"
if str(SIM) not in sys.path:
    sys.path.insert(0, str(SIM))
from paths import EXPERIMENTS_DIR  # noqa: E402

OUT_DIR = EXPERIMENTS_DIR / "figures"
MM = 1 / 25.4
SINGLE, DOUBLE = 90 * MM, 190 * MM       # Elsevier column widths

# Validated categorical slots 1-4 (blue, orange, aqua, yellow), fixed order.
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
ARMS = [("A", "A  SQLite row"), ("B0", "B0  hash chain"), ("B", "B  signed"),
        ("Bplus", "B+  anchored")]
MARKERS = ["o", "s", "^", "D"]
DASHES = ["-", "--", "-.", ":"]
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8, "axes.titlesize": 8.5,
    "axes.labelsize": 8, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
    "legend.fontsize": 7.5, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.linewidth": 0.6,
    "pdf.fonttype": 42, "ps.fonttype": 42,
})


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _newest(folder: Path, pattern: str, allow_validation: bool) -> Optional[Path]:
    hits = []
    for path in sorted(folder.glob(pattern)):
        data = json.loads(path.read_text(encoding="utf-8"))
        counts = data.get("counts_for_article", True)
        label = data.get("label", "")
        if counts or allow_validation:
            hits.append((counts, path))
    if not hits:
        return None
    counting = [p for c, p in hits if c]
    return counting[-1] if counting else hits[-1][1]


def _axes(ax) -> None:
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def _stamp(fig, validation: bool, source: str) -> None:
    if validation:
        fig.text(0.99, 0.005, f"VALIDATION RUN - not for the article ({source})",
                 ha="right", va="bottom", fontsize=6, color="#e34948")


def figure_f4(wp3: Path, out: Path) -> Dict:
    data = json.loads(wp3.read_text(encoding="utf-8"))
    growth = data["figure_f4"]
    block = growth["block"]
    fig, ax = plt.subplots(figsize=(SINGLE, 62 * MM))
    _axes(ax)
    last_points = []
    for k, (key, label) in enumerate(ARMS):
        series = growth["median_ms_per_block"][key]
        x = [(i + 1) * block for i in range(len(series))]
        ax.plot(x, series, color=SLOTS[k], linestyle=DASHES[k], linewidth=1.6,
                marker=MARKERS[k], markersize=4, markerfacecolor=SLOTS[k],
                markeredgecolor="white", markeredgewidth=0.6, label=label)
        last_points.append((series[-1], label.split()[0], SLOTS[k]))
    ax.set_xlabel("Records in the ledger")
    ax.set_ylabel("Median latency per event (ms)")
    ax.set_ylim(bottom=0)
    ax.set_xlim(0, (len(series) + 1.6) * block)
    # Direct labels at the line ends, nudged apart, in text ink.
    last_points.sort()
    placed: List[float] = []
    span = ax.get_ylim()[1]
    for y, name, colour in last_points:
        y_text = max([y] + [p + 0.065 * span for p in placed])
        placed.append(y_text)
        ax.annotate(name, xy=(len(series) * block, y), xytext=(len(series) * block + 0.25 * block, y_text),
                    fontsize=7, color=INK, va="center",
                    arrowprops=dict(arrowstyle="-", color=colour, linewidth=0.6))
    ax.legend(loc="lower left", frameon=False, ncol=2, handlelength=2.6)
    validation = not data.get("counts_for_article", True)
    _stamp(fig, validation, data.get("label", ""))
    fig.tight_layout()
    paths = _save(fig, out, "F4_latency_vs_ledger_size")
    return {"figure": "F4", "files": paths, "source": str(wp3), "source_sha256": _sha(wp3),
            "label": data.get("label"), "validation": validation,
            "environment": {k: data["environment"].get(k) for k in ("cpu", "platform", "workdir_filesystem")}}


def _seconds(value) -> float:
    """'2s' -> 2.0, '250ms' -> 0.25 (orders BatchTimeouts by duration)."""
    text = str(value)
    try:
        return float(text[:-2]) / 1000 if text.endswith("ms") else float(text.rstrip("s"))
    except ValueError:
        return float("inf")


STREAM_LEDGER = "runs/multiflow_run_steel/ledger.json"


def stream_rate(ledger_file: Optional[Path] = None) -> Dict:
    """Event rate of the live MultiFlow Steel_Industry run (published, v1).

    Events over the time from the first record to the last: the rate at which
    the dissertation's live Kafka run produced evidence, used as the arrival
    rate for the analytic wait to fill a batch."""
    from paths import PUBLISHED_DIR

    path = ledger_file or PUBLISHED_DIR / STREAM_LEDGER
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    stamps = [datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) for r in records]
    span = (stamps[-1] - stamps[0]).total_seconds()
    return {"source": str(path), "source_sha256": _sha(path), "events": len(records),
            "span_s": span, "events_per_s": (len(records) - 1) / span}


def expected_latency_s(anchor_ms: float, n: int, throughput: float, rate: float) -> Optional[float]:
    """Mean time from emission to durable evidence at arrival rate ``rate``.

    The measured latency of the anchor (saturated mode) plus the mean wait for
    the batch to fill, (N - 1)/(2 rate) (protocol WP7, estimands). None when
    serial anchoring cannot keep up with the stream (throughput below rate):
    the queue then grows without bound."""
    if throughput < rate:
        return None
    return anchor_ms / 1000 + (n - 1) / (2 * rate)


def figure_f5(wp7: Path, out: Path) -> Dict:
    data = json.loads(wp7.read_text(encoding="utf-8"))
    runs = [r for r in data["runs"] if not r.get("queries_only")
            and len(r["per_n"]) > 2]
    rate = stream_rate()
    lam = rate["events_per_s"]
    fig, (left, mid, right) = plt.subplots(1, 3, figsize=(DOUBLE, 64 * MM))
    for ax in (left, mid, right):
        _axes(ax)
        ax.set_xscale("log")
        ax.set_xlabel("Records per anchor, N")
    validation = any(str(r.get("label", "")).startswith("validation") for r in runs)
    expected_rows = {}
    # Colour follows the setting: the longer BatchTimeout (2 s, the
    # dissertation's) takes slot 1 whichever runs are present.
    for k, run in enumerate(sorted(runs, key=lambda r: -_seconds(r["environment"].get("batch_timeout")))):
        ns = sorted(int(n) for n in run["per_n"])
        bt = run["environment"].get("batch_timeout", "?")
        thr = [run["per_n"][str(n)]["throughput_records_per_s"]["median"] for n in ns]
        lat = [run["per_n"][str(n)]["durable_latency_ms_per_record"] for n in ns]
        style = dict(color=SLOTS[k], linestyle=DASHES[k], linewidth=1.6, marker=MARKERS[k],
                     markersize=4, markeredgecolor="white", markeredgewidth=0.6)
        left.plot(ns, thr, label=f"BatchTimeout {bt}", **style)
        mid.plot(ns, [q["median"] for q in lat], label=f"BatchTimeout {bt}", **style)
        mid.fill_between(ns, [q["q1"] for q in lat], [q["q3"] for q in lat],
                         color=SLOTS[k], alpha=0.12, linewidth=0)
        exp = [(n, expected_latency_s(q["median"], n, t, lam)) for n, q, t in zip(ns, lat, thr)]
        expected_rows[str(bt)] = {str(n): e for n, e in exp}
        kept = [(n, e) for n, e in exp if e is not None]
        if kept:
            right.plot([n for n, _ in kept], [e for _, e in kept], **style)
            right.annotate(f"{bt}", xy=kept[0], xytext=(-5, 0), textcoords="offset points",
                           fontsize=7, color=INK, va="center", ha="right")
        left.annotate(f"{bt}", xy=(ns[-1], thr[-1]), xytext=(4, 0), textcoords="offset points",
                      fontsize=7, color=INK, va="center")
    left.axhline(lam, color=MUTED, linewidth=0.8, linestyle=(0, (2, 2)))
    left.annotate(f"MultiFlow run\n{lam:.1f} events/s", xy=(850, lam), xytext=(0, -4),
                  textcoords="offset points", fontsize=6.5, color=MUTED, va="top", ha="right",
                  linespacing=1.1)
    right.text(0.03, 0.97, "Points omitted where serial\nanchoring is slower\nthan the stream",
               transform=right.transAxes, fontsize=6.5, color=MUTED, va="top", linespacing=1.1)
    left.set_yscale("log")
    left.set_ylabel("Durable records per second")
    left.set_title("(a) Throughput", loc="left")
    mid.set_ylabel("Latency per record (ms)")
    mid.set_ylim(bottom=0)
    mid.set_title("(b) Anchor latency (median, IQR)", loc="left")
    right.set_yscale("log")
    right.set_ylabel("Emission to durable evidence (s)")
    right.set_title(f"(c) Expected at {lam:.1f} events/s", loc="left")
    for ax in (left, mid, right):
        ax.set_xticks([1, 10, 100, 500])
        ax.set_xlim(0.7, 900)
        ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    right.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    left.legend(loc="upper left", frameon=False)
    _stamp(fig, validation, ", ".join(str(r.get("label")) for r in runs))
    fig.tight_layout()
    paths = _save(fig, out, "F5_anchoring_vs_batch_size")
    return {"figure": "F5", "files": paths, "source": str(wp7), "source_sha256": _sha(wp7),
            "validation": validation, "stream_rate": rate,
            "panel_c": {"note": "measured anchor latency (median) + (N - 1)/(2 rate); "
                                "None where throughput < rate (serial anchoring cannot keep up)",
                        "expected_s": expected_rows}}


def figure_f6(out: Path) -> Optional[Dict]:
    """JSON excerpts of one finding, complete and redacted, from the credit case.

    Exported afresh from the run's ledger with the current exporter, not read
    from the run's archived exports: those were written before the exporter
    took the article's terms (Compliance Policy Engine; "permissioned ledger"
    only for records a ledger stamped), and the figure shows the exporter as
    the article describes it. The ledger is the run's own, and its signatures
    are checked against the public keys published with the run."""
    import oscal_exporter
    from ledger_store import read_ledger

    runs = sorted((EXPERIMENTS_DIR / "wp4").glob("run_*"))
    if not runs:
        return None
    run = runs[0]
    ledger = read_ledger(run / "ledger.jsonl")
    chain_ok = oscal_exporter.verify_chain_structure(ledger)
    signatures_ok = oscal_exporter.verify_signatures(ledger, keys_dir=run / "keys")
    excerpts = {}
    # The provider's key for the redacted export's policy commitment, kept with
    # the figure so that its commitment can be opened against the run's policy.
    key = oscal_exporter.new_commitment_key()
    (out / "F6_policy_commitment.key").write_text(key.hex() + "\n", encoding="utf-8")
    for variant in ("complete", "redacted"):
        doc = oscal_exporter.to_oscal_sar(ledger, chain_valid=chain_ok, redacted=variant == "redacted",
                                          signatures_verified=signatures_ok,
                                          commitment_key=key if variant == "redacted" else None)
        result = doc["assessment-results"]["results"][0]
        # The finding on the validation of model v2 (record 8): the fairness gate.
        finding = result["findings"][7]
        observation = next(o for o in result["observations"]
                           if o["uuid"] == finding["related-observations"][0]["observation-uuid"])
        excerpts[variant] = {"observation": observation, "finding": finding}
        path = out / f"F6_finding_{variant}.json"
        path.write_text(json.dumps(excerpts[variant], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"figure": "F6", "files": [str(out / f"F6_finding_{v}.json") for v in excerpts],
            "source": str(run / "ledger.jsonl"), "source_sha256": _sha(run / "ledger.jsonl"),
            "chain_valid": chain_ok, "signatures_verified": signatures_ok,
            "note": "record 8 of the credit case (validation of v2, fairness gate), "
                    "exported with the current exporter"}


def _save(fig, out: Path, name: str) -> List[str]:
    paths = []
    for ext in ("pdf", "png"):
        path = out / f"{name}.{ext}"
        fig.savefig(path, dpi=300 if ext == "png" else None, facecolor="white")
        paths.append(str(path))
    plt.close(fig)
    return paths


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wp3", type=Path)
    parser.add_argument("--wp7", type=Path)
    parser.add_argument("--allow-validation", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    made = []
    wp3 = args.wp3 or _newest(EXPERIMENTS_DIR / "wp3", "ablation_*.json", args.allow_validation)
    made.append(figure_f4(wp3, args.out) if wp3 else {"figure": "F4", "missing": "no WP3 run"})
    wp7 = args.wp7 or _newest(EXPERIMENTS_DIR / "wp7", "summary_*.json", args.allow_validation)
    made.append(figure_f5(wp7, args.out) if wp7 else {"figure": "F5", "missing": "no WP7 summary"})
    made.append(figure_f6(args.out) or {"figure": "F6", "missing": "no credit-case run"})
    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(), "figures": made}
    (args.out / "figures_manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    for m in made:
        print(m["figure"], m.get("missing") or ", ".join(Path(f).name for f in m["files"]),
              "(validation)" if m.get("validation") else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
