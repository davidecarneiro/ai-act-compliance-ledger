# Master Traceability Matrix

This matrix is an index of partial technical coverage. It links each legal provision to the internal requirement derived from it, the component of the prototype that addresses it, the validation note, the experimental evidence, the chapters and the main references. A status of `validated` or `implemented` describes what the prototype exercises; it is not a statement that the provision is complied with. The identifiers of requirements, features and validations name notes of the author's working repository; in the delivered folder they are identifiers, not links.

## Traceability chain

| Standard / article | Internal requirement | Feature / component | Validation | Experimental evidence | Chapter(s) | Main references | Status |
|---|---|---|---|---|---|---|---|
| AI Act Art. 8 | `REQ-AIA-008-compliance-requirements` | `Feature - Compliance Oracle` | `VAL-gate-deploy-regras` | `experiments/latency/exploratory/simulator_summary_baseline_20260425T222605Z.json` | Ch. 3, Ch. 4, Ch. 5 | `RegulationEU2024`, `tabassiArtificialIntelligenceRisk2023` | implemented |
| AI Act Art. 9 | `REQ-AIA-009-risk-management` | `Feature - Compliance Oracle` | `VAL-AIA-009-risk-management`, `VAL-gate-deploy-regras` | `risk_level: high` in every scenario. The thresholds are global and configurable; the one condition tied to the risk level is that high risk requires human approval. `simulator_metrics_*.csv` | Ch. 3, Ch. 5 | `RegulationEU2024`, `tabassiArtificialIntelligenceRisk2023` | implemented |
| AI Act Art. 10 | `REQ-AIA-010-data-governance` | `Feature - Hash On-Chain Off-Chain` | `VAL-AIA-010-data-governance`, `VAL-ledger-evidencias-integridade` | `Art.10(3)` tagged on the 6 canonical records and on the 500 events of the load test, which is a separate artefact (corrected on 2026-09-17: it read «500+ events», which suggested a canonical ledger of 500). `dataset_used` in `approved_model`. `demographic_parity_diff` tracked per event | Ch. 3, Ch. 5 | `RegulationEU2024`, `limaMLOpsPracticesMaturity2022` | implemented |
| AI Act Art. 11 + Annex IV | `REQ-AIA-011-documentation` | `Feature - Audit Trail Query` | `VAL-AIA-011-documentation-completude`, `VAL-ledger-evidencias-integridade` | Signed records and OSCAL. Scope covered by 23 entries in `Anexo IV - Alcance demonstrado`. The complete technical file is not demonstrated | Ch. 3, Ch. 4, Ch. 5 (`tab:alcance_anexo_iv`) | `RegulationEU2024`, `rajmohanEUAIAct` | partial |
| AI Act Art. 12 | `REQ-AIA-012-logging` | `Feature - Ledger de Evidencias` | `VAL-ledger-evidencias-integridade` | `ledger.json`, `simulator_metrics_*.csv` | Ch. 4, Ch. 5 | `shiAUDITEMAutomatedEfficient2022`, `luSecureScalableData2020` | validated |
| AI Act Art. 13 | `REQ-AIA-013-transparency` | `Feature - Audit Trail Query` | `VAL-ledger-evidencias-integridade` | `audit_query` validated. `requirements_covered` on each event ties the decision to an article. The OSCAL export is machine-readable, and the query is reproducible by requirement (`query_by_requirement`) and by scenario (`query_by_scenario`) in `simulator.py`. There is no run identifier, because the record produced has no `trace_id` field | Ch. 2, Ch. 4, Ch. 5 | `RegulationEU2024`, `tabassiArtificialIntelligenceRisk2023` | implemented |
| AI Act Art. 14 | `REQ-AIA-014-human-oversight` | `Feature - Gate de Deploy por Compliance` | `VAL-gate-deploy-regras` | `missing_human_approval_rejected` | Ch. 4, Ch. 5 | `RegulationEU2024`, `lopesEngineeringAIAgents2026` | validated |
| AI Act Art. 15 | `REQ-AIA-015-accuracy-robustness` | `Feature - Gate de Deploy por Compliance` | `VAL-AIA-015-fairness-gate`, `VAL-gate-deploy-regras` | `low_precision_rejected`, `fairness_rejected` | Ch. 5 | `fermiFairEmpiricalRisk2021`, `zhaoConditionalLearningFair2020` | validated |
| AI Act Art. 17 | `REQ-AIA-017-quality-management` | `Feature - Compliance Oracle` | `VAL-AIA-017-quality-management`, `VAL-gate-deploy-regras` | The versioned `configs/policies.json` is a configuration of controls, identified in each record by `policy_id` and `policy_hash`; it is one input to a quality management system, not the system. The Oracle validates every event against it, and a rejection records its reason | Ch. 3, Ch. 4 | `isoiec420012023`, `tabassiArtificialIntelligenceRisk2023` | implemented |
| AI Act Art. 72 | `REQ-AIA-072-post-market-monitoring` | `Feature - Compliance Oracle` | `VAL-AIA-072-drift-detection`, `VAL-gate-deploy-regras` | `drift_detected` | Ch. 5 | `gamaSurveyConceptDrift2014`, `hinderOneTwoThings2024` | validated |
| AI Act Art. 73 | `REQ-AIA-073-serious-incidents` | `Feature - Audit Trail Query` | `VAL-AIA-073-serious-incidents`, `VAL-ledger-evidencias-integridade` | A dedicated serious-incident scenario (`build_incident_scenario`): detection → a simulated reporting event (Art. 73(2)) → audit query; nothing is sent to an authority. 3 events, chain 3/3, Art. 73 covered 3/3, OSCAL exported. `experiments/runs/incident_run` | Ch. 3, Ch. 5 | `RegulationEU2024`, `tabassiArtificialIntelligenceRisk2023` | validated |
| AI Act Art. 18 | `REQ-AIA-018-documentation-retention` | `Feature - Ledger de Evidencias` | `VAL-AIA-018-documentation-retention` | The `ledger.json` is written by appending and each record chains to the previous one by `parent_hash`. The canonical ledger holds 6 records; the 500-event load test is a separate artefact. The prototype writes no resolvable reference to the off-chain object (`off_chain_ref`), so the record identifies the artefact and does not recover it. Retention periods are not exercised | Ch. 3, Ch. 4 | `RegulationEU2024`, `isoiec270012022` | implemented |
| AI Act Art. 43 | `REQ-AIA-019-conformity-assessment` | `Feature - Compliance Oracle`, `Feature - Audit Trail Query` | `VAL-AIA-019-conformity-assessment` | `requirements_covered` on each event. OSCAL Assessment Results (31 exporter tests in the delivered version). `findings[].props[name=supports-requirement]`, class `ai-act-article`, maps `aia-*` → article (in the eight exports from April 2026 the same mapping comes out as `props[name=control-id]`). The `related-controls` inside the finding was removed on 2026-06-13 for being invalid against the OSCAL 1.1.2 schema, and appears in no export on disk | Ch. 2 (Art. 43(1)), Ch. 5 (OSCAL) | `RegulationEU2024`, `isoiec420012023` | implemented |
| AI Act Art. 26 | `REQ-AIA-026-deployer-monitoring` | `Feature - Compliance Oracle` | `VAL-gate-deploy-regras`, `VAL-AIA-072-drift-detection` | The `drift_detected` scenario (drift_score=0.22, above the threshold) together with `missing_human_approval_rejected` (the Oracle records a `rejected` decision; it does not itself stop the deployment in the external system). Post-deployment monitoring with escalation | Ch. 4, Ch. 5 | `RegulationEU2024`, `gamaSurveyConceptDrift2014` | validated |
| AI Act Art. 78 | `REQ-AIA-078-confidentiality-trade-secrets` | `Feature - Hash On-Chain Off-Chain`, `Feature - Pseudonymizer`, `Feature - OSCAL Exporter` | `VAL-ledger-evidencias-integridade`, `VAL-disclosure-seletivo-oscal` | `pseudonymizer.py` and `oscal_exporter.py`. Private HLF channels as the target stack | Ch. 2, Ch. 4, Ch. 5 | `RegulationEU2024`, `brandenburgerBlockchainTrustedComputing2018`, `sychowiecBlockchainBasedFrameworkSecure2025`, `edpbGuidelinesBlockchain2025` | implemented |

## Reading the matrix

- `validated`: there is a requirement, a feature, a completed validation and exported experimental evidence.
- `implemented`: there is an implemented component and technical evidence, but validation may still be partial.
- `mapped`: the requirement is derived and tied to the architecture, without complete experimental validation yet.
- `partial`: coverage is demonstrated by one scenario or artefact, but not all the associated controls are complete.

## Reference artefacts

- Prototype (Compliance Oracle with hash chain and Ed25519): `prototype/compliance_ledger_sim/simulator.py`
- Ed25519 key management: `prototype/compliance_ledger_sim/keys.py`
- Shared scenarios: `prototype/compliance_ledger_sim/scenarios.py`
- SQLite baseline for the measured comparison: `prototype/compliance_ledger_sim/baseline_logger.py`
- Oracle against baseline comparison: `prototype/compliance_ledger_sim/compare_oracle_vs_baseline.py`
- Sensitivity analysis: `prototype/compliance_ledger_sim/sensitivity.py`
- Test suite (98 pytest tests, by `--collect-only`: 37 simulator, 31 OSCAL, 13 boundary matrix, 8 pseudonymizer, 5 redaction boundary, 3 OSCAL schema-valid, 1 concurrency): `prototype/compliance_ledger_sim/tests/`
- Configurable policies: `prototype/compliance_ledger_sim/configs/policies.json`
- Simulated ledger: `prototype/compliance_ledger_sim/ledger.json`
- Experimental results: `experiments/`
  - `oracle_summary_oracle_baseline_*.json`: the Oracle's baseline run
  - `comparison_oracle_vs_baseline_*.json`: the measured comparison against the SQLite baseline
  - `sensitivity_analysis_*.csv|json`: the sweep of 45 threshold combinations
  - `RESULTS_SUMMARY.md`: consolidated summary of the Phase 1 results
- In the author's working repository, not in the delivered folder: the critical analysis and roadmap (`00_admin/Analise_Critica_e_Roadmap.md`), the expanded normative matrix (`ai_act_mapping/AI Act - Matriz Completa.md`) and the validation chapter (`05_latex/chapters/05_validacao_experimental.tex`)
