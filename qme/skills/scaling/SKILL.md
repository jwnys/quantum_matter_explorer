---
name: scaling
description: Read this in Stage 4, and before quoting any number that describes the infinite system - an order parameter, a gap, a central charge, a transition location, a critical exponent. Covers extrapolating from the sizes you can reach, which functional form to assume, when a fit is not good enough to report, and the systematic errors that make a clean fit give a wrong answer.
---

# What survives the thermodynamic limit

Every phase label and every boundary so far has been a statement about systems of a few dozen
sites. This stage turns those into statements about the infinite system, or admits that they cannot
be turned.

The failures here are not usually arithmetic. They are a good fit to the wrong functional form, or
a clean extrapolation of a quantity that was contaminated before the fit began.

## Map

| Quantity | Extrapolate | Reports |
|---|---|---|
| order parameter (`observables` defines it) | against `1/L` | finite ⇒ ordered, zero ⇒ not |
| gap | against `1/L`, in a fixed sector | finite ⇒ gapped |
| block entropy | against the conformal length, **not** `ln ℓ` | slope ⇒ central charge |
| transition location | crossings against size | boundary position with an uncertainty |
| correlation exponents | `C(r)` on log axes | universality class |

---

## Before fitting anything

**Check that the quantity is converged in bond dimension, not just the energy.** This one comes
first because it can invalidate everything below it, and because the convergence report does not
cover it.

A matrix-product state at bond dimension `χ` can only carry so much entanglement: the block entropy
cannot exceed `ln χ` however long the chain is. And such a state always has correlations that decay
exponentially past some length that grows with `χ`. Both of those are properties of the
approximation, not of the model.

The consequence is specific and it is the most dangerous systematic error in this file. In a
critical region the true entropy keeps growing with block size, so at some point it runs into the
`χ` ceiling and the measured curve flattens. Correlations that truly decay as a power law will,
past the same scale, look exponential. Those are exactly the two signatures used to tell a critical
region from a gapped one, and they fail *in the same direction*, so a critical region can present
as convincingly gapped, with a good fit, from two independent measurements that agree with each
other. The energy meanwhile converges beautifully, because energy is far less sensitive to `χ` than
entanglement is.

So before fitting an entropy slope or a decay exponent, repeat the measurement at a larger bond
dimension and confirm the quantity itself is unchanged. Raise it until what you are about to fit
moves by less than the uncertainty you intend to quote, which is a different and later stopping
point than the energy settling. If the entropy is anywhere near `ln χ`, or the correlation length
you fitted is comparable to the one the
approximation imposes, the region is limited by `χ` and no label is supported yet. When larger `χ`
is unaffordable, there is a way to turn this round: at a critical point, with the system far
longer than the length the bond dimension imposes, the entropy grows with the bond dimension as
`S = ln χ / (√(12/c) + 1) + const` (finite-entanglement scaling), so a series in `χ` at fixed large
size yields `c`. State the form and the sizes used whenever this route is taken.

**Where the error bar on a single number comes from.** Every quantity quoted at fixed size
carries a systematic uncertainty from the approximation. Estimate it as the change of that
quantity between the two largest bond dimensions used, once the convergence criterion above is met.
For energies, a linear extrapolation in the truncation error is the standard refinement. A fitted or
extrapolated quantity combines that with the spread obtained by varying the fit window and the
functional form. This is the uncertainty N8 asks for on every number. The spacing of a parameter
grid is never an uncertainty.

**Compare like with like.** Same observable definition, same bulk window, same convergence
settings, same boundary conditions across every size in the fit. A size series that mixes settings
produces scatter that reads as poor convergence and invites you to spend compute on bond dimension
that was never the problem.

**Check the sizes can hold the pattern.** A size series mixing lengths commensurate with the ordering
period and sizes that are not will scatter for a reason that is not statistical, and no amount of
extra points fixes it. Stage 0a chose the list, and if the order that turned up is not the one
anticipated there, the list may need revisiting rather than the fit.

**Know which quantity you are extrapolating.** `observables` defines them: the order parameter is
the normalised `m²` defined there, not the raw peak, and the gap is within one symmetry sector, with
three distinct ways of being small that it also lists. Extrapolating the wrong quantity fits
perfectly well and answers a different question.

---

## Order parameters

Extrapolate `m²(L)` against `1/L`. A finite intercept is long-range order, and an intercept
consistent with zero is not.

The leading correction is often not `1/L`: at a critical point it is a different power, and in a
phase with gapless excitations there can be logarithmic corrections.

The worst case is a channel that transforms under a *continuous* symmetry of `H`, on a chain or
fixed-width ladder with short-range couplings. There true long-range order is impossible unless
the order parameter commutes with `H`, yet the log-corrected decay of the correlator (the
isotropic spin-½ chain goes as `√(ln r)/r`) makes a linear fit in `1/L` return a small positive
intercept. `phase-id` D1a states the rule and its two exceptions. Where it applies, a finite
intercept is a failed extrapolation, not order.

If a straight line in `1/L`
fits badly, that is a result about the region rather than a nuisance: it usually means you are
inside a critical phase or too close to a boundary, and the honest report is the failure of the
form together with what it suggests.

Do not force an intercept through zero and do not extrapolate two points.

---

## Gaps

Extrapolate against `1/L`. A finite limit is a gapped region.

**Say which gap you are extrapolating, because two different ones are useful and they scale
differently.** Within a fixed sector you get an excitation gap. Where a charge is conserved, the
cost of changing it (the difference between ground-state energies in neighbouring sectors) is
often the physically interesting one and is cheaper, being two variational calculations.
`observables` distinguishes them and lists the ways each can be small for uninteresting reasons.

`1/L` is the right form at a critical point and a crude interpolation elsewhere: deep in a gapped
region the finite-size corrections die away much faster than that. Look at how your own successive
differences behave before committing to a form: if they shrink by a roughly constant ratio rather
than like `1/L`, fit the behaviour you see.

A limit consistent with zero means gapless **only if the region is disordered**. If the region has
long-range order, a vanishing same-sector splitting is the degeneracy the order implies, and the
region is gapped and degenerate. Decide with the order parameter, not with the gap alone: this is
the same crossing-check Stage 3 asks for, and it is the reason the two quantities are extrapolated
together rather than in separate passes.

For a region with quenched randomness, `1/L` is very likely the wrong form entirely. See
`disorder` before extrapolating.

---

## Central charge

This is the one fit in the library where the formula has to be written down, because three separate
things about it are easy to get wrong and each produces a believable number.

**The forms.** For a block of length `ℓ` cut from a system of length `L`. Both lengths are measured
along the direction the system is long (the number of rungs on a ladder, not the number of sites),
because that is the length the formula refers to. On a chain the two coincide and the distinction is
invisible. On anything wider it is a factor you would otherwise carry into `c` unnoticed. And the
block is contiguous in space, which on a ladder or cylinder is not the same as contiguous in the
ordering the calculation was laid out on (see `observables`):

$$ S(\ell) = \frac{c}{6}\ln\Big[\frac{2L}{\pi}\sin\frac{\pi\ell}{L}\Big] + c_1
\qquad\text{(open)}, \qquad
S(\ell) = \frac{c}{3}\ln\Big[\frac{L}{\pi}\sin\frac{\pi\ell}{L}\Big] + c_1
\qquad\text{(periodic)} $$

**Fit against that whole logarithm, not against `ln ℓ`.** They agree only for `ℓ` far smaller than
`L`, and over the range you actually measure the `sin` factor bends the curve down at both ends. Fit
`ln ℓ` instead and the slope comes out low by tens of percent, enough to turn one universality
class into another.

**The coefficient is `c/6` for open chains and `c/3` for periodic ones**, so the boundary conditions
have to travel with any quoted `c`. Get it backwards in the common direction (open data fitted with
the periodic form) and the slope you measured is `c/6` while you divide by `1/3`, so you report
**half** the true value. This is the single statement of that rule in the library, and `observables`
and `phase-id` point here rather than repeating it.

Two further ways a central charge comes out wrong. Note that only the second of them is an error in
the data. The first can be real structure that the fit is not built to see.

**A modulated profile.** Open boundaries induce an alternating component in the entropy profile
whose amplitude decays into the bulk. Fitting through it inflates the scatter and biases the slope,
and splitting the cuts by parity removes it because it has period two. You can also use the form
that accounts for the geometry directly.

Two things that does not cover, and both have cost a central charge. The lattice permits a
modulation of any small period, and a parity split leaves every period but two untouched. And a
modulation whose amplitude does *not* fall off away from the ends is not a boundary effect at all,
so excluding the ends will not remove it either.

So when the residual of a central-charge fit is large next to the precision of the entropy values
going into it, the residual is a measurement and not scatter. Find out whether it has a period. If
it has one, report that period alongside any `c` you quote, and say whether its amplitude decays
into the bulk or holds up as the system grows, since the first is a boundary artefact and the second
is bulk structure. A `c` fitted on one residue class of a modulated profile is a statement about
that class, and quoting it without the period is how a fit can look like the cleanest number in a
study while being an artefact of which cuts happened to be sampled.

**Fitting inside a phase rather than at a critical point.** The logarithm only applies where the
region is genuinely gapless. A gapped region with a long correlation length looks logarithmic over
a limited range of sizes and then saturates. If your sizes all sit below the correlation length you
will fit a slope and report a central charge for a gapped phase. Check that the growth continues at
your largest size rather than flattening.

**If the model has quenched randomness, do not quote a central charge at all.** The entropy still
grows logarithmically, but the coefficient is set by the disorder rather than by an underlying
field theory, and calling it a central charge attaches a meaning it does not have. `disorder` has
the correct statement.

---

## Transition locations

Extrapolate the crossings from `transitions`, not the peaks. Successive pairs of sizes give a
sequence of estimates, and their trend gives both the limit and an honest uncertainty. Quote the
uncertainty from that spread rather than from the spacing of the parameter grid, which measures
your scan resolution and not your knowledge of the answer.

If the sequence drifts logarithmically rather than converging, the transition is of infinite order
and extrapolating the drift to a constant produces a number that depends on where you stopped.
Report the drift.

---

## When not to report a number

Any fitted or extrapolated quantity needs enough points to be over-determined, residuals that look
like noise rather than structure, and a stated functional form. Missing any of those, report the
measurement and the reason it does not support a number.

This is also where the temptation to substitute a value you already know is strongest, because a
fit that disagrees with what you expected looks like a problem to be corrected. It is a validation
check, not a result: `reporting` states the rule and why it matters. Here it is enough to say:
write down what the fit gave, say why you distrust it, and say what would settle it.

An inconclusive result with a named cause is a contribution. A confident number with no measurement
behind it is not.

---

## Local rules

Additions specific to this group go here. They survive regeneration of the rest of the file.

<!-- e.g. house fit-quality thresholds, preferred correction-to-scaling forms -->
