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
