# Frustrated Spin-1/2 Two-Leg Ladder in a Transverse Field

## Hamiltonian

The system is a two-leg ladder of $N$ spin-1/2 sites arranged as $M = N/2$ rungs. Rung $j$
carries the two spins $S_{1,j}$ and $S_{2,j}$.

$$
\begin{aligned}
H = &-J \sum_{j=1}^{M}
   \Bigl[ \tfrac{1}{2}\bigl(S^{+}_{1,j}S^{-}_{2,j} + S^{-}_{1,j}S^{+}_{2,j}\bigr)
          + S^{z}_{1,j}S^{z}_{2,j} \Bigr] \\
        &-J \sum_{j=1}^{M-1}
   \bigl(S^{z}_{1,j} + S^{z}_{2,j}\bigr)\bigl(S^{z}_{1,j+1} + S^{z}_{2,j+1}\bigr) \\
        &-\frac{\alpha J}{2} \sum_{j=1}^{M-1}
   \Bigl[ \bigl(S^{+}_{1,j} + S^{+}_{2,j}\bigr)\bigl(S^{-}_{1,j+1} + S^{-}_{2,j+1}\bigr)
        + \bigl(S^{-}_{1,j} + S^{-}_{2,j}\bigr)\bigl(S^{+}_{1,j+1} + S^{+}_{2,j+1}\bigr) \Bigr] \\
        &-h_x \sum_{j=1}^{M} \bigl(S^{x}_{1,j} + S^{x}_{2,j}\bigr)
\end{aligned}
$$

where:

- $S^{\mu}$ are spin-1/2 operators, $S^{\mu} = \sigma^{\mu}/2$, so $S^{z}$ has eigenvalues $\pm 1/2$.
- The rung bond (first line) is an isotropic Heisenberg coupling of strength $J$.
- The inter-rung couplings (second and third lines) connect rung $j$ to rung $j+1$. Writing them
  as products of the rung sums $(S_{1,j} + S_{2,j})$ expands to four bonds per rung pair: two
  along the legs and two along the diagonals. The ladder is therefore frustrated.
- The inter-rung bonds are XXZ-anisotropic: their longitudinal ($zz$) part carries coupling $J$,
  while their transverse ($xy$) part carries $\alpha J$. So $\alpha = 0$ is a pure Ising inter-rung
  coupling, $\alpha = 1$ is fully isotropic Heisenberg, and $\alpha \gg 1$ is XY-dominated.
- $h_x$ is a uniform transverse field along $x$.
- Open boundaries along the ladder.

Fix $J = -1$ throughout (with the overall minus signs above this is the antiferromagnetic case).

## Parameter ranges to explore

- $\alpha \in [0, 2]$
- $h_x \in [0, 2]$

## Notes

Treat as unknown. Discover the phases and the boundaries between them from scratch. Do not
assume how many phases there are.

Two practical points, which are numerical rather than physical:

- An MPS is a one-dimensional object, so the ladder has to be mapped onto a chain before DMRG.
  Choose an ordering that keeps the interaction range short and state which ordering you used, since
  every coupling above must survive the mapping.
- The transverse field does not commute with $\sum_j S^{z}_j$, so no $U(1)$ charge is conserved once
  $h_x \neq 0$.

Think carefully about which diagnostics separate the candidate orders here. Different regions of this
plane break different symmetries, and some may break none at all, so a single order parameter is
unlikely to characterise the whole plane.
