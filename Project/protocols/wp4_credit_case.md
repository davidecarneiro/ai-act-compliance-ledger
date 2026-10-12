# Protocol — WP4, credit-scoring case on the Statlog German Credit data

Recorded on 2026-10-12, before any model was trained on these data. The only
look at the data before this protocol was a count of rows, labels, applicants
under 25, and applicants and bad risks per checking-account category, to fix
the subgroups below. Nothing
in this file changes after the pilot or the main run; any deviation is
reported as such in `ARTICLE_WORK.md` and in the article.

## Purpose

Show that the evidence model of the article (schema version 2) records a real
machine-learning pipeline end to end: every policy metric in the ledger is
computed by the pipeline from the data, every artefact is committed by digest
and kept in the content-addressed store, the deployment gate checks a signed
human approval, and every decision re-executes from its record and the
archived policy. It is not a study of credit models or of bias mitigation.

## Data

- Statlog (German Credit Data), UCI dataset 144, `german.data` read from the
  archive in `Project/datasets/german_credit/`, whose SHA-256 digests are
  checked before use (`PROVENANCE.md`).
- 1,000 applicants, 20 attributes (7 numerical, 13 categorical). Positive
  label: good credit risk (`1`); 700 good, 300 bad.
- Protected attribute, fixed here: age (attribute 13), with the groups under
  25 (149 applicants) and 25 or over, as in AIF360's preprocessing of this
  dataset.

## Partition

Stratified by label, 60/20/20 (600 training, 200 validation, 200 test), with
`random_state` = 42: `train_test_split(test_size=0.4, stratify=y)`, then the
40 % split in half, stratified, with the same seed.

## Models

- Features: all 20 attributes, age included. Categorical attributes one-hot
  encoded; numerical attributes standardised; fitted on the training partition.
- v1: logistic regression (scikit-learn defaults: L2, C = 1, lbfgs,
  `max_iter` = 1000), no mitigation.
- v2: the same model trained with reweighing (Kamiran and Calders, 2012):
  each training example of group g and label y weighs
  P(g)·P(y) / P(g, y), estimated on the training partition.
- Classification threshold 0.5 on the probability of a good risk.

## Policy metrics (validation partition)

- `precision`: precision of the good-risk class.
- `demographic_parity_diff`: absolute difference between the rates of
  predicted good risk for applicants aged 25 or over and under 25.
- Values are rounded to six decimal places before they enter an event.

## Policy

| Field | Value | Origin |
| --- | --- | --- |
| `min_precision` | calibrated on the pilot (below) | Pilot |
| `max_demographic_parity_diff` | 0.10 | Bound of the "fair" range of statistical parity difference in AIF360 (Bellamy et al., 2019), fixed a priori |
| `drift_alert_threshold` | 0.25 | Conventional PSI bound for a significant shift (Siddiqi, 2006), fixed a priori |
| `metric_threshold_stages` | `validation`, `deployment` | Thresholds describe a validated model; metrics mandatory there |
| `require_human_approval_for_high_risk` | false | Oversight is the signed approval at the deployment request; the boolean rule would apply to every high-risk event, ingestion included |
| `signed_approval_required_for` | `deployment_request` | WP6 |
| `authorised_approvers` | `approver-demo` | Demonstration key, committed and labelled as such, so that the case regenerates under the same policy |

Every event declares `risk_level` high: creditworthiness assessment of natural
persons is listed in Annex III, point 5(b), of the AI Act.

## Pilot and calibration

The whole pipeline runs once with `random_state` = 7 for the partition. Its
results are kept (`experiments/article/wp4/pilot_*.json`) but are not
evaluation results and are not reported as such. From the pilot:

    min_precision = floor to 0.01 of (pilot v2 validation precision − 0.05)

The margin of 0.05 allows for the variation of precision between partitions
(about 0.03 standard error with some 150 predicted good risks). The policy is
then written, committed, and not changed.

## Drift (monitoring)

- Induced and declared as such: covariate shift towards applicants with a
  checking account below 0 DM (attribute 1 = `A11`; 274 of 1,000), the
  checking-account category with the highest share of bad risks in the
  dataset (49 %, against 39 %, 22 % and 12 % for the other three).
- Six batches of 50 applicants drawn from the test partition. Batch k has
  round(50 · q_k) applicants from the subgroup and the rest from the other
  test applicants, without replacement within a batch, with q = (s, s, 0.50,
  0.65, 0.80, 0.95), s being the subgroup share of the test partition.
  Batches are drawn with `numpy.random.default_rng(42)`.
- Indicator: Population Stability Index of the v2 model's scores (probability
  of good risk) in the batch against its scores on the validation partition.
  Five bins at the quintiles of the validation scores; counts smoothed by
  adding 0.5 to each bin. Five bins rather than ten because with 50 and 200
  observations the expected PSI under no shift is about
  (k − 1)(1/50 + 1/200): 0.23 with ten bins, too close to the alert
  threshold, and 0.10 with five.
- The event carries `psi` and `drift_score` = min(PSI, 1). The engine bounds
  `drift_score` to [0, 1]; since the alert threshold is below 1, the cap
  does not change any decision.

## Events

Two runs. Each event names its artefact by digest (`artifact_sha256`) and its
place in the content-addressed store (`off_chain_ref`); the events of a run
share its `run_id`.

| # | Run | `event_type` | `pipeline_stage` | Artefact | Metrics |
| --- | --- | --- | --- | --- | --- |
| 1 | `gc-run-1` | `data_ingested` | `data_preparation` | `german.data` (dataset) | — |
| 2 | `gc-run-1` | `data_split` | `data_preparation` | partition indices (dataset) | — |
| 3 | `gc-run-1` | `model_trained` | `training` | model v1 | — |
| 4 | `gc-run-1` | `model_validation` | `validation` | model v1 | precision, parity |
| 5 | `gc-run-2` | `data_ingested` | `data_preparation` | `german.data` (dataset) | — |
| 6 | `gc-run-2` | `data_split` | `data_preparation` | partition indices (dataset) | — |
| 7 | `gc-run-2` | `model_trained` | `training` | model v2 | — |
| 8 | `gc-run-2` | `model_validation` | `validation` | model v2 | precision, parity |
| 9 | `gc-run-2` | `deployment_request` | `deployment` | model v2 | precision, parity; no approval |
| 10 | `gc-run-2` | `deployment_request` | `deployment` | model v2 | precision, parity; approval signed by `approver-demo` |
| 11–16 | `gc-run-2` | `monitoring_batch` | `post_deploy_monitoring` | batch report | `psi`, `drift_score` |

The sequence is fixed: every event is sent whatever the decisions on earlier
events, and the engine's decisions are recorded, not acted upon. Event 9 is a
deliberate test of the deployment gate and is reported as such. Only v2 is put
forward for deployment, as the provider's declared candidate.

## Outputs

Under `experiments/article/wp4/run_<UTC time>/`: the ledger (JSONL), the
artefact store, the case policy and the engine's public key, OSCAL Assessment
Results (complete and redacted), the re-execution report, the artefact
verification report, the recomputation of every metric from the stored
artefacts, and a summary.

## Acceptance

1. No metric in the ledger is set by hand: each one is recomputed from the
   stored dataset, partition and model (and batch report) and matches.
2. The chain verifies.
3. Every artefact digest recomputes from its `off_chain_ref`.
4. Re-execution reproduces decision, rule and supported provisions for every
   record.
5. The OSCAL exports validate against the NIST schema.
6. At least one decision of each type (approved, rejected, escalated).

Which decisions the models obtain is not an acceptance criterion; it is a
result and is reported as it comes out.

## References

- Bellamy, R. K. E., et al. (2019). AI Fairness 360. IBM Journal of Research
  and Development, 63(4/5), 4:1–4:15.
- Kamiran, F., and Calders, T. (2012). Data preprocessing techniques for
  classification without discrimination. Knowledge and Information Systems,
  33(1), 1–33.
- Siddiqi, N. (2006). Credit Risk Scorecards. Wiley.
