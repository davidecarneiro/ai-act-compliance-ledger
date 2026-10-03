#!/usr/bin/env python3
"""Compare Python and Go canonical hashes over six test vectors.

Three synthetic vectors exercise escaping. The first record from each of
three delivered ledgers supplies the real-data vectors. Missing or empty
required ledgers cause failure. Run: python3 test_interop.py."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SIM = Path(__file__).parents[1].parent / "compliance_ledger_sim"
sys.path.insert(0, str(SIM))
from simulator import canonical_json  # noqa: E402

from paths import EXPERIMENTS_DIR, run_dir  # noqa: E402

HERE = Path(__file__).parent
EXPERIMENTS = Path(EXPERIMENTS_DIR)
DERIVED = {"record_hash", "issuer_signature", "chain_hash"}
em_falta: list = []


def body_of(record: dict) -> dict:
    """The hashed canonical body is the record without its derived fields."""
    return {k: v for k, v in record.items() if k not in DERIVED}


def vectors() -> list[tuple[str, dict]]:
    vs: list[tuple[str, dict]] = []
    # 1. Demanding synthetic vector: HTML, non-ASCII, an array and unsorted keys
    vs.append(("sintetico_html_naoascii", {
        "reason": "a < b & c > d",
        "note": "conformity assessment — incidenté",
        "requirements_covered": ["Art.73", "Art.12"],
        "id": "x",
    }))
    # 1b. Astral plane (emoji) plus U+2028 line separators: exercises asciiEscape's
    # surrogate pairs, which have to match Python's ensure_ascii.
    vs.append(("sintetico_astral_emoji", {
        "reason": "serious incident \U0001F6A8 reported",
        "tag": "line separator end",
        "id": "y",
    }))
    # 1c. Control character 0x7F (DEL): Python's ensure_ascii escapes it, while Go
    # left it literal by default. Edge case fixed in asciiEscape.
    vs.append(("sintetico_control_del", {
        "reason": "field with DEL \x7f and tab \t in the middle",
        "id": "z",
    }))
    # 2. Real record bodies from the ledgers. These are the point of the exercise:
    # the synthetic vectors exercise the escaping, and only the real bodies show
    # that the two implementations agree on the records the dissertation ships.
    # The ledgers sit in different places in the vault and in the delivered
    # folder, so they are resolved through the same EXPERIMENTS_DIR that the
    # prototype uses, and the local one is taken next to the simulator.
    for name, p in [
        ("incident", run_dir("incident_run") / "ledger.json"),
        ("multiflow_real", run_dir("multiflow_run_real") / "ledger.json"),
        ("canonico", SIM / "ledger.json"),
    ]:
        if not p.exists():
            em_falta.append((name, p, "missing"))
            continue
        try:
            led = json.loads(p.read_text())
        except Exception as e:                    # noqa: BLE001
            em_falta.append((name, p, f"unreadable: {e}"))
            continue
        if not led:
            em_falta.append((name, p, "empty"))
            continue
        corpo = body_of(led[0])
        if not isinstance(corpo, dict) or "record_hash" in corpo or not corpo:
            em_falta.append((name, p, "the first record does not look like an evidence body"))
            continue
        vs.append((f"real_{name}", corpo))
    return vs


def main() -> int:
    ok = 0
    total = 0
    todos = vectors()          # once only: the missing-ledger list grows on every call
    for label, payload in todos:
        total += 1
        py = canonical_json(payload)
        with tempfile.NamedTemporaryFile("wb", suffix=".bin", delete=False) as f:
            f.write(py)
            tmp = f.name
        res = subprocess.run(
            ["go", "run", str(HERE / "canonical_interop.go"), tmp],
            capture_output=True, text=True,
        )
        passed = "hash coincide  : true" in res.stdout
        ok += passed
        print(f"[{'OK  ' if passed else 'FAIL'}] {label}")
        if not passed:
            print(res.stdout)
            print(res.stderr)
    print(f"\n{ok}/{total} vectors with identical Python/Go hash")
    reais = sum(1 for label, _ in todos if label.startswith("real_"))
    if em_falta or reais != 3:
        print("\nERROR: the interoperability proof needs the three real ledgers, and")
        print("without them it compares nothing but synthetic vectors.")
        for nome, caminho, porque in em_falta:
            print(f"   {nome}: {porque} — {caminho}")
        if not em_falta:
            print(f"   only {reais} of the 3 real vectors ran")
        return 1
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
