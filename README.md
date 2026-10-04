# Compliance evidence ledger for the EU AI Act

Code and evidence for the dissertation *Blockchain for Compliance, Auditability
and Traceability of Technical Documentation in the AI Act* (Master's in Digital
Legal Practices, ESTG, Polytechnic of Porto). Every path the manuscript cites
as `Project/…` resolves from the root of this repository.

## User manuals

The manuals show how to navigate the Compliance Ledger Explorer platform, inspect records and
verify evidence, with screenshots and step-by-step instructions.

- [Manual completo em português](user_manuals/MANUAL_UTILIZACAO.md)
- [Complete user manual in English](user_manuals/USER_MANUAL.md)

After downloading the repository, open
`Project/ledger_explorer/LEDGER_EXPLORER.html` in your browser. The
`user_manuals/` folder also contains both manuals in HTML for browser reading.

## 1. What the project does

A provider of a high-risk AI system has to keep technical documentation and
logs, and to show them to an authority on request. Conventional logs can
support an audit, but their integrity needs additional safeguards when the
audited party controls their storage: nothing in the log itself shows that it
was not rewritten after the fact. This prototype turns the events of an MLOps
pipeline into evidence that a third party can check without trusting whoever
holds it.

Each event is evaluated against a declared policy. The decision goes into a
23-field record, which is hashed (SHA-256), signed (Ed25519) and chained to the
record before it. Anyone holding the public key can recompute every hash, link
and signature, and the ledger exports as OSCAL Assessment Results, in full or
with free-text fields suppressed.

```text
MultiFlow → Kafka → Bridge → Compliance Oracle
                               ↓
                         Signed ledger
                               ↓
                  Verification + OSCAL export
```

[MultiFlow](https://github.com/davidecarneiro/multiflow) is a platform that
replays industrial datasets as Kafka streams. It is a separate project, with
its own repository, and it is not copied here: the scripts below clone it. The
bridge joins its Kafka network as one more consumer and leaves the platform's
repository untouched.

**What is measured and what is configured.** From the stream the bridge
computes one thing: a drift indicator per batch of 20 rows (the mean
per-column z-score against the first 20 rows, divided by three and capped at
one). The precision (0.85), the demographic-parity difference (0.03) and the
human approval carried in each event are values configured for the
demonstration. They stand for the monitored model's validation and are not
observed by the bridge. The indicator is illustrative, not a validated drift
detector.

**What the result is not.** A verified chain shows that the records present
have not changed since they were signed. It is not a finding that a system
complies with the AI Act.

## 2. Prerequisites

| For | You need | Version on the machine used for this release |
|---|---|---|
| Everything | macOS or Linux. The simulator uses `fcntl` file locks, so it does not run on native Windows; WSL should work but was not tested | macOS 15.8.1, x86_64 |
| Sections 6 to 8 | Python 3.9 or later, with the packages in `prototype/compliance_ledger_sim/requirements.txt` | Python 3.9.6 |
| Sections 8 and 9 | Go 1.21 or later (1.24 for the Gateway client), for the chaincode tests, the interoperability check and the Fabric client | Go 1.25.4 |
| Sections 3 to 5 | Git, and Docker with Compose v2, running. The [MultiFlow repository](https://github.com/davidecarneiro/multiflow) is cloned by the script | Git 2.50.1, Docker 29.7.2, Compose 5.4.0 |
| Section 4 only | Node.js and npm, for the MultiFlow web interface | Node 20.19.2, npm 10.8.2 |

Sections 3 to 5 download the MultiFlow repository (about 160 MB) and the Kafka
images. Section 8 needs neither Docker nor a network connection once the
Python packages are installed, and the same holds for section 7 except its
container alternative in 7.1, which needs Docker.

### Set-up done once: the Python environment

Every Python command in this README runs in a virtual environment inside the
repository. Create it once, from the root of the repository:

```bash
python3 -m venv prototype/compliance_ledger_sim/.venv
. prototype/compliance_ledger_sim/.venv/bin/activate
python3 -m pip install -r prototype/compliance_ledger_sim/requirements.txt
python3 -m pip install kafka-python==2.0.2      # only for section 7.1
deactivate
```

### Set-up done in every terminal

Variables exported in one terminal do not exist in another. Every terminal
you open for sections 3 to 8 starts with this block, and the commands in those
sections assume it has run:

```bash
cd /path/to/this/repository                      # wherever you cloned or unpacked it
export PROJECT="$(pwd)"
export MULTIFLOW="$PROJECT/../multiflow-demo"    # where MultiFlow is cloned
export EXPERIMENTS_DIR="$PROJECT/results/demo"   # where new runs are archived
export PROTOTYPE_DIR="$PROJECT/prototype"        # what Docker Compose builds the bridge from
mkdir -p "$EXPERIMENTS_DIR/runs"
. "$PROJECT/prototype/compliance_ledger_sim/.venv/bin/activate"
```

`EXPERIMENTS_DIR` keeps new runs apart from the published evidence: without
it, the scripts archive over `experiments/runs/` and replace the published
runs. Section 8 is the one place where it must be unset.

> **What was run for this release.** Sections 3 to 8 were run on 2 October
> 2026, with these scripts, from a clean copy of the repository. Sections 3 and
> 5 gave what this README states (4 events, then 29 with 12 approved and 17
> escalated, both chains intact); section 4 streamed `Muvu_Janeiro.csv` from
> the interface and the bridge produced the 19 expected events, with only the
> services that route needs started; section 7 was run on a topic of its own,
> and section 7.2's code as printed. `docs/VERIFICATION_REPORT.md` has the
> details. The published evidence came
> from the Kafka injector of sections 3 and 5, not from the interface.

## 3. Quick start: from the stream to the results

One command clones [MultiFlow](https://github.com/davidecarneiro/multiflow) at
[the commit the published runs used](https://github.com/davidecarneiro/multiflow/tree/a0a97863181eb4cc158c32bad70cf6a1d415081c),
adds the bridge, starts Kafka, publishes a synthetic stream, verifies the chain, exports
OSCAL and archives the run. In a terminal prepared with the block of section 2:

```bash
bash "$PROJECT/prototype/multiflow_bridge/run_multiflow_proof.sh"
```

**What this run is.** The script uses the platform's Kafka broker and
publishes 100 messages in the format MultiFlow's stream server writes
(`{"csv_data": "…"}`) to the topic `phd_kafka`: 60 stationary rows, then 40
with a shifted mean. It does not go through the MultiFlow web interface; that
route is section 4.

**What to expect.** The first 20 rows become the reference and the other 80
make four batches. On a fresh clone the output ends with four evidence events,
two `approved` and two `escalated`, and `chain 4/4 INTACT`. If
`$MULTIFLOW/compliance_out/` already holds a ledger from an earlier run, the
new records are appended to it.

The containers stay up afterwards. Kafdrop, at http://localhost:19000, shows
the topic and the `compliance-bridge` consumer group. To stop everything, in a
prepared terminal (Compose reads the override, whose build context needs
`PROTOTYPE_DIR`):

```bash
cd "$MULTIFLOW" && docker compose down
```

## 4. Running it through the MultiFlow interface

This is the platform's normal way of producing the same messages. It needs
three terminals; open each one and run the set-up block of section 2 in it
before anything else. If you skipped section 3, clone MultiFlow first with the
same script, or by hand from https://github.com/davidecarneiro/multiflow at
commit
[`a0a9786`](https://github.com/davidecarneiro/multiflow/tree/a0a97863181eb4cc158c32bad70cf6a1d415081c).
The platform's own README, in that repository, documents the interface in full.

**Terminal A, the platform's dependencies and containers.** The `node` and
`websocket` containers mount these folders from the host, so the `npm install`
steps come first. The last command starts the services this route needs:
Kafka and its ZooKeeper, Kafdrop, MongoDB, the platform's backend and stream
server, and the bridge.

```bash
cd "$MULTIFLOW/app/node" && npm install
cd "$MULTIFLOW/app/react-app" && npm install
cd "$MULTIFLOW/app/ws" && npm install

cp "$PROJECT/prototype/multiflow_bridge/docker-compose.override.yml" "$MULTIFLOW/"
cd "$MULTIFLOW" && docker compose up -d --build zookeeper kafka kafdrop compliance-bridge mongodb node websocket
```

(The whole platform, with its Faust apps, Grafana and InfluxDB, is
`docker compose up -d --build` with no service names. It builds several
gigabytes of images and is not needed to stream.)

**Terminal B, the web interface.**

```bash
cd "$MULTIFLOW/app/react-app" && npm start     # opens http://localhost:3000
```

**In the browser.**

1. Open the **Projects** tab and choose **Add Project**; give it a name and
   create it.
2. Open the project and choose **Add Stream**.
3. Set the **Stream Topic** to `phd_kafka`. The bridge listens on that topic
   only; any other name produces no evidence.
4. Set `Data Source Type` to `File` and pick a dataset from MultiFlow's
   `datasets/` folder, for instance `Muvu_Janeiro.csv`.
5. Under `Playback Configuration Type` choose `Lines per Second` and set the
   value, for instance 20.
6. Create the stream. Back on the project page, press the play button under
   **Project Status**: it starts every stream of the project, and the progress
   bar shows how much of the file has been sent.

**Before starting the stream: has the bridge already consumed something?**
The bridge builds its reference from the first 20 rows it sees after it
starts, and that reference fixes the number of columns. After section 3 it
holds a 3-column reference, so every 11-column row of `Muvu_Janeiro.csv` would
be skipped. Restart it first, in terminal A, so that it starts afresh:

```bash
cd "$MULTIFLOW" && docker compose restart compliance-bridge
```

**Terminal C, the bridge.**

```bash
docker logs -f compliance_bridge
# [bridge] batch=1 rows=20 drift_score=0.0859 decision=approved chain_hash=06ebaa2218bd…
```

One line appears for every 20 rows streamed, after the first 20. With
`Muvu_Janeiro.csv` (409 rows) at 20 rows per second that is 19 lines in about
twenty seconds, the last 9 rows staying in an incomplete batch; the end-of-stream
message the platform sends is logged as one skipped message. This route
does not archive anything: the ledger stays in `$MULTIFLOW/compliance_out/`,
and new records are appended to whatever is already there. Verify it as in
section 6 and copy the folder if you want to keep it.

## 5. Running it on industrial data

With the containers of section 3 still up, in a prepared terminal:

```bash
bash "$PROJECT/prototype/multiflow_bridge/inject_real_datasets.sh"
```

This script **resets the bridge's working ledger**
(`$MULTIFLOW/compliance_out/ledger.json`) and restarts the bridge, then
publishes two datasets that ship in the MultiFlow repository, under
`datasets/`: `Muvu_Janeiro.csv` (409 rows)
followed by `Muvu_Marco.csv` (203 rows). The synthetic run of section 3 is not
lost: it was archived in a different folder.

The published run on the same data has 29 events, 12 approved and 17
escalated. The January batches are a mix, and every March batch is escalated:
the equipment's readings moved between the two months, and the indicator
saturates. That is a statement about drift relative to the first 20 rows, not a
compliance verdict on the data.

## 6. Where the results are and what they mean

With the commands above, the two runs are archived in
`results/demo/runs/multiflow_run/` and `results/demo/runs/multiflow_run_real/`.

| File | What it lets you check |
|---|---|
| `ledger.json` | The events, decisions, hashes and signatures |
| `oscal_multiflow.json` | The full OSCAL Assessment Results |
| `oscal_multiflow_redacted.json` | The same report with reduced disclosure |
| `bridge_log.txt` | The processing of each batch, and what was skipped |
| `MULTIFLOW_COMMIT.txt` | The version of the platform that was used |
| `RUN_TIMESTAMP.txt` | When the run was archived |

**Verify explicitly**, inside the container:

```bash
docker exec compliance_bridge python3 /bridge/verify_output.py
```

It exits with status 2 when the chain is broken and 1 when there is no
ledger, so it can gate a script. The same check from the host, with Python
only (the environment of section 2 must be active):

```bash
cd "$PROJECT/prototype/compliance_ledger_sim"
python3 - "$EXPERIMENTS_DIR/runs/multiflow_run_real/ledger.json" <<'EOF'
import sys
from pathlib import Path
from simulator import ComplianceOracle
report = ComplianceOracle(ledger_file=Path(sys.argv[1])).verify_chain()
ok = report.total > 0 and report.valid == report.total
print(f"chain {report.valid}/{report.total}",
      "INTACT" if ok else ("EMPTY" if report.total == 0 else report.issues[:3]))
sys.exit(0 if ok else 1)
EOF
```

`chain N/N INTACT` means that for each of the N records the hash of the body
was recomputed, the link to the previous record matches, and the Ed25519
signature verifies against the issuer's public key: the records are what was
signed with that key. It does not, on its own, establish legal compliance, and
it cannot show that no record is missing from the end of the file: that needs
a count or a final `chain_hash` recorded somewhere else.

**Seeing it in the explorer.** `ledger_explorer/LEDGER_EXPLORER.html` opens in
a browser with no server (double-click it). What it shows by default is the
published evidence, embedded in the file, not the run you just made. To look
at a new run, go to its **Open a ledger** page, drop or paste
`results/demo/runs/multiflow_run_real/ledger.json`, and the page lists the
records and re-verifies them in the browser. A ledger signed with the
demonstration key shows as authenticated at once; one signed with a key of
your own (section 7.2) needs its public key pasted on the same page first,
under **Trust this key**.

**The decisions.**

| `decision` | Meaning |
|---|---|
| `approved` | Every policy rule passed |
| `rejected` | A threshold was not met (precision, parity gap, missing human approval) or the event was malformed; `rule_id` and `reason` say which |
| `escalated` | Sent for human review: drift above the threshold, or a serious incident. The prototype records the escalation, not what the reviewer then decides |
| `verified` | An audit query was recorded. It is not the result of an integrity check, which is `verify_chain()` |

## 7. Connecting your own platform

MultiFlow is one source of events. Anything that produces them can use the
same evidence layer, in one of two ways. There is no network API in this
repository: integration is either through Kafka or in-process Python.

### 7.1 Your platform publishes to Kafka

The bridge is a plain Kafka consumer, configured by environment variables. On
a machine that reaches your broker, with a broker that advertises an address
that machine can resolve, in a prepared terminal:

```bash
export OUT_DIR="$PROJECT/results/my_platform"     # where the bridge writes its ledger
cd "$PROJECT/prototype/multiflow_bridge"
ORACLE_PATH=../compliance_ledger_sim \
KAFKA_BOOTSTRAP=localhost:9092 STREAM_TOPIC=my_topic BATCH_SIZE=20 \
MODEL_ID=my-model MODEL_PRECISION=0.91 MODEL_DP_DIFF=0.02 \
python3 bridge.py
```

Your platform publishes, on `STREAM_TOPIC`, one JSON object per row:

```json
{"csv_data": "18.48,9.22,11.279,210,190.2"}
```

The rules the bridge applies to that stream:

- `csv_data` holds comma-separated numbers, all finite. The first usable row
  fixes the number of columns; rows with another count, messages that are not
  JSON objects, and non-finite values are skipped and logged, never fatal.
- The first `BATCH_SIZE` usable rows are the reference. Every complete batch
  after them yields one evidence event with a `drift_score` in [0, 1], the mean
  per-column z-score against the reference, divided by three and capped. A
  partial batch waits for more rows.
- `MODEL_PRECISION` and `MODEL_DP_DIFF` are copied into every event as the
  monitored model's precision and demographic-parity difference, and
  `human_approval` is always `true`. They describe the model your platform is
  monitoring; the bridge does not measure them. If your platform does, use
  route 7.2 instead.
- Decisions follow the policy in
  `prototype/compliance_ledger_sim/configs/policies.json`, in the order section
  7.2 gives. With the values above (precision 0.91, parity gap 0.02) the first
  rules pass, and the outcome is `escalated` when `drift_score` is above
  `drift_alert_threshold` (0.15) and `approved` otherwise. Set
  `MODEL_PRECISION` below 0.80, or `MODEL_DP_DIFF` above 0.05, and every event
  is `rejected` instead.

The bridge runs until stopped (Ctrl-C). The ledger at
`results/my_platform/ledger.json` is written on every event, so the events already recorded survive a stop; the
reference and a partial batch live in memory and do not, and after a restart
the bridge builds a new reference from the next 20 rows. Verify the ledger
with the host command of section 6 (pass its path), and export OSCAL with:

```bash
cd "$PROJECT/prototype/compliance_ledger_sim"
python3 - "$PROJECT/results/my_platform/ledger.json" "$PROJECT/results/my_platform" <<'EOF'
import sys
from pathlib import Path
from oscal_exporter import export_oscal

print(export_oscal(Path(sys.argv[1]), Path(sys.argv[2]), redacted=True))
EOF
```

If your broker runs in Docker, run the bridge as a container on the broker's
network instead. Build the image from this repository, name the broker's
Docker network and the broker's address inside it, and start the container:

```bash
docker build -t compliance-bridge -f "$PROJECT/prototype/multiflow_bridge/Dockerfile" "$PROJECT/prototype"
export BROKER_NETWORK="multiflow-demo_broker-kafka"   # your broker's Docker network
export BROKER_ADDRESS="kafka:29092"                   # the broker as seen inside that network
mkdir -p "$PROJECT/results/my_platform"
docker run -d --rm --name my_platform_bridge --network "$BROKER_NETWORK" \
  -e KAFKA_BOOTSTRAP="$BROKER_ADDRESS" -e STREAM_TOPIC=my_topic -e BATCH_SIZE=20 \
  -e MODEL_ID=my-model -e MODEL_PRECISION=0.91 -e MODEL_DP_DIFF=0.02 -e OUT_DIR=/out \
  -v "$PROJECT/results/my_platform:/out" compliance-bridge
docker logs -f my_platform_bridge
```

The two values shown are those of the MultiFlow stack of section 3. From the host, that broker accepts
the connection on `localhost:9092` but advertises itself as `kafka:9092`, which
the host cannot resolve, so a host-side bridge connects and then receives
nothing; the container form avoids that.

### 7.2 Your platform calls the Oracle directly

For a platform written in Python, or able to call it, the Oracle takes one
event at a time and returns the signed record. The modules import from the
simulator's folder, so run this there, in a prepared terminal
(`cd "$PROJECT/prototype/compliance_ledger_sim"`):

```python
from pathlib import Path
from simulator import ComplianceOracle
from keys import load_or_create_key

key = load_or_create_key(issuer_id="my-platform", keys_dir=Path("my_keys"))
oracle = ComplianceOracle(ledger_file=Path("my_ledger.json"), issuer_key=key)

record = oracle.process_mlops_event({
    "event_type": "model_validation",
    "artifact_id": "credit-model-v7",
    "artifact_type": "model",
    "pipeline_stage": "validation",
    "risk_level": "high",
    "human_approval": True,
    "metrics": {"precision": 0.91, "demographic_parity_diff": 0.02, "drift_score": 0.05},
})
print(record["decision"], record["rule_id"], record["chain_hash"])
```

The first call creates an Ed25519 key pair for `my-platform` under `my_keys/`;
keep the private half where your deployment keeps secrets. Every record names
the key by its fingerprint. The event contract:

| Field | Required | Domain | Effect |
|---|---|---|---|
| `event_type`, `artifact_id`, `artifact_type`, `pipeline_stage` | yes | non-empty text | Identity of the event; part of the record |
| `risk_level` | yes | `low`, `medium`, `high` | `high` requires `human_approval`, by default |
| `human_approval` | no | `true`/`false` | Gate for high-risk events. A boolean: it does not say who approved |
| `metrics` | no | object of finite numbers; `precision`, `demographic_parity_diff`, `drift_score` in [0, 1] | The three named metrics are evaluated; others are sealed into the record but not judged |
| `scenario_id` | no | text | Your own correlation label |
| anything else | no | JSON | Sealed into `artifact_hash`, not copied into the record |

The rules run in this order, and the first that applies decides:

1. A malformed event (a field outside its domain) is `rejected` with
   `rule_id = input.malformed`. It is still signed and chained: a rejection is
   evidence too.
2. `event_type` equal to `serious_incident_detected` or
   `incident_reported_to_authority` is `escalated`, whatever the metrics.
3. `precision` below `min_precision` (0.80) is `rejected`. **A missing
   `precision` counts as 0.0**, so an event without it is rejected.
4. `demographic_parity_diff` above `max_demographic_parity_diff` (0.05) is
   `rejected`. **A missing value counts as 1.0**, so an event without it is
   rejected as well.
5. `risk_level: high` without `human_approval: true` is `rejected`.
6. `drift_score` above `drift_alert_threshold` (0.15) is `escalated`.
7. `event_type` equal to `audit_query` or `incident_audit_query` is recorded
   as `verified`.
8. Otherwise `approved`.

Points 3 and 4 matter for a platform that only monitors drift: give the
validation figures of the monitored model in every event, as the bridge does,
or the policy rejects it. The thresholds are read from `configs/policies.json`
(or the `policy_file` argument); `policy_id` and `policy_hash` in each record
identify the policy that decided.

Anyone holding only the public key can re-verify the ledger (same folder):

```python
import sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from verify_delivery import read_chain, verify_chain

pub = serialization.load_pem_public_key(Path("my_keys/my-platform.ed25519.pub.pem").read_bytes())
records = read_chain(Path("my_ledger.json"))
valid, issues = verify_chain(records, pub)
ok = len(records) > 0 and not issues
print(f"{valid}/{len(records)} valid;", issues or "no issues")
sys.exit(0 if ok else 1)
```

and `export_oscal(Path("my_ledger.json"), Path("out"), redacted=True)` from
`oscal_exporter` writes the OSCAL Assessment Results. One process should write
a given ledger at a time: the file is rewritten on every event under a lock,
and the per-event cost grows with its length. For pseudonymising identifier
fields before they are sealed, pass a `Pseudonymizer`
(`pseudonymizer.py`) to the Oracle.

## 8. Verifying the published evidence and running the tests

This is a different task from producing new results. The dissertation reports
seven chains, 1,831 records in all, which ship in this repository. A new run
has other timestamps and hashes and does not confirm them; recomputing them
does.

In a prepared terminal, run `unset EXPERIMENTS_DIR` first: with that variable
set, these commands would look for the evidence in `results/demo/` and report
it missing.

```bash
unset EXPERIMENTS_DIR
cd "$PROJECT/prototype/compliance_ledger_sim"
python3 verify_delivery.py                      # 7 chains, 1,831 records
python3 -m pytest tests/ -q                     # 98 tests
python3 validate_oscal_schema.py --expect 18    # the published OSCAL exports
```

`verify_delivery.py` reads the ledgers and the public key, never the private
one, and writes nothing. It works from a declared inventory, so a chain that is
missing, empty or short fails. It also compares each chain's final
`chain_hash` with the published one and reports `NOT PUBLISHED` for a chain
that is valid but was regenerated.

The other suites:

```bash
cd "$PROJECT/prototype/multiflow_bridge" && python3 -m pytest test_bridge.py -q      # 4 tests, no Kafka
cd "$PROJECT/prototype/fabric_migration/chaincode" && go test -mod=vendor ./...      # 10 tests, no network
cd "$PROJECT/prototype/fabric_migration/interop" && python3 test_interop.py          # 6 Python/Go vectors
```

`docs/VERIFICATION_REPORT.md` records what was run on this version, with what
result, and what was not run.

**Scripts that replace published evidence.** `make baseline`, `make demo`,
`simulator.py`, `compare_oracle_vs_baseline.py`, `sensitivity.py`,
`load_test.py` and `incident_demo.py`, and on the Fabric side `gen_records.py`
and `02_submit_and_measure.py`, write new records over published chains. To
try them, work in a copy of the repository. `docs/DEMONSTRATION_GUIDE.md` walks
through them.

**Is this the version that was delivered?** `MANIFEST.sha256` lists the SHA-256
of every other file:

```bash
cd "$PROJECT" && shasum -a 256 -c MANIFEST.sha256 --quiet     # sha256sum on Linux; no output means all match
```

A manifest stored beside the files catches accidental changes. It becomes an
independent check when its own hash is compared with a value kept elsewhere.

## 9. Hyperledger Fabric

The prototype evaluated in the dissertation is the local Python simulator. The
same records were also submitted to a two-organisation Fabric 2.5 network, to
measure what distributed endorsement and ordering add. That network does not
need to be stood up to assess the work: what came out of it is recorded under
`experiments/runs/fabric_run/`, and `verify_delivery.py` checks the signed
part.

The Go chaincode, its tests and the deployment scripts are in
`prototype/fabric_migration/`. Its `chaincode/README.md` describes the
interface and distinguishes the June and July 2026 measurements from the
functional deployment of the current chaincode on 3 October 2026, whose summary
is in `docs/fabric_check_2026-10-03/`.

## 10. Limitations

- It is a research prototype. The ledger is a JSON file rewritten on every
  event, so the per-event cost grows with its length.
- The signing key in `prototype/compliance_ledger_sim/keys/` is a demonstration
  key and it is published here, private half included, because the scripts need
  it to reproduce the issuer. Anyone can sign new records with it. A valid
  signature therefore shows that a record is exactly what was signed with this
  key; it does not show who held the key, or when, and a record forged with
  the published key verifies just as well.
- Pseudonymisation is optional and covers configured identifier fields only.
  Free text and `artifact_id` can still identify someone.
- `artifact_hash` seals the event payload, not the model or dataset file it
  describes.
- The anchors and the manifest live in this repository. Against deliberate
  replacement they help only when compared with copies kept elsewhere.
- Dependencies are given as minimum versions and the container images by tag,
  not by digest.

Chapter 6 of the dissertation discusses these and the legal limits of the
approach.

## 11. Troubleshooting

| Symptom | Likely cause and what to do |
|---|---|
| `The Docker daemon is not running` | Start Docker and run the script again |
| `Kafka did not respond within 150 s` | The script prints the broker's status and last log lines. A mention of ZooKeeper or KRaft means the images were not the pinned 7.6.1: check that `docker-compose.override.yml` is in `$MULTIFLOW`, then `docker compose down` and run again |
| `compliance_bridge` keeps printing `Kafka unavailable … retry` | Kafka is still starting; the bridge retries for 2.5 minutes |
| The ledger stays empty | Nothing is arriving on `phd_kafka`. Check the stream's topic in the interface or in Kafdrop |
| Rows were streamed but no event appeared | The first 20 usable rows are the reference, and an event needs a complete batch of 20 after them. A partial batch waits in memory for more rows and is never submitted |
| `skipped unusable message` or `skipped row … column(s)` in the bridge log | Messages that were not an object or held non-finite numbers, and rows with a different number of columns from the first usable row: a CSV header, or a dataset of another shape streamed without restarting the bridge (section 4). Each is logged as it is skipped |
| The bridge says `connected` but no batch ever appears | The broker advertises an address the client cannot reach. MultiFlow's broker advertises `kafka:9092` for the host listener, so a bridge running on the host receives nothing from it; run the bridge as a container on the broker's network (section 7.1) |
| `set PROTOTYPE_DIR to the prototype/ folder` | `docker compose` was run by hand (`up`, `down`, `restart`) without `PROTOTYPE_DIR="$PROJECT/prototype"` in its environment |
| The first rows after a restart give unexpected decisions | After a restart the bridge builds a new reference from the next 20 usable rows, and the first usable row fixes the column count |
| `verify_delivery.py` reports `NOT PUBLISHED` | A script regenerated a published chain in this copy. Restore the file from a clean copy of the repository |

## 12. Repository layout

```
├── prototype/
│   ├── compliance_ledger_sim/   the Compliance Oracle: simulator, policies, demonstration
│   │                            key, tests, canonical ledger, OSCAL exporter
│   ├── multiflow_bridge/        the Kafka observer and the two scripts of sections 3 and 5
│   ├── fabric_migration/        Go chaincode with vendored dependencies, measurement
│   │                            client, deployment scripts
│   ├── fabric_notes/            the earlier version of the chaincode, kept as history
│   └── delivery_paths.sh        resolves prototype/ and experiments/ for the shell scripts
├── experiments/                 the published evidence
│   ├── runs/                    complete runs, with ledger and OSCAL exports
│   ├── latency/  load/  sensitivity/  oscal/  validation_cost/
│   └── RESULTS_SUMMARY.md       a reading of all of them
├── traceability/                Master Matrix, Legal Register, Claims Register
├── ledger_explorer/             interactive explorer, a single HTML file
├── docs/                        latency protocol, demonstration guide, verification report
└── MANIFEST.sha256
```

## 13. Licence and citation

MultiFlow is a separate project and is not distributed here. Its code and
datasets are at https://github.com/davidecarneiro/multiflow, under that
repository's own terms, and it is described in:

> Torres, D., Peixoto, E., Carneiro, D., Palumbo, G., & Alves, V. (2026).
> MultiFlow: An ambient intelligence digital twin. In *Ambient Intelligence –
> Software and Applications – 16th International Symposium on Ambient
> Intelligence (ISAmI 2025)*, Lecture Notes in Networks and Systems, vol. 1776,
> pp. 12–19. Springer. https://doi.org/10.1007/978-3-032-14138-5_2

To cite this work: No DOI Yet
