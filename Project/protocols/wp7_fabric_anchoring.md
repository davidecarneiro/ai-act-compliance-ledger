# Protocol — WP7, ledger anchoring per record and in batches (plan 4.2)

Recorded on 2026-11-12, before any measurement with the WP7 client. Section
4.2 of the article plan, with what it left open fixed here. Nothing changes
after a measurement; deviations are reported in `ARTICLE_WORK.md` and in the
article.

## Question

Where does the cost of anchoring evidence on a permissioned ledger lie, and
what does anchoring in batches trade: durable-evidence throughput against the
time a record waits to be covered by an anchor?

## Network

- `fabric-samples` test network, Fabric 2.5.10, as in the dissertation: two
  organisations (Org1MSP, Org2MSP), one CA per organisation (`-ca`),
  chaincode as a service, endorsement `AND('Org1MSP.peer','Org2MSP.peer')`.
- One Raft orderer, the test network's default. Three orderers are not used;
  the article says so.
- State database: LevelDB for the anchoring runs; CouchDB for a second run of
  the query measurements only.
- Orderer `BatchTimeout` ∈ {2 s, 250 ms}, set in the test network's
  `configtx.yaml` before the network is brought up; all other orderer
  parameters at their defaults (`MaxMessageCount` 10). The client records the
  value it finds.

## Evidence

Issued on the measurement machine by the Compliance Policy Engine (schema
version 2, the engine's own key, registered on the chain before anything is
submitted), from workload W2 of WP3 (the six canonical scenarios in turn),
before the timed loop: issuance cost is WP3's subject.

- Per-record chain: 601 records; record 1 is a warm-up, records 2–201,
  202–401 and 402–601 are the three repetitions of N = 1.
- Anchored stream: 1,000 records, anchored for each N ∈ {10, 50, 100, 500}
  and repetition r in stream `n<N>-r<r>` (1,000/N anchors each). A separate
  stream `warmup` of two anchors precedes the runs and is not counted.
- Credit case: the 16 records of the WP4 case, issued again by the engine on
  the measurement machine, anchored one by one (N = 1, stream `credit-case`);
  their on-chain anchors, with the submitting organisation the chaincode
  stamped, are exported for configuration C of the tamper experiment and for
  Q12 of WP5.

## Modes

- **N = 1:** `SubmitEvidence(record)`: the whole record goes on the chain;
  the chaincode verifies its signature against the registry, recomputes its
  hashes and checks that it follows the head.
- **N ≥ 10:** `AnchorBatch(anchor)`: one signed statement per N records
  (`batch_anchor.py`): the RFC 9162 Merkle root over the records' hashes, the
  batch's sequence numbers and the last record's `chain_hash`.

## Client and timing

- Go, Fabric Gateway SDK, one persistent connection, identity
  `User1@org1.example.com` (`fabric_migration/gateway/anchorbench`).
- Serial submission, one transaction in flight: both heads (evidence and
  anchor stream) serialise writers through MVCC.
- Per transaction, wall-clock time from the call to the return of the
  commit status (endorsement by both organisations, ordering, validation
  and commit).
- Order per repetition: N = 1, 10, 50, 100, 500, rotated by one position in
  each repetition (r = 1 starts at N = 1, r = 2 at N = 10, r = 3 at N = 50).

## Estimands

- Submit → commit latency per transaction, per N and BatchTimeout: median,
  IQR and 95th percentile.
- **Durable-evidence latency per record**, from the moment the record is
  available to the client to the commit of the transaction that covers it.
  Records are issued before the loop, so a whole batch is available when its
  anchor is submitted (saturated mode): the measured latency of a record is
  the latency of its anchor. At an event cadence λ, a record also waits for
  its batch to fill, on average (N − 1)/(2λ) and at most (N − 1)/λ; the
  article adds that wait analytically for the cadences of the two real cases
  and says so.
- **Durable-evidence throughput:** records covered per second over a
  repetition (records / time from the first submission to the last commit).
- **Queries** (read-only evaluation through the Gateway): `VerifyInclusion`
  for 100 records sampled with seed 42 from stream `n100-r1`, one call each;
  `VerifyChain` over the per-record chain, 20 calls. Median and 95th
  percentile, on LevelDB and on CouchDB.
- **Proof size** in bytes (compact JSON), per N, computed from the proofs.

## Governance check

One anchor submitted with endorsement requested from Org1 only. Expected:
the transaction is refused at validation (`ENDORSEMENT_POLICY_FAILURE`) and
nothing is written. Recorded as observed.

## Expected

N = 1 reproduces the order of magnitude of the dissertation (about one
durable record per BatchTimeout, about 0.5 records/s at 2 s). Throughput
should grow roughly with N and latency per transaction should stay close to
the BatchTimeout. No threshold of acceptability is set.

## What is not measured

Concurrency, several orderers, separate machines per organisation, TLS
between chaincode and peer: the network is a laboratory network on one
machine. The article says so in the threats to validity.

## Output

`experiments/article/wp7/fabric_<label>_<UTC time>.json` per network
bring-up (BatchTimeout and state database recorded in it), with every timing,
the environment, the governance check and the exports; produced by
`fabric_migration/wp7/run_wp7.py` and the client. `run_wp7.py summarise`
builds the rows and series of Figure F5 from them.
