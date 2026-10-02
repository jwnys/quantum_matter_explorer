#!/usr/bin/env bash
#
# docs/setup_julia.sh: provision Julia and the ITensor stack for QuantumMatterExplorer.
#
# Installs a plain official Julia binary (downloaded from julialang.org if it is not
# already present), then provisions and precompiles the packages the agent's DMRG and
# ED scripts use (ITensors, ITensorMPS, JSON3, XDiag) into the project directory that
# config/config.yaml points at. Doing this once up front means the first real run does
# not pay the install and precompile cost mid-study.
#
# The agent should not run through the juliaup shim: its launcher takes a global
# config lock on every invocation and periodically self-updates, and on machines where
# that state lives on NFS the lock can hang, which makes every Julia call time out
# (juliaup issues #598, #254). A plain official binary has no such lock.
#
# Defaults, overridable via environment variables:
#   JULIA_VERSION      Julia version to install              (default 1.12.6)
#   JULIA_PREFIX       install prefix                        (default $HOME/.local/opt)
#   JULIA_DEPOT        package depot; leave unset to use the default ~/.julia.
#                      On clusters where $HOME is a slow or quota-limited network
#                      filesystem, point this at local disk.
#   JULIA_PROJECT_DIR  Julia project to provision            (default <repo>/output/julia_project)
#
# Idempotent: re-running with everything already present is a fast no-op.
# After running, set the printed paths in config/config.yaml under `julia:`.
#
set -euo pipefail

VER="${JULIA_VERSION:-1.12.6}"
PREFIX="${JULIA_PREFIX:-$HOME/.local/opt}"
DEST="$PREFIX/julia-$VER"
DEPOT="${JULIA_DEPOT:-}"

echo ">> Target install : $DEST"
echo ">> Depot          : ${DEPOT:-(default ~/.julia)}"

if [ -x "$DEST/bin/julia" ]; then
  echo ">> Julia already installed at $DEST, skipping download."
else
  # Reuse a matching official binary that juliaup may already have downloaded.
  SRC="$(ls -d "$HOME"/.julia/juliaup/julia-"$VER"*/ 2>/dev/null | head -1 || true)"
  if [ -n "${SRC:-}" ] && [ -x "${SRC}bin/julia" ]; then
    echo ">> Copying existing local Julia from juliaup install: $SRC"
    mkdir -p "$PREFIX"
    cp -a "${SRC%/}" "$DEST"
  else
    MAJMIN="${VER%.*}"
    URL="https://julialang-s3.julialang.org/bin/linux/x64/${MAJMIN}/julia-${VER}-linux-x86_64.tar.gz"
    echo ">> Downloading $URL"
    mkdir -p "$PREFIX"
    TMPTAR="$(mktemp --suffix=.tar.gz)"
    curl -fL --retry 3 -o "$TMPTAR" "$URL"
    tar -xzf "$TMPTAR" -C "$PREFIX"
    rm -f "$TMPTAR"
    [ -x "$DEST/bin/julia" ] || { echo "!! extraction did not produce $DEST/bin/julia"; exit 1; }
  fi
fi

if [ -n "$DEPOT" ]; then
  mkdir -p "$DEPOT"
  export JULIA_DEPOT_PATH="$DEPOT"
fi

echo ">> Verifying the binary (bypasses juliaup, should be instant):"
"$DEST/bin/julia" --startup-file=no --version

# Provision and precompile the package stack into the project the agent uses.
# First run downloads and precompiles, which can take several minutes; re-runs
# are fast no-ops.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJ="${JULIA_PROJECT_DIR:-$REPO_ROOT/output/julia_project}"
mkdir -p "$PROJ"
echo ">> Provisioning ITensors/ITensorMPS/JSON3/XDiag into project: $PROJ"
"$DEST/bin/julia" --startup-file=no --project="$PROJ" -e '
    using Pkg
    Pkg.add(["ITensors", "ITensorMPS", "JSON3", "XDiag"])
    Pkg.instantiate()
    Pkg.precompile()
    using ITensors, ITensorMPS, LinearAlgebra, JSON3   # force-load = smoke test
    println(">> ITensor stack loaded OK")'

# XDiag (the exact-diagonalization cross-check engine) is force-loaded in a separate
# process: ITensors and XDiag both export OpSum/Op, so they must never share a session
# (the agent's ED scripts use `using XDiag` alone). This also smoke-tests the setup.
"$DEST/bin/julia" --startup-file=no --project="$PROJ" -e '
    using XDiag
    set_verbosity(0)
    b = Spinhalf(2); o = OpSum(); o += "J" * Op("SdotS", [1, 2]); o["J"] = 1.0
    e0 = eigval0(o, b)
    @assert abs(e0 - (-0.75)) < 1e-12
    println(">> XDiag loaded OK (2-site singlet energy check passed)")'

echo
echo ">> Done. Set these in config/config.yaml under julia:"
echo "     executable: $DEST/bin/julia"
if [ -n "$DEPOT" ]; then
  echo "     depot_path: $DEPOT"
else
  echo "     depot_path: null"
fi
