# XXZ Heisenberg Chain with External Field

## Hamiltonian

$$
H = J \sum_{i=1}^{L-1} \left( S_i^x S_{i+1}^x + S_i^y S_{i+1}^y + \Delta S_i^z S_{i+1}^z \right) - h \sum_{i=1}^{L} S_i^z
$$

where:
- $J > 0$ is the antiferromagnetic exchange coupling (set $J = 1$ as energy unit)
- $\Delta$ is the anisotropy parameter (controls the XXZ anisotropy)
- $h$ is an external magnetic field along the $z$-axis
- $S_i^\alpha = \frac{1}{2} \sigma_i^\alpha$ are spin-1/2 operators

## Parameter ranges to explore

- $\Delta \in [-1.5, 2.0]$  (ferromagnetic to Ising-like antiferromagnet)
- $h \in [0, 3.0]$           (zero field to above saturation)

## Notes

This is a standard model, but treat it as unknown:
discover all phases from scratch using DMRG.
