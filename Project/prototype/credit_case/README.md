# Credit-scoring case (WP4)

A real machine-learning pipeline recorded end to end in the evidence ledger
(schema version 2), on the Statlog German Credit data
(`Project/datasets/german_credit/`). The protocol,
`Project/protocols/wp4_credit_case.md`, was committed before any model was
trained; `credit_case.py` implements it.

| Step | Command | Output |
| --- | --- | --- |
| Pilot (seed 7) | `make pilot` | `experiments/article/wp4/pilot_*.json`; writes `policy.json` once, refuses to overwrite it |
| Case (seed 42) | `make run` | `experiments/article/wp4/run_<UTC time>/` |
| Tests | `make tests` | runs the case once in a temporary folder and checks it |

## What a run folder holds

| File | Content |
| --- | --- |
| `ledger.jsonl` | the 16 evidence records |
| `store/sha256/<digest>` | every artefact the records cite: dataset, partition, models, monitoring reports |
| `policy.json`, `policies_archive/` | the case policy, under the identifier the records name |
| `keys/` | public keys of the engine and of the demonstration approver |
| `oscal_assessment_results_{complete,redacted}.json` | OSCAL 1.1.2 Assessment Results |
| `reexecution.json` | every decision re-executed from its record and the archived policy |
| `artefacts.json` | every artefact digest recomputed from its `off_chain_ref` |
| `recomputation.json` | every metric recomputed from the ledger and the store alone |
| `summary.json` | environment, metrics, decisions, acceptance checks |

## Keys

The engine signs with its own key (`compliance-policy-engine-v2`, created on
first use, not committed). The approver key in `keys/` is demonstration
material, committed so that the case regenerates under the same policy and
policy identifier; in use, the approver alone holds it.
