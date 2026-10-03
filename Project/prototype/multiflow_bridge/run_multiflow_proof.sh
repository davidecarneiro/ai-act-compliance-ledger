#!/usr/bin/env bash
# =====================================================================
# MultiFlow to Compliance Oracle integration proof, in a single command.
#
# With Docker running, from the root of the repository:
#   bash prototype/multiflow_bridge/run_multiflow_proof.sh
#
# It clones MultiFlow at a pinned commit if needed, installs the override, brings
# the compose stack up, injects a synthetic stream with drift induced halfway
# through (in the message format the platform's ws/server.js publishes), verifies
# the chain, exports OSCAL and archives the run.
# The containers are left running afterwards (so Kafdrop stays usable); shut them
# down with:  cd "$MULTIFLOW" && PROTOTYPE_DIR=<prototype folder> docker compose down
# (Compose reads the override, whose build context needs that variable.)
#
# Environment (all optional):
#   MULTIFLOW          where the MultiFlow clone lives (default ~/Desktop/multiflow)
#   MULTIFLOW_COMMIT   the platform commit to clone (default: the one the
#                      published runs recorded)
#   EXPERIMENTS_DIR    where the run is archived (default: experiments/ of this
#                      repository, which REPLACES the published multiflow_run)
# =====================================================================
set -euo pipefail

# Paths are derived from where this script sits, so the folder delivered with
# the dissertation runs on any machine. Override with the environment if needed:
#   MULTIFLOW=~/src/multiflow EXPERIMENTS_DIR=/tmp/out bash run_multiflow_proof.sh
BRIDGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BRIDGE_DIR/../delivery_paths.sh"
MULTIFLOW="${MULTIFLOW:-$HOME/Desktop/multiflow}"
# The commit recorded in MULTIFLOW_COMMIT.txt of every published run.
MULTIFLOW_COMMIT="${MULTIFLOW_COMMIT:-a0a97863181eb4cc158c32bad70cf6a1d415081c}"
RUN_DIR="$(run_dir multiflow_run)"

step() { echo ""; echo "═══ $1 ═══"; }

step "0/7 Prerequisites"
command -v docker >/dev/null || { echo "Docker not found. Install or start Docker Desktop."; exit 1; }
docker info >/dev/null 2>&1 || { echo "The Docker daemon is not running. Start Docker Desktop."; exit 1; }
echo "Docker is up"

step "1/7 Clone MultiFlow at the pinned commit"
if [ ! -d "$MULTIFLOW/.git" ]; then
  mkdir -p "$MULTIFLOW"
  git -C "$MULTIFLOW" init -q
  git -C "$MULTIFLOW" remote add origin https://github.com/davidecarneiro/multiflow.git
  git -C "$MULTIFLOW" fetch --depth 1 origin "$MULTIFLOW_COMMIT"
  git -C "$MULTIFLOW" checkout -q --detach FETCH_HEAD
  echo "cloned at $MULTIFLOW, commit $(git -C "$MULTIFLOW" rev-parse --short HEAD)"
else
  ATUAL="$(git -C "$MULTIFLOW" rev-parse HEAD)"
  echo "already cloned at $MULTIFLOW, commit ${ATUAL:0:7}"
  [ "$ATUAL" = "$MULTIFLOW_COMMIT" ] || {
    echo "NOTE: this is not the pinned commit ${MULTIFLOW_COMMIT:0:7}. The run goes ahead";
    echo "      and records the commit actually used in MULTIFLOW_COMMIT.txt."; }
fi

step "2/7 Install the bridge override (zero changes to the repo)"
# The override uses ${PROTOTYPE_DIR} as its build context. It is exported here
# so that compose resolves it on whichever machine is running this.
cp "$BRIDGE_DIR/docker-compose.override.yml" "$MULTIFLOW/"
export PROTOTYPE_DIR
echo "docker-compose.override.yml in place"

step "3/7 Bring up the platform and the bridge"
cd "$MULTIFLOW"
docker compose up -d --build zookeeper kafka kafdrop compliance-bridge
echo "waiting for Kafka to accept connections…"
for i in $(seq 1 30); do
  docker exec kafka_server kafka-topics --bootstrap-server localhost:9092 --list >/dev/null 2>&1 && break
  sleep 5
done
docker exec kafka_server kafka-topics --bootstrap-server localhost:9092 --list >/dev/null 2>&1 \
  || { echo "Kafka did not respond within 150 s. Automatic diagnostics:";
       echo "--- status:"; docker ps -a --filter name=kafka_server --format "{{.Status}}";
       echo "--- last logs:"; docker logs kafka_server 2>&1 | tail -12;
       echo "If it mentions ZooKeeper or KRaft, the override pin 7.6.1 fixes it:";
       echo "  cd $MULTIFLOW && docker compose down && docker compose up -d --build zookeeper kafka kafdrop compliance-bridge";
       exit 1; }
echo "Kafka ready; the bridge is subscribing (consumer group compliance-bridge)"
sleep 10

step "4/7 Inject a test stream (100 rows, drift induced halfway)"
# Same {\"csv_data\": \"...\"} format the platform's ws/server.js publishes.
docker exec -i kafka_server bash -c '
{
  for i in $(seq 1 60); do
    echo "{\"csv_data\": \"10.$((RANDOM%90)),5.$((RANDOM%90)),7.$((RANDOM%90))\"}"
  done
  for i in $(seq 1 40); do
    echo "{\"csv_data\": \"30.$((RANDOM%90)),25.$((RANDOM%90)),27.$((RANDOM%90))\"}"
  done
} | kafka-console-producer --bootstrap-server localhost:9092 --topic phd_kafka' \
  && echo "100 messages published to topic phd_kafka"

step "5/7 Give the bridge time and show the evidence appearing"
sleep 12
docker logs --tail 12 compliance_bridge

step "6/7 Full verification and OSCAL export"
docker exec compliance_bridge python3 /bridge/verify_output.py

step "7/7 Archive the run"
mkdir -p "$RUN_DIR"
# An earlier run must not pass for this one: if a ledger is already archived,
# its hash is kept to confirm at the end that it was replaced.
ANTES=""
[ -f "$RUN_DIR/ledger.json" ] && ANTES=$(shasum -a 256 "$RUN_DIR/ledger.json" | cut -d" " -f1)

# The run must have produced a chain. A non-empty folder is not enough: the
# commit file below would make it non-empty even if nothing had been copied.
[ -d "$MULTIFLOW/compliance_out" ] || {
  echo "ERROR: $MULTIFLOW/compliance_out does not exist. The bridge produced no"
  echo "       evidence, so there is nothing to archive. See: docker logs compliance_bridge"
  exit 1; }
cp "$MULTIFLOW"/compliance_out/* "$RUN_DIR/" && rm -f "$RUN_DIR"/*.lock || {
  echo "ERROR: copying the artefacts to $RUN_DIR failed."; exit 1; }
[ -s "$RUN_DIR/ledger.json" ] || {
  echo "ERROR: $RUN_DIR/ledger.json is missing or empty. A run is not archived"
  echo "       without the chain it produced."
  exit 1; }
if [ -n "$ANTES" ] && [ "$ANTES" = "$(shasum -a 256 "$RUN_DIR/ledger.json" | cut -d" " -f1)" ]; then
  echo "ERROR: the ledger in $RUN_DIR is byte for byte the one of the earlier run."
  echo "       Either the bridge did not run, or the same file was copied again."
  exit 1
fi
( cd "$MULTIFLOW" && git rev-parse HEAD ) > "$RUN_DIR/MULTIFLOW_COMMIT.txt"
docker logs compliance_bridge > "$RUN_DIR/bridge_log.txt" 2>&1
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$RUN_DIR/RUN_TIMESTAMP.txt"
echo "artefacts in $RUN_DIR"
ls -la "$RUN_DIR"

echo ""
echo "Proof complete. The containers keep running so you can explore:"
echo "   Kafdrop:  http://localhost:19000  (topic and the bridge consumer group)"
echo "   Shut down: cd $MULTIFLOW && PROTOTYPE_DIR=$PROTOTYPE_DIR docker compose down"
echo ""
echo "This is a new run: its timestamps and hashes differ from the published ones."
