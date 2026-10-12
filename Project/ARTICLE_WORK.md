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
