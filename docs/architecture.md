# Architecture

QuantumMatterExplorer is a single deep agent in a tool-calling loop, built on
LangChain's [deepagents](https://docs.langchain.com/oss/python/deepagents/overview):
one strong model with good tools, a real filesystem, subagents it can spawn, and
automatic context compression. Given a Hamiltonian spec, it plans the study, writes
and runs Julia (ITensorMPS DMRG, XDiag exact diagonalization), detects phase
boundaries, identifies the order, does finite-size scaling, and writes a research
note with figures.

## The single agent

`src/agent.py::build_agent` wires `deepagents.create_deep_agent` with:

- **Model**: any provider via `src/llm/provider.py::build_llm` (default: a local vLLM
  server). Before use, `model.profile["max_input_tokens"]` is set from the configured
  context length so summarization triggers at a fraction of the window rather than at
  a fixed token count.
- **Backend**: `LocalShellBackend(root_dir=<run dir>, virtual_mode=True)`. The built-in
  filesystem tools (`read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep`) and
  `execute` operate on real files, run-dir-relative and sandboxed, and the custom tools
  resolve paths into the same space.
- **Custom tools**: `run_julia` (the DMRG instrument), `run_julia_batch` (many points
  as concurrent subprocesses, the fast survey and finite-size-scaling path),
  `run_python` (guarded Python execution for analysis and plotting), `validate`,
  `lookup_doc`, `update_run_summary`, and `finish` (the explicit done signal that
  writes the `.finished` sentinel the run driver stops on). These sit on top of the
  deepagents built-ins (`write_todos`, filesystem, `execute`, `task`,
  `compact_conversation`).
- **Subagents**: `data-analyst` (reads and summarizes large data, returns numbers) and
  `physics-critic` (an independent, skeptical reviewer), plus the automatic
  `general-purpose` one. Each runs in an isolated context and returns only a final
  report. The custom subagents carry the same path-safety and edit-regrounding
  middleware as the main agent.
- **Skills**: the files under `skills/`, one per stage of the study plus
  `itensor-dmrg` for code and `disorder` as a cross-cutting topic, loaded by
  progressive disclosure: only the manifest sits in the prompt, the body is read on
  demand. The system prompt carries control flow and the non-negotiable rules, the
  skills carry the method, and nothing appears in both. `SkillGateMiddleware` blocks a
  tool once (then releases) if its load-bearing skill has not been read.

## Middleware

| Middleware | Role |
|---|---|
| summarization (built-in) | compacts the conversation at 85% of the effective window; plus a manual `compact_conversation` tool |
| `IncrementalOutputNudge` | soft reminders on loop, edit-thrash, stale note, and stale RUN_SUMMARY signals |
| `PathSafeExecuteMiddleware` | normalizes recurring path confusions in `execute` commands (virtual leading-slash paths, run-dir path tangles, host-wide scans) |
| `EditRegroundMiddleware` | on a failed `edit_file`, returns the file's current content so the model corrects against reality instead of resubmitting a stale edit |
| `SkillGateMiddleware` | blocks a tool once until the relevant skill has been read |
| `HitlGateMiddleware` | with human-in-the-loop on, blocks full DMRG until the plan is reviewed |
| `SubagentLogMiddleware` | records every subagent call (prompt and reply) to `logs/subagents.jsonl` |
| `ContextOverflowClassifier` | reclassifies a vLLM context-overflow 400 into the error type deepagents' recovery handles |
| `ToolErrorGuard` | returns tool exceptions to the agent as error text instead of letting them end the run |
| `ImageReadGuard` | on non-vision models, stops image files from being read into the conversation (a text-only endpoint 400s unrecoverably) |
| rate limiting (optional) | `RateLimitRetryMiddleware` waits out provider 429s; `TokenRateLimitMiddleware` throttles to a tokens-per-minute budget |

The three crash guards (`ContextOverflowClassifier`, `ToolErrorGuard`,
`ImageReadGuard`) are registered on the deepagents harness profile rather than
appended per agent, because that is the only route that also covers the auto-created
`general-purpose` subagent. The optional rate-limit middleware is appended per agent.

## Tools (`src/tools/`)

| Tool | Role |
|---|---|
| `run_julia` | DMRG via ITensorMPS. `fresh=False` is a persistent REPL for probing; `fresh=True` a subprocess for full runs. Guards: refuses placeholder couplings; auto-reports convergence (truncation error, total Sz, final energy). |
| `run_julia_batch` | Runs one script over a list of `params,output` points as concurrent fresh subprocesses (capped by `julia.batch_max_parallel`). Each point is isolated, so one crash or timeout fails one point. Returns a JSON manifest with per-point status and convergence; full logs are written only for failed or oversized points (`logs/julia/`). |
| `run_python` | Python for analysis and plotting, with a timeout, a memory cap, and bounded output. |
| `validate` | sub-second Python/Julia syntax check before a launch. |
| `lookup_doc` | greps the local ITensor source mirror for a symbol's real signature. |
| `update_run_summary` | one-call append to `RUN_SUMMARY.md`, the durable results ledger. |
| `finish` | the explicit done signal: writes the `.finished` sentinel the run driver stops on. Called once, when the study is complete. |
| `request_plan_review`, `request_review` | human-in-the-loop checkpoints (registered only when HITL is on): write a review file, wait for the human, return their comments. |

## Planning (`plan.md`)

Planning is iterative: plan, execute, analyze, replan. `write_todos` is the short
tracker, and the elaborate plan lives in `plan.md` (mandate, fixed observable spec, DMRG
settings, evolving experiment design, revision log), reviewed by the physics-critic
and re-read at stage boundaries.

## Context management

The usual four moves, mostly provided by deepagents: write (system prompt for
always-on rules, files for state), select (`read_file` pagination, `grep`/`glob`,
skills), compress (auto-summarization plus large-tool-result offload), isolate
(subagents return only a concise report).

## Run flow (`main.py`)

Set the Julia and `QME_*` environment, create a timestamped `output/run_<stamp>/`
(copying input, config and skills in), start the loggers and a terminal tee,
auto-launch the vLLM server if configured, `build_llm`, `build_agent`, then the run
driver: `agent.stream(kickoff)` with a stable `thread_id` and an in-memory
checkpointer. The driver re-invokes a yielded-but-unfinished agent with a soft nudge,
and stops cleanly on the first of: the agent calling `finish` (the `.finished`
sentinel), a no-progress backstop (no new artifacts for `run.no_progress_iterations`
rounds), or the agent yielding with no tool calls. The `run.max_outer_iterations` cap
is a runaway backstop: on hitting it the driver sends one final synthesis nudge
rather than cutting the run off. A figure-reference integrity check runs at finalize,
then everything shuts down gracefully.

## Output run folder

```
output/run_<stamp>/
  input/  scripts/  params/  data/  plots/  note/research_note.md
  plan.md  RUN_SUMMARY.md  skills/  phase_diagram.json
  config/{<input config>, effective_config.yaml}
  logs/{interactions.jsonl, transcript.txt, stats.{jsonl,csv}, terminal.log,
        subagents.jsonl, verdicts.jsonl}
  conversation_history/  large_tool_results/   # summarization offload (deepagents)
```

The Julia project and depot are shared infrastructure (environment variables), not
under the run folder. A run is self-contained and survives a crash: the note and the
plots are written incrementally.

## Hard versus soft

Everything scientific is soft (strong prompt and skill guidance) except a few
objective guards: `run_julia` refuses non-numeric couplings and auto-reports
convergence, `finish` self-checks its preconditions, and `main.py` checks
figure-reference integrity at finalize. Promoting another invariant to a hard gate is
a localized change (a thin middleware), not a redesign.
