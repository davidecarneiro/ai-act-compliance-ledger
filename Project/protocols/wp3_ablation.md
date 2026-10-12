# Protocol — WP3, cost of verifiable evidence (four-arm ablation)

Recorded on 2026-10-12, before any measurement with `bench_ablation.py`.
Section 4.1 of the article plan, with the details it left open fixed here.
Nothing in this file changes after a measurement; any deviation is reported
as such in `ARTICLE_WORK.md` and in the article.

## Question

What does each property of the evidence record cost per event, compared with
an ordinary log? The arms add one property at a time, so paired differences
isolate each cost.

## Arms

Every arm receives the same event, takes its decision with the same function
(`simulator.evaluate_event`) under the same policy, schema version 2, and
persists the outcome durably before returning. They differ only in what they
persist and how.

| Arm | Per event | Durability |
| --- | --- | --- |
| A | One row in SQLite (`baseline_logger.BaselineLogger.record`): identity fields, decision, reason, rule, metrics as JSON. No canonical form, hash or signature. | SQLite as shipped: rollback journal, `synchronous = FULL`, one commit per event |
| B0 | The engine's version 2 record (canonical RFC 8785 body, `record_hash`, `chain_hash`), appended to the append-only store (WP1). No signature: the engine with its signing step removed (`_sign` returns nothing), everything else identical. | One write and one fsync per record; head file replaced atomically |
| B | B0 with the Ed25519 signature: the engine as it is. | As B0 |
| B+ | B, plus every K = 100 records the signed head (sequence number, `chain_hash`, time) appended to an external anchor file, standing in for a transparency log. | As B0; anchor line fsynced |
| C | B submitted to the chaincode on Fabric. Measured under protocol 4.2, outside the paired loop, because network ordering dominates its latency. | Ledger commit |

The timed call is the arm's processing of one event, from receiving the event
to the durable write returning. Nothing is printed in the timed path. The
Python garbage collector stays enabled.

## Workloads

- **W1:** the dissertation's benchmark event, a high-risk model validation
  that is approved (precision 0.85, parity 0.02, human approval), each with
  its own `scenario_id` and `artifact_id`.
- **W2:** the six canonical scenarios (`scenarios.build_scenarios`) in turn,
  in equal proportions: one approval, three rejections, one escalation, one
  audit query.

Policy: the shipped policy (`configs/policies.json`).

## Paired design

- Ten rounds of 200 measured events per workload, after 50 warm-up events
  that are discarded. Fresh storage for every arm in every round.
- The order of the arms changes from event to event following a Williams
  4×4 design (rows 0-1-3-2, 1-2-0-3, 2-3-1-0, 3-0-2-1 over A, B0, B, B+,
  event i using row i mod 4), so that each arm runs equally often in each
  position and after each other arm.
- Timing: `time.perf_counter_ns()` immediately around the call.

## Estimands and summaries

- Per workload and arm: latency per event, as the median of the ten per-round
  medians; IQR and 95th percentile over the 2,000 pooled observations.
- Paired differences per event (same event, same round): B0 − A (canonical
  form, hashing and append-only persistence against a database row), B − B0
  (signature), B − A (a verifiable centralised log against a plain one),
  B+ − B (anchoring). Same summaries. The anchoring cost falls on one event
  in 100, so for B+ − B the mean is reported as the amortised cost, and the
  latency of the anchor operation itself is reported separately.
- Every individual observation is kept in the output JSON.

## Dependence on ledger size

One run of 10,000 events per arm with W1, interleaved with the same Williams
rotation, on storage that grows throughout; median per block of 1,000 events.

## Environment

- The measurement that enters the article runs on a physical machine, the
  one that hosts the Fabric network if possible, with no other workload. The
  run carries a label naming the machine.
- The working directory is on the machine's main disk, not on a memory-backed
  file system (a tmpfs makes fsync free); the script records the file system.
- Recorded: CPU, operating system, Python and library versions, SQLite
  version and settings.
- On macOS, `fsync` does not force the drive's write cache (that needs
  `F_FULLFSYNC`); the same holds for SQLite's default. Both arms are treated
  alike, and the article says so.
- Runs elsewhere (the cloud container where the script was written) only
  validate the script; they are labelled as such and are not reported.

## Acceptability

RQ3 does not ask whether the cost is acceptable. The article relates the cost
to the event cadence of the two real cases (MultiFlow: one event per batch of
20 rows; credit scoring: 16 events over two training runs) and sets no threshold after
the fact.

## Output

`experiments/article/wp3/ablation_<label>_<UTC time>.json`, produced by
`prototype/compliance_ledger_sim/bench_ablation.py`, with the parameters,
the environment, every observation and the summaries (including the rows of
Table T9 and the series of Figure F4).
