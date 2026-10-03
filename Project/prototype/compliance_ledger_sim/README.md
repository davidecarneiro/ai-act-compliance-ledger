# Compliance Ledger Simulator

Prototype of the Compliance Oracle and Evidence Ledger described in Chapters 4
and 5 of the dissertation.

## Components

- `simulator.py`: the Compliance Oracle, with a hash chain (parent_hash + chain_hash) and an Ed25519 signature over every record.
- `keys.py`: persistent Ed25519 key management under `keys/`.
- `scenarios.py`: shared definition of the six canonical scenarios, plus the Art. 73 serious-incident sequence.
- `baseline_logger.py`: the centralised SQLite baseline used for comparison. Same interface, no chain, no signature.
- `pseudonymizer.py`: HMAC-SHA256 pseudonymisation with a versioned, rotatable organisational key.
- `oscal_exporter.py`: exports the ledger as OSCAL 1.1.2 Assessment Results, full and redacted (AI Act Art. 78).
- `verify_delivery.py`: re-verifies every chain shipped in `experiments/` using the public key alone, and compares each chain's final `chain_hash` with the published one. Writes nothing.
- `compare_oracle_vs_baseline.py`: runs Oracle and baseline side by side, tampers with one record in each, and exports comparative metrics.
- `bench_latency.py`: the paired latency protocol of 2026-09-14, ten interleaved rounds of 200 events.
- `bench_validation.py`: cost of input validation per event.
- `sensitivity.py`: sensitivity analysis of the policy thresholds, 45 combinations.
- `load_test.py`: 500-event load test. It rewrites `ledger.json`; rerunning `simulator.py` gives six valid records again, but new ones, so restore the published file from the delivered copy.
- `incident_demo.py`: standalone Art. 73 serious-incident demonstration, on a ledger of its own.
- `validate_oscal_schema.py`: validates the OSCAL exports against the official NIST 1.1.2 schema, vendored in `tests/fixtures/`.
- `configs/policies.json`: the policy thresholds. Its `policy_id` is derived from the file's content, and the canonical ledger names `pol-c3d1fc49f36e`. The key `require_hash_verification` is declared but not read by any code: the integrity check is `verify_chain()`, run on request, never as a condition of a decision. It stays in the file because removing it would change the `policy_id` the published records carry.
- `paths.py`: finds the output directory. It recognises both the dissertation vault and the delivered folder, and `EXPERIMENTS_DIR` overrides the search.
- `Makefile`: the entry points. `make verify` checks the shipped evidence, `make tests` runs the suite, `make demo` runs everything end to end.
- `tests/`: 98 pytest tests over decisions, chain, signatures, tampering, pseudonymisation, OSCAL structure and schema validity, plus the boundary matrix of the evidence contract.

## How to run

The commands after the first write new records over the published canonical
ledger (and `incident_demo.py` over the published incident run). Run them in a
copy of the folder; `verify_delivery.py` then reports those chains as NOT
PUBLISHED.

```bash
# Verify the evidence shipped with the dissertation (writes nothing)
python3 verify_delivery.py

# Baseline run (writes ledger.json + experiments/oracle_*)
python3 simulator.py

# Comparison against the baseline (writes experiments/comparison_*.json)
python3 compare_oracle_vs_baseline.py

# Sensitivity analysis (writes experiments/sensitivity_*.csv|.json)
python3 sensitivity.py

# OSCAL export + schema validation
python3 oscal_exporter.py
python3 validate_oscal_schema.py

# Tests
python3 -m pytest tests/ -v
```

## Evidence model

Every ledger record carries 23 fields:

```
evidence_id, scenario_id, event_type, artifact_id, artifact_type,
pipeline_stage, timestamp, decision, reason, rule_id, metrics,
policy_id, policy_hash, artifact_hash, requirements_covered,
issuer_id, issuer_pubkey_fingerprint, sig_alg, hash_alg,
parent_hash, record_hash, issuer_signature, chain_hash
```

Two of them are the conceptual model's fields under another name: `decision` is
the model's `policy_decision`, and `requirements_covered` is its
`ai_act_articles`. Appendix A of the dissertation states the correspondence,
without which the twelve-of-thirteen count cannot be checked against the JSON.

The chain is defined by:
- `parent_hash[0]` = `0x00...00` (genesis, 32 bytes)
- `parent_hash[i]` = `chain_hash[i-1]` for `i >= 1`
- `record_hash[i]` = SHA-256(canonical body[i])
- `chain_hash[i]` = SHA-256(parent_hash[i] || record_hash[i])
- `issuer_signature[i]` = Ed25519(canonical body[i])

A change to the signed body of a record is caught by three checks over that body and its chain links. They are not independent: they read the same bytes, and a change usually trips all three at once. They assume the verifier trusts the public key and holds an anchor (the final `chain_hash`) published earlier; removing records from the end of a chain is only caught against such an anchor or a declared count, as `verify_delivery.py` does:
1. recomputed record_hash differs from the stored one
2. the Ed25519 signature fails over the modified body
3. recomputed chain_hash differs from the stored one

## Scenarios

| Scenario | Expected decision | Policy triggered |
|---|---|---|
| `approved_model` | approved | all metrics within thresholds + human approval |
| `low_precision_rejected` | rejected | precision 0.74 < min 0.80 |
| `fairness_rejected` | rejected | demographic_parity_diff 0.09 > 0.05 |
| `missing_human_approval_rejected` | rejected | high risk without human approval |
| `drift_detected` | escalated | drift 0.22 > 0.15 |
| `audit_query` | verified | records that an audit query was made (`audit.query_recorded`); the integrity check itself is `verify_chain()`, whose result is not written into the record |

## Licence and citation

This prototype is released under the **MIT Licence** (see `LICENSE`).

If you use this code in academic research, please cite the dissertation:
> Sousa, R. P. T. (2026). *Blockchain for Compliance, Auditability and Traceability of Technical Documentation in the AI Act*. Master's dissertation, Master in Digital Legal Practices, ESTG, Polytechnic of Porto (P.PORTO).

No DOI has been minted for this code. A Zenodo snapshot of the submitted
version is planned, and the identifier will be added here once it exists.

## Target stack

The migration to Hyperledger Fabric (Go chaincode with a two-organisation AND
endorsement policy, X.509 identities issued by per-organisation Fabric CAs,
deployment as Chaincode-as-a-Service, latency measured through the Fabric
Gateway SDK) has been carried out and is described in
`prototype/fabric_migration/` and in Chapter 5 of the dissertation.
The keys shipped under `keys/` are demonstration material only. Production
custody, in a KMS or an HSM, is discussed as future work in Chapter 6.
