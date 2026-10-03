#!/usr/bin/env bash
# =====================================================================
# 00_setup_fabric.sh — migration phase 0: installs Hyperledger Fabric.
#
# Installs fabric-samples, the binaries and the Docker images into an EXTERNAL
# workspace (~/fabric-workspace, NOT versioned) to keep the thesis repository small.
# Reproducible: anyone can run this to recreate the environment.
#
#   bash 00_setup_fabric.sh
#
# Requirements (audited in MIGRATION_LOG.md): Docker running, Go, curl, git.
# Intel MacBook (x86_64): native images, no arm64 friction.
# =====================================================================
set -euo pipefail

FABRIC_VERSION="2.5.10"
CA_VERSION="1.5.13"
WORKSPACE="$HOME/fabric-workspace"

echo "=== Phase 0: Hyperledger Fabric ${FABRIC_VERSION} setup ==="
mkdir -p "$WORKSPACE"
cd "$WORKSPACE"

if [ ! -f install-fabric.sh ]; then
  echo "-> fetching the official install-fabric.sh"
  curl -sSL https://raw.githubusercontent.com/hyperledger/fabric/main/scripts/install-fabric.sh -o install-fabric.sh
  chmod +x install-fabric.sh
fi

echo "-> installing binaries, images and samples (Fabric ${FABRIC_VERSION}, CA ${CA_VERSION})"
echo "  (large download; this can take several minutes)"
./install-fabric.sh --fabric-version "${FABRIC_VERSION}" --ca-version "${CA_VERSION}" binary docker samples

echo ""
echo "=== Verification ==="
"$WORKSPACE/bin/peer" version 2>&1 | head -3 || echo "WARNING: peer binary not found"
echo "Fabric images:"
docker images | grep -i hyperledger || echo "WARNING: no hyperledger images"
echo ""
echo "Phase 0 complete. test-network at: $WORKSPACE/fabric-samples/test-network"
echo "   Next: bring up the two-org network (see MIGRATION_LOG.md, phase 1)."
