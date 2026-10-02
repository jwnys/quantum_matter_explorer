"""Turn a finished run's research note into a readable standalone LaTeX report + PDF.

    python tools/note_to_pdf.py <run_dir>
    python tools/note_to_pdf.py <run_dir> --config config/config_opus5.yaml
    python tools/note_to_pdf.py <run_dir> --no-llm          # mechanical, no model call

Read-only with respect to the run. Everything is written under `<run_dir>/report/`, so this can be
pointed at a finished (or still-running) run without disturbing it, and re-run as often as you like.

Why an LLM at all: the notes are written for correctness, not for reading. They carry long tables
squeezed into Markdown pipes, figures dumped inline with one-line alt text, and numbered findings
that would read better as sections. A converter that only escapes characters reproduces all of that
faithfully. Handing it to a model gets a document you would actually hand to a colleague.

The model is not allowed to do physics. Its brief forbids changing any number, claim, hedge or
caveat. The output is diffed against the input on numbers before it is accepted, and the run falls
back to a mechanical conversion rather than emit a document whose values drifted from the note. A
prettier report that quietly rounds a correlation length is worse than no report.

Any provider the harness already supports works, since this calls `build_llm` on the same config
objects as a run. A cloud config is the sensible choice for a one-shot conversion. A vLLM config
works too but needs a server already up, and spinning up a large local model to reformat one
document is a poor trade.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
# Numbers as they appear in physics prose: 1.25, -0.185, 4.7e-15, 2\times10^{-3} handled loosely.
# A physics value, not a Markdown artefact. Requires digits after any decimal point, so "1." from
# an ordered-list marker is not a number. List markers are stripped separately, because "1" alone
# still matches and `1. Foo` legitimately becomes `\item Foo` in the conversion.
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
LIST_MARKER_RE = re.compile(r"^\s{0,8}\d{1,3}[.)]\s", re.M)

CONVERT_PROMPT = """You are turning a computational physicist's working notes into a standalone
LaTeX report that a colleague can read.

RULES YOU MAY NOT BREAK:
- Do not change any number, unit, symbol, or parameter value.
- Do not add, remove, strengthen or weaken any claim. Hedges ("candidate", "not established",
  "unresolved") are load-bearing and must survive verbatim in meaning.
- Do not invent citations, references, or results that are not in the source.
- Keep every figure. They are already `\\includegraphics` targets named in the source.

WHAT YOU SHOULD DO:
- Produce a complete document: \\documentclass through \\end{document}.
- Use article class, 11pt, a4paper, with graphicx, amsmath, amssymb, booktabs, hyperref, geometry.
- Give it a title from the note's subject, and \\date{{}} left empty.
- Turn Markdown headings into sections. Turn Markdown pipe tables into booktabs tabulars, sized to
  fit \\textwidth. Turn inline code spans into \\texttt.
- Inline maths in the source is ALREADY LaTeX. Pass it through untouched.
- Put each figure in a float with the alt text as the caption, `[htbp]`, width 0.9\\textwidth.
- Escape LaTeX specials (% & # _ outside maths) so the document compiles.

Return ONLY the LaTeX. No commentary, no markdown fences.

--- THE NOTE ---
@@NOTE@@
"""

COMPILE_SH = """#!/usr/bin/env bash
# Build report.pdf, then remove the build litter. Regenerate with tools/note_to_pdf.py.
set -euo pipefail
cd "$(dirname "$0")"

if command -v latexmk >/dev/null 2>&1; then
    latexmk -pdf -interaction=nonstopmode -halt-on-error report.tex
    latexmk -c                      # clean aux/log/fls/fdb, keep the pdf
else
    pdflatex -interaction=nonstopmode -halt-on-error report.tex
    pdflatex -interaction=nonstopmode -halt-on-error report.tex   # twice, for refs
    rm -f report.aux report.log report.out report.toc report.fls report.fdb_latexmk
fi

echo "wrote $(pwd)/report.pdf"
"""


def text_of(resp) -> str:
    """Pull plain text out of a LangChain response.

    `.content` is a str for most models but a list of typed blocks for reasoning models, where the
    LaTeX sits in the `text` blocks and the rest is thinking. Calling .strip() on that list raises
    an AttributeError.
    """
    c = getattr(resp, "content", resp)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        out = []
        for b in c:
            if isinstance(b, str):
                out.append(b)
            elif isinstance(b, dict) and b.get("type") in (None, "text"):
                out.append(b.get("text", ""))
        return "\n".join(x for x in out if x)
    return str(c)


REPAIR_PROMPT = """The LaTeX you produced does not compile. Here is what the compiler said:

--- ERRORS ---
@@ERRORS@@

--- THE LINES IT POINTS AT ---
@@CONTEXT@@

Fix ONLY what is needed to make it compile. Do not change any number, claim or hedge, do not drop
any figure, and do not restructure anything that already works. Return the COMPLETE corrected
document, \\documentclass through \\end{document}, with no commentary and no markdown fences."""


def latex_errors(log: Path) -> tuple[str, str]:
    """The compiler's complaints, plus the source lines they point at.

    A bare `! Undefined control sequence` is not actionable on its own. The `l.<n>` line that
    follows it is where the problem actually is, so both are collected.
    """
    if not log.exists():
        return "", ""
    text = log.read_text(encoding="utf-8", errors="ignore")
    errs = [ln for ln in text.splitlines() if ln.startswith("! ") or ln.startswith("l.")]
    return "\n".join(errs[:40]), ""


def compile_tex(out_dir: Path) -> tuple[bool, str]:
    """Run the build. Returns (ok, errors). Never raises."""
    sh = out_dir / "compile.sh"
    try:
        r = subprocess.run(["bash", str(sh)], capture_output=True, text=True,
                           cwd=str(out_dir), timeout=120)
    except subprocess.TimeoutExpired:
        return False, "latexmk exceeded 120s and was killed"
    if r.returncode == 0 and (out_dir / "report.pdf").exists():
        return True, ""
    errs, _ = latex_errors(out_dir / "report.log")
    return False, errs or (r.stdout + r.stderr)[-2000:]


def collect_figures(note: str, run_dir: Path, out_dir: Path) -> tuple[str, list[str]]:
    """Copy every figure the note references into `out_dir/figs/` and flatten the paths.

    Note paths are written relative to `note/` (`../plots/x.png`). The report lives somewhere
    else, so the references have to be rewritten or the document will not compile.
    """
    figs_dir = out_dir / "figs"
    figs_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []

    def _sub(m: re.Match) -> str:
        alt, rel = m.group(1), m.group(2).strip()
        src = (run_dir / "note" / rel).resolve()
        if not src.exists():                       # keep the reference, flag it in the report
            return f"![{alt}](MISSING:{rel})"
        shutil.copy(src, figs_dir / src.name)
        copied.append(src.name)
        return f"![{alt}](figs/{src.name})"

    return IMG_RE.sub(_sub, note), copied


def numbers_in(text: str) -> list[str]:
    """Every number that carries meaning, for the drift check, as a multiset.

    Ordered-list markers are removed first. `1. Foo` becoming `\\item Foo` is a correct conversion,
    and counting the "1" as a lost value made the check reject every good document the model
    produced. Normalised so 1.50 and 1.5 compare equal, since a model may reasonably reformat a
    value without changing it."""
    text = LIST_MARKER_RE.sub(" ", text)
    out = []
    for n in NUM_RE.findall(text):
        try:
            out.append(f"{float(n):g}")
        except ValueError:
            out.append(n)
    return sorted(out)


def check_no_drift(src: str, out: str) -> list[str]:
    """Numbers present in the note but absent from the report. Missing ones are the danger:
    the model dropped or altered a value. Extra numbers in the output are usually LaTeX
    lengths (0.9\\textwidth, 11pt) and are not evidence of tampering."""
    from collections import Counter
    lost = Counter(numbers_in(src)) - Counter(numbers_in(out))
    return sorted(lost.elements())


_ESC_MAP = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
            "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}"}
_ESC_RE = re.compile("|".join(re.escape(k) for k in _ESC_MAP))


def _esc(t: str) -> str:
    """Escape LaTeX specials in PLAIN PROSE only. Never call this on maths, or on text that
    already holds LaTeX commands.

    One pass, not a chain of str.replace. A chain corrupts itself: replacing the backslash first
    yields \\textbackslash{}, and the later brace rules then escape ITS braces into
    \\textbackslash\\{\\}. A single regex pass cannot re-enter its own output.
    """
    return _ESC_RE.sub(lambda m: _ESC_MAP[m.group(0)], t)


def mechanical(note: str, title: str) -> str:
    r"""Fallback for --no-llm, and whenever the model path is refused. Plain but faithful, and it
    must always compile, because it is the conversion of last resort.

    Order matters. Inline maths and code spans are lifted out first and restored last, because
    both legitimately contain characters (`_`, `^`, `\`) that must not be escaped in the first
    case and must be escaped differently in the second. Headings are converted before `#` is
    escaped, or every heading would become a literal hash.
    """
    stash: list[str] = []

    def _keep(payload: str) -> str:
        stash.append(payload)
        return f"\x00{len(stash) - 1}\x00"

    # 1. figures out (paths must not be escaped), maths out (already LaTeX), code out (escaped
    #    with its own rules since underscores are common in identifiers).
    note = IMG_RE.sub(lambda m: _keep(
        "\\begin{figure}[htbp]\\centering\n"
        f"\\includegraphics[width=0.9\\textwidth]{{{m.group(2)}}}\n"
        f"\\caption{{{_esc(m.group(1)) or 'Figure'}}}\n\\end{{figure}}"), note)
    note = re.sub(r"\$\$(.+?)\$\$", lambda m: _keep(f"$${m.group(1)}$$"), note, flags=re.S)
    note = re.sub(r"(?<!\\)\$([^$\n]+?)\$", lambda m: _keep(f"${m.group(1)}$"), note)
    note = re.sub(r"`([^`]+)`", lambda m: _keep(f"\\texttt{{{_esc(m.group(1))}}}"), note)

    # 2. structure, while '#' and '*' still mean what Markdown means by them
    for n, cmd in ((4, "paragraph"), (3, "subsubsection"), (2, "subsection"), (1, "section")):
        note = re.sub(rf"^{'#' * n} +(.+)$", lambda m, c=cmd: _keep(f"\\{c}{{{_esc(m.group(1))}}}"),
                      note, flags=re.M)
    note = re.sub(r"\*\*([^*]+)\*\*", lambda m: _keep(f"\\textbf{{{_esc(m.group(1))}}}"), note)

    # 3. everything still standing is prose
    note = _esc(note)

    # 4. put the protected pieces back, repeatedly: the stashes nest. A `**bold $D$ text**` span
    #    is stashed in step 2 with the step-1 maths placeholder still inside it, so one pass
    #    reveals an inner placeholder it has already walked past, and a raw NUL reaches LaTeX as
    #    `^^@`. Loop until the text stops changing.
    for _ in range(10):
        new_note = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], note)
        if new_note == note:
            break
        note = new_note
    if "\x00" in note:                                    # never ship a NUL to LaTeX
        note = note.replace("\x00", "")

    return ("\\documentclass[11pt,a4paper]{article}\n"
            "\\usepackage{graphicx,amsmath,amssymb,booktabs,hyperref}\n"
            "\\usepackage[margin=2.5cm]{geometry}\n"
            f"\\title{{{_esc(title)}}}\\author{{}}\\date{{}}\n"
            f"\\begin{{document}}\\maketitle\n{note}\n\\end{{document}}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path, help="a run folder containing note/research_note.md")
    ap.add_argument("--config", "-c", type=Path, default=None,
                    help="config for the LLM. Default: the run's own effective_config.yaml, so the "
                         "report is made by the model that wrote the note; else config/config.yaml")
    ap.add_argument("--provider", "-p", default=None,
                    help="override llm.provider from the config (vllm, openai, anthropic, ...)")
    ap.add_argument("--model", "-m", default=None,
                    help="override the model id inside the active provider block")
    ap.add_argument("--outdir", type=Path, default=None, help="default <run_dir>/report")
    ap.add_argument("--no-llm", action="store_true", help="mechanical conversion, no model call")
    ap.add_argument("--no-compile", action="store_true", help="write the .tex, do not run latexmk")
    ap.add_argument("--timeout", type=int, default=300,
                    help="total wall-clock budget in seconds (default 300). A conversion call runs "
                         "30-120s on a reasoning model and a compile 3-10s. On expiry it falls "
                         "straight to the mechanical path, which always compiles and takes seconds, "
                         "so a low budget costs you polish and never the document.")
    ap.add_argument("--max-repairs", type=int, default=2,
                    help="how many times the model may read its own compiler errors and retry "
                         "(default 2). A model that cannot fix its LaTeX will not manage it on "
                         "round three.")
    a = ap.parse_args()

    run_dir = a.run_dir.resolve()
    note_path = run_dir / "note" / "research_note.md"
    if not note_path.exists():
        print(f"error: no note at {note_path}", file=sys.stderr)
        return 2
    note = note_path.read_text(encoding="utf-8")
    out_dir = (a.outdir or run_dir / "report").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    note, figs = collect_figures(note, run_dir, out_dir)
    print(f"  note: {len(note.split())} words | figures copied: {len(figs)}")

    m = re.search(r"^#\s+(.+)$", note, re.M)
    title = m.group(1).strip() if m else f"Research note: {run_dir.name}"

    sh = out_dir / "compile.sh"
    sh.write_text(COMPILE_SH, encoding="utf-8")
    sh.chmod(0o755)
    have_tex = bool(shutil.which("latexmk") or shutil.which("pdflatex"))
    deadline = time.monotonic() + a.timeout

    def _left() -> float:
        return deadline - time.monotonic()

    def _emit(tex: str, label: str) -> bool:
        """Write the .tex and try to build. Returns True on a PDF."""
        (out_dir / "report.tex").write_text(tex, encoding="utf-8")
        if a.no_compile or not have_tex:
            return False
        ok, errs = compile_tex(out_dir)
        print(f"  {label}: {'compiled' if ok else 'FAILED'}")
        _emit.errors = errs
        return ok

    _emit.errors = ""

    tex = ""
    if not a.no_llm:
        cfg_path = a.config or (run_dir / "config" / "effective_config.yaml")
        for cand in (cfg_path, run_dir / "config" / "generated_config.yaml", REPO / "config/config.yaml"):
            if cand and Path(cand).exists():
                cfg_path = Path(cand)
                break
        try:
            import yaml
            from src.llm.provider import build_llm
            cfg = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8"))
            if a.provider:                       # same override shape as main.py
                cfg.setdefault("llm", {})["provider"] = a.provider
            if a.model:
                _pv = cfg.get("llm", {}).get("provider", "vllm")
                cfg.setdefault("llm", {}).setdefault(_pv, {})["model"] = a.model
            shown = cfg_path.relative_to(REPO) if str(cfg_path).startswith(str(REPO)) else cfg_path
            print(f"  model: {cfg.get('llm', {}).get('provider')} via {shown}   "
                  f"budget: {a.timeout}s, up to {a.max_repairs} repair round(s)")
            llm = build_llm(cfg["llm"])
            # not .format(): the prompt is full of literal LaTeX braces (\begin{document},
            # [htbp], \textwidth) that str.format would try to resolve as fields.
            tex = text_of(llm.invoke(CONVERT_PROMPT.replace("@@NOTE@@", note))).strip()
            tex = re.sub(r"^```(?:latex|tex)?\s*|\s*```$", "", tex).strip()
        except Exception as e:
            print(f"  LLM conversion failed ({type(e).__name__}: {e}); falling back to mechanical",
                  file=sys.stderr)
            tex = ""

    # Accept the model's document only if it is complete and kept every number.
    if tex and not ("\\begin{document}" in tex and "\\end{document}" in tex):
        print("  model returned something that is not a complete document; falling back",
              file=sys.stderr)
        tex = ""
    if tex:
        lost = check_no_drift(note, tex)
        if lost:
            print(f"  REFUSED: {len(lost)} number(s) from the note are missing in the LaTeX: "
                  f"{lost[:8]}{' ...' if len(lost) > 8 else ''}", file=sys.stderr)
            print("  falling back to the mechanical conversion, which cannot drop values.",
                  file=sys.stderr)
            tex = ""
        else:
            print(f"  no-drift check: passed ({len(numbers_in(note))} numbers all present)")

    # Write, compile, and let the model read its own compiler errors and try again. Bounded twice:
    # by round count and by wall clock, because a model that cannot fix its own LaTeX will not
    # discover that on round four, and this is a formatting tool rather than a research task.
    if tex and _emit(tex, "round 1"):
        print(f"  built {out_dir}/report.pdf")
        return 0
    for rnd in range(2, a.max_repairs + 2):
        if not tex or a.no_llm or a.no_compile or not have_tex:
            break
        if _left() < 60:
            print(f"  out of time budget ({a.timeout}s) after {rnd - 1} round(s); "
                  f"falling back to mechanical", file=sys.stderr)
            tex = ""
            break
        print(f"  repairing (round {rnd}, {_left():.0f}s left)")
        try:
            fixed = text_of(llm.invoke(
                REPAIR_PROMPT.replace("@@ERRORS@@", _emit.errors[:4000])
                             .replace("@@CONTEXT@@", tex[:2000]))).strip()
            fixed = re.sub(r"^```(?:latex|tex)?\s*|\s*```$", "", fixed).strip()
        except Exception as e:
            print(f"  repair call failed ({type(e).__name__}); falling back", file=sys.stderr)
            tex = ""
            break
        if not ("\\begin{document}" in fixed and "\\end{document}" in fixed):
            print("  repair was not a complete document; falling back", file=sys.stderr)
            tex = ""
            break
        lost = check_no_drift(note, fixed)
        if lost:      # a "fix" that deletes the offending numbers is not a fix
            print(f"  repair dropped {len(lost)} number(s); refusing it", file=sys.stderr)
            tex = ""
            break
        tex = fixed
        if _emit(tex, f"round {rnd}"):
            print(f"  built {out_dir}/report.pdf")
            return 0

    # Mechanical is the floor: it cannot drop values and it is known to compile.
    tex = mechanical(note, title)
    print("  using the mechanical conversion")
    if _emit(tex, "mechanical"):
        print(f"  built {out_dir}/report.pdf")
        return 0
    if a.no_compile or not have_tex:
        print(f"  wrote {out_dir}/report.tex and compile.sh (not compiled)")
        return 0
    print("  LaTeX failed even on the mechanical conversion:\n    "
          + "\n    ".join(_emit.errors.splitlines()[-10:]), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
