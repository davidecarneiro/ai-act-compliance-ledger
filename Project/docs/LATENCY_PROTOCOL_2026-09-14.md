# Protocol for the latency experiment

**Fixed on 2026-09-14, before any measurement in this series.** This document
exists so that the design cannot be adjusted after the results are seen. The
numbers produced under this protocol are published in the dissertation whatever
their sign.

## Why it was redone

The reference run of April 2026 measured **six events**, once, and it is where
the figure of +1.55 ms per event that opened both summaries came from. On
re-measurement, on 2026-09-14, the sign flipped: the Oracle came out faster
than the baseline. Six events in a single run are dominated by cache and
machine state, and a result that changes sign between runs cannot support a
claim about overhead.

> Current-reading note (3 October 2026): the exploratory runs did not control
> cache or machine state. The sign reversal shows that those runs do not provide
> a stable estimate of overhead; it does not identify the cause of the
> difference. The experimental design below is unchanged.

## What is compared

Two **complete** paths, as they are implemented. This is not a measurement of
the cryptographic primitives in isolation, and the results should not be read
as one.

| | Oracle | Baseline |
|---|---|---|
| Read | the whole JSON file | --- |
| Decision | input validation and policy rules | the same policy rules |
| Evidence | canonical serialisation, SHA-256, Ed25519 signature, chaining | --- |
| Write | the whole JSON file | SQLite `INSERT` and `commit` |
| Expected cost | **O(n)** in the size of the ledger | **O(1)** amortised |

The asymmetry in complexity is a real property of the two implementations and
is the main known confounder: as the ledger grows, the Oracle rereads and
rewrites more. Latency is therefore also measured as a function of the size of
the ledger.

## Design

1. **Paired and interleaved.** Both paths run on every event, and the order
   alternates from event to event, so that neither benefits systematically from
   warm cache left by the other.
2. **Ten independent rounds** of 200 events each. Each round starts with an
   empty ledger and an empty SQLite database, created in a temporary directory.
3. **A warm-up of 50 events per round**, discarded, before recording starts.
4. **Primary estimand:** the paired per-event difference (Oracle − baseline),
   summarised by the median of each round. What is reported is the distribution
   of the ten medians, not a single mean.
5. **Secondary estimand:** the Oracle's latency as a function of the number of
   records already in the ledger, to expose the O(n) component.
6. **Statistics:** median and interquartile range. No significance tests are
   applied: ten rounds on one machine are not a population sample, and the aim
   is to characterise the order of magnitude and the sign, not to infer about a
   population of machines.

## What the experiment does not determine

- It does not isolate the cost of the cryptography. Doing so would require a
  third arm with the same persistence and no signature.
- It does not represent a distributed network, where coordination dominates.
- It does not characterise maximum sustained throughput: the events are
  sequential, with no concurrency.
- It does not generalise to other machines, file systems or volumes.

## Artefacts

`prototype/compliance_ledger_sim/bench_latency.py` produces
`experiments/latency_protocol_<timestamp>.json` with every round, the
environment and the protocol embedded. The earlier
`comparison_oracle_vs_baseline_*.json` files are now treated as **exploratory**
and kept as such.
