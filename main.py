"""
main.py
Entry point for QuantumMatterExplorer. Owns the run folder, the LLM-server
lifecycle, and the autonomous run driver around the single deep agent.

  python3 main.py --input input/xxz_chain.md
  python3 main.py --input input/j1j2_chain.tex --provider anthropic

Run it from the project virtual environment. With the [vllm] extra installed,
the model server runs from the same environment; alternatively point
llm.vllm.server_python (or QME_VLLM_PYTHON) at a separate server environment.
"""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import time
import shutil
from pathlib import Path
from typing import Any, Optional

import typer
import yaml
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer(name="qme", help="QuantumMatterExplorer: a deep agent for autonomous "
                                   "discovery of quantum many-body phases of matter",
                  add_completion=False)


KICKOFF = """You are starting a new, long, autonomous DMRG study of the following Hamiltonian.
Today's date is {date}. Use this real date for any timestamps in plan.md / the note / logs (never a placeholder).

INPUT ({fmt}):
------------------------------------------------------------
{raw_input}
------------------------------------------------------------

Work in the current run directory. Begin by drafting `plan.md` (mandate + observable spec + DMRG
settings + the Stage-1 coarse-survey design. Give a one-line rationale for each design choice and state
the candidate phases you expect; keep the spec tables compact), lay out a short `write_todos` checklist,
and get a `physics-critic` review of the plan before spending compute. Then run the study: coarse survey,
detect boundaries, discover the order, refine + finite-size scaling. Open the note with a FULL
`## Introduction` (write out the Hamiltonian, define every symbol, state the research question), not a
one-liner, and write each finding as explanatory PROSE, not a bare table. Update `note/research_note.md`,
the figures in `plots/`, and `RUN_SUMMARY.md` after EVERY experiment. Keep `RUN_SUMMARY.md` current
through the FSS/analysis stages too, not just the early survey. Keep working until the phase diagram is
fully characterized and written up with a `## Phase diagram` and `## Conclusion`."""


RESUME_KICKOFF = """You are taking over a study that another investigator already ran and closed.
Today's date is {date}. Use this real date for any timestamps in plan.md / the note / logs.

You are NOT continuing your own work. You arrive fresh. Their run directory is now yours: their
`plan.md`, `RUN_SUMMARY.md`, `note/research_note.md`, `data/`, `scripts/` and `plots/` are all here,
and you inherit them as a starting position, not as settled fact.

ORIGINAL INPUT ({fmt}):
------------------------------------------------------------
{raw_input}
------------------------------------------------------------

THEY STOPPED BECAUSE:
{parent_reason}

WHAT THE HUMAN WANTS FROM THIS CONTINUATION:
{human_brief}

Everything you need has already been copied into YOUR run directory. Work only there, with
run-dir-relative paths, exactly as in a fresh run. The previous run's own folder still exists
elsewhere on disk as read-only history: never write to it, never read from it, and never construct
an absolute path to it. If you find one recorded anywhere, it is provenance for a human, not a
location for you to touch.

Start with two documents: `RUN_SUMMARY.md` (what they ran, stage by stage) and
`note/research_note.md` (what they concluded and what they said was missing). Their note's stated
limitations are usually the task list. Their `plan.md` is preserved as `plan_previous.md`; yours is
a fresh `plan.md`.

Trust the note over the JSON. `note/research_note.md` is the most up to date and most detailed
record of what was found, while the inherited `phase_diagram.json` is a coarse summary written
from it at the end of a run and routinely left unrevised while the note is edited around it, so
it can be both cruder and older. Take the phases, the boundaries and the reasoning from the note,
and fix the JSON where the two disagree.

Then read `scripts/` before writing any of your own, and check any number you intend to rely on or
dispute, with one `run_python` pass over `data/` rather than `read_file` on the dumps. What you must
not do is re-run their survey to reproduce results they already have: inherit those, and spend the
budget on what is missing.

Their settings are not yours. The bond dimensions, cutoffs and per-call time limits recorded in the
inherited data say what the previous investigator's run could afford. The tool descriptions state
the limits actually in force here, and they may be more generous. Something they deferred as too
expensive can be routine for you.

Their conclusions are a previous investigator's claims, not yours. Where their evidence does not
support a label, downgrade it. Where they declined a label the data does support, say so and
measure it. Disagreeing with them is in scope and is not a contradiction to explain away.

FINISHING. The note you inherited already has a `## Phase diagram` and a `## Conclusion`, so it
will look finished before you have done anything. It is not yours until you have revised it.
Update `note/research_note.md` and `RUN_SUMMARY.md` as you go, exactly as in a fresh study: every
result you add gets its figure and its prose, and every claim you revise or withdraw is rewritten
rather than left standing next to your new data. Rewrite `phase_diagram.json` last, from the note as
it then stands. Only then call `finish`. Do not call it on the strength of the previous
investigator's write-up.

{first_action}"""


# Two ways to continue a run. The gated variant waits for a human at the plan checkpoint. The
# unattended variant takes the brief up front and runs straight through. The distinction matters
# because `request_plan_review` is only registered when human_in_the_loop is on (qme/agent.py),
# so telling an unattended run to call it points it at a tool that does not exist.
FIRST_ACTION_GATED = """FIRST ACTION, before any compute: write a fresh `plan.md` for this continuation, starting from
`plan_previous.md` (theirs - read it, do not edit it): what you are keeping,
what you are re-examining, what you are adding, and why - then call `request_plan_review` and wait.
The human will reply in the review file. Only after that gate clears do you spend compute."""

FIRST_ACTION_UNATTENDED = """FIRST ACTION, before any compute: write a fresh `plan.md` for this continuation, starting from
`plan_previous.md` (theirs - read it, do not edit it): what you are keeping,
what you are re-examining, what you are adding, and why, with the brief above folded in as the
priority. Nobody is going to review it. There is no plan-review gate in this run and no
`request_plan_review` tool, so do not look for one and do not wait: write the plan, then start.

Because nothing will catch you, be stricter than usual about the two things a reviewer would have
caught. Anything the brief asks for that you decide NOT to do gets a line in `plan.md` saying so and
why. Anything you inherit and keep relying on gets checked before you build on it."""

# Figure-reference integrity check, run at finalize.
_IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def figure_reference_check(run_dir: Path) -> list[str]:
    """Return a list of broken `![](...)` references in the research note: targets
    that don't exist on disk or are empty."""
    note = run_dir / "note" / "research_note.md"
    if not note.exists():
        return []
    broken: list[str] = []
    for rel in _IMG_RE.findall(note.read_text(encoding="utf-8", errors="replace")):
        target = (note.parent / rel).resolve()
        if not target.exists():
            broken.append(f"{rel} (missing)")
        elif target.stat().st_size == 0:
            broken.append(f"{rel} (empty)")
    return broken


def _count_tool_calls(messages: list) -> int:
    from langchain_core.messages import AIMessage
    return sum(len(m.tool_calls or []) for m in messages if isinstance(m, AIMessage))


def find_parent_config(parent: Path) -> Optional[Path]:
    """The config a --resume continuation starts from. Prefer the parent's effective
    config (what actually ran, CLI overrides included); fall back to the
    generated_config.yaml name that runs from older versions of this tool carry."""
    for cand in ("config/effective_config.yaml", "config/generated_config.yaml"):
        if (parent / cand).exists():
            return parent / cand
    return None


def _artifact_fingerprint(run_dir: Path) -> tuple:
    """A cheap signature of all the run's durable artifacts (per-dir file counts plus latest
    mtimes; per-file sizes plus mtimes). The outer loop compares it across iterations to detect
    an agent that keeps making tool calls without changing anything on disk. Tracking the full
    set (scripts/params/plan.md too, not just data/plots/note) is deliberate: a run still in
    setup or debugging IS progressing, since it writes scripts and params, so it must not trip
    the backstop. Only a genuinely idle agent, where nothing changes anywhere, does."""
    parts: list = []
    # Plots are matched with a bare "*": the figures may be .png, .svg or .pdf depending on the
    # plotting script, and a narrower pattern here would make active plot-making invisible to
    # the fingerprint and misclassify a working run as converged.
    for sub, pat in (("data", "*.json"), ("plots", "*"), ("scripts", "*"), ("params", "*")):
        files = list((run_dir / sub).glob(pat))
        latest = max((f.stat().st_mtime for f in files), default=0.0)
        parts.append((len(files), round(latest, 1)))
    for rel in ("note/research_note.md", "RUN_SUMMARY.md", "plan.md"):
        p = run_dir / rel
        if p.exists():
            st = p.stat()
            parts.append((st.st_size, round(st.st_mtime, 1)))
        else:
            parts.append((0, 0.0))
    return tuple(parts)


@app.command()
def main(
    input_file: Optional[Path] = typer.Option(None, "--input", "-i", exists=True,
                                     help="Hamiltonian description (Markdown or LaTeX). "
                                          "Optional with --resume (taken from the parent run)."),
    config_file: Path = typer.Option(Path("config/config.yaml"), "--config", "-c"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p"),
    model: Optional[str] = typer.Option(None, "--model", "-m"),
    output_dir: Optional[Path] = typer.Option(None, "--output", "-o"),
    hitl: Optional[bool] = typer.Option(
        None, "--hitl/--no-hitl",
        help="Human-in-the-loop review at the plan + final checkpoints (overrides config for this run)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Build the agent and validate wiring; don't run."),
    resume: Optional[Path] = typer.Option(
        None, "--resume", exists=True, file_okay=False,
        help="Continue a finished run: copies its directory to a NEW run dir and restarts the agent "
             "as a fresh investigator briefed from RUN_SUMMARY.md + the note. The parent is untouched."),
    brief: Optional[str] = typer.Option(
        None, "--brief", help="With --resume: what you want from the continuation, either as text or "
                              "as a path to a file holding it. With HITL on (the default) you can "
                              "also leave it out and say it at the plan-review gate instead; with "
                              "--no-hitl this is the only instruction the run gets."),
    force: bool = typer.Option(False, "--force", help="With --resume: allow changing provider/model."),
    julia_parallel: Optional[int] = typer.Option(
        None, "--julia-parallel",
        help="Override julia.batch_max_parallel (how many DMRG points a batch runs at once). Each "
             "point also takes julia.threads cores and about 1 GB, so the product of the two is the "
             "core count a full batch asks for. DMRG is most of the wall clock in a study, so this "
             "is the dial that buys a longer per-call budget back."),
    julia_timeout: Optional[int] = typer.Option(
        None, "--julia-timeout",
        help="Override julia.run_timeout_seconds (the per-DMRG-call wall-clock budget). On a resume "
             "this is the usual thing to raise: the parent's points that timed out are exactly the "
             "ones a continuation wants to reach."),
) -> None:
    # Resume: the parent run supplies the config and the spec.
    parent_reason = ""
    if resume is not None:
        resume = resume.resolve()
        parent_cfg = find_parent_config(resume)
        missing = [f for f in ("RUN_SUMMARY.md", "note/research_note.md")
                   if not (resume / f).exists()]
        if parent_cfg is None:
            missing.append("config/effective_config.yaml")
        if missing:
            raise typer.BadParameter(f"--resume {resume}: not a resumable run, missing {missing}")
        if (provider or model) and not force:
            raise typer.BadParameter(
                "--resume with --provider/--model changes the backbone mid-study, which makes the "
                "result uninterpretable. Pass --force if that is really what you want.")
        config_file = parent_cfg                                 # parent config is the base
        if input_file is None:                                   # spec travels with the run
            cands = [f for f in sorted((resume / "input").glob("*")) if f.is_file()]
            if len(cands) != 1:
                raise typer.BadParameter(
                    f"--resume: expected exactly one file in {resume}/input, found {len(cands)}. "
                    f"Pass --input explicitly.")
            input_file = cands[0]
        if brief:                       # a path is read; anything else is taken literally
            _bp = Path(brief).expanduser()
            if _bp.is_file():
                brief = _bp.read_text(encoding="utf-8").strip()
                print(f"[resume] brief read from {_bp} ({len(brief.split())} words)", flush=True)
        # The literal name is used here because the tools cannot be imported until QME_RUN_DIR is set.
        fin = resume / ".finished"
        parent_reason = (fin.read_text(encoding="utf-8").strip() if fin.exists()
                         else "(no .finished sentinel; the parent was cut off rather than finishing)")
    elif input_file is None:
        raise typer.BadParameter("--input is required (unless you pass --resume).")
    if not config_file.exists():
        raise typer.BadParameter(f"Config file {config_file} not found.")
    cfg: dict[str, Any] = yaml.safe_load(config_file.read_text(encoding="utf-8"))

    # CLI overrides.
    if provider:
        cfg.setdefault("llm", {})["provider"] = provider
    if model:
        prov = cfg.get("llm", {}).get("provider", "vllm")
        cfg.setdefault("llm", {}).setdefault(prov, {})["model"] = model
    if output_dir:
        cfg.setdefault("run", {})["output_dir"] = str(output_dir)
    elif resume is not None:
        # The parent's effective config records the parent's own run folder as
        # output_dir; inheriting that verbatim would nest the continuation inside
        # the parent. Anchor the continuation next to the parent instead.
        cfg.setdefault("run", {})["output_dir"] = str(resume.parent)
    if julia_timeout is not None:
        cfg.setdefault("julia", {})["run_timeout_seconds"] = int(julia_timeout)
    if julia_parallel is not None:
        cfg.setdefault("julia", {})["batch_max_parallel"] = int(julia_parallel)
    if hitl is not None:  # --hitl / --no-hitl overrides the config for this run
        cfg.setdefault("agent", {})["human_in_the_loop"] = hitl
    elif resume is not None:
        # A resumed run exists to take new instructions, so it stops at the plan gate by default.
        # --no-hitl is the escape for the unattended case (re-running one that hit the time cap).
        cfg.setdefault("agent", {})["human_in_the_loop"] = True

    # Settled here, right after the last write to cfg["agent"], because the resume block below
    # needs it: without it the RUN_SUMMARY handover and the kickoff's no-brief fallback would both
    # promise a plan-review gate that an unattended run does not have.
    hitl_on = bool((cfg.get("agent") or {}).get("human_in_the_loop", False))

    repo_root = Path(__file__).resolve().parent

    # Temp and cache hygiene; must be set before vLLM or the tools start. A default $HOME or /tmp
    # cache can be too small for the FlashInfer JIT build, and a partial build left there makes
    # every later vLLM start fail on the first completion. Keyed per GPU group so parallel runs
    # do not race the same JIT compile. setdefault: never override what the caller already set.
    _gpu_key = str((cfg.get("llm", {}).get("vllm", {}) or {}).get("gpu_id", "cpu")).replace(",", "-")
    _scratch = repo_root / ".scratch" / (_gpu_key or "cpu")
    (_scratch / "tmp").mkdir(parents=True, exist_ok=True)
    (_scratch / "cache" / ".cache").mkdir(parents=True, exist_ok=True)
    for _k, _v in (("TMPDIR", _scratch / "tmp"), ("TMP", _scratch / "tmp"),
                   ("TEMP", _scratch / "tmp"),
                   ("FLASHINFER_WORKSPACE_BASE", _scratch / "cache"),
                   ("XDG_CACHE_HOME", _scratch / "cache" / ".cache")):
        os.environ.setdefault(_k, str(_v))

    # Julia and tool environment; must be set before importing the tools.
    jl = cfg.get("julia", {}) or {}
    if jl.get("depot_path"):
        os.environ["JULIA_DEPOT_PATH"] = str(Path(jl["depot_path"]).expanduser())
    if jl.get("threads"):
        os.environ["JULIA_NUM_THREADS"] = str(jl["threads"])
    if jl.get("blas_threads"):
        os.environ["OPENBLAS_NUM_THREADS"] = str(jl["blas_threads"])
        os.environ["OMP_NUM_THREADS"] = str(jl["blas_threads"])
    if jl.get("executable"):
        os.environ["QME_JULIA_EXE"] = str(jl["executable"])
    if jl.get("project_dir"):
        os.environ["QME_JULIA_PROJECT"] = str((repo_root / jl["project_dir"]).resolve())
    if jl.get("itensor_libraries_dir"):
        os.environ["QME_ITENSOR_LIB"] = str((repo_root / jl["itensor_libraries_dir"]).resolve())
    os.environ["QME_JULIA_LAUNCH_TIMEOUT"] = str(jl.get("run_timeout_seconds", 600))
    # Default wall-clock for a run_julia DMRG call. Must be generous (minutes): a small default
    # silently times out every full run. run_julia uses this when timeout_s <= 0.
    os.environ["QME_JULIA_RUN_TIMEOUT"] = str(jl.get("run_timeout_seconds", 600))
    # run_julia_batch: how many DMRG points run concurrently (each its own subprocess).
    os.environ["QME_JULIA_BATCH_MAX_PARALLEL"] = str(jl.get("batch_max_parallel", 8))

    # Run folder.
    base_out = Path(cfg.get("run", {}).get("output_dir", "./output"))
    job_stamp = time.strftime("run_%Y%m%d_%H%M%S")
    out = (repo_root / base_out / job_stamp).resolve()
    cfg.setdefault("run", {})["run_dir"] = str(out)
    for sub in ["logs", "data", "plots", "note", "params", "scripts", "input", "config"]:
        (out / sub).mkdir(parents=True, exist_ok=True)
    if resume is not None:
        # Copy the parent in first, then let the lines below overwrite what must be current.
        # dirs_exist_ok: `out` already has its empty subdirs. The parent is never mutated.
        #
        # Results are inherited; the parent's run record is not. Copying `logs/` would make the
        # child append to the parent's stats.jsonl / interactions.jsonl / terminal.log, so every
        # per-run measurement (LLM calls, tokens, cost, wall time) would silently double-count two
        # runs as one. The parent keeps its own logs, and config/resume_from.json points at them.
        _not_inherited = shutil.ignore_patterns(
            "logs", "conversation_history", "large_tool_results", "scratch")
        shutil.copytree(resume, out, dirs_exist_ok=True, ignore=_not_inherited)
        # copytree preserves modes, so a parent protected with `chmod -R a-w` (a sensible thing to
        # do to a run a paper depends on) would yield a child the agent cannot write to. The child
        # is a working directory and must always be writable, whatever the parent's permissions.
        # `out` itself goes first: copytree copies the source mode onto the destination root, and
        # unlinking a file needs write permission on its containing directory, not on the file.
        for _p in [out, *out.rglob("*")]:
            try:
                _p.chmod(_p.stat().st_mode | (0o700 if _p.is_dir() else 0o600))
            except OSError:
                pass
        # The parent's experiment_meta.json describes the parent. Leaving it in the child's dir
        # would mislabel this run's model and spec in any downstream collector.
        (out / "experiment_meta.json").unlink(missing_ok=True)
        # `write_file` refuses to overwrite an existing file, so an inherited plan.md would make
        # the agent's first substantive action fail. Renaming costs nothing, makes `write_file
        # plan.md` behave exactly as in a fresh run, and keeps the previous investigator's plan
        # readable as history, which fits the handover framing anyway.
        _parent_plan = out / "plan.md"
        if _parent_plan.exists():
            # .replace() overwrites, so resuming a resumed run would destroy the grandparent's
            # plan. Number them instead: plan_previous.md, then plan_previous_2.md, and so on.
            _dest, _n = out / "plan_previous.md", 2
            while _dest.exists():
                _dest = out / f"plan_previous_{_n}.md"
                _n += 1
            _parent_plan.replace(_dest)
        # Sentinels are per-run state, not results. A stale `.finished` would make the outer loop
        # exit on iteration one; stale HITL sentinels would let `finish` skip the review gate.
        for sentinel in (".finished", ".plan_reviewed", ".review_approved"):
            (out / sentinel).unlink(missing_ok=True)

    # Skills travel with the run so skills=["/skills"] resolves under the backend root.
    # On resume this deliberately overwrites the parent's copy: a continuation runs on the current
    # skill library, which is usually the point of continuing. The hashes of both are recorded below.
    shutil.copytree(repo_root / "qme" / "skills", out / "skills", dirs_exist_ok=True)
    if input_file is not None and input_file.exists():
        shutil.copy(input_file, out / "input" / input_file.name)
    if config_file.exists():
        shutil.copy(config_file, out / "config" / config_file.name)
    # The copy above is the input config. Every CLI override (--provider/--model/--hitl, and the
    # HITL-on default a resume applies) lives only in the in-memory `cfg`, so the run dir would
    # otherwise claim settings the run did not use. Write what actually ran.
    with open(out / "config" / "effective_config.yaml", "w", encoding="utf-8") as _f:
        yaml.safe_dump(cfg, _f, sort_keys=False, allow_unicode=True)

    if resume is not None:
        # Provenance. Skills and prompts are deliberately not pinned to the parent's (see above),
        # so the only defence against an invisible comparability break is recording both fingerprints.
        import hashlib as _hl

        def _fp() -> dict:
            fp = {"prompts_sha256": _hl.sha256((repo_root / "qme" / "prompts.py").read_bytes())
                  .hexdigest()[:16]}
            try:
                h = _hl.sha256()
                for f in sorted((repo_root / "qme" / "skills").glob("*/SKILL.md")):
                    h.update(f.name.encode())
                    h.update(f.read_bytes())
                fp["skills_sha256"] = h.hexdigest()[:16]
            except Exception:
                fp["skills_sha256"] = None
            return fp

        parent_meta = {}
        pm = resume / "experiment_meta.json"
        if pm.exists():
            try:
                parent_meta = json.loads(pm.read_text(encoding="utf-8"))
            except Exception:
                pass
        child_fp = _fp()
        try:                       # repo-relative: never hand the agent an absolute path it could
            _parent_rel = str(resume.relative_to(repo_root))   # paste into an open() and clobber
        except ValueError:                                     # the parent run
            _parent_rel = resume.name
        # Resuming a resumed run would otherwise overwrite this file and silently forget every
        # ancestor before the immediate parent. Carry the parent's record forward so the chain,
        # and therefore the total compute across it, stays reconstructable.
        _ancestors = []
        _prev = resume / "config" / "resume_from.json"
        if _prev.exists():
            try:
                _pp = json.loads(_prev.read_text(encoding="utf-8"))
                _ancestors = list(_pp.get("ancestors") or [])
                _ancestors.append({k: _pp.get(k) for k in
                                   ("resumed_from", "resumed_at_utc", "parent_label", "human_brief")})
            except Exception:
                pass
        prov = {
            "generation": len(_ancestors) + 1,
            "ancestors": _ancestors,
            "resumed_from": _parent_rel,
            "resumed_from_note": "repo-relative, for humans. The previous run is READ-ONLY history: "
                                 "everything you need was copied into this run directory.",
            "resumed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "parent_label": parent_meta.get("label"),
            "parent_finish_reason": parent_reason,
            "parent_prompts_sha256": parent_meta.get("prompts_sha256"),
            "parent_skills_sha256": parent_meta.get("skills_sha256"),
            "child_prompts_sha256": child_fp["prompts_sha256"],
            "child_skills_sha256": child_fp["skills_sha256"],
            "human_brief": brief or "",
            "config_base": str(config_file.relative_to(repo_root))
                            if str(config_file).startswith(str(repo_root)) else config_file.name,
        }
        (out / "config" / "resume_from.json").write_text(json.dumps(prov, indent=2), encoding="utf-8")
        if brief:
            # The brief is an input to this run, exactly like the spec, so it belongs next to it:
            # `input/` then holds everything the agent was handed. Numbered rather than overwritten
            # so resuming a resumed run keeps each generation's instruction (cf. plan_previous).
            _bd, _n = out / "input" / "continuation_brief.md", 2
            while _bd.exists():
                _bd = out / "input" / f"continuation_brief_{_n}.md"
                _n += 1
            _bd.write_text(
                f"# Continuation brief (generation {prov['generation']})\n\n"
                f"Given on the command line with `--brief` when this run was started from\n"
                f"`{_parent_rel}`.\n\n{brief.strip()}\n", encoding="utf-8")
        drift = [k for k in ("prompts_sha256", "skills_sha256")
                 if parent_meta.get(k) and parent_meta[k] != child_fp[k]]
        if drift:
            print(f"[resume] NOTE: {', '.join(drift)} differ from the parent run. This continuation "
                  f"runs on the current prompt/skill library, so it is not poolable with the parent "
                  f"for comparability purposes. Recorded in config/resume_from.json.", flush=True)
        # The agent reads RUN_SUMMARY.md as half its briefing, so the handover belongs in it too.
        with open(out / "RUN_SUMMARY.md", "a", encoding="utf-8") as f:
            f.write(f"\n## RESUMED  ({prov['resumed_at_utc']})\n"
                    f"Description: continuation of {resume.name}"
                    f"{' (' + str(parent_meta.get('label')) + ')' if parent_meta.get('label') else ''}"
                    f", restarted as a fresh investigator.\n"
                    f"Findings: everything above this line was produced by the PREVIOUS "
                    f"investigator. Treat it as their claims, to be checked, not as settled fact.\n"
                    f"Next: {brief or ('see the plan-review gate.' if hitl_on else 'no brief given; see plan.md.')}\n---\n")

    # QME_RUN_DIR must be set before the tools (sandbox.py) are imported.
    os.environ["QME_RUN_DIR"] = str(out)
    os.environ["QME_REPO_ROOT"] = str(repo_root)
    # Human-in-the-loop: the review tools (qme/tools/hitl.py) and the finish guard read these.
    _agent_cfg = cfg.get("agent", {}) or {}
    # hitl_on was settled above, next to the last write to cfg["agent"].
    os.environ["QME_HITL"] = "1" if hitl_on else "0"
    os.environ["QME_HITL_TIMEOUT_MIN"] = str(_agent_cfg.get("hitl_timeout_minutes", 720))
    os.environ["QME_HITL_NOTIFY_URLS"] = ",".join(str(u) for u in (_agent_cfg.get("hitl_notify_urls") or []))
    # Make `execute`'s `python`/`python3` resolve to this venv (with its scientific stack:
    # numpy/scipy/pandas/h5py/matplotlib), not whatever bare system python a shell finds.
    # Do NOT .resolve() here: sys.executable is the venv's symlink, and resolving it follows
    # the link out of the venv bin.
    _venv_bin = str(Path(sys.executable).parent)
    os.environ["PATH"] = _venv_bin + os.pathsep + os.environ.get("PATH", "")

    # Terminal tee to logs/terminal.log.
    ansi = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    class LoggerTee:
        def __init__(self, stream, fh):
            self.stream, self.fh = stream, fh

        def write(self, data):
            self.stream.write(data)
            self.fh.write(ansi.sub("", data) if isinstance(data, str) else data)
            self.fh.flush()

        def flush(self):
            self.stream.flush()
            self.fh.flush()

        def isatty(self):
            return hasattr(self.stream, "isatty") and self.stream.isatty()

        def __getattr__(self, a):
            return getattr(self.stream, a)

    term_fh = open(out / "logs" / "terminal.log", "a", encoding="utf-8")
    sys.stdout = LoggerTee(sys.stdout, term_fh)
    sys.stderr = LoggerTee(sys.stderr, term_fh)

    # Loggers.
    from qme.obs.logger import InteractionLogger
    from qme.obs.stats_logger import StatsLogger
    log_cfg = cfg.setdefault("logging", {})
    log_cfg["log_dir"] = str(out / "logs")
    ilog = InteractionLogger.initialise(log_cfg)
    from qme.agent import context_length
    StatsLogger.initialise(out / "logs", context_window=context_length(cfg))
    ilog.info("system", f"QuantumMatterExplorer: input={input_file}, output={out}")
    if hitl_on:
        _nurls = os.environ.get("QME_HITL_NOTIFY_URLS", "")
        ilog.info("system", f"Human-in-the-loop ON: plan + final review checkpoints; "
                            f"timeout={os.environ.get('QME_HITL_TIMEOUT_MIN')}min; "
                            f"notify={'yes' if _nurls else 'banner+marker only'}")

    raw_input = input_file.read_text(encoding="utf-8")
    input_fmt = "latex" if input_file.suffix in {".tex", ".latex"} else "markdown"

    # LLM server lifecycle (auto-launch for the local provider).
    llm_cfg = cfg["llm"]
    provider_name = llm_cfg.get("provider", "vllm")
    vllm_mgr = None

    if provider_name == "vllm" and llm_cfg.get("vllm", {}).get("auto_launch", False):
        from qme.llm.vllm import VllmServer
        v = llm_cfg["vllm"]
        host = v.get("base_url", "http://localhost:11436").replace("http://", "").replace("https://", "")
        # Where model weights are downloaded/cached. Only set when configured, so an existing
        # Hugging Face cache (~/.cache/huggingface) is reused by default.
        _dl = v.get("download_dir")
        vllm_mgr = VllmServer(
            model=v.get("model"), host=host, gpu_id=str(v.get("gpu_id", "-1")),
            context_length=v.get("context_length"), gpu_memory_utilization=v.get("gpu_memory_utilization"),
            tensor_parallel_size=v.get("tensor_parallel_size"),
            launch_timeout_seconds=v.get("launch_timeout_seconds", 900),
            base_dir=str((repo_root / _dl).resolve()) if _dl else None,
            python_bin=v.get("server_python"),
            log_dir=str(out / "logs"),
            pid_dir=str(_scratch),
            enforce_eager=v.get("enforce_eager", False),
            tool_call_parser=v.get("tool_call_parser", "gemma4"),
            chat_template=v.get("chat_template"),
            reasoning_parser=v.get("reasoning_parser"),
            rope_scaling=v.get("rope_scaling"),
            startup_cleanup=v.get("startup_cleanup", "own"),
        )
        vllm_mgr.start()
        v["base_url"] = f"http://{vllm_mgr.host}"
        ilog.info("system", f"vLLM serving at {v['base_url']}")
        vllm_mgr.ensure_model_loaded()

    def _shutdown(*_a):
        ilog.info("system", "Shutting down...")
        from qme.tools.julia import shutdown_julia
        try:
            shutdown_julia()
        except Exception:
            pass
        if vllm_mgr:
            vllm_mgr.stop()
        try:
            StatsLogger.get().close()
        except Exception:
            pass
        ilog.close()

    signal.signal(signal.SIGINT, lambda *a: (_shutdown(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *a: (_shutdown(), sys.exit(0)))

    # Build model + agent (env is set, safe to import the tools now).
    from qme.llm.provider import build_llm
    from qme.agent import build_agent
    from qme.obs.callback import DeepAgentCallbackHandler
    from qme.tools.helpers import FINISHED_SENTINEL
    from langchain_core.messages import HumanMessage

    model_obj = build_llm(llm_cfg)
    agent = build_agent(cfg, out, model_obj)

    if dry_run:
        ilog.info("system", "Dry run: agent built and wiring validated. Exiting.")
        _shutdown()
        typer.echo(f"Dry run OK. Run folder: {out}")
        return

    # Run driver: autonomous and long-horizon, with re-invocation between agent runs.
    agent_cfg = cfg.get("agent", {}) or {}
    run_cfg = cfg.get("run", {}) or {}
    cb = DeepAgentCallbackHandler()
    invoke_cfg = {
        "configurable": {"thread_id": job_stamp},
        "recursion_limit": int(agent_cfg.get("recursion_limit", 100000)),
        "callbacks": [cb],
    }
    max_outer = int(run_cfg.get("max_outer_iterations", 100))
    no_progress_limit = max(1, int(run_cfg.get("no_progress_iterations", 2)))
    finished_path = out / FINISHED_SENTINEL
    if resume is not None:
        msg: Any = HumanMessage(RESUME_KICKOFF.format(
            fmt=input_fmt, raw_input=raw_input, date=time.strftime("%Y-%m-%d"),
            first_action=FIRST_ACTION_GATED if hitl_on else FIRST_ACTION_UNATTENDED,
            parent_reason=parent_reason or "(not recorded)",
            human_brief=brief or (
                "(nothing specific was given up front; ask at the plan-review "
                "gate, and in the meantime work from the limitations the previous "
                "investigator named in their own note)" if hitl_on else
                "(no brief was given, and nobody will be asked. Take your task list from the "
                "limitations the previous investigator named in their own note, and from any "
                "inherited label their own data does not support.)")))
    else:
        msg = HumanMessage(KICKOFF.format(fmt=input_fmt, raw_input=raw_input,
                                          date=time.strftime("%Y-%m-%d")))

    # Each outer iteration is a full agent run; between runs we re-nudge a yielded-but-unfinished
    # agent. The key is to stop re-nudging a done agent, so after each run we check, in order,
    # three clean exit conditions before sending another nudge:
    #   (1) the agent called `finish` (the .finished sentinel)        - explicit done signal;
    #   (2) the artifact fingerprint is unchanged for N iterations    - no-progress backstop;
    #   (3) the agent yielded with no new tool calls                  - the standard ReAct stop.
    stagnant = 0
    last_fp: Optional[tuple] = None
    done = False
    try:
        for outer in range(max_outer):
            ilog.info("system", f"-- outer iteration {outer + 1}/{max_outer} --")
            final_state = None
            for state in agent.stream({"messages": [msg]}, config=invoke_cfg, stream_mode="values"):
                final_state = state
            msgs = (final_state or {}).get("messages", [])

            # (1) explicit finish signal: never re-nudge a finished agent
            if finished_path.exists():
                ilog.info("system", "Agent called finish, study complete.")
                done = True
                break
            # (2) no-progress backstop: no new data/figures/note for N consecutive iterations
            fp = _artifact_fingerprint(out)
            if fp == last_fp:
                stagnant += 1
            else:
                stagnant, last_fp = 0, fp
            if stagnant >= no_progress_limit:
                ilog.info("system", f"No new artifacts for {stagnant + 1} outer iterations, "
                                    f"treating as converged.")
                done = True
                break
            # (3) standard ReAct stop: agent yielded with no new tool calls
            if (_count_tool_calls(msgs[-12:]) if msgs else 0) == 0:
                ilog.info("system", "Agent yielded with no new tool calls, treating as done.")
                done = True
                break

            # Still genuinely working: send a continuation nudge that points at `finish`.
            msg = HumanMessage(
                "You yielded. If the phase-diagram study is NOT complete (survey, boundaries, order, "
                "FSS, and a written note with ## Phase diagram + ## Conclusion and the figures embedded), "
                "keep going. If it IS complete, run a final physics-critic review, then call "
                "`finish(reason)` to FINALIZE. Do not keep re-polishing a finished note.")

        # Hit the cap without finishing: one final synthesis turn rather than a hard cut.
        # Ask for the best final answer plus `finish`, then stop.
        if not done:
            ilog.info("system", f"Reached max_outer_iterations={max_outer}, sending a final "
                                f"synthesis nudge before stopping.")
            synth = HumanMessage(
                "You have reached the maximum number of iterations. Do NOT start new experiments. "
                "Synthesize your best FINAL answer now: ensure note/research_note.md has "
                "## Phase diagram + ## Conclusion with the figures embedded, then call `finish(reason)`.")
            for state in agent.stream({"messages": [synth]}, config=invoke_cfg, stream_mode="values"):
                pass
    except Exception as exc:
        import traceback
        ilog.error("system", f"Run failed:\n{traceback.format_exc()}")
        typer.echo(f"ERROR: {exc}", err=True)

    # Finalize: figure-reference integrity.
    broken = figure_reference_check(out)
    if broken:
        ilog.warning("system", f"Figure-reference check: {len(broken)} broken/empty figure link(s): {broken}")

    note_path = out / "note" / "research_note.md"
    plots = [p for ext in ("*.svg", "*.png", "*.pdf") for p in (out / "plots").glob(ext)]
    data = list((out / "data").glob("*.json"))
    _shutdown()
    typer.echo("\n" + "=" * 60)
    typer.echo("EXPLORATION COMPLETE")
    typer.echo(f"Research note: {note_path}")
    typer.echo(f"Plots: {len(plots)} | Data points: {len(data)}")
    typer.echo(f"Run folder: {out}")
    typer.echo("=" * 60)


if __name__ == "__main__":
    app()
