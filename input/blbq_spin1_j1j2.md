# Frustrated Bilinear-Biquadratic Spin-1 Chain with Single-Ion Anisotropy

## Hamiltonian

$$
H = \sum_{i}\Bigl[
  J_{1}\bigl(\cos\theta \, \mathbf{S}_{i}\cdot\mathbf{S}_{i+1}
           + \sin\theta \, (\mathbf{S}_{i}\cdot\mathbf{S}_{i+1})^{2}\bigr)
  + J_{2}\bigl(\cos\theta \, \mathbf{S}_{i}\cdot\mathbf{S}_{i+2}
           + \sin\theta \, (\mathbf{S}_{i}\cdot\mathbf{S}_{i+2})^{2}\bigr)
  + D (S^{z}_{i})^{2} \Bigr]
$$

where:

- $\mathbf{S}_i$ are spin-1 operators ($S = 1$, so $S^{z}$ has eigenvalues $-1, 0, +1$).
- Each bond carries both a bilinear term $\mathbf{S}_i\cdot\mathbf{S}_j$ and a biquadratic
  term $(\mathbf{S}_i\cdot\mathbf{S}_j)^2$, mixed by the single angle $\theta$.
- $J_1$ is the nearest-neighbour coupling and $J_2$ the next-nearest-neighbour coupling.
- $D$ is a single-ion anisotropy acting on every site.
- Open boundaries.

Fix $J_{1} = 1$ to set the energy scale, and fix the bilinear-biquadratic angle at

$$\theta = 0.2\pi .$$

## Parameter ranges to explore

- $J_{2} \in [0, 1]$
- $D \in [-4, 4]$

## Notes

Treat as unknown. Discover the phases and the boundaries between them from scratch. Do not
assume how many phases there are.
