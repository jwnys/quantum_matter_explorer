"""Structural checks on the prompt and the skill library.

The checks are cheap and run in a second, so run them after any edit to
`qme/prompts.py` or `qme/skills/`.

    python scripts/check_skills.py

- DUPLICATION  A canonical rule must be stated in full in exactly one skill, the owner.
               Every other file points at the owner instead of restating the rule, so a
               fix cannot leave stale copies behind.
- VOCABULARY   "Phase" means a phase of matter. Steps of the workflow are stages, so the
               two senses cannot collide in a term like "phase boundary".
- REFERENCES   Every step label a file points at (`D1`, `E2`, ...) has to be defined in
               some skill.
- STRUCTURE    Frontmatter, an opening map, a closing `## Local rules`.
- PROSE        No shouting. Capitals for emphasis read as generated rather than written
               text.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "qme" / "skills"
PROMPTS = ROOT / "qme" / "prompts.py"

FAILURES: list[str] = []


def fail(check: str, msg: str) -> None:
    FAILURES.append(f"{check}: {msg}")


def skill_files() -> list[Path]:
    return sorted(SKILLS.glob("*/SKILL.md"))


# Duplication check.
# A rule is "stated in full" where its distinctive phrasing appears. Pointers use the
# owner's name instead, so they do not match.
def _loose(phrase: str) -> str:
    r"""Turn a phrase into a regex that survives line wrapping.

    A phrase can wrap across two lines in a skill file, and a literal pattern with a
    plain space would miss it there. Any whitespace run, including a newline, matches
    any other.
    """
    return r"\s+".join(re.escape(w) for w in phrase.split())


CANONICAL_RULES = {
    "entanglement coefficient": (
        "scaling",
        re.compile("|".join([r"c\s*/\s*6[\s\S]{0,200}c\s*/\s*3",
                             _loose("open chains carry half"),
                             _loose("coefficient is `c/6`"),
                             _loose("half the coefficient periodic")])),
    ),
    # The rule is the *formula*, not a mention of the normalisation. A sentence that
    # points at the owner ("the 1/N² convention `observables` fixes") is not a restatement,
    # so match the definition itself: the normalisation next to the double sum, or the
    # superseded `S(q*)/N` form.
    "order-parameter definition": (
        "observables",
        re.compile("|".join([r"S\(q\^?\*?\)\s*/\s*N\b",
                             r"\\frac\{1\}\{N\^\{?2\}?\}\s*\\sum",
                             r"1\s*/\s*N\s*\^?\s*2[^`]{0,40}\\?sum"])),
    ),
    "remembered value is not a result": (
        "reporting",
        re.compile("|".join([_loose("remembered value is never a result"),
                             _loose("A remembered value is never")])),
    ),
}


def _prose_only(text: str) -> str:
    """Drop fenced code. A snippet that *implements* a convention is not a second
    statement of it, the structure-factor code has to divide by N² to be correct."""
    return re.sub(r"```.*?```", "", text, flags=re.S)


def check_duplication() -> None:
    for rule, (owner, pattern) in CANONICAL_RULES.items():
        hits = [f.parent.name for f in skill_files()
                if pattern.search(_prose_only(f.read_text()))]
        if owner not in hits:
            fail("DUPLICATION", f"'{rule}' should be owned by `{owner}` but is not stated there")
        extra = [h for h in hits if h != owner]
        if extra:
            fail("DUPLICATION",
                 f"'{rule}' is owned by `{owner}` but also stated in: {', '.join(extra)}. "
                 f"Point at the owner instead of restating it.")


# Vocabulary check.
WORKFLOW_PHASE = re.compile(
    r"\bPhase\s+[0-9]|\bphases?\s+of\s+the\s+study|\bphase\s+boundar\w*\s+(?:of\s+the\s+)?(?:study|workflow)"
    r"|at\s+every\s+phase\s+boundary|\bphase\s+machine\b"
)


def check_vocabulary() -> None:
    for f in [PROMPTS, *skill_files(), SKILLS / "README.md"]:
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if WORKFLOW_PHASE.search(line):
                rel = f.relative_to(ROOT)
                fail("VOCABULARY", f"{rel}:{n} uses 'phase' for a workflow step; say 'stage'")


# References check.
STEP_REF = re.compile(r"\b(?:step\s+)([A-E][0-9]a?′?)\b")
STEP_DEF = re.compile(r"^#{2,3}\s+([A-E][0-9]a?′?)\b", re.M)


def check_references() -> None:
    defined: set[str] = set()
    for f in skill_files():
        defined |= set(STEP_DEF.findall(f.read_text()))
    for f in skill_files():
        text = f.read_text()
        for ref in set(STEP_REF.findall(text)):
            if ref not in defined:
                fail("REFERENCES",
                     f"{f.relative_to(ROOT)} points at step `{ref}`, which no skill defines")


# Structure check.
def check_structure() -> None:
    for f in skill_files():
        text = f.read_text()
        rel = f.relative_to(ROOT)
        if not text.startswith("---\n"):
            fail("STRUCTURE", f"{rel} has no frontmatter")
        for key in ("name:", "description:"):
            if f"\n{key}" not in text[:1200]:
                fail("STRUCTURE", f"{rel} frontmatter is missing `{key}`")
        if "## Local rules" not in text:
            fail("STRUCTURE", f"{rel} has no `## Local rules` section")


# Prose check.
ACRONYMS = {"DMRG", "ARGS", "JSON", "MPS", "MPO", "SVD", "SPT", "ED", "OK", "FAIL", "NB",
            "SU", "ID", "LSM", "XY", "XXZ"}   # SU(2), the rule-ID scheme, and model names
                                              # used as illustrations
SHOUT = re.compile(r"\b[A-Z]{2,}\b")


def check_prose() -> None:
    for f in [*skill_files(), SKILLS / "README.md"]:
        text = f.read_text()
        # strip fenced code blocks, capitals there are code, not emphasis
        prose = re.sub(r"```.*?```", "", text, flags=re.S)
        prose = re.sub(r"`[^`]*`", "", prose)
        bad = {w for w in SHOUT.findall(prose) if w not in ACRONYMS}
        if bad:
            fail("PROSE", f"{f.relative_to(ROOT)} shouts: {', '.join(sorted(bad))}")


# Assertions check.
# A skill file should not assert facts the agent could verify itself in seconds. This
# flags the phrasings that mark such an assertion. It over-fires, since a definition and
# a structural argument look the same to a regex, so it reports for review rather than
# failing the build.
ASSERTION_SHAPES = re.compile(
    r"\b(is broken by|lands on|always gives|never has|will always|is guaranteed"
    r"|are identically equal|is exactly what you)\b", re.I)


def check_assertions() -> None:
    for f in [PROMPTS, *skill_files()]:
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if ASSERTION_SHAPES.search(line):
                print(f"REVIEW  {f.relative_to(ROOT)}:{n} reads like an asserted fact: "
                      f"could the agent check this instead? {line.strip()[:70]}")


def main() -> int:
    check_duplication()
    check_vocabulary()
    check_references()
    check_structure()
    check_prose()
    check_assertions()

    if FAILURES:
        for line in FAILURES:
            print(line)
        print(f"\n{len(FAILURES)} problem(s)")
        return 1
    print(f"skills OK: {len(skill_files())} skills, all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
