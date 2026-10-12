# Protocol — WP5, answerability of audit questions

Recorded on 2026-10-12, before the queries were implemented. The fourteen
questions are those of section 4.5 of the article plan, derived from the text
of the AI Act; this file fixes how each one is put to each configuration and
how the answer is classified.

## Evidence

The 16 events of the credit-scoring case (seed 42, case policy), followed by
two **synthetic** events, declared as such, so that Q9 has an incident to ask
about: `serious_incident_detected` and `incident_reported_to_authority` for
model v2 in run `gc-run-2` (stage `post_deploy_monitoring`, risk high, the
model's digest), sent after the drift alert. 18 events in all, sent through
the configurations of the WP3 ablation.

## Configurations (what the auditor holds)

| | Holds | Integrity it can check |
| --- | --- | --- |
| A | Arm A's SQLite table | none |
| B | Arm B's signed ledger, the issuer's public key, the policy archive, the artefact store | hash chain and signatures |
| C | Arm B+ with an anchor after every record (K = 1), the issuer's public key, the anchor file, the policy archive, the artefact store, the complete OSCAL export | B, plus every anchored head; stands in for the Fabric ledger, where every record is committed |
| D | The redacted OSCAL export only | none (the export is not signed and carries no record bodies) |

For C, the Fabric ledger adds the submitting organisation, stamped by the
chaincode (`submitter_msp`). Q12 in C is therefore answered from the Fabric
run (WP7); here it is reported for the stand-in, marked as such.

## Questions and how each is asked

| # | Question | Operationalisation |
| --- | --- | --- |
| Q1 | Which model version (artefact digest) was approved for deployment, and when? | Deployment requests, their decision, the model's digest and the time; "none approved" is an answer. |
| Q2 | Was deployment approved by an authorised human overseer, and by whom? | Approvals on deployment requests: approver, whether the approver is authorised by the policy that decided, whether the approval's signature verifies. |
| Q3 | Which validation metrics and thresholds supported the decision? | For the validation and deployment decisions: metric values and the thresholds of the deciding policy. |
| Q4 | Was bias examined before deployment, with which metric and outcome? | Records with a parity metric preceding the first deployment request: metric, value, outcome. |
| Q5 | Which dataset version (digest) trained model version X? | X = model v2: the dataset digest in the same run as the training record of X. |
| Q6 | Which policy version decided, and does re-execution reproduce the decision? | Policy identity per record; re-execution of every decision from the record and the archived policy. |
| Q7 | Which events belong to run R? | R = `gc-run-2`. |
| Q8 | Were drift alerts raised after deployment, and when? | Drift alerts and their times, relative to the first deployment request. |
| Q9 | Did the drift alert precede serious incident Y? | Y = the synthetic incident: order and times of the drift alert and the incident. |
| Q10 | Has any record been altered since issuance? | Any alteration detectable by the configuration's own check, including by the key holder. |
| Q11 | Is the record sequence complete between t1 and t2? | t1 = first record of run `gc-run-2`, t2 = the time of the audit (the end of the evidence held). |
| Q12 | Which organisation submitted each record? | The submitter of each record. |
| Q13 | From the redacted export alone, which articles are supported and with which technical outcome? | Per record: supported provisions and outcome (put to every configuration; the question's point is D). |
| Q14 | Does the redacted export disclose the artefact identity or the policy logic? | Search the redacted export for artefact names and digests, the UUIDs the complete export derives from them, reasons, threshold values and metric values. Asked of D only. |

## Classification

- **Answerable:** yes (every element the question asks for is in the
  configuration), partial (some elements; the missing ones are named), no.
- **Third-party verifiable without trusting the issuer:** yes when the
  records used pass the configuration's integrity check and, for questions
  about completeness or absence (Q1, Q2, Q7, Q8, Q9, Q11), the
  configuration can also exclude truncation (anchors); partial when the
  records verify but completeness cannot be established, or when an
  alteration by the key holder cannot be excluded (Q10 in B); no in A and D.
- Also recorded per pair: records read and time taken.

## Expected

The plan expects Q11 to be answerable only in C; this is a result, not a
failure of the other configurations. No other outcome is fixed in advance.

## Output

`experiments/article/wp5/answerability_<UTC time>.json`, with the answer,
classification, records read and time per question and configuration, and the
condensed counts of Table T10. Produced by
`prototype/credit_case/answerability.py`.
