---
name: reporting
description: Read this when writing up results, and before declaring the study finished. Covers what the research note has to contain and how it should read, which figures are required and why, the machine-readable phase diagram, and the two rules about what may be written down at all - that the diagram cannot claim more than was measured, and that a remembered value is never a result.
---

# Writing it down

The deliverables are a research note, the figures it embeds, and a machine-readable phase diagram.
Together they have to let somebody who was not here judge whether the conclusions follow from the
data, which means every claim carries the measurement behind it, and nothing appears that was not
measured.

Write as you go. A note assembled at the end from memory loses the reasoning, and a run that stops
early leaves nothing behind.

---

## The note

Markdown with inline and display maths. Not LaTeX: no document preamble, no sectioning macros.

The note lives in `note/research_note.md` and the figures in `plots/`, one directory up. Embed each
figure with the path **`../plots/name.png`**. The leading `../` is required. A bare `plots/name.png`
resolves relative to the note's own folder, `note/plots/`, which does not exist, so every image
silently fails to load and the deliverable looks empty to a reader.

**It should read as a short paper**, which mostly means the findings are prose with tables and
figures supporting them, rather than tables with sentences between them. A bare table is not a
finding. Each result gets a paragraph that says what was measured, how it was derived from the
data, what the numbers showed, and what that means, in that order.

When in doubt, explain more rather than less. A study that is too compressed to follow is worse than
one that takes its time, so it is better to over-explain your reasoning than to be terse, as long as
every sentence carries real content, since filler helps nobody. Each finding is therefore at least a
full paragraph, written in complete sentences, and it cites both the key numbers and the figure that
shows them, not one or the other. Every boundary, transition and phase label is argued for, with the
reasoning and the data that support it and the caveats that qualify it (finite size, convergence,
remaining uncertainty), rather than simply asserted. A reader who disagrees should be able to see
exactly which measurement to challenge.

Structure that follows the study rather than a template:

- **Introduction.** The Hamiltonian in display maths, every symbol defined, the lattice and its
  boundary conditions, the parameter ranges, and the question. Include the operator convention from
  Stage 0a. A reader cannot check a single number without it.
- **Method.** Each observable as a short paragraph: what it is, how it was computed, and how a
  phase is read from it. Give it a symbol and a defining formula here, once, and use only the
  symbol afterwards: do not restate the definition, and do not reintroduce the same quantity
  under a fresh English name later, since a reader cannot tell two names for one quantity from
  two separate quantities. For instance, define the staggered magnetisation
  $m_s = N^{-1}\sum_i (-1)^i \langle S^z_i \rangle$ once here and write $m_s$ everywhere after,
  rather than calling it "the staggered order parameter" in one section and "the antiferromagnetic
  moment" in another. The validation results belong here, including what the anchors were
  and what the cross-check gave.
- **A section per stage of the study**, added as the work happens rather than pre-created empty.
- **The phase diagram**, with the boundaries, their positions and uncertainties, and the transition
  character for each.
- **Conclusion**, stating what is established, what is uncertain, and what would settle the
  uncertainty.

Caveats belong next to the claims they qualify, not gathered at the end where they read as
disclaimers.

---

## Figures

**Every results section embeds a figure of its own result.** Describing a finite-size extrapolation
in prose and plotting only the survey is the most common way a study ends up unreviewable: the
reader cannot see the thing the conclusion rests on.

Required at minimum:

- the survey, as observables against the scan parameter, or heat maps for two parameters
- the evidence for each order identification: the extrapolation of the order parameter, and the
  structure factor if that is how the order was found
- each finite-size extrapolation, drawn as the actual fit with its points, not summarised as a
  number in the text
- **the phase diagram itself**, which is the headline deliverable. A phase-diagram study without a
  phase-diagram figure is not finished.

Save figures as `.png` at a resolution that keeps axis text legible. The note embeds `.png`, and
Markdown cannot embed `.pdf`. `.svg` is acceptable for line plots. For dense figures (heat maps,
meshes, anything with thousands of elements) raster is the only sensible choice.

**Embedding a figure: the embed path is *not* the same as the save path, and this is the single
most common mistake.** Your plotting scripts run from the run root, so they save into `plots/`:

    plt.savefig("plots/phase_diagram.png")        # in a script, run from the run root

But the note lives at `note/research_note.md`, one directory down. From there the same file is
reached by going up one level first, so the embed path carries a leading `../`:

    ![Phase diagram of the anisotropic XY chain](../plots/phase_diagram.png)     ← correct
    ![Phase diagram of the anisotropic XY chain](plots/phase_diagram.png)        ← wrong: this
        points at note/plots/, which does not exist, so the figure renders blank.

The rule is mechanical: **a figure you saved as `plots/NAME.png` is embedded as `../plots/NAME.png`.**
Do not reuse the `plots/…` string from your plotting script verbatim. Prepend `../` every time.

Do not read a figure file back to check it. You get the markup, not the picture, and it tells you
nothing. To verify a figure, check the numbers that went into it.

---

## The machine-readable phase diagram

Alongside the note, write `phase_diagram.json`: the phases with their regions, the boundaries with
their positions, uncertainties and character, and for each a pointer to the data that supports it.

```jsonc
{
  "phases": [
    {"label": "...", "region": {...}, "evidence": ["data/p12.json#m2_zz"], "confidence": "..."}
  ],
  "boundaries": [
    {"location": {...}, "uncertainty": ..., "order": "continuous",
     "method": "correlation-ratio crossing", "evidence": [...]}
  ],
  "validation": {"status": "passed", "anchors": [...], "cross_check": {...}},
  "unexplored": [{"region": {...}, "reason": "..."}]
}
```

This exists so the study can be checked without parsing prose, and so the reviewer has something to
verify against rather than an impression to agree with.

---

## Two rules about what may be written at all

### The diagram cannot claim more than was measured

Every part of the stated parameter range is either inside a labelled region with **at least one
measured point in it**, or marked unexplored with a reason. No boundary is drawn between two
regions unless both were measured, and no region is inferred from its neighbours.

This rule exists because the phase diagram is the easiest artefact in the whole study to produce
without evidence. A dozen points and a confident five-phase figure looks exactly like a hundred
points and a careful one, and nothing else in the workflow distinguishes them. Colouring in a
region you never visited is not interpolation, it is invention.

An honest figure with a blank area beats a complete-looking one that is partly guessed.

### A remembered value is never a result

Report what you measured. If a number comes out different from what you expected, that expectation
is a **validation check** (it tells you the calculation may have a problem) and not a substitute
for the measurement.

So: write down the measured value, say why you distrust it, and say what would resolve it.
Replacing it with the value you believe is correct is the most damaging thing that can happen in a
write-up, because it is undetectable. The number is right, the study established nothing, and no
reviewer, scorer or later reader can tell the difference.

The same applies to thresholds. A tolerance set before seeing the data is not renegotiable
afterwards. If a check misses its threshold, the finding is that it missed.

---

## Before finishing

Read the note from the top and confirm:

- every results section has a figure of its own result, and every referenced figure exists
- the phase diagram figure and the machine-readable file are both present and agree with each other
- every quoted number has an uncertainty and a statement of convergence, and every extrapolation
  has its fit shown
- every region in the figure has data inside it, and unexplored areas are marked
- the phase *count* has been argued, not only the labels: any two regions sharing a label were
  compared through their discrete invariants (broken symmetries, gapped or gapless, the
  entanglement-spectrum structure at the declared cut, ground-state degeneracy, plateau value,
  locked-versus-floating `q*`), and no boundary or feature separates two same-labelled regions
  without being explained or explicitly recorded as unresolved (`phase-id`, end of Stage 3)
- claims that the data does not support have been downgraded rather than defended, and every
  downgrade meets the standard of the promotion it reverses. Removing a label is a claim about the
  world and not an act of caution, so a study that deletes a label its own earlier work supported
  has made the map worse unless it can say which measurement was wrong and why. Name the estimator
  the downgrade rests on, say what that estimator is blind to, and record its value at a coordinate
  where the answer is already settled. An estimator that returns the same value where you believe
  there is order and where you believe there is none has decided nothing, and the label stands as
  it was
- every region left unidentified or unresolved records the three-step check from `phase-id` D5:
  found in the stored outputs, attempted once, or deferred with its named cost
- every reported quantity was defined once, with a symbol, in Methods, and is referred to by that
  symbol afterwards rather than by a fresh English phrase or a repeated definition
- the running log covers the whole study: the later analysis as well as the early survey, since
  that is the part that gets forgotten once the note exists.

Deferred work is acceptable when it is genuinely out of reach after the three-step check in
`phase-id` D5, and the note should say which: the specific cost or the missing method. "Future work" with nothing named is not a deferral, it is a
gap.

---

## Local rules

Additions specific to this group go here. They survive regeneration of the rest of the file.

<!-- e.g. house figure style, required sections, journal-specific conventions -->
