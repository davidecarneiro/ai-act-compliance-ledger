# Hyperledger Fabric measurements: what to read and what to ignore in these artefacts

*Written on 2026-09-17, after an audit found the problem described below.*

## The `note` field of the three Gateway artefacts is out of date

`fabric_latency_gateway.json`, `fabric_latency_gateway_leveldb.json` and
`fabric_latency_gateway_couchdb.json` carry a `note` field that ends by saying:

> «Contrast with the simulator's 3.79 ms in-process (RQ4).»

**Do not draw that contrast.** The 3.79 ms come from the run of 2026-04-29,
which was declared **exploratory** on 2026-09-14: it measured six events in a
single run, with no warm-up and no repetition, and on re-measurement the sign
of the difference flipped. The citable local latency comes from the paired
protocol fixed before the measurements (`LATENCY_PROTOCOL_2026-09-14.md`):
the first paired run reports an Oracle median of round medians of **6.47 ms**
and a paired median of round medians of **+5.08 ms**. The second run preserves
2,000 paired event observations, whose interquartile interval is **3.21 to
7.30 ms**.

The `note` is also half in Portuguese: it was written before the code's
comments and messages were translated into English.

**The measurements themselves were not touched**, neither the times, nor the
percentiles, nor the chaining proof. Only the annotation aged, and rewriting a
published artefact to correct it would be worse than declaring it here. The
source that generates them
(`prototype/fabric_migration/gateway/gateway_measure.go`) has already been
corrected, and a new run writes the right note, in English.

## What these artefacts measure, and what they do not

| Field | What it is |
|---|---|
| `evaluate_endorse_ms_*` | A read-only `VerifyChain` query over thirty records through the Gateway: client, transport and peer execution costs, **without ordering or commit**. The key name is historical; it is not the endorsement of a write. Median about 16.9 ms on LevelDB, about 27.1 ms on CouchDB. |
| `submit_commit_ms_*` | Time to **durable** evidence, ordering included. About 2,030 ms on LevelDB and 2,054 ms on CouchDB, dominated by the orderer's `BatchTimeout=2s`, which is a configuration parameter and not a cryptographic cost. |
| `verify_chain` | The literal output of the verification transaction. |

The baseline artefact the dissertation cites is the **LevelDB** one. The
re-measurement of 2026-06-13 used the **same thirty records** in both
configurations, deliberately: the aim was to isolate the state engine, not the
size of the chain. `VerifyChain` scales with the number of signatures, so
comparing runs over chains of different sizes would say nothing about LevelDB
against CouchDB.

## The first measurement, through the `peer` CLI (`fabric_latency.json`)

The first run of 2026-06-13 (Gate C of the migration) submitted 30 records on
a fresh chain through the `peer` command-line client, one process per call:
`chain valid: 30 records`. It recorded a mean of 2,152 ms to commit (n = 29,
P95 2,200 ms) and a mean of 104 ms per query (n = 20). Every call includes
about 74 ms of process start-up (the time of `peer version` with no network),
plus TLS and gRPC set-up, so these figures are an upper bound and not the
execution time of the chaincode. That the commit time is dominated by the
orderer's two-second batch timeout is an inference from the small variance
around 2,000 ms; no control run with another timeout was made. The file's
`honest_caveat` and `interpretation` fields, in Portuguese, say the same and,
like the `note` above, still contrast with the withdrawn 3.79 ms. The Gateway
measurement replaced this one; it stays as a cross-check.

## The Gateway re-measurement of 2026-06-13

Made later the same day, on the network brought up with a Fabric CA per
organisation and with the chaincode that has the issuer registry and the head
pointer. The same thirty records were used with each state database:

| Artefact | State database | `VerifyChain` query | Commit |
|---|---|---|---|
| `fabric_latency_gateway_leveldb.json` | LevelDB | median 16.9 ms, P95 18.4 ms | median 2,030.7 ms |
| `fabric_latency_gateway_couchdb.json` | CouchDB | median 27.1 ms, P95 31.6 ms | median 2,053.7 ms |

`fabric_latency_gateway.json` is a copy of the LevelDB run.

## Acknowledged limitations

A single orderer, TLS between chaincode and peer disabled, and no KMS or HSM.
On a production network each of these would change the numbers. The
dissertation says so in Chapter 6.
