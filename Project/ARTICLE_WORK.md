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
