---
name: itensor-dmrg
description: Read this before writing or editing any DMRG Julia file. Code patterns for the Hamiltonian, the observables and the parameterised scan script, how to tell a converged run from an unconverged one, and the library traps that cost the most time - a correlator identity that silently does nothing, a deprecated constructor, and a scope rule that produces a confusing error. Verified against ITensorMPS v0.4.1.
---

# Writing the Julia

Everything here is verified against the pinned `third_party/ITensorMPS.jl` v0.4.1. Where a name has
changed, the old one usually still works through a deprecation shim. Use the current name, because
the shim will go and the warning is easy to miss.

Physics decisions do not live here. What to measure is in `observables`, which sector to work in is
in `model-setup`, and what the numbers mean is in `phase-id`.

## Start every Julia file with these imports

```julia
using ITensors
using ITensorMPS      # REQUIRED: siteinds, MPO, MPS, dmrg, random_mps, correlation_matrix
```

`ITensors` alone is *not* enough and fails in a way that looks like a typo rather than a missing
import. The MPS/DMRG layer was split out into its own package, so the names this skill uses live in
`ITensorMPS`. Loading only `ITensors` gives

```
UndefVarError: `siteinds` not defined in `Main`
```

on the very first line that builds a lattice, and the same for `dmrg`, `random_mps`, `MPO` and
`correlation_matrix`. Add `using JSON3` (or `JSON`) when the file writes results, and `using Random`
when it shuffles. Every code block below assumes these imports are already at the top of the file
and does not repeat them.

## File layout

Three files, all included at top level (never inside a function, which triggers a world-age error):

- `hamiltonian.jl`: `build_hamiltonian(sites, params)` returning the MPO. Read couplings with a
  default so older parameter files keep working, and add terms, never rename them. The operator sum
  takes terms on any number of sites at any separation: a three-site chirality or a ring exchange
  is written the same way as a nearest-neighbour bond, by listing operator and site index in turn.
  Longer and denser terms cost bond dimension in the resulting MPO, which is a performance matter
  rather than a correctness one. A Dzyaloshinskii-Moriya or other chiral term makes the operator
  sum complex. The library needs no flag for that, the MPO and the state simply become complex, but
  the structure factor below must then use the complex exponential, and correlators may be complex.
- `observables.jl`: the measurement functions, one per quantity, writing under the canonical keys
  fixed in `plan.md`. Additive, with stable signatures.
- `scan.jl`: one parameterised script. Reads a parameter file path from `ARGS[1]`, writes its
  output JSON to `ARGS[2]`. Print compact diagnostics to standard output.

For a series of independent points (a survey grid, a size ladder), use the batch runner with one
call and a list of argument strings rather than a Julia loop inside the script or many separate
calls. It runs them in parallel in isolated processes, so one crash costs one point.

Prefer a batch that holds one system size across many couplings over one that spans several
sizes: every point you want at N=24 in one call, then every point at N=36, and so on. A batch
returns only when its slowest job returns, and DMRG cost climbs steeply with size, so a batch
that mixes sizes leaves most slots idle while a few large points finish, and hands you nothing
until they do. One size per batch keeps the jobs roughly equal in cost, and the small sizes come
back in minutes.

---

## A run

```julia
sites  = siteinds("S=1/2", N; conserve_qns = true)   # or "S=1", "S=3/2"
H      = build_hamiltonian(sites, params)            # returns the MPO already; do not re-wrap
psi0   = random_mps(sites, initial_state; linkdims = 10)
sweeps = Sweeps(12)
maxdim!(sweeps, 64, 128, 256)                        # the last value repeats for later sweeps
cutoff!(sweeps, 1e-8)
noise!(sweeps, 1e-6, 1e-7, 1e-8, 0.0)
energy, psi = dmrg(H, psi0, sweeps; outputlevel = 0)
truncerr = maximum(last(dmrg_obs).truncerr)          # see below: record this, do not discard it
```

`random_mps` takes the state as a positional argument and the bond dimension as a keyword. The
older `randomMPS` name and its positional-`linkdims` forms are deprecated in v0.4.1.

**Those numbers are an example, not a setting.** Let the cutoff decide how many states to keep.**
`maxdim` and `cutoff` are two different things: the cutoff says how accurate you want the state,
the maxdim is a ceiling on how much memory you will spend getting there. Set the ceiling high
enough that it is usually not the thing stopping you, and let the cutoff do the work. Then record,
for every run, the truncation error and the bond dimension the state actually reached
(`maxlinkdim(psi)`).

That pair is the whole convergence story, and without it there is no way to choose a bond
dimension except by copying a number and doubling it when a result looks wrong. Read it like this:

- the state reached a bond dimension well below the ceiling, and the truncation error is at or
  below the cutoff: the cutoff was in control and the point is converged to that accuracy
- the state sat at the ceiling and the truncation error is above the cutoff: the ceiling was in
  control, the point is bond-dimension limited, and `scaling` says no label rests on it

A measured example of why this is not bookkeeping. One study ran the same points at maxdim 256 and
512 and got half-chain entropies identical to four decimals (0.1560, 1.0667, 1.5802 at three
points). DMRG costs go as the cube of the bond dimension, so the 512 runs were eight times the work
for no change in the answer, and the wasted time was spent on exactly the largest sizes that then
failed to finish. The 256-vs-512 comparison was already sitting in its own output. Nothing had
asked it to look.

**Raise the bond dimension until the quantity you will fit stops moving**, not until the energy
settles. Energy converges long before entanglement does, so an energy that looks converged tells
you almost nothing about an entropy or a correlation exponent (`scaling` owns this rule).

**`conserve_qns = true` fixes the sector to whatever the initial state has**, for the whole run.
That is a large speed-up when the sector is right and an invisible wrong answer when it is not.
`model-setup` decides which sector. This file is how you land in it.

**Building the initial state, which is how the sector actually gets chosen.** It is a list of
per-site state names, and the names depend on the spin length: `"Up"` and `"Dn"` for spin-½, with
`"Z0"` in the middle for spin-1, and so on up. Their `S^z` values add up to the sector you will be
stuck in.

So to target a total `S^z` of `M`, pick per-site states whose `S^z` values add up to `M`. Build the
list by walking the sites and taking whatever local state moves the running total towards the
target. That works for any spin length and any mixture of them, where counting "how many up" only
works for spin-½ with an even site count:

```julia
using Random                       # `shuffle` is not in Base

# names[i], vals[i]: the state names available at site i and their S^z values,
#   e.g. (["Up","Dn"], [0.5,-0.5]) for spin-1/2, (["Up","Z0","Dn"], [1.0,0.0,-1.0]) for spin-1.
function target_state(names, vals, M)
    N = length(vals); state = String[]; run = 0.0
    for i in 1:N
        lo = sum(minimum(vals[j]) for j in (i+1):N; init = 0.0)   # what the rest can still reach
        hi = sum(maximum(vals[j]) for j in (i+1):N; init = 0.0)
        k  = findfirst(v -> lo <= M - run - v <= hi, vals[i])     # keep the target reachable
        k === nothing && error("total Sz = $M is not reachable with these sites")
        push!(state, names[i][k]); run += vals[i][k]
    end
    return shuffle(state)              # spread them out; all-up-then-all-down is a domain wall
end
```

Seed the generator first (`Random.seed!(seed)`, with the seed recorded in the parameter file) so the
initial state can be reproduced when a run has to be repeated to diagnose a local minimum.

Check the target is reachable at all before you aim for it. The available totals run from `−S_max`
to `+S_max` in whole steps, so on a system whose spin lengths sum to a half-integer there is no
zero sector: asking for one is not a near miss, it is a value that does not exist.

And check the total afterwards: the convergence report prints it, and a mismatch means the sector
scan you think you are running is not the one you are running.

**Excited states.** `dmrg(H, [psi_gs], psi_init, sweeps; weight = w)` gives the lowest state
orthogonal to `psi_gs` *within the same sector*, which is frequently not the excitation you want.
See the gap section of `observables`. `w` has to dominate the gap you are resolving, and `10.0` is
a reasonable start, but the interface leaves three things to you and each one has produced a wrong
gap here.

*The energy it returns is not an energy of `H`.* The orthogonality is imposed by adding
`w |psi_gs><psi_gs|` to the Hamiltonian, and the reported eigenvalue belongs to that sum, so it
carries a `w |<psi_gs|psi>|^2` term. Recover the physical value with `inner(psi', H, psi)` before
you subtract anything.

*Nothing checks that the state came out orthogonal.* Store `inner(psi_gs, psi)` at every point. A
small overlap is what makes the difference a gap. A large one means you re-converged the ground
state, which happens when `w` is too small and also when the penalised run simply found a better
minimum than the first run did.

*A negative gap indicts the ground state, not the excited one.* Both runs search the same manifold,
and the penalised objective is nowhere below the plain `<H>` on it, so a penalised run cannot come
out below the true minimum of `<H>` there. If it comes out below your ground energy, the ground run
never reached that minimum. So treat the penalised energy as a better
upper bound on the ground energy, recompute every gap at that point against the lowest energy any
run there produced, including gaps that needed no penalty at all, and report none of them until two
independent starts agree. The same reasoning applies to a gap that is positive but far out of line
with its neighbours in size or in parameter.

Give the two calculations the **same** sweeps, maxdim and cutoff. It is tempting to give the excited
state more sweeps because excited states converge more slowly, and that is true, but while both
energies are still falling a sweep-count asymmetry biases the difference by construction and the
sign it produces is the sign of whichever run you stopped later. If one of them needs more sweeps,
give both more, and stop on a convergence criterion rather than a fixed count: sweep until the
last-sweep energy change is small compared with the gap you intend to resolve, in both runs.

---

## Is it converged?

The tool reports truncation error, total conserved charge and the final energy after every run.
Read them.

- **Truncation error** small and falling across sweeps.
- **Conserved charge** at the value you intended, which catches a sector mistake immediately.
- **Energy change over the last sweep** small compared to the differences you plan to resolve.

**Do not test for a monotonically decreasing energy.** With noise switched on the energy is not
variational sweep to sweep, so that check fails on healthy runs and teaches you to ignore it. Judge
the noiseless sweeps at the end.

**Run a second initial state at a few points in every study.** Different starting points can land
in different local minima, and if the energies differ by more than the truncation error the lower
one is the ground state and the settings need strengthening until they agree. Nothing else in the
workflow notices this. It is tempting to reserve the check for "frustrated" models, but that is an
adjective rather than something you can compute from a Hamiltonian you have not seen before, and
the check is cheap enough that a handful of representative points costs nothing.

One thing this check is not: evidence about the physics. Two starting points disagreeing means the
optimisation is stuck, not that the model has two competing states. `transitions` describes the
related experiment (sweeping a parameter up and then down) and is explicit that bistability there
must be shown to survive a larger bond dimension before it means anything.

**Two dials.** Bond dimension buys accuracy at fixed size, while size probes the thermodynamic limit.
The convergence report tells you which is limiting: if the truncation error is already small, more
bond dimension changes nothing and the question is finite size. Raising both by habit wastes the run.

---

## Entanglement entropy

There is no built-in function. Take the singular values yourself. The bond index and the tensor
index must match, which is the part that goes wrong:

```julia
function entanglement_profile(psi)
    N = length(psi)
    entropies = Float64[]
    for b in 1:(N - 1)                    # bond b cuts {1..b} | {b+1..N}
        orthogonalize!(psi, b)            # orthocentre at b, then decompose psi[b]
        linds = b == 1 ? (siteind(psi, b),) : (linkind(psi, b - 1), siteind(psi, b))
        _, S, _ = svd(psi[b], linds)
        p = [S[i, i]^2 for i in 1:dim(S, 1)]        # S is an ITensor; extract scalars
        push!(entropies, max(0.0, -sum(pj * log(pj) for pj in p if pj > 1e-14)))
    end
    return entropies
end
```

Iterate bonds `1 … N-1`. `linkind(psi, 0)` does not exist. Floor the small weights, or rounding
gives a tiny negative entropy. Avoid `pi` as a loop variable: it is already Julia's constant.

The same decomposition gives the Schmidt spectrum at the central bond, which `phase-id` uses at D4.
Take a fresh decomposition rather than reusing a leftover `S` from a loop, and keep the values,
not only the entropy made from them (`observables`):

```julia
# the leading Schmidt values at bond b, with their conserved-charge labels when quantum numbers are on
function schmidt_at_bond(psi::MPS, b::Int; nkeep = 16)
    psi = orthogonalize(psi, b)
    linds = b == 1 ? (siteind(psi, b),) : (linkind(psi, b - 1), siteind(psi, b))
    U, S, V = svd(psi[b], linds)
    u = commonind(U, S)
    vals = [real(S[k, k]) for k in 1:dim(u)]
    labels = Any[nothing for _ in 1:dim(u)]
    if hasqns(u)
        off = 0
        for bn in 1:nblocks(u)
            for k in 1:blockdim(u, bn); labels[off + k] = qn(u, bn); end
            off += blockdim(u, bn)
        end
    end
    p = sortperm(vals; rev = true)[1:min(nkeep, length(vals))]
    return vals[p], labels[p]
end
```

Store `vals` and `string.(labels)` under canonical keys at the designated bonds, the central
unit-cell-boundary cut and its neighbours one cell away. With open ends and an edge multiplet
present, take the spectrum with the edge modes polarised, as `phase-id` D4 prescribes. The labels
are what let multiplets be counted rather than guessed.

---

## One-point expectation values

```julia
mz = expect(psi, "Sz")            # ⟨S^z_i⟩ for every site in one call ("Sx" needs quantum numbers off)
```

A profile is cheap and three later steps read it: the magnetisation curve (`phase-id` D0), the
edge-versus-bulk test for a small gap (`observables`), and the decomposition of `S(q)` into its
one-point and connected parts (`observables`). So store it with every run. Whether a one-point
value *means* anything is a question about the symmetries of `H`, answered in `observables`. The
call itself is always allowed.

## Correlators

```julia
Czz = correlation_matrix(psi, "Sz", "Sz")     # C[i,j] = <psi| Sz_i Sz_j |psi>
Cpm = correlation_matrix(psi, "S+", "S-")
Cmp = correlation_matrix(psi, "S-", "S+")
C   = Czz .+ 0.5 .* (Cpm .+ Cmp)              # <S_i . S_j>
```

**The third call is not optional, and the shortcut that omits it silently does nothing.** Writing
`0.5 .* (Cpm .+ Cpm')` looks like a symmetrisation, but `'` is the adjoint, and for a Hermitian
expectation value the adjoint of that matrix *is* that matrix: `Cpm'[i,j] = conj⟨S⁺_j S⁻_i⟩ =
⟨S⁺_i S⁻_j⟩ = Cpm[i,j]`. The expression collapses to `Cpm`, so you have quietly dropped half the
exchange term.

What the real second call gives you is the transpose. Away from the diagonal `S⁺_i` and `S⁻_j`
commute, so `Cmp = Cpmᵀ` there, and `0.5 .* (Cpm .+ Cmp)` symmetrises in the *indices*. That
matters whenever `Cpm` is not already symmetric under swapping `i` and `j` (a complex or chiral
ground state, for instance).

On the diagonal the two orderings genuinely differ, always, whatever the state: they are
`S(S+1) − ⟨(S^z_i)²⟩ ± ⟨S^z_i⟩`, so they are separated by `2⟨S^z_i⟩`. For spin-½ that reads
`1/2 ± ⟨S^z_i⟩`. The diagonal enters a structure factor with weight `N`, so getting it wrong is not
a rounding matter.

Component correlators need quantum numbers switched off:

```julia
Cxx = correlation_matrix(psi, "Sx", "Sx")     # needs conserve_qns = false
Cyy = C .- Cxx .- Czz                         # exact, no extra call
```

The first call is why quantum numbers have to be off for these particular measurements: the
component correlator will not run with them on. That is a constraint of the tool. Whether the two
components can differ *at all* is a separate question about `H`, and `phase-id` D1a has the test.
Measuring both at one point answers it in seconds.

**Bond quantities come from the correlation matrix too.** Building a two-site operator on a freshly
created set of site indices gives indices that do not match `psi`, which is both wrong and slow:

```julia
function spin_correlations(psi)               # <S_i . S_j> for every pair
    Czz = correlation_matrix(psi, "Sz", "Sz")
    Cpm = correlation_matrix(psi, "S+", "S-")
    Cmp = correlation_matrix(psi, "S-", "S+")
    return Czz .+ 0.5 .* (Cpm .+ Cmp)
end

function bond_energies(psi)                   # <S_i . S_{i+1}> for every bond, in one shot
    C = spin_correlations(psi)
    return [real(C[i, i + 1]) for i in 1:(length(psi) - 1)]
end
```

---

## Structure factor

`S(q)` is a finite double sum and is defined at any `q`, so evaluate it on a grid as fine as you
like and fit the peak. Do not restrict to `q = πk/N`. `observables` explains what that costs.

```julia
# r = the physical position of each site. On a chain r[i] == i; on a ladder or cylinder it is
# NOT the index, because the index runs along the path the calculation was laid out on.
Sq(C, r, q) = real(sum(C[i, j] * cis(dot(q, r[i] - r[j]))
                       for i in axes(C, 1), j in axes(C, 2))) / size(C, 1)^2
```

Use the full complex exponential, not a cosine. They agree when the correlator is real and
symmetric, which it usually is, but a model with Dzyaloshinskii-Moriya terms or a chiral ground
state has a complex `C`, and a cosine throws away the part of it that carries the chirality. The
`cis` form costs nothing and is right in both cases. `real` at the end is then just discarding
round-off, since the sum is real for any Hermitian `C`.

Note the `1/N²`: that is the convention `observables` fixes, and it is chosen so the order parameter
is `S(q*)` itself with no second division. Store it that way and there is nothing left to normalise
twice or forget to normalise.

Save the full array with its `q` grid, and record which correlator it was built from. Saving a
structure factor under a key naming a different correlator ships two objects under one name, and
nothing catches it until someone tries to reproduce the figure.

---

## Operators on more than two sites: string order, chirality, bond-bond, pair-pair

`correlation_matrix` handles two single-site operators and nothing larger. Everything else is a
product of several single-site operators, and one pattern covers all of them. Write the product as
an `OpSum`, turn it into an MPO on the state's own site indices, and take the expectation value with
the three-argument `inner`. A term may hold any number of operator-site pairs, at any sites, with
any coefficient. Quantum numbers can stay on as long as every operator in the product is written in
the `S^z`, `S^+`, `S^-` basis.

```julia
# ⟨psi| O |psi⟩ for any operator written as an OpSum
function expect_opsum(psi::MPS, os::OpSum)
    M = MPO(os, siteinds(psi))          # on the state's own indices, never a fresh siteinds(...)
    return inner(psi', M, psi)
end

# A two-site operator A_i = Σ c · op1_i op2_{i+1} is a list of (c, op1, op2). Three examples:
bond     = [(1.0, "Sz", "Sz"), (0.5, "S+", "S-"), (0.5, "S-", "S+")]   # B_i = S_i · S_{i+1}
kappa    = [(1/(2im), "S-", "S+"), (-1/(2im), "S+", "S-")]               # κ^z_i = (S_i × S_{i+1})^z
pair     = [(1.0, "S+", "S+")]                                           # P_i = S^+_i S^+_{i+1}
pair_dag = [(1.0, "S-", "S-")]                                           # P_i^†

function twosite(terms, i)              # the operator itself, at site i, as an OpSum
    os = OpSum()
    for (c, a, b) in terms; os += c, a, i, b, i + 1; end
    return os
end
function twosite_corr(psi, A, B, i, j)  # ⟨A_i B_j⟩, a four-point function
    os = OpSum()
    for (c1, a1, b1) in A, (c2, a2, b2) in B
        os += c1 * c2, a1, i, b1, i + 1, a2, j, b2, j + 1
    end
    return real(expect_opsum(psi, os))
end
# ⟨B_i B_j⟩ = twosite_corr(psi, bond, bond, i, j)        ⟨κ_i κ_j⟩ = twosite_corr(psi, kappa, kappa, i, j)
# ⟨P_i P_j†⟩ = twosite_corr(psi, pair, pair_dag, i, j)   ⟨κ_i⟩ = real(expect_opsum(psi, twosite(kappa, i)))

# String correlator ⟨S^z_i exp(iπ S^z_{i+1}) ⋯ exp(iπ S^z_{j-1}) S^z_j⟩ for spin-1. Define the
# diagonal string operator once as a local op (exp(iπ m) over the S^z eigenvalues m = 1, 0, −1),
# and it is then just another name inside a product. Another spin length: write its own diagonal.
ITensors.op(::OpName"expiπSz", ::SiteType"S=1") = [-1.0 0 0; 0 1.0 0; 0 0 -1.0]
function string_correlator(psi, i, j)
    t = Any[1.0, "Sz", i]
    for k in i+1:j-1; push!(t, "expiπSz"); push!(t, k); end
    push!(t, "Sz"); push!(t, j)
    os = OpSum(); os += Tuple(t)
    return real(expect_opsum(psi, os))
end
```

Check any new operator against an independent dense diagonalisation at a small size before
trusting it (`ed-validation`). When many separations are needed, the MPO construction rather than
the contraction is the slow part.

## Fidelity between two states

```julia
F = abs(inner(psi_a, psi_b))        # |⟨ψ_a|ψ_b⟩|
```

Between neighbouring points of a scan at fixed size this is the model-free boundary flag described
in `transitions`. Two states in different conserved-charge sectors return exactly zero. That is a
statement about the sector, not about a transition, so read the reported charge first. Both states
must live on the same `sites` object, which means the same Julia process. Compute the overlap in a
scan that walks neighbouring points in sequence, keeping the previous state (the warm-started
refinement in `transitions` already has that shape), rather than across independent batch
processes.

## Output

```julia
using JSON3
results = Dict{String, Any}(
    "energy_per_site"     => energy / N,
    "structure_factor"    => collect(Sq_values),
    "q_grid"              => collect(q_values),
    "spin_correlation"    => [collect(r) for r in eachrow(C)],   # matrices → lists of lists
    "von_neumann_entropy" => collect(entropies),
    "sz_profile"          => collect(mz),                          # one-point profile (observables)
    "schmidt_center"      => collect(schmidt_vals),                # leading Schmidt values
    "schmidt_center_qn"   => string.(schmidt_labels),
)
open(ARGS[2], "w") do f
    JSON3.write(f, results)
end
```

Convert matrix rows before writing. Keep the key names identical to `plan.md`.

---

## Errors worth recognising

| What you see | What it is |
|---|---|
| `MethodError: no method matching inner(::MPS, ::MPO)` | That signature does not exist. The ground-state energy is what `dmrg` returned. Do not recompute it. For a general expectation value use the three-argument form with a primed bra |
| `AssertionError: hasinds(A, s)`, or a `MPO(::MPO, ...)` method error | An already-built MPO wrapped in `MPO(...)` again. `build_hamiltonian` returns the MPO. Use it directly |
| `UndefVarError: os not defined in local scope` | Julia soft scope: the operator sum was assigned inside a loop or branch, creating a new local. Create it at the top of the function and pass everything in as arguments |
| A world-age `MethodError` from a function you just defined | An `include` inside a function. Include at top level |
| `log(::Vector)` method error | Scalar functions do not broadcast implicitly. Use the dotted form |
| `BoundsError` assigning into an empty array | Push, or pre-allocate |
| Deprecation warning naming `random_mps`, `random_mpo`, `MPO` | You used `randomMPS`, `randomMPO` or `toMPO`. The shim works today |
| A negative entropy of order `1e-15` | Rounding. Floor the weights and clamp at zero |

**Same error three times means stop editing and shrink the problem.** Strip to the smallest thing
that can fail: build the Hamiltonian and run one tiny system, print the energy, no observables.
Confirm that works, then add measurements back one at a time. Editing a large script repeatedly
without running it fixes nothing, and a repeated timeout is the same signal: change the settings or
the size, do not resubmit them.

---

## Local rules

Additions specific to this group go here. They survive regeneration of the rest of the file.

<!-- e.g. house sweep schedules, local helper functions, cluster-specific settings -->
