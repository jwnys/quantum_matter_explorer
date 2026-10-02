#!/usr/bin/env bash
# Clone the ITensor and XDiag sources into <repo>/third_party.
#
# These checkouts are a read-only reference mirror for the agent's `lookup_doc` tool,
# which greps them to answer questions about library symbols. The runtime packages the
# DMRG scripts use come from the Julia registry (see setup_julia.sh), not from here,
# so this mirror is optional: without it, lookup_doc simply reports that no library
# path is configured.
set -euo pipefail

TARGET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/third_party"

echo "Cloning ITensor and XDiag sources into $TARGET_DIR ..."
mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"

for repo in \
    https://github.com/ITensor/ITensors.jl.git \
    https://github.com/ITensor/ITensorMPS.jl.git \
    https://github.com/ITensor/ITensorDocs.jl.git \
    https://github.com/awietek/XDiag.jl.git
do
    name="$(basename "$repo" .git)"
    if [ ! -d "$name" ]; then
        git clone --depth 1 "$repo"
    else
        echo "$name already exists, pulling latest..."
        (cd "$name" && git pull)
    fi
done

echo "Done. config/config.yaml should point at it with:"
echo "  itensor_libraries_dir: third_party"
