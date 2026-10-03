# Status of the latency results

## Exploratory: `comparison_oracle_vs_baseline_*.json`

These files measure **six events in a single run**, with no warm-up, no
repetition and no interleaving of the two paths. The one from 2026-04-29
(`...20260429T075151Z.json`) served as the «reference run» until 2026-09-14 and
is where the figure of +1.55 ms per event came from.

On re-measurement, on 2026-09-14, **the sign flipped**: the Oracle came out
faster than the baseline. A single six-event run does not control cache or machine state, and a result
that changes sign between runs cannot support a claim about overhead. These
files are therefore **exploratory**: they show that both paths work and produce
evidence, and they do not quantify the difference.

They are kept because they are genuine measurements, and because their
instability is itself the documented reason for redoing the experiment.

## Confirmatory: `latency_protocol_*.json`

Produced by `bench_latency.py` under the protocol fixed in
`LATENCY_PROTOCOL_2026-09-14.md` **before** any measurement in this series:
ten independent rounds of 200 events, paired, interleaved with alternating
order, 50 warm-up events discarded per round, and a fresh ledger and SQLite
database for each round.

These are the ones the dissertation cites. The artefact embeds the protocol,
the environment and all ten rounds.

## Paths recorded inside the result files

The exploratory summaries record the absolute path of the policy file at the
time of the run. Two are paths on the author's machine. The others lie under
session or working-tree folders of the AI coding assistant used during
development, in which those runs were executed (see the declaration on the use
of AI in the dissertation). The
files are published as they were written, because the paths document the
environment in which each run was executed.
