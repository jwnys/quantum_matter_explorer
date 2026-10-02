# The skill library: a guide for whoever maintains it

This directory is the group's method for mapping a phase diagram, written down. The agent reads
it, but it is meant for you first: if you cannot read a file here, disagree with it, and add your
own rule to it, then it has failed at its main job and the physics will drift without anyone
noticing.

This page is not read by the agent. It explains where things live, how the files are written, and
how to change them.

---

## How the whole thing is arranged

The system prompt in `qme/prompts.py` holds control flow: the stages, the rules that always apply,
and how to operate the workspace. Everything else lives here.

The division is deliberate and worth stating precisely, because getting it wrong has already cost
us. A rule that must hold everywhere appears in the prompt as a one-line invariant with a one-line
reason, because the prompt is in context on every turn and a skill is only in context if it was
opened. The *method* (how you actually do the thing, and what goes wrong) lives in exactly one
skill, and every other file that touches it points there rather than restating it.

That last part is not a style preference. The entanglement-scaling rule was once written out in
three skills, and one of the three had the factor the wrong way round. Anyone fixing "the one file"
would have left two stale copies behind. `tools/check_skills.py` now fails the build if a canonical
rule is stated in more than one place.

The agent sees every skill's name and description at all times, and reads the body of a skill when
it needs it. So descriptions are routing: they say *when* a skill applies, not what topic it
covers.

## The stages, and which file owns each

| Stage | What it decides | Skill |
|---|---|---|
| **0a** Understand | What the Hamiltonian actually is: operator convention, symmetries, sector, geometry, sizes, anchors | `model-setup` |
| **0b** Prove | Whether the code implements that Hamiltonian | `ed-validation` |
| **1** Survey | A coarse map: where anything changes across the full range | `observables` |
| **2** Refine | Where each boundary sits, and what order the transition is | `transitions` |
| **3** Identify | What phase each region is | `phase-id` |
| **4** Scale | What survives to the infinite system | `scaling`, and `disorder` if anything is random |
| **5** Report | The note, the figures, `phase_diagram.json` | `reporting` |

These numbers are the ones the system prompt uses. There is one scheme, not two. Inside a skill,
individual decision steps carry their own labels (`A1`-`A5` in `model-setup`, `D0`-`D5` in
`phase-id`, `E1`-`E4` in `transitions`) and those are what cross-references point at.

Two skills sit outside the sequence. `itensor-dmrg` is code (patterns, settings, and the crashes
worth knowing about), read whenever Julia gets written. `disorder` is cross-cutting: it applies at
every stage, for any model with quenched randomness.

The stages are a loop, not a pipeline. Stages 2 and 3 in particular feed each other: you cannot
place a boundary between two regions you have not identified, and you often identify a region from
points taken while refining the boundary beside it. A validation failure goes back to 0a, or to the
run settings: `ed-validation`'s triage table says which.

---

## How these files are written

Every skill follows the same shape, and the shape exists so that you can find things and add
things, not so that every section reads alike.

- A map at the top, for orientation. It is a table of contents, not the content.
- The body in readable prose. Each decision step says what the question is, how to measure it,
  how to read the branches, and how the step is usually got wrong.
- `## Local rules` at the end, reserved for this group's own additions.

Three principles matter more than the shape.

**Every rule says why it exists.** "Divide by `N`" is an instruction. "Divide by `N`, or every
critical region gets labelled ordered" is something you can maintain, because you can tell when
it applies and whether a rule you want to add would conflict with it. A rule without its reason
becomes untouchable: nobody knows if it is load-bearing.

**Teach the judgement, not the answer.** A bare number gets followed blindly and is wrong the
first time it meets a model we did not anticipate. So where a quantity has to be chosen (bond
dimension, sizes, sweeps, how many disorder realisations), the file explains what the choice
trades off and how to read the right value off the convergence report and the remaining budget.
Numbers appear as worked illustrations carrying their conditions, never as instructions.

**No model names as triggers.** Rules are tests on the Hamiltonian or on the data. A rule that
fires on "this is an XXZ chain" fails on the next model. The same rule written as "`H` conserves
`S^z_tot` and carries a field conjugate to it" works on models nobody has written down yet. Model
names appear only as illustrations, and are marked as such.

### The structure is a skeleton, not a mould

A step whose answer is unambiguous needs three sentences. One that is genuinely hard needs a
worked example and a paragraph on when the method fails. If thirty consecutive sections have
identical proportions, the file reads as generated no matter how good each section is: sameness
is its own kind of unreadable.

Keep the headings, since they are what makes a file navigable. Vary everything underneath them.

### Things that make text unreadable, which these files avoid

Capitals used for emphasis. Bold stacked on top of capitals. Three asides packed into one
sentence. Ideas arriving in threes because three sounds complete. Repeating a rule in four places
so it sticks: say it once, in the file that owns it, and trust the reader. Every bullet opening
with a bolded phrase and a dash.

A useful check: read a paragraph aloud. If you cannot get through it in one breath, it has too
many clauses.

Write in a voice. "We take the exact-diagonalisation point at `N = 12` because that is where it
is still instant" carries a reason and an author. "The ED cross-check should be performed at a
small system size" carries neither. And say where the method is genuinely uncertain instead of
hedging everything at the same pitch: a file that admits a measurement is ambiguous below some
size is more useful than one that sounds equally confident about everything.

---

## Adding a rule

1. **Find the stage it belongs to** from the table above. If it does not belong to one, it is
   probably an invariant that holds everywhere, which means it belongs in the non-negotiables in
   `qme/prompts.py` rather than here.
2. **Put it in that file, and only that file.** If it seems to belong in two, it is two rules.
3. **Say what goes wrong without it.** If you cannot, it may not be a rule yet.
4. **Give it an ID** if it is a decision step, following the local scheme (`D1`, `E2`, and so on).
   IDs get cited by the critic and in run logs, so they should not be reshuffled casually.
5. **If it is specific to this group** rather than general physics (a house convention, a
   preferred diagnostic, a local threshold), put it under `## Local rules` at the end of the file.
   That section is yours and does not get rewritten.

### Where the rules run out

These files are a floor, not a ceiling. The system prompt tells the agent that if it knows a better
method than the one written here it should use it, on two conditions: that it says so and why, and
that the licence covers *methods* only: never a remembered answer standing in for a measurement.

That matters for maintenance, because it turns the library into something that grows. A run that
reached for a technique these files do not mention has, in effect, filed a suggestion: the
reasoning is in its `plan.md` and its note. Reading those is the cheapest source of additions you
will get, and `## Local rules` is where they land until someone decides they are general enough to
move up.

The non-negotiables in the prompt are the exception and are not open to improvement by a better
technique: each marks a place where the plausible move produces a wrong answer that survives every
check. If you think one of them is wrong, that is a conversation, not an override.

### A rule that would be wrong

Rules keyed to a model name, or to an adjective standing in for a test. "Anisotropic models need
component-resolved correlators" sounds right and misfires on any model with an exchange anisotropy
along the quantisation axis, which is anisotropic and conserves `S^z_tot` perfectly. Written as
"if `[H, S^z_tot] ≠ 0`, resolve the correlators by component", it is correct and applies to models
nobody has thought of.

---

## Enforcement

Some skills are not optional, and the agent is stopped in code rather than asked in prose:
`model-setup` before the first production run, `itensor-dmrg` before writing Julia,
`ed-validation` before writing an exact-diagonalisation script, `reporting` before finishing.

Each gate fires once and then releases: it is a speed bump, not a wall, so a bug in the gate
cannot deadlock a run. The gates turn off entirely when skills are disabled, so the no-skills
ablation still runs. The flag is `agent.enable_skill_gate`.

---

## Known gaps

Recorded so they are found rather than rediscovered. None is fixed. Each is a real hole.

**The library demands an uncertainty it never teaches how to compute.** N8 says no number without
one. `scaling` supplies fit uncertainties, but the standard way to put an error bar on a DMRG result
(extrapolating in the discarded weight, or quoting how much a quantity moved between two bond
dimensions) appears nowhere. As it stands the agent is asked for something the library does not
explain.

**Coverage can be satisfied by a grid that missed a phase.** N13 requires every part of the range to
be inside a labelled region or marked unexplored, and a coarse scan can meet that while stepping
straight over a narrow phase. Nothing says how to choose the initial scan resolution, or how to
record the width below which a phase would have been invisible. `observables` covers *what* to
measure and `transitions` starts from a boundary you have already found. Survey design has no owner.

**Deterministic non-uniformity has no owning skill.** `disorder` covers parameters drawn from a
distribution. A modulated or incommensurate coupling is neither uniform nor random, and the only
place that knows it exists is the localisation check inside `phase-id` D3′.

## Glossary

Terms the skills use without re-defining.

**Channel**: a correlation function you measure and test for order: spin along some component,
bond, chirality, and so on. Each channel has its own structure factor and its own order
parameter.

**Structure factor `S(q)`**: the Fourier transform of a correlation function. Its peak position
gives the ordering wavevector, and its peak is the squared order parameter. `observables` fixes
the normalisation that makes that true. Nothing else restates it.

**Ordering wavevector `q*`**: where `S(q)` peaks. `π` is a two-sublattice antiferromagnet, `0` a
ferromagnet, anything else a spiral or incommensurate structure.

**Order parameter `m²`**: defined in `observables`, extrapolated to infinite size. Finite means
long-range order. Zero means none.

**Long-range order**: correlations that survive to infinite separation. Distinguished from
**quasi-long-range order**, where correlations decay as a power law: both give a growing `S(q*)`,
and only the first gives a finite `m²`.

**Sector**: a subspace with a fixed value of a conserved charge, usually `S^z_tot`. DMRG works
inside one, which is a speed-up when you know the right one and a trap when you do not.

**Conjugate field**: a term coupling to a conserved charge, such as a field along `z` coupling to
`S^z_tot`. Its presence means the ground-state charge varies rather than staying fixed.

**Plateau**: a range of field over which the magnetisation stays constant. A gapped phase, not a
feature.

**Commensurate `L`**: a system size compatible with the periodicity of the order you expect. A
period-four pattern needs `L` divisible by four. Mixing commensurate and incommensurate sizes
scatters extrapolations.

**Central charge `c`**: the coefficient of logarithmic entanglement growth in a critical region,
identifying the universality class. The coefficient differs by a factor of two between open and
periodic boundaries, so the boundary conditions must be stated with any quoted `c`.

**Correlation ratio**: a dimensionless combination of structure-factor values whose curves for
different sizes cross at a transition. The primary tool for locating continuous boundaries.

**Self-averaging**: whether a disordered system's sample-to-sample fluctuations shrink as it
grows. If they do not, a mean over realisations is not a meaningful number and typical values are
needed instead.

**Typical versus average**: for a quantity varying wildly between disorder realisations, the
arithmetic mean can be dominated by rare samples while the typical value, `exp⟨ln X⟩`, describes
what you would actually see. They can differ by a diverging factor.

**SPT (symmetry-protected topological)**: a gapped phase with no local order that cannot be
connected to a product state without breaking a specific symmetry. Distinct from intrinsic
topological order, which does not exist in one dimension.

**String order parameter**: a non-local correlation function that detects SPT order where every
local order parameter vanishes.

**Entanglement spectrum**: the Schmidt values across a cut, viewed as a spectrum. Its degeneracy
pattern is the sharper SPT diagnostic.

**Anchor**: a parameter point where the answer is known without computation, used to check the
code. At least one must be sensitive to the operator convention.
