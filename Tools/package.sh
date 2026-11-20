#!/usr/bin/env bash
# Build a standalone HeatCheck.app into Build/Packaged/Mac.
set -euo pipefail
source "$(dirname "$0")/common.sh"
"$UE_UAT" -WaitForUATMutex BuildCookRun -project="$UPROJECT" -platform=Mac -clientconfig=Development \
  -build -cook -stage -pak -archive -archivedirectory="$PROJECT_DIR/Build/Packaged" -noP4 -utf8output -unattended
# The archived .app can come out binary-only; the staged .app is the complete, self-contained one.
rm -rf "$PROJECT_DIR/Build/Packaged/Mac/HeatCheck.app"
mkdir -p "$PROJECT_DIR/Build/Packaged/Mac"
ditto "$PROJECT_DIR/Saved/StagedBuilds/Mac/HeatCheck.app" "$PROJECT_DIR/Build/Packaged/Mac/HeatCheck.app"
echo "Packaged build: $PROJECT_DIR/Build/Packaged/Mac/HeatCheck.app"
