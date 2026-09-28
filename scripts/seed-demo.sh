#!/usr/bin/env sh
# Re-create workspace/demo from the pristine template (discarding agent changes).
set -eu
cd "$(dirname "$0")/.."
rm -rf workspace/demo
mkdir -p workspace
cp -r examples/demo workspace/demo
echo "workspace/demo reset."
