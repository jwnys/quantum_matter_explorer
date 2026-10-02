# Installing Julia

The agent shells out to Julia for every DMRG run, every REPL probe, and every
pre-flight `validate` parse check. Use a plain official Julia binary, not the
`juliaup` shim.

## Why not juliaup

`juliaup`'s `julia` launcher takes a global config lock on every invocation and
periodically runs a background self-update. On shared machines where juliaup's
state lives on NFS, that lock can hang (juliaup issues
[#598](https://github.com/JuliaLang/juliaup/issues/598),
[#254](https://github.com/JuliaLang/juliaup/issues/254)). When it does, every
Julia call in the pipeline times out and the agent loops on code that was never
broken. The Julia manual itself recommends the
[generic official binaries](https://docs.julialang.org/en/v1/manual/installation/)
for Linux servers.

## Setup

Run the provisioning script once per machine:

```bash
bash docs/setup_julia.sh
```

It downloads and installs an official Julia binary (reusing a local juliaup copy
if one exists), then provisions and precompiles the package stack the agent uses
(`ITensors`, `ITensorMPS`, `JSON3`, `XDiag`) into the Julia project at
`output/julia_project/`, matching `julia.project_dir` in the config. It finishes
by printing the two values to set in `config/config.yaml`.

Defaults, overridable via environment variables:

- `JULIA_VERSION` (default `1.12.6`)
- `JULIA_PREFIX`: install dir (default `$HOME/.local/opt`)
- `JULIA_DEPOT`: package depot. Unset means the default `~/.julia`. On clusters
  where `$HOME` is a slow or quota-limited network filesystem, point this at
  local disk.
- `JULIA_PROJECT_DIR`: project to provision (default `<repo>/output/julia_project`)

The script is idempotent: re-running with everything present is a fast no-op.

## The source mirror for lookup_doc

`third_party/` is a separate, read-only source mirror consumed only by the
agent's `lookup_doc` tool (configured by `julia.itensor_libraries_dir`). It is
populated by its own script:

```bash
bash docs/download_libraries.sh
```

which clones ITensors.jl, ITensorMPS.jl, ITensorDocs.jl and XDiag.jl from
GitHub into `third_party/`. It is optional: without it, `lookup_doc` reports
that no library path is configured and the rest of the agent works normally.
On a fresh machine run both scripts.

## Wire it into the config

Set the printed paths in `config/config.yaml` under `julia:`:

```yaml
julia:
  executable: /home/<user>/.local/opt/julia-1.12.6/bin/julia
  depot_path: null          # or the JULIA_DEPOT you chose
```

`main.py` exports `depot_path` as `JULIA_DEPOT_PATH` for every Julia subprocess,
and `executable` is used by the `run_julia`, `run_julia_batch` and `validate`
tools. Nothing in the pipeline touches `juliaup` after this.
