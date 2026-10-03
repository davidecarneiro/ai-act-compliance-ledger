# Functional check on a Fabric test network, 3 October 2026

The current chaincode (`prototype/fabric_migration/chaincode/`, with the
changes of September and October 2026) was deployed on a Hyperledger Fabric
test network and exercised through the delivered Gateway client. This is a
functional check. It is **not** one of the runs the dissertation cites: those
are the runs of June and July 2026 under `experiments/runs/fabric_run/`, and
the timings below do not replace them.

## Environment

Hyperledger Fabric 2.5.10 with Fabric CA 1.5.13, on one macOS machine (x86_64,
Docker 29.7.2). Two organisations (Org1MSP, Org2MSP), one Raft orderer, one CA
per organisation and one for the orderer, LevelDB. Channel `compliancechannel`,
chaincode `compliance` as Chaincode-as-a-Service, built with the delivered
Dockerfile from the vendored dependencies, endorsement policy
`AND('Org1MSP.peer','Org2MSP.peer')`. The network was brought up from a copy of
`fabric-samples` with the same channel, CA and policy parameters as
`deploy/01_up_and_deploy.sh`; the script itself was not used, because it starts
by tearing down the network under `~/fabric-workspace`.

## What was checked

| Check | Result | File |
|---|---|---|
| `SubmitEvidence` before `RegisterIssuer` | refused: issuer not registered | `negative_before.json` |
| `RegisterIssuer` with an Org2 identity | refused: only Org1MSP may register | `negative_before.json` |
| 30 records submitted through `gateway/gateway_measure.go` | all committed; `VerifyChain` returned `chain valid: 30 records` | `gateway_timings.json` |
| `GetEvidence`, `QueryByRequirement("Art.72")` | record returned with `submitter_msp = Org1MSP`; 30 records | `gateway_checks.json` |
| A signed record with `artifact_id` altered | refused: issuer signature verification failed | `gateway_checks.json` |
| An earlier record submitted again | refused: `parent_hash` mismatch | `gateway_checks.json` |
| A proposal endorsed by Org1MSP alone | ordered, then invalidated at commit: `ENDORSEMENT_POLICY_FAILURE` (block 37, code 10) | `gateway_checks.json`, `block_summary.json` |
| Two proposals endorsed over the same version of the head pointer | the first valid (block 38, code 0), the second invalidated: `MVCC_READ_CONFLICT` (block 39, code 11) | `gateway_checks.json`, `block_summary.json` |
| One more record with `scenario_id = null` | committed, returned with `null` preserved | `gateway_checks.json` |
| `VerifyChain` at the end | `chain valid: 31 records` | `gateway_checks.json` |
| Block 39's `previous_hash` against the recomputed header hash of block 38; channel information from both peers | equal; both peers report height 40 and the same hashes | `block_summary.json` |

The channel reached height 40 with 31 application records, because blocks
also hold configuration and lifecycle transactions and the two invalidated
ones. A transaction that fails validation stays in its block, marked invalid,
and does not change the state.

## The records

`onchain_records.json` holds the 31 records as returned by the peer, each with
the two fields the chaincode adds at commit (`submitter_msp`, `submitter_id`).
Without those two fields, which are outside the signed body, the records
verify with the public key alone:

```bash
cd prototype/compliance_ledger_sim
python3 - <<'EOF'
import json, sys
from cryptography.hazmat.primitives import serialization
from verify_delivery import verify_chain
records = json.load(open("../../docs/fabric_check_2026-10-03/onchain_records.json"))
signed = [{k: v for k, v in r.items() if k not in ("submitter_msp", "submitter_id")}
          for r in records]
pub = serialization.load_pem_public_key(
    open("keys/compliance-oracle-v1.ed25519.pub.pem", "rb").read())
valid, issues = verify_chain(signed, pub)
print(f"{valid}/{len(signed)} valid", issues)
sys.exit(0 if valid == len(signed) and not issues else 1)
EOF
```

It prints `31/31 valid []`. The final `chain_hash` is
`92e5b43dadeb16e37a8dd1970d2c767646bd1f3fd004fc21a7a8f85a29a27502`. The records
were signed with the demonstration key that ships with this project, so a valid
signature shows that they are unchanged since signing, not who signed them.

## Timings

`gateway_timings.json` is the output of the delivered client on this run:
median 2,035.5 ms to commit (29 submissions after one warm-up) and median
20.0 ms for a `VerifyChain` query over 30 records (20 calls). The keys
`evaluate_endorse_*` and the note inside the file use the client's earlier
wording; what they time is a read-only query through the Gateway, executed on
one peer, without ordering or commit. No LevelDB/CouchDB comparison was
repeated.

## What this does not show

Fault tolerance with several orderers, organisations on separate machines,
keys in an HSM or KMS, or the security of a production deployment. The link
between peer and chaincode (CCaaS) ran without TLS, as on the test network.
The block files, the endorsers' certificates and the container logs of the run
are kept by the author and are not part of this folder.
