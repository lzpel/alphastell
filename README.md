# alphastell

A Rust CAD generator for stellarator fusion reactors, built on top of OpenCASCADE (via [`cadrum`](https://github.com/lzpel/cadrum)) and inspired by [parastell](https://github.com/svalinn/parastell).

![Cutaway render of the alphastell in-vessel build with the magnet coil set](./figure/image.png)

*Cutaway of the six in-vessel layers (chamber → vacuum vessel) with the 40-filament magnet coil set, produced by `make showcase`.*

## Overview

alphastell reads a [VMEC](https://princetonuniversity.github.io/STELLOPT/VMEC) magnetic equilibrium (`wout_*.nc`, NetCDF3) and produces solid CAD geometry for a full stellarator in-vessel build plus its modular coil assembly. It is intended as a small, fast, statically-linked companion tool for reactor-design studies — write a VMEC surface, get a STEP file you can drop into a CAD viewer or a neutronics pipeline.

Key outputs:

- **STEP** for CAD (`chamber`, `first_wall`, `breeder`, `back_wall`, `shield`, `vacuum_vessel`, `magnet_set`)
- **SVG** projected bird's-eye renderings for reports and docs
- **CSV** `x,y,z` point clouds for quick verification and plotting

One command reproduces the hero image above:

```bash
make showcase
```

points command for quick verification and plotting

```bash
make points
```

![img](figure/points.png)

## Relationship to parastell

alphastell is a Rust reimplementation of the core in-vessel and magnet geometry generation from [parastell](https://github.com/svalinn/parastell) (Python, MIT, maintained by the [Svalinn](https://github.com/svalinn) group at UW-Madison). It borrows:

- the VMEC Fourier evaluation recipe for `R(θ, φ)` and `Z(θ, φ)`
- the six-layer material stack (first wall, breeder, back wall, shield, vacuum vessel) and the standard thicknesses (5 / 50 / 5 / 50 / 10 cm)
- the `wall_s = 1.08` offset convention and the `Planar` in-cross-section normal offset method
- the `coils.example` MAKEGRID format for magnet filaments

Differences: the kernel is Rust + OCCT (bundled statically through `cadrum`), outputs can be cross-checked with `validate` against reference parastell STEP files (vendored under `parastell/examples/alphastell_full/`), and boolean-subtract-based shell construction is used instead of `Shell::offset`.

The `parastell/` directory is a vendored snapshot (not a git submodule). All credit for the underlying approach goes to the parastell authors; bugs in the Rust port are mine.

## Geometry recipe

### VMEC Fourier evaluation

Each `wout_*.nc` stores, for every radial grid point $s_i \in \{0, 1/(n_s-1), \ldots, 1\}$, the Fourier coefficients $\hat R_k(s_i)$ and $\hat Z_k(s_i)$ together with integer mode numbers $(m_k, n_k)$. Under stellarator symmetry (`lasym = 0`) the magnetic surface is

$$
R(s, \theta, \varphi) = \sum_{k=1}^{m_{\max}} \hat R_k(s)\,\cos\bigl(m_k\theta - n_k\varphi\bigr),\qquad
Z(s, \theta, \varphi) = \sum_{k=1}^{m_{\max}} \hat Z_k(s)\,\sin\bigl(m_k\theta - n_k\varphi\bigr).
$$

The 3D point is then $\mathbf p(s,\theta,\varphi) = \bigl(R\cos\varphi,\; R\sin\varphi,\; Z\bigr)$.

### Off-grid $s$: cubic spline per coefficient

For $s \notin \{s_i\}$ (in particular the `wall_s = 1.08` extrapolation point used by `vessel`), each coefficient $\hat R_k(s)$ and $\hat Z_k(s)$ is interpolated by an independent **cubic spline** along $s$. Two boundary conditions are implemented:

- **Natural** ($M_0 = M_{n-1} = 0$): calm extrapolation, used by default in the current code because `cadrum`'s periodic B-spline shell is sensitive to large coefficient swings.
- **NotAKnot** (scipy-compatible, $C^3$ across the first/last internal knot): reproduces parastell numerically, recommended once the cadrum side switches to a 2D poloidal offset.

The splines are constructed once per `VmecData` (lazy, cached in `OnceLock`) — per-point evaluation is then pure polynomial work.

### Analytic partial derivatives

Because the representation is a closed-form Fourier series, $\partial_\theta$ and $\partial_\varphi$ are obtained termwise without any finite difference. Let $\alpha_k = m_k\theta - n_k\varphi$. Then

$$
\frac{\partial R}{\partial \theta} = -\sum_k m_k\,\hat R_k(s)\,\sin\alpha_k,\quad
\frac{\partial R}{\partial \varphi} = +\sum_k n_k\,\hat R_k(s)\,\sin\alpha_k,
$$

$$
\frac{\partial Z}{\partial \theta} = +\sum_k m_k\,\hat Z_k(s)\,\cos\alpha_k,\quad
\frac{\partial Z}{\partial \varphi} = -\sum_k n_k\,\hat Z_k(s)\,\cos\alpha_k.
$$

All four partials fall out of the same loop that evaluates $R, Z$, so sampling on the $(M, N) = (128, 48)$ grid used by `vessel` costs one Fourier sweep per node.

### Two thickness conventions: `Planar` vs `Surface`

Each of the six in-vessel layers is defined as an **offset surface** of the reference flux surface at `wall_s = 1.08`, with cumulative offsets

| Layer          | Thickness [cm] | Cumulative offset $o$ [cm] |
| ---            | ---:           | ---:                       |
| chamber        |  0             |   0                        |
| first_wall     |  5             |   5                        |
| breeder        | 50             |  55                        |
| back_wall      |  5             |  60                        |
| shield         | 50             | 110                        |
| vacuum_vessel  | 10             | 120                        |

Given a surface point $\mathbf p$ and a unit outward normal $\hat{\mathbf n}$, the offset point is

$$
\mathbf p_{\mathrm{offset}} = \mathbf p + o\,\hat{\mathbf n}.
$$

alphastell evaluates $\mathbf p$ in the $\varphi = 0$ cross-section frame (so $\mathbf p = (R, 0, Z)$) and then applies the $\varphi$ rotation around $\hat{\mathbf z}$ at the end. The normal $\hat{\mathbf n}$ is computed in the same frame via one of two recipes, selected by `NormalKind` in `src/vmec.rs`:

**`Planar`** — parastell-compatible 2D normal inside the constant-$\varphi$ slice. Only the poloidal tangent is used; the toroidal component $\partial_\varphi \mathbf p$ is ignored.

$$
\mathbf t_\theta = (\partial_\theta R,\; 0,\; \partial_\theta Z),\quad
\mathbf t_\varphi^{\mathrm{Planar}} = (0, 1, 0),\qquad
\mathbf n_{\mathrm{Planar}} = \mathbf t_\varphi^{\mathrm{Planar}} \times \mathbf t_\theta = (\partial_\theta Z,\; 0,\; -\partial_\theta R).
$$

**`Surface`** — true 3D outward normal of the flux surface. The arclength term $R\,\hat{\mathbf y}$ from the rotational embedding makes $\mathbf t_\varphi$ three-dimensional:

$$
\mathbf t_\varphi^{\mathrm{Surface}} = (\partial_\varphi R,\; R,\; \partial_\varphi Z),\qquad
\mathbf n_{\mathrm{Surface}} = \mathbf t_\varphi^{\mathrm{Surface}} \times \mathbf t_\theta.
$$

Both are then normalized, scaled by $o$, added to $\mathbf p$, and the whole point is rotated by $\varphi$ around $\hat{\mathbf z}$ to build the final 3D mesh. `Planar` is the default (matches parastell to within the shell construction error); `Surface` captures the helical tilt more faithfully and is useful when the mesh feeds into a true 3D offset operation.

## Subcommands

| Subcommand | Output | Purpose |
|---|---|---|
| `vessel`   | 6 × `.step` + `.csv` | 6-layer in-vessel build from a VMEC `wout_*.nc` |
| `magnet`   | `magnet_set.step` + `.csv` | Rectangular-cross-section sweep of 40 coil filaments |
| `cut`      | 1 × `.step` | Sector-wedge boolean: `--cut` keeps the wedge, `--union` removes it |
| `compound` | merged `.step` + `.svg` | Merge multiple STEP inputs (optionally plus an in-memory magnet sector) with chamber→vacuum-vessel gradient coloring, and write a projected SVG |
| `validate` | stdout | Volume-ratio check (and optional boolean-Union volume) against a reference STEP |

Run `cargo run --release -- <subcommand> --help` for the full flag set.

## Getting started

```bash
git clone https://github.com/lzpel/alphastell
cd alphastell

cargo build --release

make run              # vessel + validate against the bundled parastell reference
make showcase         # reproduce figure/image.png as out/showcase.step + .svg
make points           # 3D scatter of every out/*.csv (needs `uv`)
```

Prerequisites: stable `rustc` with edition 2024 support, GNU `make`, and [`uv`](https://docs.astral.sh/uv/) for the Python viewer scripts under `tools/` (optional). OCCT is statically linked through the `cadrum` crate, so no separate install is required.

## Example usage

```bash
# 6 in-vessel layers (parastell default: wall_s=1.08, scale=100 → cm output)
cargo run --release -- vessel --input parastell/examples/wout_vmec.nc --output out/

# 40-coil magnet set
cargo run --release -- magnet --input parastell/examples/coils.example --output out/magnet_set.step

# Keep half the torus of first_wall (sector [-1/4, +1/4] of τ = [-90°, +90°])
cargo run --release -- cut --cut -i out/first_wall.step -o out/fw_half.step -s -1/4 -e 1/4

# Merge vessel layers + a magnet sector into one colored STEP + SVG
cargo run --release -- compound \
    -i out/chamber.step -i out/vacuum_vessel.step \
    --input-magnet parastell/examples/coils.example \
    -o out/merged.step
```

The `make showcase` target wires this together: each vessel layer is cut with a progressively wider window (`i · τ/36` half-span, i = 0..6), then all six layers and the `−τ/6..τ/6`-complementary coil set are compounded. Vessel layers get a linear RGB gradient from `#EE7800` (chamber) to `#FFFFFF` (vacuum vessel); coils keep their per-filament rainbow color from `magnet::build_sector`.

## Repository layout

```
src/             Rust source for each subcommand
tools/           Python viewers (view_points.py, etc.)
parastell/       Vendored parastell snapshot — reference algorithms and example data
parastell/examples/    wout_vmec.nc, coils.example, alphastell_full/*.step
figure/          Rendered showcase images
notes/           Design notes (Japanese)
examples/        Small cadrum usage examples (seam-dent repro etc.)
```

## Known limitations

- **[cadrum#120](https://github.com/lzpel/cadrum/issues/120)** — the periodic B-spline seam in `Solid::bspline(grid, periodic=true)` leaves mm-scale dents on chamber-like surfaces; the grid is deliberately kept at M=128, N=48 to keep the artifact small.
- **[cadrum#122](https://github.com/lzpel/cadrum/issues/122)** — round-tripping a multi-solid compound STEP (40 magnet coils) through `read_step` currently returns zero solids. `compound --input-magnet` bypasses this by building the coils in-memory.
- The STEP header declares `SI_UNIT(.MILLI., .METRE.)`, but `vessel --scale` defaults to cm. Viewers therefore render everything at 1/10 of the intended physical size. Relative dimensions are still correct.

## Contact

If any of this is useful to your group — or if you just want to compare notes on stellarator CAD / VMEC pipelines — feel free to reach out: [Satoshi Misumi on LinkedIn](https://www.linkedin.com/in/satoshi-misumi-b17261322/).

## License

Released under the MIT License — see [LICENSE](./LICENSE). The vendored `parastell/` tree keeps its upstream MIT license (`parastell/LICENSE.md`).
