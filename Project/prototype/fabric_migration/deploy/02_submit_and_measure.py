#!/usr/bin/env python3
"""Historical peer-CLI measurement client for the Fabric experiment.

Times include process startup, connection setup and the requested network
operation. They do not isolate endorsement or cryptographic execution.
The Gateway client provides the separate persistent-connection measurement.

The issuer key is registered first (RegisterIssuer, as the Org1 admin), then
each record is submitted with SubmitEvidence(recordJSON); the chaincode takes
the verification key from its on-chain registry, never from the caller.

Run: python3 02_submit_and_measure.py [N]  (default N=30; the network must be up
with the 'compliance' chaincode deployed by 01_up_and_deploy.sh)."""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE.parents[1] / "compliance_ledger_sim"
WORKSPACE = Path.home() / "fabric-workspace"
SAMPLES = WORKSPACE / "fabric-samples"
TESTNET = SAMPLES / "test-network"
PEERORG = TESTNET / "organizations" / "peerOrganizations"
ORDORG = TESTNET / "organizations" / "ordererOrganizations"
def _experiments() -> Path:
    """Same markers as compliance_ledger_sim/paths.py: vault or delivered folder."""
    env = os.environ.get("EXPERIMENTS_DIR")
    if env:
        return Path(env)
    for parent in HERE.parents:
        if (parent / "06_dados").is_dir() and (parent / "04_projeto").is_dir():
            return parent / "06_dados" / "experiments"
        if (parent / "prototype").is_dir() and (parent / "experiments").is_dir():
            return parent / "experiments"
    return HERE.parents[2] / "experiments"


_EXP = _experiments()
# Same rule as paths.py: in the delivered folder the runs live under runs/.
OUT = (_EXP / "runs" / "fabric_run") if (_EXP / "runs").is_dir() else (_EXP / "fabric_run")

CHANNEL = "compliancechannel"
CCNAME = "compliance"
ORDERER_CA = str(ORDORG / "example.com" / "orderers" / "orderer.example.com" /
                 "msp" / "tlscacerts" / "tlsca.example.com-cert.pem")
ORG1_CA = str(PEERORG / "org1.example.com" / "peers" / "peer0.org1.example.com" /
              "tls" / "ca.crt")
ORG2_CA = str(PEERORG / "org2.example.com" / "peers" / "peer0.org2.example.com" /
              "tls" / "ca.crt")


def org1_env() -> dict:
    env = os.environ.copy()
    env["PATH"] = f"{SAMPLES/'bin'}:{env['PATH']}"
    env["FABRIC_CFG_PATH"] = str(SAMPLES / "config")
    env["CORE_PEER_TLS_ENABLED"] = "true"
    env["CORE_PEER_LOCALMSPID"] = "Org1MSP"
    env["CORE_PEER_TLS_ROOTCERT_FILE"] = ORG1_CA
    env["CORE_PEER_MSPCONFIGPATH"] = str(
        PEERORG / "org1.example.com" / "users" /
        "Admin@org1.example.com" / "msp")
    env["CORE_PEER_ADDRESS"] = "localhost:7051"
    return env


def raw_pubkey_hex() -> str:
    sys.path.insert(0, str(SIM))
    from keys import load_or_create_key  # noqa: E402
    from cryptography.hazmat.primitives import serialization  # noqa: E402
    raw = load_or_create_key().public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    return raw.hex()


def gen_chain(n: int, cont: bool) -> list[dict]:
    """Generate n records. With cont=False, a fresh chain from the genesis. With
    cont=True, CONTINUE the chain already on Fabric (reads _gen_ledger.json and
    extends it), for a second measurement without restarting the network."""
    sys.path.insert(0, str(SIM))
    from simulator import ComplianceOracle  # noqa: E402
    from scenarios import build_scenarios  # noqa: E402
    tmp = OUT / "_gen_ledger.json"
    OUT.mkdir(parents=True, exist_ok=True)
    oracle = ComplianceOracle(ledger_file=tmp)
    before = len(json.loads(tmp.read_text())) if (cont and tmp.exists()) else 0
    if not cont:
        oracle.reset_ledger()
    base = build_scenarios()
    for i in range(before, before + n):
        ev = dict(base[i % len(base)])
        ev["scenario_id"] = f"{ev['scenario_id']}-{i:04d}"  # unique id per event
        oracle.process_mlops_event(ev)
    return json.loads(tmp.read_text())[before:before + n]


def _invoke(function: str, args: list[str], env: dict, wait: bool) -> float:
    ctor = json.dumps({"function": function, "Args": args})
    cmd = [
        "peer", "chaincode", "invoke",
        "-o", "localhost:7050", "--ordererTLSHostnameOverride", "orderer.example.com",
        "--tls", "--cafile", ORDERER_CA,
        "-C", CHANNEL, "-n", CCNAME,
        "--peerAddresses", "localhost:7051", "--tlsRootCertFiles", ORG1_CA,
        "--peerAddresses", "localhost:9051", "--tlsRootCertFiles", ORG2_CA,
    ] + (["--waitForEvent"] if wait else []) + ["-c", ctor]
    t0 = time.perf_counter()
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    dt = (time.perf_counter() - t0) * 1000
    if res.returncode != 0 or "result: status:200" not in (res.stdout + res.stderr):
        raise RuntimeError(f"{function} failed: {res.stderr.strip()[:300]}")
    return dt


def register_issuer(pubkey: str, env: dict) -> None:
    """Put the issuer key in the on-chain registry. Registering the same key again
    overwrites it with itself, so this is safe on a network that already has it."""
    _invoke("RegisterIssuer", [pubkey], env, wait=True)


def invoke_submit(record: dict, env: dict, wait: bool) -> float:
    # Only the record: the verification key comes from the on-chain registry.
    return _invoke("SubmitEvidence", [json.dumps(record, separators=(",", ":"))], env, wait)


def query_verify(env: dict) -> tuple[str, float]:
    """Query VerifyChain (executes on the peer, WITHOUT ordering). Returns (result, ms)."""
    cmd = ["peer", "chaincode", "query", "-C", CHANNEL, "-n", CCNAME,
           "-c", json.dumps({"function": "VerifyChain", "Args": []})]
    t0 = time.perf_counter()
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    dt = (time.perf_counter() - t0) * 1000
    return (res.stdout or res.stderr).strip(), dt


def cli_startup_baseline(env: dict, k: int = 8) -> float:
    """Median time of 'peer version': peer process start-up plus config reading,
    WITHOUT network. Isolates the overhead that EVERY CLI measurement carries, so
    that the contrast with the in-process simulator is honest."""
    xs = []
    for _ in range(k):
        t0 = time.perf_counter()
        subprocess.run(["peer", "version"], env=env, capture_output=True, text=True)
        xs.append((time.perf_counter() - t0) * 1000)
    return round(statistics.median(xs), 2)


def p95(xs: list[float]) -> float:
    s = sorted(xs)
    k = max(0, min(len(s) - 1, round(0.95 * (len(s) - 1))))
    return s[k]


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    cont = os.getenv("CONTINUE", "0") == "1"
    env = org1_env()
    pubkey = raw_pubkey_hex()
    records = gen_chain(n, cont)
    register_issuer(pubkey, env)
    print(f"submitting {len(records)} records to the Fabric network (2-org endorsement)…")

    # WRITE path: SubmitEvidence with --waitForEvent. The design chains each record
    # onto the previous one (parent_hash == chainHead), so waiting for each commit
    # before the next is MANDATORY. It cannot be pipelined.
    # Warm-up: the first invoke starts the CCaaS container (cold start), so it is
    # excluded.
    write = []
    for idx, rec in enumerate(records):
        dt = invoke_submit(rec, env, wait=True)
        if idx == 0:
            print(f"  [warm-up] first invoke (cold start) = {dt:.1f} ms, excluded")
            continue
        write.append(dt)
        if idx % 5 == 0:
            print(f"  {idx}/{len(records)} … last {dt:.1f} ms")

    # EXECUTION/ENDORSEMENT path: query (no ordering, no commit). Isolates the
    # execution cost on the peer from the ordering and batch-timeout cost of a write.
    verify, _ = query_verify(env)
    qlat = []
    for _ in range(20):
        _, qdt = query_verify(env)
        qlat.append(qdt)

    # Baseline: EVERY CLI measurement includes 'peer' process start-up, config reading
    # and TLS/gRPC setup. 'peer version' (no network) is measured to make that explicit.
    cli_base = cli_startup_baseline(env)

    res = {
        "fabric_version": "2.5.10",
        "endorsement_policy": "AND('Org1MSP.peer','Org2MSP.peer')",
        "orderer_batch_timeout_s": 2,
        "orderer_max_messages_per_block": 10,
        "chain_length_after_run": verify,
        "method": "peer CLI (subprocess) per invocation, no connection reuse",

        "cli_process_startup_ms_median": cli_base,

        "write_commit_n": len(write),
        "write_commit_ms_mean": round(statistics.mean(write), 2),
        "write_commit_ms_median": round(statistics.median(write), 2),
        "write_commit_ms_p95": round(p95(write), 2),
        "write_commit_ms_min": round(min(write), 2),
        "write_commit_ms_max": round(max(write), 2),

        "query_exec_n": len(qlat),
        "query_exec_ms_mean": round(statistics.mean(qlat), 2),
        "query_exec_ms_median": round(statistics.median(qlat), 2),
        "query_exec_ms_p95": round(p95(qlat), 2),

        "honest_caveat": (
            f"All times are measured through the 'peer' CLI process (one fork per call, "
            f"no connection reuse) and INCLUDE about {cli_base} ms of CLI start-up plus "
            f"TLS/gRPC setup. They are therefore an UPPER BOUND on the cost attributable to "
            f"the chaincode and the network. Pure chaincode execution is a fraction of "
            f"query_exec. The citable figures come from the Fabric Gateway SDK client "
            f"(gateway/gateway_measure.go); do not compare these with the simulator's local "
            f"times, whose citable figure is the paired protocol of 2026-09-14."
        ),
        "interpretation": (
            "write_commit is dominated by the orderer's BatchTimeout=2s (each serial "
            "transaction waits for the block to be cut; the chained parent_hash==chainHead "
            "design cannot be pipelined). This is an INFERENCE from the minimal variance "
            "around 2000 ms, not a controlled run. The direction of RQ4 (the bottleneck moves "
            "from local cryptography to distributed coordination) holds; the exact multiples depend on the measurement method."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fabric_latency.json").write_text(json.dumps(res, indent=2))
    print("\n=== RESULTADO ===")
    print(json.dumps(res, indent=2, ensure_ascii=False))
    print(f"\nsaved to {OUT/'fabric_latency.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
