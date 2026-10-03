#!/usr/bin/env bash
# =====================================================================
# 01_up_and_deploy.sh — phase 1: brings up the two-organisation test network and
# deploys the `compliance` chaincode as CHAINCODE-AS-A-SERVICE (CCaaS).
#
# CCaaS is the PRIMARY route (and the one that works on Docker Desktop): the
# chaincode image is built on the HOST, avoiding the peer-managed build that
# fails with 'broken pipe' on docker.proxy.sock (see ../MIGRATION_LOG.md).
# The peer-managed mode (deployCC) is kept as a commented fallback at the end.
#
# Org1MSP and Org2MSP are the two organisations (Org1 maps to TechMSP, Org2 to
# ComplianceMSP in the thesis). The AND policy makes both endorse every SubmitEvidence.
#
# The network is brought up with -ca: each organisation's identities are issued by
# its own Fabric CA, which is the configuration of the Gateway measurement the
# dissertation cites (see ../MIGRATION_LOG.md). Set FABRIC_CA=0 to fall back to
# cryptogen; gateway_measure.go records which of the two it found.
#
#   bash 01_up_and_deploy.sh
#
# Prerequisite: 00_setup_fabric.sh already run. If the pull or the daemon hangs,
# use 'docker desktop stop' followed by 'docker desktop start' ('restart' is not enough).
# =====================================================================
set -euo pipefail

WORKSPACE="$HOME/fabric-workspace"
SAMPLES="$WORKSPACE/fabric-samples"
TESTNET="$SAMPLES/test-network"
CC_SRC="$(cd "$(dirname "$0")/../chaincode" && pwd)"
CHANNEL="compliancechannel"
CCNAME="compliance"
IMAGETAG="2.5.10"
POLICY="AND('Org1MSP.peer','Org2MSP.peer')"
CA_FLAG=$([ "${FABRIC_CA:-1}" = "1" ] && echo "-ca" || echo "")

export PATH="$SAMPLES/bin:$PATH"
export FABRIC_CFG_PATH="$SAMPLES/config"

echo "=== 0/4 Align versions: tag $IMAGETAG images as ':latest' ==="
# The main-branch test network detects the version by running 'fabric-peer:latest'.
# Since $IMAGETAG is pinned (2.5 LTS), our images are tagged :latest so that the
# detection matches and does NOT pull 3.x ('binaries and images out of sync').
for repo in fabric-peer fabric-orderer fabric-tools fabric-ccenv fabric-baseos; do
  docker tag "hyperledger/${repo}:${IMAGETAG}" "hyperledger/${repo}:latest" 2>/dev/null || true
done
docker tag "hyperledger/fabric-ca:1.5.13" "hyperledger/fabric-ca:latest" 2>/dev/null || true

echo "=== 1/4 Tear down the previous network ==="
cd "$TESTNET"
./network.sh down || true

echo "=== 2/4 Bring up the two-org network and channel '$CHANNEL' (Fabric $IMAGETAG) ==="
# shellcheck disable=SC2086  # CA_FLAG is empty or a single word on purpose
./network.sh up createChannel $CA_FLAG -c "$CHANNEL" -i "$IMAGETAG"

echo "=== 3/4 Vendor the Go dependencies (offline, deterministic CCaaS build) ==="
( cd "$CC_SRC" && go mod vendor )

echo "=== 4/4 CCaaS deploy of chaincode '$CCNAME' with endorsement $POLICY ==="
echo "  source: $CC_SRC"
./network.sh deployCCAAS \
  -c "$CHANNEL" \
  -ccn "$CCNAME" \
  -ccp "$CC_SRC" \
  -ccep "$POLICY"

echo ""
echo "Network up with chaincode '$CCNAME' as CCaaS (two-org endorsement)."
echo "   Channel: $CHANNEL · Policy: $POLICY"
echo "   Chaincode containers: peer0org1_${CCNAME}_ccaas, peer0org2_${CCNAME}_ccaas"
echo "   Next: go run ../gateway/gateway_measure.go records.json pubkey.txt (the measurement"
echo "   the dissertation cites), or python3 02_submit_and_measure.py (CLI, upper bound)."
echo ""
echo "   [Peer-managed fallback, should the peer build ever work in this environment:"
echo "    ./network.sh deployCC -c $CHANNEL -ccn $CCNAME -ccp $CC_SRC -ccl go -ccep \"$POLICY\" -i $IMAGETAG ]"
