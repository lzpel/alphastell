//! `vessel` subcommand. Builds parastell-compatible 6-layer in-vessel structures
//! outside the VMEC LCFS via `VmecData::interpolate()` and writes each layer as a
//! separate STEP file.
//!
//! # Layer structure (inside → outside)
//!
//! | index | file                | thickness [cm] | role                              |
//! |-------|---------------------|----------------|-----------------------------------|
//! | 0     | chamber.step        | —              | plasma / vacuum region            |
//! | 1     | first_wall.step     | 5              | plasma-facing wall (FW)           |
//! | 2     | breeder.step        | 50 (*)         | tritium breeding blanket          |
//! | 3     | back_wall.step      | 5              | structural back wall              |
//! | 4     | shield.step         | 50             | neutron shield                    |
//! | 5     | vacuum_vessel.step  | 10             | vacuum vessel (VV)                |
//!
//! (*) parastell's standard 25–75 cm poloidal variation is approximated here by a
//!     fixed 50 cm. Per-layer poloidal-varying offset can be expressed by swapping
//!     the `surface` closure of that layer.
//!
//! # Algorithm
//!
//! Register layers in order (inside → outside) via `vessel::builder()`. Each layer
//! is defined by a `(phi, theta) -> [x,y,z]` surface closure. `build()` samples
//! each layer on an M×N grid, constructs a closed B-spline filled solid, and
//! carves shells via **boolean subtract** between adjacent solids. The chamber
//! keeps the innermost filled solid as-is.
//!
//! The shell API (`cadrum::Solid::shell`) is not used. Normal-direction offsets
//! are delegated to `VmecData::interpolate(..., NormalKind::Planar)` (parastell-
//! compatible, in-cross-section normal at constant φ).
//!
//! # Known issues
//!
//! cadrum (OCCT) `Solid::bspline(grid, periodic=true)` does not guarantee C¹
//! continuity at the periodic U seam, leaving mm-scale dents on chamber-like
//! surfaces (see lzpel/cadrum#120 for details, repro, and OCCT-internal
//! diagnosis). We accept this and move forward — at M=128, N=48 the artifact
//! becomes visually small. `examples/08_bspline_with_waves.rs` can serve as a
//! regression check once cadrum gets a fix.

use cadrum::{DVec3, Solid};
use std::f64::consts::TAU;
use std::io::{Read, Seek};

use crate::Result;
use crate::artifact::Artifact;
use crate::vmec::{NormalKind, VmecData};

type SurfaceFn<'a> = Box<dyn Fn(f64, f64) -> [f64; 3] + 'a>;

struct LayerSpec<'a> {
	name: &'static str,
	color: &'static str,
	surface: SurfaceFn<'a>,
}

/// Builder that registers layers in order and produces nested solids on `build()`.
///
/// Insertion order is **inside → outside**. `build()` returns layer 0 as a filled
/// solid and layers i ≥ 1 as `solid[i].subtract([&solid[i-1]])` shells.
pub struct VesselBuilder<'a> {
	grid_phi: usize,
	grid_theta: usize,
	scale: f64,
	layers: Vec<LayerSpec<'a>>,
}

impl<'a> VesselBuilder<'a> {

	/// Construct a `VesselBuilder`. `grid_phi × grid_theta` is the B-spline
	/// sampling resolution; `scale` is the multiplier from VMEC m to output units
	/// (100 → cm).
	pub fn builder(grid_phi: usize, grid_theta: usize, scale: f64) -> Self {
		VesselBuilder {
			grid_phi,
			grid_theta,
			scale,
			layers: Vec::new(),
		}
	}
	/// Append a single layer. `surface(phi, theta) -> [x,y,z]` returns a point in
	/// VMEC m units.
	pub fn layer<F>(mut self, name: &'static str, color: &'static str, surface: F) -> Self
	where
		F: Fn(f64, f64) -> [f64; 3] + 'a,
	{
		self.layers.push(LayerSpec {
			name,
			color,
			surface: Box::new(surface),
		});
		self
	}

	pub fn build(self) -> Result<Vec<Artifact>> {
		let m = self.grid_phi;
		let n = self.grid_theta;
		println!(
			"Building {} nested filled solids (scale = {}, grid = {}×{})...",
			self.layers.len(),
			self.scale,
			m,
			n
		);

		let mut full_solids: Vec<Solid> = Vec::with_capacity(self.layers.len());
		let mut layer_points: Vec<Vec<DVec3>> = Vec::with_capacity(self.layers.len());
		for (i, spec) in self.layers.iter().enumerate() {
			println!("  [{}] sampling layer {}", i, spec.name);
			let pts: Vec<DVec3> = (0..m)
				.flat_map(|ii| {
					let phi = TAU * (ii as f64) / (m as f64);
					(0..n).map(move |jj| {
						let theta = TAU * (jj as f64) / (n as f64);
						DVec3::from((spec.surface)(phi, theta)) * self.scale
					})
				})
				.collect();
			let solid = Solid::bspline(m, n, true, |ii, jj| pts[ii * n + jj])
				.map_err(|e| format!("bspline #{}: {:?}", i, e))?;
			full_solids.push(solid);
			layer_points.push(pts);
		}

		let mut artifacts: Vec<Artifact> = Vec::with_capacity(self.layers.len());
		for (i, spec) in self.layers.iter().enumerate() {
			println!("Building layer: {}", spec.name);
			let solids: Vec<Solid> = if i == 0 {
				vec![full_solids[0].clone()]
			} else {
				full_solids[i]
					.subtract([&full_solids[i - 1]])
					.map_err(|e| format!("subtract {}: {:?}", spec.name, e))?
			};
			if solids.is_empty() {
				return Err(format!("layer {} produced no solid", spec.name).into());
			}
			let colored: Vec<Solid> = solids.into_iter().map(|s| s.color(spec.color)).collect();
			artifacts.push(Artifact {
				name: spec.name.to_string(),
				solids: colored,
				points: layer_points[i].clone(),
			});
		}
		Ok(artifacts)
	}
}

/// Entry point for the `vessel` subcommand.
///
/// # Arguments
/// - `input` : VMEC NetCDF stream (`Read + Seek`). The CLI passes a `File::open`,
///             the API passes uploaded bytes wrapped in `Cursor`.
/// - `scale` : Multiplier from VMEC m to output units (100 → cm).
///
/// `wall_s` is hard-coded to 1.08 (parastell default).
///
/// Returns `Artifact` with 6 elements (inside → outside). Use
/// `Artifact::write(out_dir, name)` to write them out.
pub fn run(input: impl Read + Seek + 'static, scale: f64) -> Result<Vec<Artifact>> {
	let vmec = VmecData::load(input)?;
	println!(
		"  ns = {}, mnmax = {}, s_max in grid = {}",
		vmec.s_grid.len(),
		vmec.mode_poloidal.len(),
		vmec.s_grid.last().unwrap()
	);

	/// Number of ribs along the toroidal direction (φ axis). Kept as a multiple
	/// of nfp=4 to align with the periodic symmetry. M=128 is slightly coarser
	/// than parastell's M=240, but keeps the cadrum#120 seam dents inconspicuous
	/// while keeping boolean_subtract time practical.
	const M_TORO: usize = 128;
	/// Number of points per rib along the cross-section direction (θ axis).
	const N_POLO: usize = 48;

	// Layer thicknesses [m] (VMEC native units)
	const THICK_FW_M: f64 = 0.05;
	const THICK_BREEDER_M: f64 = 0.50;
	const THICK_BACK_WALL_M: f64 = 0.05;
	const THICK_SHIELD_M: f64 = 0.50;
	const THICK_VV_M: f64 = 0.10;

	let normal = NormalKind::Planar;
	let wall_s = 1.08;
	let o0 = 0.0;
	let o1 = THICK_FW_M;
	let o2 = o1 + THICK_BREEDER_M;
	let o3 = o2 + THICK_BACK_WALL_M;
	let o4 = o3 + THICK_SHIELD_M;
	let o5 = o4 + THICK_VV_M;

	// 6 層の色: HSV(H, 1, 1) で H = 0.0 (赤) → 0.25 (黄緑) を等間隔に分配。
	// 計算結果: i/5 * 0.25 をビルド時に丸めて #RRGGBB を埋め込み。
	VesselBuilder::builder(M_TORO, N_POLO, scale)
		.layer("chamber",       "#FF0000", |phi, theta| vmec.interpolate(phi, theta, wall_s, o0, normal))
		.layer("first_wall",    "#FF4D00", |phi, theta| vmec.interpolate(phi, theta, wall_s, o1, normal))
		.layer("breeder",       "#FF9900", |phi, theta| vmec.interpolate(phi, theta, wall_s, o2, normal))
		.layer("back_wall",     "#FFE500", |phi, theta| vmec.interpolate(phi, theta, wall_s, o3, normal))
		.layer("shield",        "#CCFF00", |phi, theta| vmec.interpolate(phi, theta, wall_s, o4, normal))
		.layer("vacuum_vessel", "#80FF00", |phi, theta| vmec.interpolate(phi, theta, wall_s, o5, normal))
		.build()
}
