# QuantumMatterExplorer

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Julia 1.12](https://img.shields.io/badge/julia-1.12-9558B2.svg)](https://julialang.org/)
[![vLLM](https://img.shields.io/badge/serving-vLLM-orange.svg)](https://github.com/vllm-project/vllm)
[![arXiv](https://img.shields.io/badge/arXiv-2610.32001-b31b1b.svg)](https://arxiv.org/abs/2610.32001)

QuantumMatterExplorer is an autonomous research agent for quantum many-body physics.
Given a Hamiltonian it has never seen, it maps the ground-state phase diagram with
DMRG (ITensorMPS/Julia) and exact diagonalization (XDiag): it plans the study, writes
and runs the simulation code, detects phase boundaries, identifies the order in each
region, performs finite-size scaling, and writes everything up as a research note
with figures, the way a careful PhD student would.

The system is a single deep agent (built on LangChain
[deepagents](https://docs.langchain.com/oss/python/deepagents/overview)): one strong
model in a tool-calling loop, with a real filesystem, custom simulation tools, two
helper subagents (a data analyst and an independent physics critic), and a library of
"skills" that encode the scientific method one stage at a time. The backbone model is
pluggable: a local model served by vLLM, or a cloud API (Anthropic, OpenAI, DeepSeek,
and others). See [docs/architecture.md](docs/architecture.md) for how it fits together.

## Installation

Tested on Linux with Python 3.13 (3.11+ required). Running a local model needs CUDA
GPUs. With a cloud provider no GPU is needed.

Clone the repository:

```bash
git clone https://github.com/jwnys/quantum_matter_explorer.git
cd quantum_matter_explorer
```

### 1. The Python environment

One environment runs everything. Add the `[vllm]` extra if you will serve a local
model on this machine, and leave it off for cloud-only use:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[vllm]"     # local models + everything else
# or: .venv/bin/pip install -e .       # cloud providers only
```

### 2. Julia and the ITensor stack

DMRG runs through Julia. One script installs an official Julia binary and
precompiles the packages the agent uses (ITensors, ITensorMPS, JSON3, XDiag):

```bash
bash docs/setup_julia.sh
```

It prints the `executable` and `depot_path` values to set in `config/config.yaml`.
Optionally, also clone the ITensor sources that the agent's `lookup_doc` tool greps
for function signatures:

```bash
bash docs/download_libraries.sh     # clones into ./third_party
```

Details and cluster-specific advice are in [docs/install_julia.md](docs/install_julia.md).

### 3a. A local model with vLLM

With the `[vllm]` extra installed, nothing else is needed: `main.py` launches the
server from the same environment and stops it at the end of the run.

If you prefer to keep the inference server in its own environment (useful on
clusters, where the two stacks are easier to rebuild separately), create one from
`requirements-server.txt` and point the launcher at it, either in `config/config.yaml`
(`llm.vllm.server_python: <venv>/bin/python`) or via the environment:

```bash
export QME_VLLM_PYTHON=~/.venvs/vllm-server/bin/python
```

The default config serves `google/gemma-4-31B-it`. Gemma is a gated model, so accept
its license on [Hugging Face](https://huggingface.co/google/gemma-4-31B-it) once and
put a `HF_TOKEN` in `.env` (see below). Weights download automatically on first
launch into your Hugging Face cache (set `llm.vllm.download_dir` to use a different
location). `main.py` starts and stops the server by itself.

### 3b. Or a cloud provider

No GPU or server environment needed. Copy the secrets template and fill in the key
for the provider you use:

```bash
cp .env.example .env    # then edit .env
```

`.env` is gitignored and loaded automatically.

## Quick start

Run the example study, the XXZ chain in a field, with the default local-vLLM config:

```bash
.venv/bin/python main.py --input input/xxz_chain.md
```

The agent launches the model server, drafts a plan, has its physics critic review the
plan, validates its Hamiltonian against exact diagonalization, then surveys the phase
diagram and keeps going until the study is written up. Everything lands in a
timestamped folder:

```
output/run_<timestamp>/
  note/research_note.md    the write-up, with figures embedded
  phase_diagram.json       the result in machine-readable form
  plots/  data/  scripts/  params/
  plan.md  RUN_SUMMARY.md  logs/
```

A full study takes hours, so for a first look you may want `--dry-run`, which builds
the agent and validates the wiring without starting the study:

```bash
.venv/bin/python main.py --input input/xxz_chain.md --dry-run
```

Other useful invocations:

```bash
# a different Hamiltonian (Markdown or LaTeX spec, see input/)
.venv/bin/python main.py --input input/j1j2_chain.tex

# a cloud backbone instead of local vLLM
.venv/bin/python main.py --input input/xxz_chain.md --config config/config_opus5.yaml

# long unattended run
nohup .venv/bin/python main.py --input input/blbq_spin1_j1j2.md > nohup.out 2>&1 &

# kill one run and all its children (server, Julia workers), by run id
./kill_run.sh run_20260101_120000
```

A run always terminates on its own: the agent calls its `finish` tool when the study
is complete, and a no-progress backstop stops a run that stalls.

## Configuration

`config/config.yaml` is the default (local vLLM). The other files in `config/` are
tuned per-model variants: `config_opus5.yaml` and `config_sonnet5.yaml` (Anthropic),
`config_gpt56luna.yaml` (OpenAI), `config_deepseek.yaml` (DeepSeek),
`config_qwen36_27b.yaml` and `config_gptoss120b.yaml` (other local models). Pick one
with `--config`, or override pieces on the command line (`--provider`, `--model`,
`--julia-timeout`, `--julia-parallel`).

The main sections:

- `llm:` chooses the provider and its settings (model, context window, sampling,
  parsers for tool calls and reasoning traces). Set `llm.vision: true` only for
  models that accept images, so the agent may look at its own plots.
- `agent:` tunes the deep agent: the subagents, the skill library and its read
  gates, the soft nudges, context compaction, optional rate limiting.
- `julia:` points at the Julia binary, depot and project, and sets the per-call
  time budget and the batch parallelism (`batch_max_parallel` times `threads`
  should stay within your core count).
- `run:` output directory and the outer-loop backstops.

Several runs can share a machine: each reaps only its own leftover server, a busy
port resolves to the next free one, and parallel local runs just need distinct
`gpu_id` settings.

### Human-in-the-loop mode

By default the agent is fully autonomous. With `--hitl` (or
`agent.human_in_the_loop: true`) it pauses twice: after drafting its plan and before
finishing. At each checkpoint it writes a `HUMAN_REVIEW.md` in the run folder and
waits. Write your comments under `## Your comments` and set `STATUS: GO`. An empty
comment box with `STATUS: GO` means approve and proceed. Any non-empty comment is
treated as a revision request, and the agent comes back to the gate after addressing
it. Optional webhooks (`agent.hitl_notify_urls`) ping you when a review is waiting.

### Continuing a finished run

A finished run can be picked up and taken further. The continuation is a new run in
a new folder that inherits the old one's results. The parent is never modified.

```bash
.venv/bin/python main.py --resume output/run_20260101_120000 \
    --brief "Re-run the small-D region with the sector constrained, then map the gap."
```

`--input` and `--config` come from the parent. The new agent is briefed as a fresh
investigator: it inherits the data and the note as claims to check, not as settled
fact, and by default it stops at the plan-review gate so you can steer it (use
`--no-hitl` to run a continuation unattended). The resume records provenance in
`config/resume_from.json`, including fingerprints of the prompt and skill versions.
On a resume, `--julia-timeout` is often the flag to raise: the parent's points that
timed out are exactly the ones a continuation wants to reach.

### A readable PDF of the note

```bash
.venv/bin/python scripts/note_to_pdf.py output/run_20260101_120000
```

writes `report/report.tex` and `report.pdf` into the run folder. An LLM reformats
the note into a proper document but is forbidden from touching any number or claim,
and the output is rejected in favour of a mechanical conversion if any value from
the note goes missing. `--no-llm` selects the mechanical conversion directly, and
the whole script is read-only with respect to the run.

### Inspecting a run

```bash
.venv/bin/python -m qme.analysis output/run_20260101_120000
```

prints an overview (tool usage, tokens, timing, data points) and saves diagnostic
plots of the run's trajectory.

## Make it your own

The agent harness is deliberately separate from the science, so most adaptation
happens in plain Markdown and YAML rather than in code.

- **The skills are the method.** Everything the agent knows about running a phase
  diagram study (conventions, validation, observables, transitions, scaling,
  reporting) lives in `qme/skills/*/SKILL.md`, one file per stage.
  [qme/skills/README.md](qme/skills/README.md) is the maintainer's guide: how the files are
  written, where a new rule goes, and a glossary. Edit them, disagree with them, add
  your group's own rules. `scripts/check_skills.py` lints the library for the
  structural conventions.
- **New problems are new input files.** An input spec is a short Markdown or LaTeX
  document stating the Hamiltonian, the operators, and the parameter ranges to
  explore. The files in `input/` are the templates to copy.
- **The system prompt** (`qme/prompts.py`) carries the workflow and the
  non-negotiable rules, including the prompts of the data-analyst and physics-critic
  subagents.
- **Another backbone** is a config file away if it speaks an existing API, or one
  builder function in `qme/llm/provider.py` if it does not.
- **Another domain entirely** is also within reach: the harness (planning, skills,
  gates, critics, run driver) is not specific to DMRG. Swap the simulation tool in
  `qme/tools/`, the skill library and the prompts, and the same machinery drives a
  different instrument.

## Repository layout

```
main.py                  entry point: run folder, server lifecycle, run driver
qme/agent.py             deep-agent assembly: tools, subagents, middleware
qme/prompts.py           system prompt + subagent prompts
qme/tools/               the agent's tools: run_julia, run_julia_batch, run_python, validate, ...
qme/skills/              the method, one skill per stage of a study
qme/llm/                 provider layer (vLLM server manager, cloud builders)
qme/obs/                 logging: transcript, stats, subagent records
qme/analysis.py          post-hoc run inspection (plots, summaries)
input/                   example Hamiltonian specs
config/                  per-model configurations
scripts/                 command-line helpers: check_skills.py (skill lint), note_to_pdf.py
tests/                   pytest suite for the guards and middleware
docs/                    architecture, Julia install, setup scripts
```

## Citation

If you use this code, please cite
[the paper](https://arxiv.org/abs/2610.32001):

```bibtex
@misc{nys2026quantummatterexplorerautonomousagentdiscovery,
      title={QuantumMatterExplorer: An Autonomous Agent for the Discovery of Quantum Many-Body Phases of Matter},
      author={Jannes Nys and Andrew Jreissaty and Juan Carrasquilla},
      year={2026},
      eprint={2610.32001},
      archivePrefix={arXiv},
      primaryClass={quant-ph},
      url={https://arxiv.org/abs/2610.32001},
}
```

## License

Apache License 2.0. See [LICENSE](LICENSE).
