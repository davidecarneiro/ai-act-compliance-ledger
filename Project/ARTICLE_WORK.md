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

- The policy applies the precision and fairness thresholds to every event, so
  an event without metrics (data ingestion, training) is rejected on
  precision. Version 1 had no such events. To settle before WP4: apply the
  thresholds by pipeline stage, or to events that carry the metric.
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
