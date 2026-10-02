---
name: disorder
description: Read this whenever any coupling, field or other parameter of the Hamiltonian is drawn from a distribution rather than fixed. Covers how many realisations to run and how to seed them, why an average over realisations can be the wrong number to report, and which of the standard extrapolations stop working. Applies at every stage, not at one point in the workflow.
---

# When the Hamiltonian is drawn from a distribution

Everything else in this library assumes each parameter point is one Hamiltonian. Here it is an
ensemble, and three habits that are safe elsewhere become unsafe: reporting a mean, extrapolating
against `1/L`, and reading a logarithmic entropy as a central charge.

Read this at the start of the study, not at the end. It changes how the survey is run, not just how
the results are summarised.

## Map

```
one realisation is not a result       →  run many, with a controlled seed set
does the quantity self-average?       →  test it before quoting any mean
   yes  →  mean and standard error are fine, proceed normally
   no   →  report the distribution; typical and mean are different numbers
extrapolations                        →  1/L may be the wrong form; check before fitting
```

---

## The seed set

**A single realisation is not a measurement.** It is one sample from a distribution, and at small
sizes the sample-to-sample spread is often larger than the effect you are looking for.

Two rules for how to draw them:

**Use the same seeds across system sizes.** If each size samples an independent set, the
finite-size trend mixes the size dependence with sampling noise, and the extrapolation scatters for
a reason that has nothing to do with the physics. A common seed set means you are following the
same ensemble as it grows. Make that concrete: one seed per realisation index, consumed in site
order, so that realisation `r` of a smaller system is the first `L` couplings of realisation `r` of
the larger one. The same seed alone does not guarantee this if the draws are consumed in a
different order.

**Spend more realisations near a boundary than inside a phase.** Deep inside a phase the samples
agree and a handful suffices. Near a transition the distribution broadens. That broadening is
itself physics, and you need enough samples to resolve it rather than to average it away.

If the spread next to your signal is large, the first response is more realisations, not a wider
error bar on the ones you have.

**How many.** Order-of-magnitude guidance, to be adjusted by the self-averaging test below: a few
tens of realisations (30–50) deep inside a phase, where samples agree, and a hundred or more near
a transition, or wherever the distribution itself is the result. Report the number of realisations
beside every disorder-averaged quantity.

---

## Does the quantity self-average?

This is the test that decides how to report everything else, and it is usually skipped.

**The question.** As the system grows, do different realisations agree better or not?

**How to measure it.** For the quantity in question, compute the spread across realisations
relative to its mean, at two or three sizes. If that relative spread shrinks as the system grows,
the quantity self-averages: the ensemble is converging on a single value, and the mean over
realisations is the number to report.

If the relative spread stays constant or grows, it does not. Then the mean is a summary of a
distribution that never narrows, and quoting it alone hides the result.

**What to do when it does not self-average.** Report the distribution, and report two numbers where
you would normally report one:

- the **arithmetic mean**, which can be dominated by rare samples
- the **typical value**, the exponential of the mean of the logarithm, which describes what a
  single realisation actually looks like.

When these differ substantially, that difference is the finding. It says the ensemble is controlled
by rare regions rather than by the average one: a real physical statement, and one that vanishes
if you report only the mean. For strongly disordered systems the two can differ by a factor that
grows without bound as the system does.

Medians and quantiles are better than mean-and-standard-error for anything with this character,
because a standard error is a statement about a distribution being narrow, which is exactly what
you have established it is not.

---

## Which extrapolations stop working

**Gaps.** In strongly disordered systems the gap does not close as a power of system size. The
logarithm of the gap scales with a power of the size instead, so plotting the gap against `1/L`
gives a curve that bends and an extrapolation that depends entirely on where you truncated. Look at
the distribution of the logarithm of the gap across realisations before choosing a form: if the
logarithm scales cleanly and the gap does not, use the form that fits.

**Correlations.** The average correlation function and the typical one can decay with different
functional forms: one as a power of distance, the other stretched-exponentially. Fitting the mean
and quoting a single exponent then describes neither. Fit both and say which is which.

**Entropy.** A strongly disordered critical region still shows logarithmic growth of the block
entropy, so the measurement succeeds and the fit looks fine, but the slope is not a central
charge, and it is worth being precise about why, because the naive correction is as wrong as the
error.

In a clean critical region the coefficient is fixed by the underlying conformal field theory and
names the universality class. A disordered critical point is governed by a fixed point of a
different kind, where the disorder grows without bound under coarse-graining, and no such field
theory describes it. What survives is an *effective* coefficient. It is still universal (it does
not depend on which distribution the couplings were drawn from) and its value identifies the
phase, which makes it one of the more informative numbers a disordered study can produce. For the
random-singlet phase of a random antiferromagnetic spin-½ chain it is `ln 2`.

So: measure it, report it as an effective coefficient, say plainly that it is not a central charge,
and compare it against the known infinite-randomness values. Do not attach a universality class to
it, and do not throw it away.

Two things this does not license. Logarithmic growth is a property of the disordered *critical*
regime. A disordered region that is gapped obeys an area law and the entropy saturates, so confirm
which you are in before fitting. And if you quote a reference value for a fixed point other than
the random-singlet one, check it against a source first rather than from memory.

---

## Consequences elsewhere in the workflow

**Translation invariance is gone for any single realisation**, so `q` is not a good label there and
the transform of one sample mixes unrelated things. Averaging restores it, though: the averaged
correlator depends only on separation, so a structure factor built from the *averaged* correlator is
well defined and is the usual object. Average first, transform second (never the other way round),
and use whichever statistic the self-averaging test above told you to.

**Order parameters** are still extrapolated the same way once you have chosen the right statistic.
The change is which statistic, not which quantity.

**Validation** is unaffected in kind, but pin the seed. The exact-diagonalisation cross-check must
use the identical realisation as the DMRG point it is compared against, or the two are solving
different Hamiltonians and the disagreement means nothing. Record the seed alongside the couplings.

**Budget.** Every parameter point now costs a factor equal to the number of realisations. That is
the dominant cost multiplier in a disordered study and it has to be in the plan from the start, not
discovered in Stage 4. Fewer parameter points with adequate sampling beats a dense scan with one
realisation each: the latter is not a coarse version of the right calculation, it is a different
and wrong one.

---

## Local rules

Additions specific to this group go here. They survive regeneration of the rest of the file.

<!-- e.g. house realisation counts, preferred seeding scheme, local conventions for reporting distributions -->
