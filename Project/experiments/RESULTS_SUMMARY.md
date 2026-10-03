# Summary of the experimental results

This file has two parts. The first states what holds for the delivered
version. The second is the capture of 2026-04-29, kept as a dated record with
the notes added since; its counts and timings are those of that date.

## State of the delivered version (October 2026)

| Item | Value | Where |
|---|---|---|
| Latency the dissertation cites | Oracle median 6.47 ms, baseline 1.38 ms, paired median difference +5.08 ms (ten rounds of 200 events); second run +5.11 ms | `latency_protocol_20260914T160731Z.json`, `latency_protocol_20260914T200554Z.json` |
| Load test | 500 events, 110.08 events/s, mean 9.08 ms, P95 16.07 ms | `load_test_20260610T173644Z.json` |
| Sensitivity | 45 threshold combinations | `sensitivity_analysis_*` |
| Record | 23 fields | `ledger.json` |
| Published chains | 7 chains, 1,831 records | `python3 verify_delivery.py` |
| OSCAL exports | 18, valid against the NIST 1.1.2 schema | `python3 validate_oscal_schema.py --expect 18` |
| Tests | 98 pytest (simulator), 4 pytest (bridge), 10 Go (chaincode) | `tests/`, `multiflow_bridge/`, `fabric_migration/chaincode/` |
| Dependencies | minimum versions in `requirements.txt` (`>=`), not pinned | `requirements.txt` |

## Capture of 2026-04-29

Taken after Phase 1 (M1, M5, M3, M6, M14) and the Phase 2 quick wins (M21 pseudonymisation, M22 reproducibility, M23 OSCAL exporter).

> **Status of the latencies in this file (note of 2026-09-15).** The times
> recorded here are those of the capture of 2026-04-29 and became
> **exploratory** on 2026-09-14: they measure six events in a single run, with
> no warm-up and no repetition, and on re-measurement the sign of the
> difference flipped. The latency the dissertation cites comes from the paired
> protocol (`LATENCY_PROTOCOL_2026-09-14.md`, artefacts
> `latency_protocol_*.json`): Oracle median **6.47 ms**, baseline median
> **1.38 ms**, paired median difference **+5.08 ms**, with the Oracle slower in
> 10 rounds out of 10. See `README_LATENCY.md`. The decisions, the article
> coverage and the chain checks of the six scenarios are unchanged; the test
> counts, the dependency versions and the file lists below are those of the
> capture, and the table above gives the current ones.
>
> The same applies to the **record field count** below. On the date of this
> capture a record carried 19 fields. It carries **23** since September 2026,
> when `metrics`, `policy_id`, `policy_hash` and `rule_id` were added.

## Compliance Oracle: baseline run (6 scenarios)

| Metric | Value |
|---|---|
| Events processed | 6 |
| Approved decisions | 1 |
| Rejected decisions | 3 |
| Escalated decisions | 1 |
| Verified queries | 1 |
| Mean latency per event | 3.79 ms *(exploratory; see the note above)* |
| P95 latency per event | 4.11 ms |
| Triple chain verification | 6/6 valid (record_hash, Ed25519, chain_hash) |
| Signature algorithm | Ed25519 (RFC 8032) |
| Hash algorithm | SHA-256 (FIPS 180-4) |
| Pseudonymisation | HMAC-SHA256 with a versioned organisational key |
| Maximum coverage per event | 6 AI Act articles |

## Phase 2: HMAC pseudonymisation (M21)

An HMAC-SHA256 layer with a persistent, versioned and rotatable organisational key. It is applied to `subject_id`, `user_id`, `patient_id`, `customer_id` and other sensitive identifiers before any hashing or signing.

| Property | Verified by |
|---|---|
| Determinism within the org/version pair | 1 test (audit replay) |
| Divergence across organisations | 1 test (cross-org non-correlation) |
| Divergence across key versions | 1 test (rotation takes effect) |
| Replay with an older version | 1 test (historical queries) |
| Recursive application to the event | 2 tests (substitution and preservation) |
| Integration with the Oracle | 1 test (`subject-42` does not appear in the ledger) |

**Total:** 8 pseudonymiser tests, all passing.

## Phase 2: OSCAL 1.1.2 exporter (M23)

An OSCAL Assessment Result document, valid against the NIST schema, with:

| OSCAL field | Origin in the ledger |
|---|---|
| `assessment-results.metadata.parties[]` | Issuer Ed25519 fingerprint |
| `results[].observations[]` | One per record (UUID v5 derived from `evidence_id`) |
| `results[].findings[]` | One per decision, with `state=satisfied` or `not-satisfied` |
| `findings[].props[name=supports-requirement]` (class `ai-act-article`). In the eight exports from April 2026 the same prop is called `control-id`; the `related-controls` inside the finding was removed on 2026-06-13 for being invalid against the OSCAL 1.1.2 schema | `aia-15`, `aia-12`, `aia-72` and so on (the AI Act article mapping) |
| `results[].assessment-log.entries[]` | The result of `verify_chain()`, with `chain_valid` and `records_total` |

**Total:** 7 OSCAL tests, all passing. Sample output: 6 observations, 6 findings and 1 log entry.

## Phase 2: Reproducibility (M22)

| Artefact | State |
|---|---|
| `requirements.txt` | `cryptography==46.0.6`, `pytest==9.0.3` at the time of the capture. The delivered file sets minimum versions (`>=`) and also lists `jsonschema` and `regex` |
| `Dockerfile` | `python:3.11-slim-bookworm`, non-root user |
| `Makefile` | targets `setup`, `tests`, `verify`, `baseline`, `compare`, `sensitivity`, `oscal`, `demo`, `docker-build`, `docker-run`, `clean` |

## Oracle against the baseline (centralised SQLite log)

| Metric | Oracle | Baseline | Delta |
|---|---|---|---|
| Mean latency (ms) | 3.79 | 2.24 | +1.55 ms *(exploratory; the figure measured under protocol is +5.08 ms)* |
| P95 latency (ms) | 4.11 | 2.96 | +1.15 ms |
| Audit query (ms) | 1.12 | 0.11 | +1.01 ms |
| Tamper detection | **Yes** | **No** | qualitative |
| Fields per record | 19 | 9 | +10 fields |

## Phase 2: OSCAL selective disclosure for Art. 78 (M24d)

The OSCAL exporter accepts a `redacted=True` mode. Redaction operates on the serialisation, not on the ledger:

| OSCAL field | State in redacted mode |
|---|---|
| `observations[].description` | redacted |
| `observations[].props[reason]` | redacted |
| `observations[].props[redaction_applied]` | `"true"` (marker) |
| `findings[].description` | redacted |
| `observations[].relevant-evidence[].description` (record_hash, chain_hash, signature_alg) | preserved |
| `findings[].props[name=supports-requirement]` (`control-id` in the April 2026 exports) | preserved (`aia-*`) |
| `findings[].target.status.state` (`satisfied`/`not-satisfied`) | preserved |
| `metadata.parties[].props[ed25519-fingerprint]` | preserved |
| v5 UUIDs of `observations` and `findings` | identical to the full version |

**Total:** 5 further tests for selective disclosure, all passing.

## Consolidated test suite

> Real output from 2026-09-13, pasted and NOT updated:

```
pytest tests/ -v
============================== 79 passed in 0.96s ==============================
```

> A run of 2026-09-13, pasted from the real output and therefore NOT updated: as
> of 2026-09-15 the suite has **98 tests**. Added after this run were the 13 of
> `test_fronteiras.py`, which walks the matrix of 16 cases over the input
> domain, and the 4 of `test_redaction_boundary.py`, which sweeps the redacted
> OSCAL document field by field. The suite went from 39 to 79 tests over two
> corrections to the OSCAL exporter. Three cases cover `chain_valid`: an intact
> chain, a tampered chain, and a result supplied by whoever ran the full
> verification. Before them the exporter assumed `chain_valid=true` by default,
> and a document could assert integrity that had never been verified. Two cases
> cover the finding's objective: before, all of them pointed at `aia-10-3`,
> because the objective was the first article of an alphabetically ordered
> list, so a rejection for want of human oversight was filed against the data
> quality objective. The pair of exports from 2026-09-13 shows the corrected
> distribution, and the April ones predate it.

| Module | Tests | Coverage |
|---|---|---|
| `tests/test_simulator.py` | 16 | decision, chain, signature, queries, genesis |
| `tests/test_pseudonymizer.py` | 8 | EDPB 02/2025 mitigation properties |
| `tests/test_oscal_exporter.py` | 17 | NIST OSCAL 1.1.2 schema, UUID determinism, Art. 78 redaction |

## Load test (500 sequential events)

The published load-test summary is `load_test_20260610T173644Z.json`. It
records the event count, the total duration, the throughput, the mean latency
and the P95. It does not contain the individual event observations:

| Metric | Value |
|---|---|
| Events processed | 500 |
| Throughput | 110.08 events/s |
| Mean latency | 9.08 ms |
| P95 latency | 16.07 ms |

Two other runs of 2026-06-10 on macOS arm64, outside the container, gave about
120 events/s at 8.32 ms with a P95 of 15.52 ms, and 116.75 events/s at 8.56 ms
with a P95 of 15.67 ms. No artefact of those two runs was kept, so they are
reported and not cited as measurements.
`load_test.py` now persists every run as `load_test_<timestamp>.json` in this
directory.

The degradation relative to the 6-scenario run (3.79 ms, exploratory) comes
from re-serialising the JSON ledger to disk as the history grows.

## Generated files

- `oracle_metrics_oracle_baseline_*.csv` and `.json`
- `comparison_oracle_vs_baseline_*.json`
- `sensitivity_analysis_*.csv` and `.json`
- `oscal_assessment_results_*.json` (full version)
- `oscal_assessment_results_redacted_*.json` (Art. 78 version)
- `load_test_*.json` (the 500-event load test)

All of them under `experiments/` (in the delivered folder,
`experiments/`).
