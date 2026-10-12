# Protocol addendum — WP4, stability of the gate decisions across partitions

Recorded on 2026-10-12, after the main run of the credit-scoring case
(`experiments/article/wp4/run_20261012T145744Z/`) and before this analysis
was run. It is **post hoc and exploratory**: it was decided after seeing that
both models fell just above the parity bound (0.1116 against 0.10) with only
32 applicants under 25 in the validation partition. It does not replace or
qualify the main run, whose results stand as reported; the article presents
it as a supplementary analysis and says when and why it was added.

## Question

How often would the policy gate of the case take the same decision on another
random partition of the same data? The gate decides on two metrics estimated
from 200 validation applicants, 30 or so of them under 25.

## Design

- The pipeline of `protocols/wp4_credit_case.md`, unchanged: same data,
  features, models, metrics, rounding, batches (`default_rng(42)`) and PSI.
  Only the partition seed varies.
- Partition seeds 0 to 499 (500 partitions). Seeds 7 (pilot) and 42 (main
  run) are among them and are not treated differently.
- The policy is the committed case policy (`pol-16d3a1645858`), unchanged.
- Decisions are taken by the engine's own function, `evaluate_event`, on the
  events the case would send (validation of v1 and v2; deployment request of
  v2 with a valid signed approval; the six monitoring batches). No ledger is
  written: the decision function is pure, so the outcome is the one the
  engine would record.

### Amendment (2026-10-12, before any result)

A trial run on seeds 40–44 stopped on an error before producing any result:
in some partitions the test partition holds fewer applicants of the drift
subgroup than a batch needs (48 for the share 0.95), and the case protocol
draws without replacement within a batch. Rule added: when the subgroup has
fewer applicants than the batch needs, the batch takes all of them and the
rest from the other applicants; the realised subgroup count is recorded, and
the number of partitions where this happens is reported. The rule cannot bind
in the main run (60 subgroup applicants in its test partition), whose code
path is unchanged.

## Measures, per seed

- Validation precision and parity difference of v1 and v2; number of
  applicants under 25 in the validation partition.
- Gate decision and rule for the validation of v1 and v2 and for the
  deployment request of v2.
- The same two metrics on the test partition (200 other applicants), and the
  decision the same thresholds would give there. Agreement between the
  validation and test decisions measures how far the gate's decision carries
  over to unseen applicants.
- PSI of the six monitoring batches and whether each raises the alert.

## Summary statistics

- Distribution of each metric (median, IQR, 5th and 95th percentiles).
- Share of partitions in which each model passes validation, in which the
  deployment request of v2 is approved, and in which v1 and v2 obtain
  different decisions.
- Share of partitions in which the validation and test decisions agree, per
  model.
- Alert rate per monitoring batch (by target share of the drift subgroup).
- Proportions are reported with their Wilson 95 % interval.

## Output

`experiments/article/wp4/seed_stability_<UTC time>.json`, with every per-seed
observation kept and the environment recorded. Produced by
`prototype/credit_case/seed_stability.py`.
