# Prototype execution and demonstration guide

> **Written on 2026-07-04, revised on 2026-10-03.** How to run the prototype's three components and what to expect from each, what each file is for, what the code does block by block, and the known problems with their remedies. The repository's `README.md` is the reproduction path; this guide is the longer companion to it.

---

## 0. The prototype in 30 seconds

The prototype has **three** runnable components, all under `prototype/`, plus a visual explorer that needs no installation:

| Component | Folder | What it proves | How it runs |
|---|---|---|---|
| **0. Explorer (nothing to install)** | `ledger_explorer/` | A complete, verifiable view of everything the other three components produce: it re-verifies in the browser the complete records embedded in the page, with a live operations room, compliance by AI Act article, Fabric latencies, the auditor's view (Art. 78) and a live tampering demonstration | **Double-click `LEDGER_EXPLORER.html`**: no Python and no Docker, offline, in a browser whose WebCrypto supports Ed25519 (current Chrome, Edge, Firefox and Safari) |
| **Compliance Oracle (simulator)** | `compliance_ledger_sim/` | The dissertation's central artefact: a SHA-256 chained, Ed25519 signed ledger, policy decisions, OSCAL, and tamper detection against an SQLite baseline | Pure Python, no Docker, seconds |
| **MultiFlow bridge** | `multiflow_bridge/` | Non-invasive integration with an existing MLOps platform (MultiFlow) over Kafka, with industrial datasets | Docker Compose, about 10 minutes end to end |
| **Fabric migration** | `fabric_migration/` | The same evidence model running on a two-organisation Hyperledger Fabric test network, with a latency measurement through the Gateway SDK | Docker, Go and fabric-samples (outside the vault, in `~/fabric-workspace`), 6 to 9 minutes if already installed |

> **Where to start:** with **Component 0 (the Explorer)**. It shows, with nothing installed, what the three runnable components produced, and the browser re-verifies the complete records embedded in the page. The seven chains hold 1,831 records; the long ones (the Steel run has 1,750) are represented in the page by a documented selection, and `python3 verify_delivery.py` verifies all 1,831. The explorer has a **▶ Presentation mode** (a guided tour of 14 steps) that walks through RQ1–RQ4. Components 1 to 3 come afterwards, for anyone who wants to watch the code generate the evidence.

The data flow is always the same: an **MLOps event** (JSON) comes in → the Oracle **validates it against policies** (precision, fairness, human approval, drift) → it produces a **23-field evidence record**, chained to the previous one by hash and signed with Ed25519 → the ledger can be **verified** (a change to a signed record is detected; removing records from the end is detected against a published anchor or count) and **exported as OSCAL** (the NIST format, schema-valid) with *selective disclosure* (AI Act Art. 78).

### Flow diagram (what connects to what)

```
                       MOMENT 2 (gate)                 MOMENT 3 (continuous)
  ┌──────────────┐   pipeline events       ┌─────────────────────────────────┐
  │ MLOps        │ ──────────────────────► │                                 │
  │ pipeline     │                         │      COMPLIANCE ORACLE          │
  │ (train/val.) │                         │  1. pseudonymise (HMAC v. N)    │
  └──────────────┘                         │  2. decide against policies.json│
  ┌──────────────┐    batches of 20 rows   │  3. build the 23-field record   │
  │ MultiFlow    │   ┌──────────────────┐  │  4. chain it (SHA-256)          │
  │ (stream      │──►│ bridge.py (Kafka)│─►│  5. sign it (Ed25519)           │
  │  replay)     │   │ drift_score      │  │                                 │
  └──────────────┘   └──────────────────┘  └───────────────┬─────────────────┘
                       topic phd_kafka                     │ append
                                                           ▼
                     ┌─────────────────────────────────────────────────┐
                     │  LEDGER (the evidence chain)                    │
                     │  simulator: ledger.json (1 node, ADR-003)       │
                     │  Fabric test network: 2 orgs, AND endorsement,  │
                     │             one Raft orderer (ADR-001)          │
                     └───────────────┬─────────────────────────────────┘
                       MOMENT 5      │ verify_chain() + query_by_requirement()
                       (audit)       ▼
                     ┌─────────────────────────────────────────────────┐
                     │  OSCAL 1.1.2 (NIST)                             │
                     │  full → the authority │ redacted → third parties│
                     │  (Art. 78, selective disclosure)                │
                     └─────────────────────────────────────────────────┘
```

### 0.0 Blockchain role by component

The dissertation is titled «**Blockchain** for Compliance, Auditability and Traceability…», and the demonstration has to make clear where the blockchain sits in each component, because the answer differs across the three:

- **In the simulator (`compliance_ledger_sim`)**, the blockchain is present as **a data structure and a set of cryptographic properties, without a network**: each record chains to the previous one by hash (`chain_hash = SHA-256(parent_hash ‖ record_hash)`), the same mechanism a blockchain uses to make changes detectable, and it is signed with Ed25519. This is the **ADR-003** decision: within DSR, implementing locally the properties the evaluation exercises (chaining, signature, tamper detection, verification with the public key alone) validates the design without the cost of operating a network. The simulator is a local signed hash-chain, not a network: it has no consensus, no replication and a single point of trust, and those are what the Fabric migration addresses.

- **In the Fabric migration (`fabric_migration`)**, the blockchain is a **permissioned network**: Hyperledger Fabric 2.5 with two organisations, each with its own MSP issued by its own Fabric CA, a shared channel, an ordering service (Raft) that cuts blocks, and an **AND endorsement policy**: a transaction updates the world state only with endorsements from Org1MSP and Org2MSP. A transaction that fails validation can still be recorded in a block, marked invalid. Choosing Fabric over Ethereum, Besu or Quorum is **ADR-001**: for this prototype a **permissioned** network was selected to control membership and identity governance (X.509 identities managed by the MSP), in line with the *QEL-ready* positioning against Reg. 2025/2531. ADR-001 records the alternatives and the reasons for the choice.

- **In the MultiFlow bridge**, the blockchain does not change. The bridge is the **event producer** that connects an existing MLOps platform to the evidence layer. It shows that the architecture observes existing pipelines without restructuring them (RQ3).

The principle running through all of it is **hash-on-chain**: what enters the chain are hashes, decisions and metadata, not the artefacts themselves (RQ2). When pseudonymisation is enabled, the configured identifiers are replaced in the source event before its payload digest is computed; the record keeps its selected fields and hashes, and does not keep every field of the source event or the pseudonymisation metadata. The dataset or model stays outside. `artifact_hash` is the SHA-256 digest of the event payload the pipeline sent, not of the dataset or model file: the prototype writes no resolvable reference to the off-chain object (`off_chain_ref`). This reduces what is exposed on chain; it does not remove the tension between the GDPR and immutability, because a pseudonym or a hash can still be personal data, and free-text fields and `artifact_id` are recorded as received.

### 0.1 When in the process each thing happens

The architecture follows the MLOps life cycle end to end. Each of the prototype's mechanisms has its own moment in the process, and it is worth making that explicit in the demonstration, because it answers the question «when does this run in real life?»:

| Moment in the life cycle | What happens | Where it lives in the prototype |
|---|---|---|
| **1. Configuration (once, by the Compliance Officer)** | The policies are defined (thresholds for precision, fairness, drift, human approval) and the organisation's keys are generated | `configs/policies.json` · `keys.py` (the issuer's Ed25519 key) · `pseudonymizer.py` (the HMAC v1 key) |
| **2. Training and validation pipeline (on every model iteration)** | Every relevant step emits an event. BEFORE any hashing, the personal fields are pseudonymised, the Oracle decides (approved or rejected) and writes the chained evidence | Scenarios 1 to 4 of `scenarios.py` (approved model, low precision, fairness, missing human approval), which correspond to the gate into production |
| **3. Post-deployment monitoring (streaming, around the clock)** | The model is already in production, each new batch of data is compared against the reference, and drift above the threshold produces an `escalated` event | Scenario 5 (`drift_detected`) and the whole **MultiFlow bridge** (`pipeline_stage: post_deploy_monitoring`): this is where Art. 72 (post-market monitoring) lives |
| **4. Serious incident (exceptional, with legal deadlines)** | Detection → a simulated reporting event → audit query: three chained events whose issuer timestamps can be compared with the Art. 73(2) deadline. Nothing is sent to an authority, and the timestamps are the issuer's own, not proof of receipt | `incident_demo.py` / `build_incident_scenario()` |
| **5. Audit (on request, months or years later)** | The authority or the auditor verifies the whole chain and queries by article, and the organisation exports OSCAL, full for the authority and redacted for third parties (Art. 78) | Scenario 6 (`audit_query`) · `verify_chain()` · `query_by_requirement()` · `oscal_exporter.py` |
| **6. Key rotation (periodic, by security policy)** | The HMAC key rotates without invalidating old records, because each pseudonym carries the version it was created with | `pseudonymizer.rotate_key()` |

In other words: steps 1 and 2 happen **before the model goes into production** (that is the compliance gate), step 3 is **continuous operation**, step 4 is **reactive, with a legal clock**, and step 5 is **retrospective**: the chain makes a later change to what was recorded at steps 2 to 4 detectable at step 5, provided the issuer's private key was kept and the final `chain_hash` is compared with a copy held elsewhere. The Fabric migration adds no new moment: it replicates steps 2 to 5 on a two-organisation test network, where the AND policy means that **one organisation's endorsement alone does not update the state**.

### 0.2 The evidence record: the 23 fields

Every event generates a record with exactly these fields (this is the «evidence model» of Chapter 4. The SQLite baseline keeps 9 columns, 8 of which have a counterpart here, so there are 15 additional fields of regulatory evidence):

| Group | Fields | What for |
|---|---|---|
| Identification | `evidence_id`, `scenario_id`, `event_type`, `artifact_id`, `artifact_type`, `pipeline_stage`, `timestamp` | Which artefact, at which pipeline stage, when |
| Decision | `decision`, `reason`, `rule_id` | The policy's verdict, the textual justification, and the label of the rule that fired, from a closed vocabulary |
| Measurement and policy | `metrics`, `policy_id`, `policy_hash` | The measured values the decision used, and the identifier and digest of the policy in force at the time |
| Regulatory coverage | `requirements_covered` | The list of AI Act articles the record evidences (it feeds the queries and the OSCAL prop) |
| Artefact provenance | `artifact_hash` | The SHA-256 fingerprint of the event payload (hash-on-chain) |
| Issuer identity | `issuer_id`, `issuer_pubkey_fingerprint`, `sig_alg`, `hash_alg` | Who issued it, with which key (the SHA-256 fingerprint of the public one) and with which algorithms. `sig_alg` is the post-quantum crypto-agility hook of Chapter 6 |
| Chain | `parent_hash`, `record_hash`, `issuer_signature`, `chain_hash` | The 4 cryptographic fields: the link to the previous record, the hash of the body, the Ed25519 signature (base64) and the chaining hash |

On Fabric, the chaincode adds two more at commit time: `submitter_msp` and `submitter_id`, the provenance of the NETWORK (who submitted the transaction), which is distinct from the issuer's (who signed the evidence).

### 0.3 The 6 canonical scenarios: expected decisions

To follow `simulator.py`'s output live (any deviation from this would be a bug):

| # | Scenario | Simulated violation | Decision | Rule that fires |
|---|---|---|---|---|
| 1 | `approved_model` | none (precision 0.89, DP diff 0.03, drift 0.04, human approval ✓) | **approved** | (no rule fired) |
| 2 | `low_precision_rejected` | precision 0.74 | **rejected** | `min_precision 0.80` (Art. 15) |
| 3 | `fairness_rejected` | demographic disparity 0.09 | **rejected** | `max_demographic_parity_diff 0.05` (Art. 10(2)(f)–(g); the record carries the label `Art.10(3)`) |
| 4 | `missing_human_approval_rejected` | high risk without human approval | **rejected** | `require_human_approval` (Art. 14) |
| 5 | `drift_detected` | drift 0.22 in production | **escalated** | `drift_alert_threshold 0.15` (Art. 72) |
| 6 | `audit_query` | (an audit query) | **verified** | (Art. 12) — records that the query was made (`audit.query_recorded`); the chain check itself is `verify_chain()` |

### 0.4 Reference figures (checked against the artefacts)

| Figure | Value | Source |
|---|---|---|
| Median latency per event, Oracle against baseline | **6.47 ms against 1.38 ms**, paired median difference **+5.08 ms**, with the Oracle slower in 10 rounds out of 10. These are medians of the ten round medians, and 5.03–5.14 ms is the interquartile interval of those round medians; this run did not preserve the individual observations | `latency_protocol_20260914T160731Z.json`, under `LATENCY_PROTOCOL_2026-09-14.md` |
| Repeatability of the measurement | A second run under the same protocol: **+5.11 ms**, also 10 out of 10 (5.00–5.19 ms between rounds). This run preserves the 2,000 paired event observations: their median difference is 5.12 ms and their interquartile interval 3.21–7.30 ms (minimum −3.98, maximum +23.88). These event-level statistics are a different estimator from the median of the ten round medians | `latency_protocol_20260914T200554Z.json` |
| Evidence fields | **23 against 9** (15 additional, 8 with a counterpart in the baseline) | `ledger.json` · `baseline_logger.py` |
| Tamper detection | Oracle: **3 signals** (`record_hash mismatch, invalid signature, chain_hash mismatch`); baseline: **0** («row count only») | the same (`tamper_detection`) |
| Simulator load test | **500 events at 110 events/s**, 9.1 ms mean, P95 16.1 ms | `load_test_20260610T173644Z.json` |
| Sensitivity | **45 combinations** (5 precision × 3 fairness × 3 drift), rejection rate 16.7% to 83.3% | `sensitivity_analysis_…161348Z.json` |
| Tests | **98/98 pytest** (simulator) and **10 go test** (chaincode) | `tests/` · `chaincode/` |
| MultiFlow, real data | **29 events** (12 approved, 17 escalated), chain 29/29 | `multiflow_run_real/` |
| MultiFlow, load | **1,750 events** (94 and 1,656), chain 1750/1750 | `multiflow_run_steel/` |
| Fabric VerifyChain (30 records) | **about 17 ms** on LevelDB (median 16.9, P95 18.4) · about 27 ms on CouchDB | `fabric_latency_gateway_leveldb.json` / `_couchdb.json` |
| Fabric durable commit | **about 2,030 ms** (BatchTimeout = 2 s) | the same |
| OSCAL | **18/18 schema-valid exports** (NIST 1.1.2) | `validate_oscal_schema.py` |

> Beware of one old figure: «about 11 ms» for VerifyChain circulates in earlier files, and it was measured on shorter chains (verification scales with the number of signatures). The citable figure is about 17 ms over 30 records.

### 0.5 What each demonstration answers (RQ ↔ demo)

| Research question | Where it shows in the demonstration |
|---|---|
| **RQ1**: turning AI Act requirements into verifiable evidence | The table in §0.3: each violation fires a rule anchored in an article. `requirements_covered` on every record, and `query_by_requirement("Art.15")` |
| **RQ2**: end-to-end integrity while minimising personal data on chain | `pseudonymizer.py` (versioned HMAC of the configured fields, before hashing), hash-on-chain (§0.0) and the tampering demonstration |
| **RQ3**: compliance-as-code without restructuring pipelines | The MultiFlow bridge (the platform's repository untouched, §2) and an editable `policies.json` (see the example in §3.A) |
| **RQ4**: technical feasibility and acceptable overhead | The figures in §0.4: +5.08 ms per event in the simulator, measured under a paired protocol, about 17 ms for a `VerifyChain` query and about 2 s to commit on the Fabric test network, where the commit time is dominated by ordering (the 2 s batch timeout) |

---
## 1. Before running: checklist and warnings

### 1.1 Preparation

1. **Open Docker Desktop** and wait until `docker info` succeeds.
2. Confirm that the 98 tests pass (30 seconds, and it destroys nothing):
   ```bash
   cd prototype/compliance_ledger_sim
   python3 -m pytest tests/ -q
   ```
3. Confirm the ledger's canonical state: `ledger.json` should hold **6 records** (`python3 verify_delivery.py`).
4. For the Fabric component: start Docker and run `bash deploy/01_up_and_deploy.sh` first (3 to 5 minutes). The network stays up for the submission and the verification.

### 1.2 Commands that overwrite published evidence

- **`load_test.py`**: it calls `reset_ledger()`, deleting the 6 canonical records and writing 500 synthetic ones. If it happens by mistake, restore `ledger.json` from the delivered copy of the folder (in the author's repository, `git checkout -- prototype/compliance_ledger_sim/ledger.json`).
- **`sensitivity.py`**: it also resets during the run (restoring at the end, though a Ctrl-C part way through leaves the ledger in an intermediate state, recovered the same way). Even a complete run leaves six new records, not the published ones. Until 2026-09-17 the restore built the policy by hand, with four of the five keys in `configs/policies.json`, and because `policy_id` is derived from the content, the restored ledger named a policy other than the `pol-c3d1fc49f36e` of Appendix A. Fixed: the restore now lets the Oracle reread the policy file.
- **`simulator.py`, `compare_oracle_vs_baseline.py`, `incident_demo.py`**, and on the Fabric side **`gateway/gen_records.py`** and **`deploy/02_submit_and_measure.py`**: each writes new records over a published chain (the canonical ledger, the incident run, `gateway/records.json`, `fabric_run/_gen_ledger.json`). Run them in a copy; `verify_delivery.py` reports any chain that no longer matches the published one.
- **`docker system prune`**: a last resort only, because it deletes images that take a long time to pull again.

### 1.3 Known fragilities and their remedies

| Symptom | Cause | Recovery |
|---|---|---|
| `docker build` hanging, 0 bytes of progress (Fabric) | A known Docker Desktop bug («broken pipe» on the proxy socket) | `docker desktop stop`, wait 10 s, `docker desktop start`, wait 30 s. The menu's «Restart» is **not** enough. |
| `NoBrokersAvailable` in the first minute or so (MultiFlow) | Kafka is still starting | Normal. The bridge retries automatically for up to 150 s. |
| The first Fabric invoke takes 3 to 5 s | Cold start of the CCaaS container | Normal, and the scripts exclude the warm-up from the measurements. |
| `gateway_measure.go` fails with «User1 not found» | The network was brought up without `-ca` | Bring it up again: `./network.sh down` and then `bash deploy/01_up_and_deploy.sh` |
| An invoke fails part way through the measurement | The ordering service or the peer is momentarily slow | `CONTINUE=1 python3 deploy/02_submit_and_measure.py 30` resumes where it stopped |

### 1.4 Fixes already applied (2026-07-04)

- The simulator's `requirements.txt` now declares `jsonschema` and `regex` (they were needed by `validate_oscal_schema.py` and by 3 of the 98 tests, but were not listed. On a clean Mac the OSCAL validation would fail with an `ImportError`).
- `sensitivity.py` said «27 combinations» in its docstring and in its print, but the real grid is 5×3×3 = **45** (confirmed in the results JSON and in what the dissertation cites). Fixed, so that the screen and the dissertation agree.

### 1.5 Known imperfections

- **Two items from earlier versions of this list are resolved and no longer apply.** The prints no longer mix Portuguese and English, and `paths.py` no longer assumes the vault's layout: it resolves the output directory by markers and honours `EXPERIMENTS_DIR`.
- **Ed25519 demonstration keys, unencrypted at rest** (`keys/*.pem`, `NoEncryption`). Assumed in the dissertation: a real KMS or HSM is future work, and the demonstration key is identified as such in the README.
- **`gateway_measure.go` looks for the test network under `~/fabric-workspace/fabric-samples/`**, which is where it usually sits. Anyone who keeps it elsewhere sets `FABRIC_CRYPTO_PATH`, and the result is written next to the records file that was read, or into `EXPERIMENTS_DIR` if that is set.
- **OSCAL redaction (Art. 78) hides free text but preserves hashes**: that is by design, because the hashes link each finding to its record. A digest is not an anonymous value: someone holding a candidate payload can confirm a match, so whether to disclose it is for the disclosing party to assess.
- **A single orderer (one-node Raft)** and **Org1 and Org2 on the same machine**, limitations acknowledged in Chapters 5 and 6. Several orderers on one laptop share one machine, one disk and one administrator, so they would not test the crash or fault tolerance that multiple orderers exist for; that evaluation needs separate machines and is left as future work.

---

## 2. The MultiFlow integration: a compose override, no change to the platform

MultiFlow's `docker-compose.yml` uses `confluentinc/cp-kafka:latest` and `cp-zookeeper:latest`, with the broker configured through `KAFKA_ZOOKEEPER_CONNECT`. Confluent Platform 8.0 (Kafka 4.0) removed ZooKeeper support, so with the images `:latest` resolves to today the broker stops at start-up and the platform does not come up from a fresh clone.

The integration does not edit the MultiFlow repository. It places one additional file, `docker-compose.override.yml`, in the root of the clone. Docker Compose merges it with the platform's compose file; the override pins the two images to **Confluent Platform 7.6.1**, the version these experiments were run with, and adds the bridge service:

```yaml
services:
  zookeeper:
    image: confluentinc/cp-zookeeper:7.6.1
  kafka:
    image: confluentinc/cp-kafka:7.6.1
  compliance-bridge:
    # consumes the phd_kafka topic alongside the Faust apps,
    # in its own consumer group (compliance-bridge)
```

No file of the MultiFlow repository is modified, and removing the override restores the original behaviour. The bridge reads the same Kafka topic the Faust apps consume, aggregates batches of 20 rows, computes an illustrative drift indicator and records each batch as signed, chained evidence. The scripts clone the platform at the commit recorded with the published runs (`MULTIFLOW_COMMIT.txt`).

Two runs on the platform's own datasets are published: Muvu_January followed by Muvu_March, 29 records, chain 29/29: 12 approved and 7 escalated in the January segment, followed by 10 escalated in the March segment; and Steel_Industry, 35,040 rows as a load test, 1,750 events, chain 1,750/1,750. The indicator measures a change in the column means between the two months. It does not establish the physical cause of the difference, and the runs are not a validation of the indicator as a drift detector. The artefacts are under `experiments/runs/multiflow_run_real` and `multiflow_run_steel`.

---

## 3. Step by step for running each component

### 3.A: Compliance Oracle (the simulator) · no Docker · about 2 minutes

The recommended sequence. **Run it in a copy of the folder** (`cp -R Project Project-work`): steps 2, 3 and 5 write NEW records over the published canonical and incident ledgers, valid and signed with the same demonstration key. Afterwards `python3 verify_delivery.py` reports those chains as NOT PUBLISHED, which is how a reader tells a regenerated chain from the evidence the dissertation reports.

```bash
cd prototype/compliance_ledger_sim

# 1. Tests: 98/98 in under 2 s
python3 -m pytest tests/ -q

# 2. Run the 6 canonical scenarios (writes ledger.json again: the same 6 scenarios,
#    but new evidence ids, timestamps and hashes, so it is no longer the published chain)
#    MOMENT IN THE PROCESS: steps 2, 3 and 5 of the cycle (§0.1). Scenarios 1-4 are
#    the pre-production compliance gate, the 5th is post-deployment monitoring,
#    and the 6th is the audit
python3 simulator.py
#    → prints scenario, decision and latency per event
#    → exports oracle_metrics_*.csv and oracle_summary_*.json to experiments/

# 3. The dissertation's key comparison: Oracle against the SQLite baseline
#    MOMENT IN THE PROCESS: it simulates tampering AFTER the record was written
#    (between moment 2 and the audit of moment 5), which is the threat the chain answers
python3 compare_oracle_vs_baseline.py
#    → runs the 6 scenarios on both systems
#    → TAMPERS with one record in each: the Oracle detects it (3 signals), this baseline does not
#    → restores the state and exports comparison_*.json
#    NOTE: this script demonstrates tamper DETECTION, and its times are exploratory:
#    six events in a single run, with no warm-up and no repetition. On re-measurement
#    on 2026-09-14 the sign of the difference flipped. The citable latency comes from
#    the paired protocol: python3 bench_latency.py 10 200

# 4. Export OSCAL (full and Art. 78 redacted) and validate against the NIST schema
#    MOMENT IN THE PROCESS: moment 5 (the audit). This is what the organisation hands
#    to the authority (full) or to third parties (redacted) when asked
python3 oscal_exporter.py
python3 validate_oscal_schema.py
#    → [PASS] on every oscal_*.json

# 5. (Optional) The Art. 73 serious-incident scenario: it uses its OWN ledger, not the
#    canonical one, and replaces the published one in experiments/runs/incident_run/
#    MOMENT IN THE PROCESS: moment 4 (an incident; the report to the authority is simulated)
python3 incident_demo.py
#    → 3 events (detection → simulated report → audit query), chain 3/3, OSCAL
```

**Expected output:** in the output of step 3 the same change goes unnoticed by this baseline, which checks the row count only (`tamper_detected: false`, «row count only»), and is reported by the Oracle with the index of the altered record and 3 signals (`record_hash mismatch, invalid signature, chain_hash mismatch`). The comparison is with this baseline, not with databases in general: a database with its own integrity controls would behave differently.

**Example: changing the policy (RQ3).** In the working copy, edit `configs/policies.json`, raising `min_precision` from `0.80` to `0.90`, and run `python3 simulator.py` again. Scenario 1, which was `approved` with a precision of 0.89, becomes `rejected` with an updated reason, and the records carry a different `policy_id`, because the identifier is derived from the file's content. The thresholds are configuration read at run time, not logic embedded in the code. Restore `0.80` afterwards.

### 3.B: MultiFlow bridge · Docker · about 10 minutes

> **Moment in the process:** this is **moment 3 of the cycle (§0.1), continuous post-deployment monitoring**. In operation the bridge would stay attached beside the MLOps platform. The run replays in minutes the platform's Muvu datasets for January and March.

```bash
# Prerequisite: Docker Desktop running.

# EVERYTHING in one command: it clones MultiFlow at the pinned commit (into
# ~/Desktop/multiflow unless MULTIFLOW says otherwise), installs the override, brings
# up Kafka, Zookeeper, Kafdrop and the bridge, injects 100 test messages, verifies,
# and archives the run. Without EXPERIMENTS_DIR it archives over the published
# multiflow_run and REPLACES it, so point it elsewhere:
export EXPERIMENTS_DIR="$(pwd)/results/demo" && mkdir -p "$EXPERIMENTS_DIR/runs"
bash prototype/multiflow_bridge/run_multiflow_proof.sh

# Then, with the containers up: the platform's industrial datasets (Muvu, January then March):
bash prototype/multiflow_bridge/inject_real_datasets.sh
#    → 29 records: 12 approved and 7 escalated in the January segment, then 10 escalated in March

# To explore visually: Kafdrop at http://localhost:19000
#    → the "compliance-bridge" consumer group appears beside MultiFlow's Faust apps

# At the end (the override needs PROTOTYPE_DIR even to shut down):
(cd "${MULTIFLOW:-$HOME/Desktop/multiflow}" && \
  PROTOTYPE_DIR="$OLDPWD/prototype" docker compose down)
```

**Expected output:** the bridge's log (`[bridge] batch=N drift_score=X decision=Y chain_hash=…`) and Kafdrop, where the bridge appears as one more consumer group of the same topic.

### 3.C: Fabric migration · Docker and Go · 6 to 9 minutes (with the initial setup already done)

> **Moment in the process:** this is not a new moment in the cycle. It is the **target infrastructure** where moments 2 to 5 of §0.1 would run. Step 1 (bringing up the network and registering the issuer) corresponds to **moment 1, institutional configuration**: this is where the two organisations establish the channel and the key governance. Steps 3 and 4 are moments 2 and 5 on Fabric, where a record enters the state only with both organisations' endorsements.

```bash
cd prototype/fabric_migration

# (First time on a new Mac only: bash 00_setup_fabric.sh, 10-15 min, downloads about 2 GB)

# 1. Bring up the two-org network (with Fabric CA) and deploy the chaincode as CCaaS: 3-5 min
bash deploy/01_up_and_deploy.sh
#    → channel "compliancechannel", endorsement policy AND('Org1MSP.peer','Org2MSP.peer')
#    → 2 CCaaS containers: peer0org1_compliance_ccaas and peer0org2_compliance_ccaas

# 2. Chaincode tests with NO network (interop proved against real simulator records)
cd chaincode && go test ./... && cd ..

# 3. Submit and measure. The two methods below are ALTERNATIVES on a freshly
#    deployed, empty channel: each generates its own chain from the genesis, and
#    a second chain does not continue the head the first one left, so its records
#    are refused (parent_hash mismatch). To try the other method, repeat step 1.

# 3a. Fabric Gateway SDK over a persistent gRPC connection (the method behind
#     the figures the dissertation cites)
cd gateway
python3 gen_records.py 30          # rewrites gateway/records.json (a published chain)
go run gateway_measure.go records.json pubkey.txt
#    → a VerifyChain query in about 17 ms (30 records, LevelDB); durable commit
#      in about 2030 ms (BatchTimeout=2s). A new run gives its own timings.
#    → outputs in experiments/runs/fabric_run/

# 3b. Or the `peer` CLI (each call pays about 74 ms of process start-up)
python3 deploy/02_submit_and_measure.py 30       # about 2 min; rewrites fabric_run/_gen_ledger.json

# 4. Shut down. `network.sh down` removes the test network's containers,
#    volumes and generated identities: use it only on a network you created
#    for this purpose.
cd ~/fabric-workspace/fabric-samples/test-network && ./network.sh down
```

**Expected output:** records **signed in Python** are verified **in Go inside Fabric** (the same canonical serialisation over the domain of the evidence body). And the reading of RQ4: the time to durable evidence is dominated by ordering (about 2 s, the batch timeout, a configuration parameter), while a `VerifyChain` query over 30 records takes about 17 ms.

> A note on figures: the «about 11 ms» that appears in older files came from measurements on shorter chains, and `VerifyChain` re-verifies every record's signature, so it scales with the size of the chain. The reference measurement (30 records, controlled) gives about 17 ms on LevelDB and about 27 ms on CouchDB, and that is what the dissertation cites.

### 3.D: The archived runs

Nothing the dissertation claims depends on running the components again: **every run it cites is archived with its provenance** under `experiments/`:

| Component | Archived evidence |
|---|---|
| The simulator (unlikely, it has no external dependencies) | `latency_protocol_20260914T160731Z.json` and `latency_protocol_20260914T200554Z.json` (the two runs under the paired protocol, which are the ones cited in Chapter 5) and `RESULTS_SUMMARY.md` |
| MultiFlow (Docker, network, clone) | `multiflow_run_real/`, with `ledger.json` (29 events), `bridge_log.txt` (12 approved and 7 escalated in the January segment, then 10 escalated in the March segment), `oscal_multiflow.json`, `MULTIFLOW_COMMIT.txt` and `RUN_TIMESTAMP.txt` (provenance) |
| Fabric (Docker Desktop, broken pipe and so on) | `fabric_run/fabric_latency_gateway_leveldb.json` and `_couchdb.json` (the measurements cited for RQ4) and, offline, `cd chaincode && go test ./...`: the 10 tests run with NO network in seconds, including one that creates the contract as the executable does at start-up |

The chaincode's `go test` needs no Docker: it validates Python signatures in Go against records the simulator produced.

---

## 4. What each file is for (the full explanation)

### 4.1 `compliance_ledger_sim/`: the Oracle

| File | Role |
|---|---|
| `simulator.py` | The core. The `ComplianceOracle` class validates events against policies, builds 23-field records, chains them by hash, signs with Ed25519, verifies the chain, answers queries and exports metrics. Its entry point runs the 6 scenarios. |
| `keys.py` | Persistent Ed25519 keys. `load_or_create_key()` generates or loads a PEM under `keys/`, and `public_key_fingerprint()` gives the SHA-256 of the public key (the `issuer_pubkey_fingerprint` field of every record). |
| `paths.py` | Resolution of the output directory, by markers walking up the tree: in the vault, a folder holding `06_dados/` and `04_projeto/` leads to the `experiments` folder inside the first of them; in the folder delivered with the dissertation, a folder holding `prototype/` and `experiments/` side by side leads to that `experiments/`; with neither, it falls back to an `experiments/` next to the code. The `EXPERIMENTS_DIR` environment variable overrides all of it. |
| `scenarios.py` | The single source of the scenarios. `build_scenarios()` gives the 6 canonical ones and `build_incident_scenario()` the 3 events of Art. 73. They are shared by the Oracle and the baseline, so that the comparison is fair. |
| `baseline_logger.py` | The counterfactual: a centralised SQLite log with the SAME decision logic but no chain and no signature. `tamper()` alters a record, and `check_integrity()` counts rows and nothing else. |
| `pseudonymizer.py` | HMAC-SHA256 with a versioned, rotatable organisational key (EDPB 02/2025). `apply_to_event()` replaces sensitive fields with `{pseudonym, key_version, org_id, alg}` before `artifact_hash` is computed. Note: the record's canonical body selects a fixed set of fields and does **not** carry that object, so `key_version` never reaches the ledger. |
| `oscal_exporter.py` | Ledger → OSCAL Assessment Results 1.1.2 (NIST). One observation and one finding per record; AI Act articles become `props` (`aia-15`, `aia-10-3` and so on); the finding's objective follows the rule that fired the decision, with the `objective-basis` property recording which; the `redacted` mode hides free text and preserves hashes (Art. 78). The UUIDs are deterministic (uuid5). |
| `sensitivity.py` | A grid of 45 threshold combinations (precision × fairness × drift). It runs the 6 scenarios per combination and exports CSV and JSON, restoring the ledger at the end. |
| `load_test.py` | 500 synthetic events, measuring throughput and latency. **Destructive** (it resets the ledger). |
| `compare_oracle_vs_baseline.py` | The reference experiment of Chapter 5: it runs both systems side by side, times them, tampers and measures detection. It produces the `comparison_*.json`, which the dissertation has reported as exploratory since 2026-09-14: the citable measurement is the paired protocol's, in `bench_latency.py`. |
| `validate_oscal_schema.py` | Validates the exports against the official NIST 1.1.2 schema (vendored in `tests/fixtures/`), with support for Unicode `\p{}` patterns through the `regex` module. It fails when it finds no document or an unreadable one, and `--expect 18` also fails on a different count. |
| `verify_delivery.py` | Re-verifies the seven delivered chains, 1,831 records, against a declared inventory and without writing anything: it recomputes each record's `record_hash`, its link to the previous record and its Ed25519 signature, reading the public key file and nothing else. A chain that is missing, empty or short fails, and so does a valid chain whose final `chain_hash` differs from the published one (NOT PUBLISHED: it was regenerated in that folder). It is the entry point for anyone assessing the work without standing up Kafka or Fabric (`make verify`). |
| `incident_demo.py` | The Art. 73 demonstration, on a separate ledger (`experiments/runs/incident_run/`). The report to the authority is a simulated event. |
| `configs/policies.json` | The configurable thresholds: `min_precision 0.80`, `max_demographic_parity_diff 0.05`, `drift_alert_threshold 0.15`, and human approval mandatory for high risk. `require_hash_verification` is declared but not read by the code (removing it would change the `policy_id` of the published records). |
| `ledger.json` | The reference ledger: 6 records, chain intact. |
| `tests/` (98 tests) | simulator (decisions, chain, the 3 tampering signals, queries, input validation), pseudonymizer (determinism, rotation, replay), OSCAL (structure, redaction, recomputed chain_valid, the finding's objective, signatures reported separately), 3 NIST schema-valid tests, plus `test_fronteiras.py`, the matrix of 16 cases over the input domain that generates the `testdata_fronteiras.json` re-verified on the Go side; `test_redaction_boundary.py`, which walks the redacted OSCAL document field by field looking for free text and derivable identifiers; and `test_concorrencia.py`, which launches two processes writing the ledger at once and requires that no record be lost. |

### 4.2 `multiflow_bridge/`: the bridge

| File | Role |
|---|---|
| `bridge.py` | A Kafka consumer of the `phd_kafka` topic (the same one the Faust apps read). The first 20 rows form the statistical reference, and each subsequent batch of 20 gives a mean z-score against that reference (`drift_score`, saturated at 1.0), then a canonical event, then `oracle.process_mlops_event()`. |
| `docker-compose.override.yml` | The piece that makes it non-invasive: merged automatically with MultiFlow's original compose, it pins Confluent Platform to 7.6.1 (see §2) and adds the `compliance-bridge` service on the same Docker network, with the ledger mounted at `./compliance_out`. |
| `Dockerfile` | The bridge's image: `python:3.11-slim` with `kafka-python` and `cryptography`, copying the simulator into the container. |
| `verify_output.py` | Runs INSIDE the container: it recomputes every hash and signature of the ledger produced, prints decision statistics and exports OSCAL, full and redacted. |
| `run_multiflow_proof.sh` | The automatic end-to-end proof in 7 steps (clone → override → bring up → inject → process → verify → archive the run with a timestamp and MultiFlow's commit SHA). |
| `inject_real_datasets.sh` | Replays Muvu_January and Muvu_March (MultiFlow's industrial datasets) into a clean ledger. |
| `../delivery_paths.sh` | Resolves `PROTOTYPE_DIR` and `EXPERIMENTS_DIR` from the position of the file itself, so that the scripts run both in the vault and in the delivered folder, on any machine. `EXPERIMENTS_DIR` in the environment overrides it. It also provides `run_dir`, which finds a run's folder whether it sits directly under `experiments/` (the vault) or in the `runs/` drawer (the delivery). |
| `test_bridge.py` | 4 tests with no Kafka: a simulated stream with drift in the second half gives 4 events, an intact chain and the expected decisions; unusable messages (not an object, not finite numbers, wrong column count) are skipped and counted, not fatal. |
| `INTEGRATION_README.md` | The manual walkthrough, troubleshooting and provenance. |

### 4.3 `fabric_migration/`: the Fabric test network

| File | Role |
|---|---|
| `chaincode/compliance_chaincode.go` | The Go contract. `RegisterIssuer` (governance: only Org1MSP registers keys), `SubmitEvidence` (verifies Ed25519, recomputes the hashes and stamps the submitter's Fabric identity), `VerifyChain` (re-verifies everything from genesis), `QueryByRequirement` and `GetEvidence` (both return the stored JSON). `main()` is dual-mode: a CCaaS server, or the normal mode for `go test`. |
| `chaincode/compliance_chaincode_test.go` | 10 tests: one creates the contract with `contractapi.NewChaincode`, as the executable does at start-up; the other 9 use a MockStub to validate interoperability against records the Python simulator produced, including the 3 defects fixed during the migration (canonical serialisation, fingerprint against key, lexical ordering). A missing fixture fails the test instead of skipping it. |
| `chaincode/Dockerfile` and `go.mod` | A multistage build (go 1.21, vendored, static binary) for CCaaS. |
| `deploy/01_up_and_deploy.sh` | Brings up the test network (2 orgs, Fabric CA, channel `compliancechannel`) and deploys as CCaaS with the AND policy, working around the «broken pipe» of the peer-managed build. |
| `deploy/02_submit_and_measure.py` | Generates N records with the Python simulator, registers the issuer key (`RegisterIssuer`), submits each record through the `peer` CLI with both organisations endorsing, measures, and writes JSON stating that each call includes about 74 ms of CLI start-up. |
| `gateway/gateway_measure.go` | The Fabric Gateway SDK over a persistent gRPC connection. It times a read-only `VerifyChain` query (`EvaluateTransaction`: client, transport, Gateway and execution on one peer, no ordering) separately from the durable commit (`SubmitTransaction`). The source of the RQ4 figures. In the published JSON the query timings are under the historical keys `evaluate_endorse_*`. |
| `gateway/gen_records.py` | Generates the signed records and the public key for the Go client. |
| `interop/canonical_interop.go` and `test_interop.py` | A standalone proof that the Go serialisation is byte-identical to Python's `json.dumps` over 6 vectors (HTML, accents, emoji from the astral plane, DEL 0x7F, real bodies). |
| `00_setup_fabric.sh` | One-off installation of Fabric 2.5.10 and CA 1.5.13 into `~/fabric-workspace`. |
| `MIGRATION_LOG.md` | The execution log of the migration (gates A to C, defects, decisions, measurements). |

---

## 5. What the code does, in depth

> A block-by-block explanation with line references. For the last detail, the code has docstrings and `MIGRATION_LOG.md` documents every decision on the Fabric side.

### 5.1 The life cycle of an event in the Oracle (`simulator.py`)

**Canonical serialisation** (`canonical_json`, l. 240-250). Everything that is hashed or signed goes through `json.dumps(payload, sort_keys=True, separators=(",",":"), ensure_ascii=True)`. That guarantees that the same dictionary always produces the same bytes. Without it, hashes and signatures would not be reproducible, nor verifiable in Go (see §5.4).

**Input contract** (`_validate_input`, l. 385-475). Before any hashing, the event is checked against the domain the model declares: identity fields as text, metrics numeric and finite, and the whole event within the domain of valid Unicode scalar values. The boundary exists because `artifact_hash` is computed over the entire event: a value outside the domain either made the Oracle crash before there was a decision, or was signed in Python and reassembled differently in Go. The matrix in `test_fronteiras.py` walks this domain, and the Go side re-verifies the records it produces.

**Decision** (`_validate_compliance`, l. 477-541). The first applicable rule determines the decision, with the thresholds read from `configs/policies.json`: malformed input is rejected; serious-incident events are escalated; the precision, parity and human-approval gates may reject; drift above the threshold escalates; audit queries are recorded as `verified`; otherwise the decision is `approved`. The textual reason always accompanies the decision.

**Regulatory coverage** (`_requirement_coverage`, l. 543-561). It maps the fields present in the event to AI Act articles: human approval → Art. 14; performance metrics → Art. 15; demographic parity → the label `Art.10(3)` (the rule itself rests on Art. 10(2)(f)–(g)); drift → Art. 72; incident → Art. 73; the record itself → Art. 12. It is this list that feeds `QueryByRequirement` and the OSCAL props.

**Building the record** (`process_mlops_event`, l. 567-656). The cryptographic sequence, step by step:
1. Read the last record in the ledger and take its `chain_hash`, which becomes the new record's `parent_hash` (or 64 zeros, the genesis hash, if the ledger is empty).
2. If a pseudonymiser is present, replace the configured identifier fields BEFORE any hashing. Pseudonymisation is optional and covers only those fields: free text and `artifact_id` can still identify someone and need their own data minimisation.
3. `artifact_hash` = SHA-256 of the canonical event payload (not of the dataset or model file).
4. Decide (`approved`, `rejected` or `escalated`) and compute the article coverage.
5. Assemble the `body`, 20 fields, still WITHOUT the three derived ones.
6. `record_hash` = SHA-256 of the canonical body.
7. `issuer_signature` = Ed25519(canonical body), in base64.
8. `chain_hash` = SHA-256(`parent_hash` ‖ `record_hash`). This is what chains.
9. Add the derived fields to the body, giving a 23-field record, and append it to the ledger.

**Verification** (`verify_chain`, l. 662-714). For each record, four checks: does `parent_hash` match the previous `chain_hash`? Does the recomputed `record_hash` match? Does the Ed25519 signature verify against the body? Does the recomputed `chain_hash` match? They are not independent experiments: all four are computed over the same body and stored hashes, and all assume that the issuer's key and the final `chain_hash` are trusted. A change to a field of the signed body breaks at least one of them; removing records from the end is seen only against an anchor kept elsewhere. The SQLite baseline of this comparison has no equivalent (`check_integrity` in `baseline_logger.py`, l. 146-157, returns `tamper_detected: false, method: "row count only"`).

### 5.2 Pseudonymisation (`pseudonymizer.py`)

HMAC-SHA256 with a 32-byte secret organisational key, **versioned**: `pseudonym.{org}.v1.key`, `v2.key` and so on, with a `versions.json` of metadata. The same identifier, organisation and key version yield the same pseudonym, and rotating the key changes the value (intra-organisation linkability, which auditing needs). Different organisations yield different pseudonyms. That is divergence of values, not absence of linkage: `artifact_id` stays constant across a rotation and can serve as a bridge. `rotate_key()` creates a new version without invalidating old records, and `key_version` travels with the pseudonym **in the object the module returns**, and reproducing a historical pseudonym requires the module, the identifier and the withdrawn secret, so the record alone is not enough. Choosing HMAC-SHA256 is compatible with EDPB Guidelines 02/2025, which name HMACs among other possible measures (§33) without imposing an algorithm or a minimum. This is the answer to RQ2: the layer acts on a fixed list of field names, so an identifier placed outside that list goes in clear.

### 5.3 The MultiFlow bridge (`bridge.py`)

The design is deliberately simple: the **first 20 rows** of the stream form the reference (mean and standard deviation per column), and each subsequent batch of 20 is compared by a **mean z-score, normalised by 3 and saturated at 1.0**, a drift indicator documented as illustrative (the dissertation does not claim it is a state-of-the-art drift detector. The point is the *evidence* of monitoring, not the detector). Each batch becomes a canonical event (`event_type: stream_batch_monitoring`, `pipeline_stage: post_deploy_monitoring`, `risk_level: high`) submitted to the SAME `process_mlops_event()` of §5.1: the bridge has no evidence logic of its own, and reuses the whole Oracle inside the container.

### 5.4 The Fabric chaincode (`compliance_chaincode.go`)

The contract repeats the simulator's verification and adds issuer governance and network provenance:

- **Issuer governance** (`RegisterIssuer`): only Org1 (the registering MSP) may register Ed25519 public keys, and the key lives in on-chain state under `issuer~{fingerprint}`. `SubmitEvidence` rejects records from unregistered issuers. The simulator has no registry: it verifies against the public key file it is given.
- **Verification on submit** (`SubmitEvidence`): before persisting, the chaincode recomputes the body's canonical serialisation, verifies the Ed25519 signature against the REGISTERED key (not against the one the submitter claims), recomputes `record_hash` and `chain_hash`, and compares `parent_hash` against the head kept in `meta~head` (an O(1) pointer; because every submission reads and writes the head, two concurrent submissions conflict at validation and only one is committed). Only then does it write, stamping `SubmitterMSP` and `SubmitterID`, the network's provenance, which the simulator does not have.
- **Interoperable canonical serialisation** (`canonicalJSON` and `asciiEscape`): Go by default escapes HTML and leaves non-ASCII literal, exactly the inverse of Python's `json.dumps(ensure_ascii=True)`. The fix has two axes: `SetEscapeHTML(false)`, and a post-processing step that turns every rune above 0x7E (including DEL 0x7F and UTF-16 surrogate pairs for emoji) into `\uXXXX`. It is byte-identical to Python over the domain of the records, checked by `interop/test_interop.py` on six vectors, three of them bodies of published records. Without these fixes, records containing the affected HTML or non-ASCII characters would produce different canonical bytes and fail signature verification in Go: this was **defect #1** of the migration, the only one of the three that concerns serialisation.
- **Sequence keys** (`ev%012d`): Fabric's `GetStateByRange` returns in lexical order of the key rather than by insertion order, and the zero-padded keys make `VerifyChain` walk the chain in order (**defect #3**, ordering). And `issuer_pubkey_fingerprint` is the SHA-256 of the key, not the key, and `ed25519.Verify` needs the raw key kept in the on-chain registry (**defect #2**, fingerprint against key). All three appeared only when the chaincode was confronted with records the simulator had produced, and the Go tests cover them.

### 5.5 The two latency measurements (and why there are two)

`02_submit_and_measure.py` measures through the `peer` CLI, but every invocation pays about 74 ms of process start-up, so the JSON explicitly declares itself an **upper bound**. `gateway_measure.go` removes that overhead with a persistent gRPC connection (the Fabric Gateway SDK) and times two things the CLI mixes: a **read-only `VerifyChain` query** (`EvaluateTransaction`: about 17 ms for 30 records on LevelDB, re-verifying 30 Ed25519 signatures; the timing includes client, transport, Gateway and execution on one peer, and excludes ordering and commit) and the **durable commit** (`SubmitTransaction`: about 2,030 ms, dominated by the orderer's `BatchTimeout=2s`). The query is not the endorsement of a write, and the measurement does not isolate the cryptography from transport or serialisation. What it supports for RQ4 is narrower: the time to durable evidence is dominated by ordering, which is a configuration parameter.

---

## 6. Questions the design raises

- **Where is the blockchain, if the main prototype is a simulator?** See §0.0. The simulator implements a signed hash-chain locally, by a deliberate DSR decision (ADR-003). The same evidence model was then run on a Hyperledger Fabric test network with two organisations and an AND endorsement policy, with Python signatures verified in Go on chain. Both are controlled environments on one machine.
- **Why a permissioned ledger and not a public one, or a database?** A public ledger sits badly with the confidentiality duties of Art. 78 and with identity governance (ADR-001 records the comparison with Ethereum, Besu and Quorum). Against a database, `compare_oracle_vs_baseline.py` shows one case: a stored decision changed after the fact is reported by the chain and not by a log that keeps no hash or signature. On Fabric, the AND policy adds that one organisation's endorsement is not enough to change the state.
- **Why does the commit take 2 seconds?** It is the orderer's `BatchTimeout`, which is configurable: the transaction waits for the block to be cut.
- **Would this hold up in production?** The prototype does not show that. The simulator's load test processed 500 events at about 110 events per second (9.1 ms mean, P95 16.1 ms), and the Steel run 1,750 events with the chain intact. A single orderer, CCaaS without TLS and a demonstration key are declared in Chapters 5 and 6 as limits and future work.
- **What about the GDPR and erasure?** The configured identifier fields become versioned HMAC pseudonyms and the artefacts are referenced by digest. A pseudonym or a hash can still be personal data (Art. 4(1) and Recital 26 GDPR), and fields outside the pseudonymiser's list are recorded as received, which is why RQ2 speaks of minimising exposure. Erasure is future work, in Chapter 6.
- **Why OSCAL?** A machine-processable NIST format. The redacted export withholds free text and identifiers and keeps hashes and decisions. The 18 published exports validate against the official 1.1.2 schema.

---

*Written from a reading of the code on 2026-07-04 and revised on 2026-10-03. Should this guide and the code diverge, the code prevails. `python3 verify_delivery.py` re-verifies the published evidence, and `python3 validate_oscal_schema.py --expect 18` the exports.*
