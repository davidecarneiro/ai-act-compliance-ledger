# MultiFlow → Compliance Policy Engine integration (Docker)

> This integration connects MultiFlow to the evidence layer through a Kafka
> consumer and a Docker Compose override. MultiFlow's tracked source files
> remain unchanged. The runs it produced are
> reported in Chapter 5 and published under `experiments/runs/multiflow_run*`.
> Only the drift score is measured from the stream: precision (0.85), the parity
> gap (0.03) and `human_approval=True` are configured values standing for the
> monitored model's validation, not figures observed by the bridge. The logic is covered by tests
> (`test_bridge.py`, 4/4) against messages in MultiFlow's real format. Running
> it under Docker needs a machine with Docker installed.

## Integration architecture

```
MultiFlow (node) ──stream──▶ Kafka (topic phd_kafka) ──▶ Faust apps (MMD, …)
                                      │
                                      └──▶ compliance-bridge (this service)
                                              │  batches of 20 rows → drift_score
                                              ▼
                                  ComplianceOracle (the dissertation prototype)
                                              │
                                              ▼
                              ./compliance_out/ledger.json
                              (SHA-256 chained, Ed25519 signed, verifiable, OSCAL)
```

The bridge consumes the SAME topic as MultiFlow's own apps, as an observer. For
every batch of 20 rows it emits a canonical monitoring event (Art. 72) with a
simple, illustrative drift indicator. MultiFlow includes its own detector,
`CDDetection_MMD`; evaluating it is outside the scope of this integration.

## The quick route: a single command

The whole flow below (clone, override, compose, a test stream with drift,
verification, OSCAL, archiving of the run) is automated. The README at the root
of the repository gives the full sequence, including the variables that keep a
new run apart from the published ones:

```bash
bash prototype/multiflow_bridge/run_multiflow_proof.sh
```

It uses the Kafka injector instead of the frontend, with the same message
format as the platform. For the route with the React frontend and the platform's
datasets, follow the manual steps below.

## Steps on macOS (with Docker Desktop running)

> **Before the first block.** Every step below changes directory, and several
> of them run inside the MultiFlow clone, where a path relative to `Project/`
> means nothing. Anchor the two absolute paths once, in the shell you are going
> to use, and the rest of the sequence works from wherever you happen to be:
>
> ```bash
> PROJECT="$(pwd)"                               # run this at the root of the repository
> MULTIFLOW="$PROJECT/../multiflow-demo"          # the clone, created in step 1
> PROTOTYPE_DIR="$PROJECT/prototype"              # Compose reads this
> RUN_DIR="$PROJECT/results/demo/runs/multiflow_run"   # apart from the published runs
> export PROTOTYPE_DIR
> ```
>
> The automated script derives all of this on its own; this sequence is manual
> and does not inherit it.

### 1. Clone MultiFlow and install the frontend
```bash
git clone https://github.com/davidecarneiro/multiflow.git "$MULTIFLOW"
git -C "$MULTIFLOW" checkout --detach a0a97863181eb4cc158c32bad70cf6a1d415081c   # the commit of the published runs
cd "$MULTIFLOW"/app/node && npm install
cd ../react-app && npm install
cd ../ws && npm install
```

### 2. Add the bridge (no changes to the repository)
```bash
cp "$PROJECT"/prototype/multiflow_bridge/docker-compose.override.yml "$MULTIFLOW"/
```
Compose merges the override automatically. The override's `build.context`
reads `PROTOTYPE_DIR`, exported in the block above; without it, Compose stops
with a message naming the variable.

### 3. Bring everything up
```bash
cd "$MULTIFLOW"
docker compose up --build
```
Wait for Kafka to come up. The bridge retries on its own for up to 2.5 minutes,
and once it is ready it prints `[bridge] connected, waiting for the MultiFlow
stream…`

### 4. Start a stream in MultiFlow
```bash
cd "$MULTIFLOW"/app/react-app && npm start   # opens localhost:3000
```
In the frontend, create a Stream over a dataset from the `datasets/` folder
(for instance at 20 rows per second) and start it. **Mind the topic name**: the
frontend sets the topic per stream. According to `ws/server.js` it publishes
`{"csv_data": "<row>"}` on the chosen topic, so the stream should use
`phd_kafka`, or else `STREAM_TOPIC` in the override should be set to the chosen
name. Without the frontend:
```bash
docker exec -it kafka_server bash -c \
 'for i in $(seq 1 100); do echo "{\"csv_data\": \"$((RANDOM%20)).$i,5.2,7.$((i%9)),3.3\"}"; done | \
  kafka-console-producer --bootstrap-server localhost:9092 --topic phd_kafka'
```

### 5. Observe the bridge output
```bash
docker logs -f compliance_bridge
# [bridge] batch=1 rows=20 drift_score=0.0859 decision=approved chain_hash=06ebaa2218bd…
# [bridge] batch=3 rows=20 drift_score=1.0 decision=escalated chain_hash=3a41d6a33a9f…
# (lines from the published real-data run; above the 0.15 threshold the decision is escalated)
```
Kafdrop (http://localhost:19000) shows the topic and the `compliance-bridge`
consumer group alongside the Faust apps.

### 6. Verify the evidence produced
```bash
cd "$MULTIFLOW"/compliance_out
python3 -c "
import json
led = json.load(open('ledger.json'))
print(len(led), 'evidence events')
r = led[0]
print('coverage:', r['requirements_covered'])
print('chain   :', r['chain_hash'][:24], '← Ed25519 signed')"
```
Full verification and OSCAL in a single command, inside the container:
```bash
docker exec compliance_bridge python3 /bridge/verify_output.py
# events, decisions, chain N/N INTACT, oscal_multiflow(.redacted).json in compliance_out/
```
Alternatively, from the prototype folder:
```bash
cd "$PROJECT"/prototype/compliance_ledger_sim
python3 -c "
from simulator import ComplianceOracle
from pathlib import Path
o = ComplianceOracle(ledger_file=Path('$MULTIFLOW')/'compliance_out/ledger.json')
print(o.verify_chain())"
```

## Demonstrated scope

The runs demonstrate the path of Chapter 4 (MLOps pipeline → Kafka broker →
Compliance Policy Engine) on MultiFlow's own broker: consumption of
MultiFlow-formatted Kafka messages, creation of signed evidence records, chain
verification and OSCAL export. The article labels on the records are assigned
by the Oracle's rules; they are not legal compliance findings. Precision, the
parity gap and human approval are configured values, not measurements. The
integration is made by Docker composition, with no fork and no patch of the
platform.

## Validation without Docker

`python3 -m pytest test_bridge.py -q` → 4 passed. A simulated stream of 100
rows (60 stationary and 40 with drift) produces 4 events, 2 `approved` and
2 `escalated` with a drift reason, with a valid 4/4 chain, coverage of
Art. 10(3), 12, 14, 15 and 72, and provenance `multiflow-phd_kafka-batch-*`.

## Archive the run

The MultiFlow clone stays OUTSIDE this repository: it is third-party software
with its own git history. What is archived here is the evidence of the run:

```bash
# Every path is absolute, because earlier steps changed directory into the clone.
mkdir -p "$RUN_DIR"

# 1. the artefacts the run produced (ledger, OSCAL, bridge log)
cp "$MULTIFLOW"/compliance_out/* "$RUN_DIR"/
docker logs compliance_bridge > "$RUN_DIR"/bridge_log.txt

# 2. the exact platform commit, recorded only after the evidence is in place
( cd "$MULTIFLOW" && git rev-parse HEAD ) > "$RUN_DIR"/MULTIFLOW_COMMIT.txt

# 3. confirm the chain actually arrived; without it nothing was archived
[ -s "$RUN_DIR"/ledger.json ] && echo "archived: $(ls "$RUN_DIR" | wc -l) files"
```


## Troubleshooting

`compliance_bridge` looping on retries → Kafka is still coming up, so wait.
Persistent `NoBrokersAvailable` → check `KAFKA_BOOTSTRAP: kafka:29092`, the
internal listener. From the host, `localhost:9092` connects but the broker
advertises itself as `kafka:9092`, which the host does not resolve, so a
host-side consumer receives nothing: run the bridge inside the Docker network.
An empty ledger → the stream is not producing on the `phd_kafka` topic. Check
the topic name in the MultiFlow frontend or in Kafdrop.
