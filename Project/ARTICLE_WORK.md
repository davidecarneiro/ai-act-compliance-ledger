# Article branch: changes since the dissertation

The `article` branch prepares the code and evidence for the journal article
derived from the dissertation. The dissertation's state is the tag
`thesis-v1.0` and does not move. Work is organised in work packages (WP)
defined in the article plan; each entry below says what changed and how it
was checked.

## Rules on this branch

- Published evidence is read, never written. It lives in `Project/experiments/`
  (outside `article/`), `prototype/compliance_ledger_sim/ledger.json` and
  `prototype/fabric_migration/gateway/records.json`, and
  `prototype/compliance_ledger_sim/verify_delivery.py` checks it against the
  final `chain_hash` published with the dissertation.
- New runs write to `Project/experiments/article/` unless `EXPERIMENTS_DIR` is
  set (`compliance_ledger_sim/paths.py`).
- New records are issued under schema version 2 (RFC 8785).
  `EVIDENCE_SCHEMA_VERSION=1` reproduces the dissertation's form.

## WP0 — Versioned canonical form

**What changed**

- `compliance_ledger_sim/canonical.py`: version 1 (the dissertation's
  `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)`) and
  version 2 (RFC 8785, `rfc8785` package). `record_body_bytes(record)`
  recomputes a stored record in the form named by its own `schema_version`;
  a record without the field is version 1.
- `simulator.py`: `ComplianceOracle(schema_version=...)`, default 2. Version 2
  records carry `"schema_version": 2` in the signed body. Numbers outside the
  JCS domain (integers beyond 2**53 - 1, NaN, infinities) and keys that are not
  valid Unicode are rejected as malformed input and still recorded; payload
  hashing maps them through the existing envelope instead of raising. The
  policy digest uses the record's version; the shipped policy keeps its
  identifier `pol-c3d1fc49f36e`.
- `verify_chain`, `oscal_exporter.py`, `verify_delivery.py`: recompute bodies
  with `record_body_bytes`, so a ledger may mix versions.
- Chaincode (`canonical_versions.go`): version 1 unchanged; version 2 is JCS
  over the record's own members (`github.com/gowebpki/jcs` v1.0.2, vendored),
  and a version 2 record is stored as submitted, so members the Go struct does
  not declare are no longer dropped.
- `paths.py`: `PUBLISHED_DIR` (read) and `EXPERIMENTS_DIR` (write, default
  `PUBLISHED_DIR/article`). The default ledger of new runs, the Gateway record
  generator and `02_submit_and_measure.py` no longer write over published files.
- `validate_oscal_schema.py --published` validates the dissertation's OSCAL
  documents only.

**Checks (2026-10-07, Linux x86_64, Python 3.13 and 3.11, Go 1.24.7)**

| Check | Result |
| --- | --- |
| Python suite, schema version 2 | 124/124 (98 of the dissertation + 26 new) |
| Python suite, `EVIDENCE_SCHEMA_VERSION=1` | 124/124 |
| MultiFlow bridge tests | 4/4 |
| Go chaincode tests | 16/16 (10 + 6 new) |
| `interop/test_interop.py` | 6/6 version 1 vectors, 4/4 RFC 8785 vectors |
| `verify_delivery.py` | 1,831 records over 7 chains, all verify |
| `validate_oscal_schema.py --published --expect 18` | 18/18 |

Not tested here: Python 3.9 (the dissertation's macOS environment), the Docker
builds, and a Fabric network.

## WP1 — Append-only persistence

**What changed**

- `compliance_ledger_sim/ledger_store.py`: two stores behind one interface,
  chosen by suffix. `.jsonl` is append-only: one line per record, one write
  and one fsync per event, and a head file (`<ledger>.jsonl.head`: sequence
  number, last `chain_hash`, byte offset) replaced atomically, so an append
  never reads the ledger. `.json` keeps the dissertation's whole-file rewrite.
- Crash consistency: the record line is fsynced before the head is replaced.
  On the next append, under the lock, complete records beyond the head that
  link and recompute are rolled forward, a torn last line is cut off, a
  missing head is rebuilt by one scan. A file shorter than the head
  (truncation) or a complete line that does not link is refused
  (`LedgerCorrupted`).
- `simulator.py`: records are appended through the store; `verify_chain`,
  `query_by_requirement` and `query_by_scenario` stream the file. New runs
  default to `experiments/article/ledger.jsonl`; paths ending in `.json` (the
  tests, the bridge, the published ledgers) keep the old store.
- `oscal_exporter.py` and `compare_oracle_vs_baseline.py` read either format.
  `python3 ledger_store.py to-json in.jsonl out.json` writes an array copy for
  the Ledger Explorer page.
- `bench_store_growth.py` (`make store-growth`): the WP1 acceptance check.

**Checks (2026-10-08, Linux x86_64, Python 3.13, Go 1.24.7)**

| Check | Result |
| --- | --- |
| Python suite, v2 and `EVIDENCE_SCHEMA_VERSION=1` | 136/136 each (124 + 12 store tests) |
| Bridge, Go chaincode, interop | 4/4, 16/16, 6/6 + 4/4 |
| `verify_delivery.py`, published OSCAL | 1,831/1,831, 18/18 |
| Latency vs size, append-only, 10,000 events | median 0.88 ms in the first block of 1,000, 0.86 ms in the last (ratio 0.98) |
| Latency vs size, JSON array, 2,000 events | median 5.4 ms in the first block of 250, 66 ms in the last (ratio 12.3) |

The latency figures come from one run on the cloud container
(`experiments/article/wp1/store_growth_20261008T073951Z.json`, every
observation kept). They show the shape, flat against linear; the article's
cost figures come from the WP3 protocol on the measurement machine.

## WP2 — Evidence model, schema version 2

Version 2 was first introduced in WP0 with the dissertation's fields under
RFC 8785. No version 2 record has been published, so WP2 completes the
version 2 field set rather than opening a version 3.

**What changed**

| Version 1 (dissertation) | Version 2 (article) |
| --- | --- |
| `artifact_hash`: digest of the event payload | `payload_hash`: digest of the event payload |
| — | `artifact_hash`: digest of the artefact file (model, dataset, report), or null |
| — | `off_chain_ref`: where the artefact is kept (`store/sha256/<digest>` or another URI) |
| — | `decision_inputs`: `risk_level` and `human_approval` as the decision read them |
| — | `run_id`: the execution or release the event belongs to |
| `requirements_covered` | `supports_requirements` |
| audit query decision `verified` | `recorded` |
| bias metric supports Art. 10(3) | bias metric supports Art. 10(2)(f); a dataset digest supports Art. 10(3); any artefact digest supports Art. 11 |
| issuer `compliance-oracle-v1` (demonstration key, committed) | issuer `compliance-policy-engine-v2` (own key, created on first use, not committed) |

- `artifact_store.py`: content-addressed store. `put(path)` returns the
  digest and the reference; `verify_ledger_artifacts(ledger, store)`
  recomputes every cited artefact from the store (ok, missing,
  content-mismatch, ref-mismatch). The engine reads no file: it checks the
  form of `artifact_sha256` and `off_chain_ref` and that a store reference
  names the same digest, so its decision stays a function of the event.
- `simulator.py`: validation, evaluation and coverage are pure functions
  (`validate_event`, `evaluate_event`, `requirement_support`). Malformed
  version 2 fields are rejected and recorded with no commitment
  (`artifact_hash`, `off_chain_ref` and `run_id` null). `verify_chain`
  resolves the key by `issuer_pubkey_fingerprint` among trusted keys (the
  engine's own and, by default, the published demonstration key) and reports
  an unknown issuer separately from a bad signature. `query_by_run`.
- `reexecution.py`: `reexecute(record, policy_archive, payload=None)` loads
  the archived policy, checks it still hashes to `policy_hash`, rebuilds the
  event from the record, re-runs `evaluate_event` and compares decision,
  `rule_id` and supported provisions. Malformed-input records and version 1
  records need the original payload, whose digest is checked first.
  `python3 reexecution.py <ledger>...` re-executes whole ledgers.
- OSCAL: reads `supports_requirements` or `requirements_covered`, exports
  `recorded` findings, derives the redacted subject from `payload_hash`, and
  maps article points to distinct control IDs (`Art.10(2)(f)` →
  `aia-10-2-f`; the earlier mapping produced `aia-10-2-`).
- Chaincode: `SupportsRequirements` declared for `QueryByRequirement`; the
  other version 2 members are hashed and stored from the record itself.
- Fabric scripts register the key they sign with (the engine's key under
  version 2).

**Checks (2026-10-12, Linux x86_64, Python 3.13, Go 1.24.7)**

| Check | Result |
| --- | --- |
| Python suite, v2 and `EVIDENCE_SCHEMA_VERSION=1` | 165/165 each (136 + 25 model tests + 4 boundary v2 tests) |
| Bridge (both versions), Go chaincode, interop | 4/4, 17/17, 6/6 + 4/4 |
| Boundary matrix, version 2 | 24 cases (16 + 8), same outcome in Python and Go |
| Re-execution, six scenarios and incident run | 9/9 match (`experiments/article/wp2/reexecution_20261012T095323Z.json`) |
| Artefact digests recomputed from `off_chain_ref` | match; altered and missing artefacts reported |
| OSCAL v2 exports against the NIST schema | valid (full and redacted) |
| `verify_delivery.py`, published OSCAL | 1,831/1,831, 18/18 |

**Open points**

- ~~The policy applies the precision and fairness thresholds to every event,
  so an event without metrics (data ingestion, training) is rejected on
  precision.~~ Settled on 2026-10-12: thresholds by pipeline stage (below,
  before WP4).
- The Art. 10 mapping is a legal reading to be confirmed by the co-authors.
- The Ledger Explorer page reads `requirements_covered`; version 2 ledgers
  need it to read `supports_requirements` too (WP9).

## WP6 — Signed human approval

Version 1 recorded human oversight as a boolean asserted by whoever sent the
event. Version 2 also accepts an approval statement signed by the approver.

**What changed**

- `compliance_ledger_sim/approvals.py`: the statement (`type`
  `deployment-approval`, `artifact_sha256`, `run_id`, `decision` approve or
  deny, `approved_at`) is signed with the approver's Ed25519 key over its
  RFC 8785 form; `sign_approval`, `structure_error`, `check_approval`.
- Policy (optional fields, absent in the dissertation's policies):
  `authorised_approvers` (approver id → raw public key, 64 hex digits) and
  `signed_approval_required_for` (event types). Both are part of the policy
  content and therefore of `policy_hash`; malformed values fail closed.
- Evaluation (version 2), in the slot of the approval rule: a present
  approval is always checked. Unauthorised approver, signature that does not
  verify, statement for another artefact or run → `oversight.approval_invalid`;
  a valid denial → `oversight.approval_denied`; required but absent →
  `oversight.approval_missing`, whatever the boolean says. A valid approval
  also satisfies the high-risk boolean rule. A malformed approval makes the
  event malformed.
- The record keeps the approval whole in `decision_inputs.approval`, so a
  third party holding the archived policy can verify who approved what;
  re-execution re-verifies it. Art. 14 is supported when a boolean or an
  approval is present.
- OSCAL: objectives `obj-human-approval-verified` and
  `obj-human-approval-granted` (objectives version 1.1).
- Go fixtures include a valid and an unauthorised signed approval; the
  chaincode needs no change (the approval is a member of the body).

**What a valid approval establishes:** that the holder of an authorised key
signed an approval of this artefact in this run. Not who held the key, nor
whether oversight was effective (Art. 14(4)).

**Checks (2026-10-12)**

| Check | Result |
| --- | --- |
| Python suite, v2 and `EVIDENCE_SCHEMA_VERSION=1` | 186/186 each (165 + 21 approval tests) |
| Acceptance cases | forged signature, unauthorised key, other artefact, other run, statement altered after signing: each rejected as `oversight.approval_invalid` and recorded; chain valid |
| Bridge (both versions), Go chaincode, interop | 4/4, 17/17, 6/6 + 4/4 |
| `verify_delivery.py`, published OSCAL | 1,831/1,831, 18/18 |

## Policy — metric thresholds by pipeline stage (2026-10-12)

The dissertation's policy holds every event to the precision and fairness
thresholds, so an event without metrics (data ingestion, training) is
rejected on precision. Decided: thresholds by pipeline stage.

- Optional policy field `metric_threshold_stages` (version 2): the stages at
  which the thresholds apply. There, the metrics are mandatory; a missing one
  fails the threshold with its own reason ("precision is required at stage
  validation and is missing"). Other stages are not held to them; monitoring
  keeps the drift rule.
- Absent, every event is held to the thresholds, as in the dissertation, and
  version 1 ignores the field, so the dissertation's records and the shipped
  policy (`pol-c3d1fc49f36e`) are unchanged. An empty or malformed list fails
  closed. The field is part of the policy content and of `policy_hash`.
- Tests: `tests/test_stage_thresholds.py` (22). Python suite 208/208 under
  version 2 and under `EVIDENCE_SCHEMA_VERSION=1`.

## WP4 — Credit-scoring case (German Credit)

**Order of work, visible in the history:** protocol committed and pushed
before any model was trained (`protocols/wp4_credit_case.md`); then the
pipeline, the pilot and the case policy, committed before the main run; then
the run.

**What changed**

- `prototype/credit_case/credit_case.py`: implements the protocol. Reads
  `german.data` from the archive after checking both digests; stratified
  60/20/20 partition; logistic regression without (v1) and with reweighing
  (v2); precision and parity difference on the validation partition; six
  monitoring batches with an induced shift towards checking account < 0 DM;
  PSI of the v2 scores over quintile bins; the fixed sequence of 16 events,
  each with its artefact in the content-addressed store; the deployment
  request with an approval signed by the demonstration approver.
- `recompute_metrics(ledger, store)`: recomputes every metric in the ledger
  from the ledger and the store alone (dataset and partition from the run's
  `data_ingested` and `data_split` events, model from the record, batch from
  its monitoring report), as a third party holding them would.
- `policy.json`: the case policy, written by the pilot, fixed thereafter;
  `keys/approver-demo.*`: demonstration approver key, committed so the case
  regenerates under the same policy identifier (`pol-16d3a1645858`).
- `make pilot`, `make run`, `make tests` in `prototype/credit_case/`;
  dependency versions pinned in its `requirements.txt`.

**Pilot (partition seed 7, discarded for evaluation;
`experiments/article/wp4/pilot_20261012T145725Z.json`)**

| | Precision | Parity difference |
| --- | --- | --- |
| v1 | 0.734568 | 0.247059 |
| v2 | 0.734940 | 0.113725 |

Calibration rule of the protocol: `min_precision` = floor to 0.01 of
(0.73494 − 0.05) = 0.68.

**Run (partition seed 42; `experiments/article/wp4/run_20261012T145744Z/`)**

| # | Run | Event | Decision | Rule | Metrics |
| --- | --- | --- | --- | --- | --- |
| 1–3 | gc-run-1 | ingested, split, trained | approved ×3 | `policy.all_checks_passed` | — |
| 4 | gc-run-1 | validation (v1) | rejected | `threshold.fairness` | precision 0.793333, parity 0.111607 |
| 5–7 | gc-run-2 | ingested, split, trained | approved ×3 | `policy.all_checks_passed` | — |
| 8 | gc-run-2 | validation (v2) | rejected | `threshold.fairness` | precision 0.800000, parity 0.111607 |
| 9 | gc-run-2 | deployment request, no approval | rejected | `threshold.fairness` | as 8 |
| 10 | gc-run-2 | deployment request, signed approval | rejected | `threshold.fairness` | as 8 |
| 11–15 | gc-run-2 | monitoring, shares 0.30, 0.30, 0.50, 0.65, 0.80 | approved ×5 | `policy.all_checks_passed` | PSI 0.042, 0.103, 0.109, 0.123, 0.230 |
| 16 | gc-run-2 | monitoring, share 0.95 | escalated | `monitoring.drift_alert` | PSI 0.930 |

Decisions: 11 approved, 4 rejected, 1 escalated.

| Acceptance criterion | Result |
| --- | --- |
| No metric set by hand | 10/10 metrics recomputed from the ledger and the store, identical |
| Chain verifies | 16/16 |
| Artefact digests recompute from `off_chain_ref` | 16/16 ok |
| Re-execution | 16/16 match (decision, rule, supported provisions) |
| OSCAL exports against the NIST schema | complete and redacted valid |
| One decision of each type | approved, rejected, escalated |

**Observations (reported as they came out; nothing changed after the run)**

- Both models exceed the parity bound of 0.10, so the two deployment requests
  are rejected on fairness before the approval rules are reached. On these
  data the case therefore does not exercise `oversight.approval_missing` or
  the verification of a valid approval at the gate; the valid approval is
  recorded whole in event 10 (`decision_inputs.approval`, Art. 14 supported).
  Those rules are exercised by the WP6 tests.
- v1 and v2 have the same parity difference. Checked: reweighing equalises
  the weighted label rate of the two groups (0.70), lowers the age
  coefficient (0.245 → 0.191) and changes two validation predictions, but
  within each group, so the counts stay 129/168 (25 or over) and 21/32 (under
  25). On this training partition the groups' label rates are close (0.71 and
  0.64), which leaves reweighing little to correct; in the pilot it reduced
  the parity difference from 0.25 to 0.11.
- With 32 applicants under 25 in the validation partition, the parity
  difference has a standard error of about 0.09: a gate on this metric is
  unstable across partitions. For section 7.1 and threats to validity.
- The calibrated `min_precision` (0.68) is below the share of good risks
  (0.70): a classifier that grants every application would pass it. It
  follows from the pre-registered rule and a pilot precision of 0.735, and is
  reported rather than corrected.
- Protocol detail made explicit in the code: round(50·q) rounds halves up
  (32.5 → 33 in batch 4). The pilot draws its batches with the same seed (42)
  as the main run; only the partition seed differs, as the protocol states.

**Checks (2026-10-12, Linux x86_64, Python 3.13, scikit-learn 1.9.1, Go 1.24.7)**

| Check | Result |
| --- | --- |
| Python suite, v2 and `EVIDENCE_SCHEMA_VERSION=1` | 208/208 each |
| Credit case tests (`prototype/credit_case/tests`) | 13/13, including a full run in a temporary folder that reproduces the committed one, and a swapped model caught by the artefact check and by recomputation |
| Bridge (both versions), Go chaincode, interop | 4/4, 17/17, 6/6 + 4/4 |
| `verify_delivery.py`, published OSCAL | 1,831/1,831, 18/18 |

## WP4 addendum — stability of the gate decisions across partitions

**Post hoc and exploratory**, decided after the main run (both models just
above the parity bound, 32 applicants under 25 in the validation partition).
Protocol addendum `protocols/wp4_supplementary_seed_stability.md`, committed
before it was run and amended once before any result: a trial run on seeds
40–44 stopped on an error (a test partition with fewer drift-subgroup
applicants than the last batch needs); such batches now take all of them
(`draw_batches(cap=True)`; 40 of 500 partitions, last batch; the case's code
path is unchanged).

`prototype/credit_case/seed_stability.py` (`make stability`): the case
pipeline over partition seeds 0–499 under the committed policy, decisions by
the engine's `evaluate_event`. Seed 42 reproduces the main run exactly
(tested). Results: `experiments/article/wp4/seed_stability_20261012T160251Z.json`.

| Over 500 partitions | v1 | v2 |
| --- | --- | --- |
| Validation precision, median [5th–95th pct.] | 0.793 [0.760–0.824] | 0.790 [0.755–0.822] |
| Validation parity difference, median [IQR] | 0.151 [0.099–0.215] | 0.112 [0.053–0.168] |
| Passes validation (Wilson 95 %) | 26 % [23–30] | 44 % [40–48] |
| Rejected on precision | 0/500 | 0/500 |
| Validation and test decisions agree | 58 % [53–62] | 49 % [45–53] |

- v1 and v2 obtain different decisions in 20 % [17–24] of partitions;
  reweighing lowers the parity difference in 80 % [76–83].
- With a valid signed approval, the deployment request of v2 would be
  approved in 44 % [40–48] of partitions.
- Applicants under 25 in the validation partition: median 30 [5th–95th:
  23–37].
- The precision threshold never binds: the 5th percentile of validation
  precision is 0.755. The pilot's precision (0.735, seed 7) lies below that
  percentile, so the single-pilot calibration drew an unusually low value.
- Drift alert rate (PSI > 0.25) by subgroup share: natural 2.4 % and 2.8 %;
  0.50: 17 %; 0.65: 37 %; 0.80: 78 %; 0.95: 99 %.

Reading for the article (section 7.1 and threats to validity): with these
sample sizes, the gate's fairness decision on 200 validation applicants
carries over to 200 unseen applicants about half the time. The evidence
records exactly which decision was taken on which metric values; it cannot
make a decision on a noisy estimate reliable. Thresholds on group metrics
need the estimate's uncertainty, which the policy language does not express.

## WP3 — Ablation: code and protocol (measurement pending)

Protocol `protocols/wp3_ablation.md`, committed and pushed before any
measurement. Instructions for the measurement machine:
`protocols/RUNNING_MEASUREMENTS.md`.

**What changed**

- `ablation_arms.py`: the four arms, each deciding with `evaluate_event`
  under the same policy and differing only in what it persists. A: one
  SQLite row (`BaselineLogger.record`; SQLite as shipped, rollback journal,
  `synchronous = FULL`). B0: the engine with its signing step removed. B: the
  engine. B+: B plus a signed head appended to an external anchor file every
  100 records. Plus the verifier a third party can run on each output.
- `simulator.py`: the signature moved into `ComplianceOracle._sign`, the hook
  B0 overrides; records are byte-for-byte as before.
- `baseline_logger.py`: optional policy (decisions by `evaluate_event`, as
  arm A requires) and an untimed `record()`; without a policy the
  dissertation's rules are kept, so its scripts behave as before.
- `bench_ablation.py` (`make ablation LABEL=<machine>`): W1 and W2, ten
  rounds of 200 events after 50 warm-up, Williams 4×4 rotation, paired
  differences, anchor operation timed apart, 10,000-event growth run. Writes
  every observation, the environment (CPU, file system of the working
  directory, SQLite settings), the rows of Table T9 and the series of F4.
- `tests/test_ablation.py` (6): same decisions in every arm; B0 differs from
  B only by the signature; every output verifies; what each verifier
  catches; the rotation is balanced; a small benchmark runs.

**Validation run (cloud container; label `validation-cloud-container`; not
committed and not reported).** Full protocol in 81 s; identical decisions in
the four arms; every output verifies in every round; latency flat over
10,000 records in every arm. The article's figures come from the
measurement machine.

**Checks (2026-10-12):** Python 214/214 under each schema version; bridge
4/4; the dissertation's `compare_oracle_vs_baseline.py` still runs.

## Tamper detection (plan 4.4) — configurations A, B0, B, B+

Protocol `protocols/tamper_detection.md`, committed before the run and
amended once before it (T9b carries the fabricated metrics of T9a, so that
the approval rule is reached). Script `prototype/credit_case/tamper_experiment.py`
(`make tamper`); results `experiments/article/tamper/tamper_20261012T161251Z.json`.

The 16 events of the credit case go through each configuration (B+ anchors
every 5 records: anchors at 5, 10, 15); each attack is applied to a fresh copy
and checked by what a third party holding that output can verify.

| # | Attack | A | B0 | B | B+ |
| --- | --- | --- | --- | --- | --- |
| T1 | alter a field (record 8: rejected → approved) | not detected | detected | detected | detected |
| T2 | alter only the signature | n/a | n/a | detected | detected |
| T3 | alter and recompute every hash, without the key | not detected | not detected | detected | detected |
| T4 | swap two records | not detected | detected | detected | detected |
| T5 | delete an intermediate record (A: identifiers renumbered) | not detected | detected | detected | detected |
| T6a | truncate a suffix crossing an anchor | not detected | not detected | not detected | detected |
| T6b | truncate after the last anchor | not detected | not detected | not detected | not detected |
| T7a | insider rewrite with the key, crossing an anchor | not detected | not detected | not detected | detected |
| T7b | insider rewrite after the last anchor | not detected | not detected | not detected | not detected |
| T8 | omit an event at the source | not detected | not detected | not detected | not detected |
| T9a | forged event upstream (fabricated metrics) | not detected; approved | idem | idem | idem |
| T9b | forged approval upstream (another key) | not detected; rejected at the gate (`oversight.approval_invalid`) | idem | idem | idem |

All 48 cells as expected. Readings for sections 6.4 and 7.1–7.2:

- T3 is what the signature adds to the hash chain; T6a and T7a are what an
  external anchor adds to a signed log, and only up to the last anchor (T6b,
  T7b). The same holds for C, where every record is anchored.
- T9b is caught in every configuration, A included, because every
  configuration decides with the same engine function: protection against a
  forged approval comes from the policy engine verifying the signature, not
  from how the outcome is stored.
- T8 and T9a are outside the reach of any configuration: integrity of the
  record says nothing about events never sent or fabricated at the source.
- Configuration C is run on the Fabric machine with WP7.
- The issues in the output name records by 0-based index ("record 7" is
  record 8).

Case tests 17/17 (the tamper experiment runs once in a temporary folder and
must match the expected table).

## WP5 — Answerability of the audit questions Q1–Q14

Protocol `protocols/wp5_answerability.md`, committed before the queries were
written. Script `prototype/credit_case/answerability.py`
(`make answerability`); results
`experiments/article/wp5/answerability_20261012T161816Z.json`, with the
evidence it was computed on in `evidence_20261012T161816Z/` next to it. The
queries were developed against a trial evidence set in a scratch folder; the
committed run is the only one reported.

Evidence: the 16 events of the credit case and two synthetic incident events
(declared), through arm A, arm B, and arm B+ anchored after every record (C,
stand-in for the Fabric ledger); D is the redacted OSCAL export of C.

| | A | B | C | D |
| --- | --- | --- | --- | --- |
| Q1 deployment approved: digest, time | partial / no | yes / partial | yes / yes | no |
| Q2 approved by an authorised overseer, by whom | no | yes / partial | yes / yes | no |
| Q3 metrics and thresholds behind the decision | partial / no | yes / yes | yes / yes | partial / no |
| Q4 bias examined before deployment | yes / no | yes / yes | yes / yes | partial / no |
| Q5 dataset digest that trained model X | no | yes / yes | yes / yes | no |
| Q6 deciding policy; re-execution | no | yes / yes | yes / yes | partial / no |
| Q7 events of run R | no | yes / partial | yes / yes | no |
| Q8 drift alerts after deployment, when | yes / no | yes / partial | yes / yes | partial / no |
| Q9 drift alert before incident Y | yes / no | yes / partial | yes / yes | yes / no |
| Q10 any record altered since issuance | no | partial / partial | yes / yes | no |
| Q11 sequence complete from t1 to the audit | no | no | yes / yes | no |
| Q12 submitting organisation | no | partial / yes | partial / yes (stand-in) | partial / no |
| Q13 provisions supported and outcome | no | yes / yes | yes / yes | yes / no |
| Q14 redacted export discloses identity or logic | — | — | — | checked: nothing disclosed (56 items) |

Cells: answerable / third-party verifiable without trusting the issuer.

Table T10 (condensed): A 3 yes, 2 partial, 8 no, none verifiable; B 10 yes,
2 partial, 1 no, 6 verifiable and 6 partially; C 12 yes, 1 partial, all 13
verifiable; D 3 yes, 5 partial, 6 no, none verifiable.

Readings:

- Q11 is answerable only in C, as the plan expected: without something outside
  the issuer's reach, truncation cannot be excluded.
- Q2 is answerable only with signed approvals in the record (B, C): the case's
  approval verifies against the archived policy and names `approver-demo`,
  while the deployment itself was not approved (fairness).
- Q6 needs `decision_inputs` and the policy archive: 18/18 decisions
  re-execute in B and C; A has no policy identity, D only the policy hash.
- What B lacks against C is completeness (Q1, Q2, Q7, Q8, Q9 partially
  verifiable; Q11 not answerable) and protection against a re-signing key
  holder (Q10).
- D answers which provisions are supported and with which technical outcome
  (Q13), and the order of drift alert and incident (Q9), but cannot be
  verified on its own; nothing it must withhold was found in it (Q14).
- Q12: the stand-in names the issuer (by key), not the organisation; the
  Fabric ledger records the submitting organisation (`submitter_msp`), so Q12
  in C is to be answered from the Fabric run (WP7).
- Times per query are below 2 ms on 18 records and say little; they are kept
  in the output as the protocol asks.

Open for WP9 (seen while reading the exports): the OSCAL observation text
still says "Compliance Oracle" and "Hash-anchored evidence in the permissioned
ledger" for every ledger, including a local JSONL one; to be worded by schema
version and ledger kind.

Case tests 18/18.

## WP7 — Batch anchoring on Fabric: code ready, measurement pending

Protocol `protocols/wp7_fabric_anchoring.md`, committed before any
measurement; steps for the Fabric machine in `protocols/RUNNING_MEASUREMENTS.md`.

**What changed**

- `compliance_ledger_sim/merkle.py`, `chaincode/merkle.go`: RFC 9162 Merkle
  tree hash, inclusion paths and verification (leaf 0x00, node 0x01,
  SHA-256). Roots equal the RFC 6962 reference values (certificate-
  transparency test data, sizes 1–8); Python and Go produce identical roots
  and paths for trees of 1 to 33 entries.
- `batch_anchor.py`: signed batch anchor statements (Merkle root over the
  batch's `record_hash` values, first and last sequence number, last
  `chain_hash`, Ed25519 over RFC 8785), inclusion proofs, auditor checks.
- Chaincode: `AnchorBatch` (registered issuer, signature, strict statement,
  batches must follow one another per stream; submitter stamped),
  `VerifyInclusion` (body, hashes, issuer signature, same issuer as the
  anchor, proof to the anchored root) and `GetAnchors`. `SubmitEvidence` is
  unchanged and is the N = 1 mode. Note: a path alone does not fix the tree
  size (RFC 9162); the size is bound by the signed statement, and
  `VerifyInclusion` requires the proof's size to equal it.
- `gateway/anchorbench`: Go measurement client (Gateway SDK, persistent
  connection, serial submission). Compiled and vetted here against the exact
  module versions of `go.sum`, with the dependencies cloned from GitHub (the
  Go module proxy is not reachable from this environment); not run against a
  network.
- `wp7/run_wp7.py`: prepare, measure (protocol order, fail-fast, BatchTimeout
  and state database read from the network), summarise (latency,
  durable-evidence throughput, queries, F5 series). `deploy/01_up_and_deploy.sh`
  takes `BATCH_TIMEOUT` and `STATE_DB`.
- `credit_case/fabric_c.py`: configuration C of the tamper experiment and Q12
  of WP5, evaluated on the measurement machine right after the export of the
  credit case's per-record anchors. C's check is B's check of every record
  plus the on-chain anchors; the first wording of the protocol amendment
  listed only the anchors, which would have missed T1 and T2 (found by the
  runner's test, corrected in the protocol before C is run).

**Checks (2026-11-12):** Go 22 tests + `TestPreparedWP7Inputs` (the
chaincode accepts what `prepare` produces: per-record chain, anchors and
100 inclusion pairs); Python batch-anchor tests 47; WP7 runner 5 (end to end
with a stand-in client, including configuration C and Q12).

## WP9 — Regeneration and reproducibility (in progress)

**Regenerated under schema version 2** (`prototype/article/regenerate.py`;
`experiments/article/wp9/run_20261112T223155Z/`):

| Run | Events | Decisions | Chain | Re-execution | Against the published run |
| --- | --- | --- | --- | --- | --- |
| Canonical scenarios | 6 | 1 approved, 3 rejected, 1 escalated, 1 recorded | 6/6 | 6/6 | — |
| Incident (Art. 73) | 3 | 2 escalated, 1 recorded; Art. 73 in 3/3 | 3/3 | 3/3 | — |
| MultiFlow Muvu (Jan., Mar.) | 29 | 12 approved, 17 escalated | 29/29 | 29/29 | 29/29 batches identical |
| MultiFlow Steel_Industry | 1,750 | 94 approved, 1,656 escalated | 1,750/1,750 | 1,750/1,750 | 1,750/1,750 batches identical |

The MultiFlow runs are **replays**: the platform's CSV files
(github.com/davidecarneiro/multiflow at `a0a9786`, the commit recorded with
the published runs) go through the bridge's own logic as the messages the
injection script publishes, not through Kafka. Each replayed batch has the
scenario, decision and reason (with its drift score) of the published Kafka
run. The 8 OSCAL exports are valid against the NIST schema.

**Bridge** (`multiflow_bridge/bridge.py`): the dissertation's open limit on
acquisition state is closed. The state (reference rows, batch being filled,
counters, Kafka offsets) is saved after every message; a complete batch is
written ahead as pending and recorded on restart only if the ledger lacks it;
Kafka offsets are committed only after the state is saved; redelivered
messages are skipped by offset. Input validation was already in place. Tests
cover the three stop points and were checked by mutation (removing either
safeguard makes a test fail). The ledger is `ledger.jsonl` under version 2;
the run scripts reset the state with the ledger.

**OSCAL wording:** version 2 exports say "Compliance Policy Engine" and call a
record ledger-anchored only when it carries the submitter a ledger stamped;
version 1 exports keep the dissertation's wording (compared with the
`thesis-v1.0` exporter on the published ledger: only the objectives version,
1.0 → 1.1 from WP6, and the timestamps differ).

**Ledger Explorer:** verifies each record in the canonical form of its own
version (RFC 8785 for version 2) and reads `supports_requirements`;
`ledger_explorer/test_canonical.js` runs the page's own functions in Node on
the RFC 8785 vectors and on v1 and v2 ledgers (all records recompute).

**Figures** (`prototype/article/figures.py`): F4 from the WP3 growth run, F5
from the WP7 summary (two panels, one line per BatchTimeout), F6 as the JSON
excerpts of one finding, complete and redacted. Colours: the first four slots
of a validated categorical palette, each with its own marker, dash and direct
label (greyscale-safe). Only runs that count for the article are drawn;
validation runs are stamped as such. Checked visually with the container's
WP3 validation run and a synthetic WP7 summary; not committed.

F6 is exported afresh from the credit case's `ledger.jsonl` with the current
exporter, not read from the run's archived exports: those were written on
2026-10-12, before the exporter took the article's terms ("Compliance Policy
Engine"; "permissioned ledger" only for records a ledger stamped), and still
say "Compliance Oracle". The ledger is unchanged; chain and signatures verify
against the public keys published with the run (manifest:
`chain_valid: true`, `signatures_verified: true`). The two excerpts
(`experiments/article/figures/F6_finding_*.json`) are committed.

**`make article`** (`prototype/article/Makefile`): `make tests` runs every
suite (Python under both versions, credit case, bridge, WP7 runner, Go,
interop, Explorer, published evidence) — all pass on 2026-11-12;
`make regenerate`; `make figures`.

**Still open in WP9:** Zenodo deposit and `CITATION.cff` (wait for the
authorship decision); Docker images not rebuilt or tested here (no Docker in
this environment); the engine key that signed the 2026-10-12 runs was lost
with a replaced cloud container — the runs stay verifiable with the public
keys published beside them, and later runs are signed with a new key.

## WP3 and WP7 — measurements on `davide-m4pro` (2026-11-13)

Run by Claude Code on Davide Carneiro's Mac (Apple M4 Pro, 14 cores, 24 GB,
macOS 26.6.2, Python 3.12.7; Docker Desktop with 14 CPUs and 8 GB; Fabric
2.5.10 arm64 images), from commit `443c604`, which recorded the machine
before any measurement. Run note with the deviations:
`experiments/article/wp7/NOTE_davide-m4pro_20261113.md`.

Files that count: `wp3/ablation_davide-m4pro_20261113T090759Z.json`;
`wp7/fabric_davide-m4pro-bt2s_20261113T090921Z.json`,
`-bt250ms_20261113T101547Z.json`, `-couchdb_20261113T102152Z.json`, and
`wp7/summary_20261113T102316Z.json` built from those three. The first WP3 run
(`074543Z`) and the first 2 s run (`074915Z`) ran beside seven unrelated
containers and are superseded; they stay in the repository, and their numbers
agree with the repeats (W1 signature cost 0.018 against 0.017 ms; total
0.076 against 0.068 ms). `figures.py` picks the newest counting file, which is
the repeat; `make article` therefore draws the right ones.

**WP3** (W1, median of round medians, ms): A 0.262, B0 0.312, B 0.331,
B+ 0.338. Paired: canonical form, hashing and append-only persistence
(B0 − A) 0.048; Ed25519 signature (B − B0) 0.017; verifiable log against a
database row (B − A) 0.068; anchoring every 100 events amortised (mean
B+ − B) −0.001, with the anchor operation itself at 0.080. W2 agrees (B − A
0.059). No growth with ledger size up to 10,000 records (Figure F4); every
arm's ledger verifies after the growth run.

**WP7.** Every submission, anchor and query succeeded; the single-organisation
anchor was refused with `ENDORSEMENT_POLICY_FAILURE` in all three bring-ups.
Durable latency per record is the BatchTimeout plus about 28 ms, whatever N:
2 s gives 2,028 ms at N = 1 and 2,039 ms at N = 500; 250 ms gives 278 and
289 ms. Throughput grows with N: 0.49 records/s at N = 1 and 2 s (the
dissertation's 0.5), 245 at N = 500; at 250 ms, 3.6 and 1,730.
`VerifyInclusion` 1.6 ms median on both state databases; inclusion proofs
337 bytes at N = 10 to 673 at N = 500.

`VerifyChain` is not comparable across the two state databases as run: the
queries-only CouchDB bring-up submits one repetition of the per-record chain
(201 records), the LevelDB bring-ups three (601). Medians: 206 ms over 601
records on LevelDB (0.34 ms per record), 102 ms over 201 on CouchDB (0.51 ms
per record). The article reports both chain lengths. The first call of each
query includes a warm-up of several seconds, which is inside the 20 calls of
`VerifyChain` and raises its 95th percentile in the 2 s run (438 ms).

**Configuration C** (both counting runs, independently re-checked here for
the clean ledger and T1–T6b with the published public key): clean 16/16
records against 16 anchors; T1–T7b all detected. **Q12** in C: every anchor
submitted by `Org1MSP`, verifiable. `answerability.py --fabric-q12` replaces
the stand-in's Q12 in C with this answer and recomputes Table T10:
`wp5/answerability_20261012T161816Z_fabric_q12.json` (C: 13 of 13 answerable
and verifiable).

**Figure F5** gains a third panel. Panels (a) and (b) are measured; (c) is
the expected time from emission to durable evidence at the event rate of the
live MultiFlow Steel_Industry run (1,750 events in 80.7 s, 21.7 events/s,
from the published ledger): the measured anchor latency plus the analytic
mean wait for the batch to fill, (N − 1)/(2·rate), as the protocol's
estimands provide, and no point where serial anchoring is slower than the
stream (N = 1 at both timeouts, N = 10 at 2 s). The rate is the live run's,
not the plant's: the CSV has no timestamps.

## Keyed policy commitment in redacted exports (2026-11-19)

R. Sousa's review of the manuscript noted that the redacted export kept
`policy_hash`, an unkeyed SHA-256 of the policy's canonical content, and that
the `policy_id` it removed is `pol-` plus the digest's first twelve
characters. Both points held. The protocol amendment (`dbb84b9`) was recorded
before any run.

**Exporter.** Redacted mode now carries `policy-commitment` =
HMAC-SHA256(k, `policy_hash`), with k a random 256-bit key per export kept by
the provider, and a result-level prop `policy-commitment-alg`. Neither the
digest nor the identifier leaves. `export_oscal` writes the key beside the
export (`*.policy-commitment-key`); the credit case and WP5 keep it under
`keys/`. Tests: `test_redaction_boundary.py` (four new); suite 284 passed.

**Recovery by search** (`compliance_ledger_sim/policy_guess.py`; grid of the
amendment, 356,400 candidates; the searcher knows every field outside the
grid):

- redacted export of 2026-10-12 (plain digest): policy recovered, thresholds
  0.68 / 0.10 / 0.25 and stages exact, after 242,335 candidates in 3.45 s
  (`wp5/recovery_evidence_20261012T161816Z_20261119T215749Z.json`);
- redacted export of the new run (commitment): not recovered, 356,400
  candidates in 5.1 s; the commitment opens with the provider's key and the
  archived policy.

**WP5 rerun.** `wp5/answerability_20261119T215838Z.json`, merged with the
Fabric Q12 of WP7 into `..._fabric_q12.json`. Table T10 is identical to the
run of 2026-10-12. Q14 now checks 60 items (the 56 of the first run, the three
threshold values, the search) and finds none disclosed. Q3 and Q6 in D report
the commitment. The first rerun, `answerability_20261119T215750Z` and its
evidence folder, is superseded: its substring search matched "0.8" inside a
timestamp (note in the protocol, recorded before the second run).

**F6** regenerated from the same WP4 ledger with the new exporter; the key is
`figures/F6_policy_commitment.key`. The archived redacted exports of earlier
runs (WP4, regenerate, WP5 of 2026-10-12) keep the plain digest.
