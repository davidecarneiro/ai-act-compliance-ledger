#!/usr/bin/env bash
# =====================================================================
# Replay of the platform's industrial datasets: Muvu_Janeiro (the reference)
# followed by Muvu_Marco. The bridge applies its illustrative drift indicator
# to the difference observed between the two months; nothing synthetic is added.
#
# Prerequisite: containers already running (run_multiflow_proof.sh done).
# It RESETS the bridge's working ledger ($MULTIFLOW/compliance_out/ledger.json)
# for a clean run on real data; the synthetic run is already archived in its own
# folder. MULTIFLOW and EXPERIMENTS_DIR are honoured as in run_multiflow_proof.sh.
#   bash prototype/multiflow_bridge/inject_real_datasets.sh
# =====================================================================
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../delivery_paths.sh"
MULTIFLOW="${MULTIFLOW:-$HOME/Desktop/multiflow}"
RUN_DIR="$(run_dir multiflow_run_real)"

echo "=== 1/4 Restart with a clean ledger (a run dedicated to real data) ==="
docker exec compliance_bridge sh -c 'rm -f /out/ledger.json' 2>/dev/null || true
cd "$MULTIFLOW" && docker compose restart compliance-bridge && sleep 8

echo "=== 2/4 Inject Muvu_Janeiro then Muvu_Marco (ws/server.js format) ==="
for DS in Muvu_Janeiro.csv Muvu_Marco.csv; do
  docker exec -i kafka_server kafka-console-producer \
    --bootstrap-server localhost:9092 --topic phd_kafka < <(
      sed 's/"/\\"/g; s/^/{"csv_data": "/; s/$/"}/' "$MULTIFLOW/datasets/$DS")
  echo "  $DS injected ($(wc -l < "$MULTIFLOW/datasets/$DS") rows)"
done

echo "=== 3/4 Wait for processing and verify ==="
sleep 15
docker logs --tail 8 compliance_bridge
docker exec compliance_bridge python3 /bridge/verify_output.py

echo "=== 4/4 Archive the run (its own folder: multiflow_run_real) ==="
mkdir -p "$RUN_DIR"
# As in run_multiflow_proof.sh: what is checked is the chain itself, not
# whether the folder is empty.
ANTES=""
[ -f "$RUN_DIR/ledger.json" ] && ANTES=$(shasum -a 256 "$RUN_DIR/ledger.json" | cut -d" " -f1)
[ -d "$MULTIFLOW/compliance_out" ] || {
  echo "ERROR: $MULTIFLOW/compliance_out does not exist; the bridge produced no evidence."; exit 1; }
cp "$MULTIFLOW"/compliance_out/* "$RUN_DIR/" && rm -f "$RUN_DIR"/*.lock || {
  echo "ERROR: copying the artefacts to $RUN_DIR failed."; exit 1; }
[ -s "$RUN_DIR/ledger.json" ] || {
  echo "ERROR: $RUN_DIR/ledger.json is missing or empty."; exit 1; }
if [ -n "$ANTES" ] && [ "$ANTES" = "$(shasum -a 256 "$RUN_DIR/ledger.json" | cut -d" " -f1)" ]; then
  echo "ERROR: the ledger is byte for byte the one of the earlier run."; exit 1
fi
( cd "$MULTIFLOW" && git rev-parse HEAD ) > "$RUN_DIR/MULTIFLOW_COMMIT.txt"
docker logs compliance_bridge > "$RUN_DIR/bridge_log.txt" 2>&1
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$RUN_DIR/RUN_TIMESTAMP.txt"
echo "artefacts in $RUN_DIR"
echo ""
echo "Expected, from the published run on these datasets: 29 events, 12 approved"
echo "and 17 escalated. The January batches are a mix (12 approved, 7 escalated);"
echo "every March batch is escalated, the operational change between the months."
