#!/usr/bin/env python3
"""Stand-in for the anchorbench client, to test run_wp7.py without Fabric.

It answers each command in the client's output format, with a fixed 2 ms per
call, and keeps the anchors it was given in a state file
(FAKE_ANCHORBENCH_STATE) so that the export returns them. It verifies
nothing: the chaincode's behaviour is tested in Go (anchors_test.go).
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _args(argv):
    out, i = {}, 0
    while i < len(argv):
        if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            out[argv[i]] = argv[i + 1]
            i += 2
        else:
            out[argv[i]] = True
            i += 1
    return out


_BASE = time.time_ns()


def _call(i, ok=True, result="", error="", code=""):
    start = _BASE + i * 2_000_000          # one call after the other, 2 ms each
    c = {"i": i, "start_unix_ns": start, "end_unix_ns": start + 2_000_000, "ms": 2.0, "ok": ok}
    if result:
        c["result"] = result
    if error:
        c["error"], c["code"] = error, code
    return c


def main() -> int:
    command, args = sys.argv[1], _args(sys.argv[2:])
    state_file = Path(os.environ["FAKE_ANCHORBENCH_STATE"])
    state = json.loads(state_file.read_text()) if state_file.exists() else {"anchors": {}, "chain": 0}
    lines = []
    if isinstance(args.get("-in"), str) and command != "singleorg":
        lines = [l for l in Path(args["-in"]).read_text().splitlines() if l.strip()]
    calls = []
    if command == "register":
        calls = [_call(0)]
    elif command == "submit":
        calls = [_call(i) for i, _ in enumerate(lines)]
        state["chain"] += len(lines)
    elif command == "anchor":
        for i, line in enumerate(lines):
            anchor = json.loads(line)
            stream = anchor["statement"]["stream"]
            state["anchors"].setdefault(stream, []).append(
                {**anchor, "submitter_msp": "Org1MSP", "submitter_id": "x509::fake", "tx_id": f"tx{i}"})
            calls.append(_call(i))
    elif command == "inclusion":
        calls = [_call(i, result=json.dumps({"included": True, "seq": i + 1}, separators=(",", ":")))
                 for i, _ in enumerate(lines)]
    elif command == "verifychain":
        calls = [_call(i, result=f"chain valid: {state['chain']} records")
                 for i in range(int(args.get("-repeat", 20)))]
    elif command == "anchors":
        stream = args["-stream"]
        anchors = state["anchors"].get(stream, [])
        calls = [_call(0, result=json.dumps({"stream": stream, "anchors": anchors,
                                             "head": {"last_seq": len(anchors)}}))]
    elif command == "singleorg":
        calls = [_call(0, ok=False, error="transaction failed to commit", code="ENDORSEMENT_POLICY_FAILURE")]
    state_file.write_text(json.dumps(state))
    now = datetime.now(timezone.utc).isoformat()
    Path(args["-out"]).write_text(json.dumps({"command": command, "started_at": now,
                                              "finished_at": now, "calls": calls}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
