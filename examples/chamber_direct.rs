//! cadrum example 08_bspline (09_bspline in upstream) と同じパターンで VMEC データを
//! **直接 `Solid::bspline`** に流す。chamber.step の phi-seam 問題が、
//!
//!   (a) 我々の `VmecData::mesh()` 経由 (Vec<Vec<[f64; 3]>> → to_const_grid) のパイプライン
//!   (b) VMEC 形状固有 (高次モード / 鋭曲率) で cadrum/OCCT が扱えない
//!
//! のどちらに由来するか切り分けるためのカナリア。cadrum example と**同じ形で**
//! `[[DVec3; N]; M]` を直接組み立てて `Solid::bspline(grid, true)` を呼ぶ。

use alphastell::vmec::VmecData;
use cadrum::{DVec3, Solid};
use std::f64::consts::TAU;
use std::path::Path;

const M: usize = 48;
const N: usize = 24;

fn main() {
	let vmec = VmecData::load(Path::new("parastell/examples/wout_vmec.nc")).expect("load vmec");
	let s = 1.08;
	let scale = 1.0; // m (cadrum example と同じ coord オーダに合わせる)

	// cadrum example と同一の pattern — std::array::from_fn で直接 [[DVec3; N]; M] を組む
	let grid: [[DVec3; N]; M] = std::array::from_fn(|i| {
		let phi = TAU * (i as f64) / (M as f64);
		let (sp, cp) = phi.sin_cos();
		std::array::from_fn(|j| {
			let theta = TAU * (j as f64) / (N as f64);
			let rz = vmec.interpolate_rz(s, theta, phi);
			DVec3::new(rz.r * cp * scale, rz.r * sp * scale, rz.z * scale)
		})
	});

	let plasma = Solid::bspline(grid, true).expect("bspline");
	let objects = [plasma.color("cyan")];

	let out_path = "out/chamber_direct.step";
	let mut f = std::fs::File::create(out_path).expect("create step");
	cadrum::write_step(&objects, &mut f).expect("write step");

	let svg_path = "out/chamber_direct.svg";
	let mut f_svg = std::fs::File::create(svg_path).expect("create svg");
	cadrum::mesh(&objects, 0.1)
		.and_then(|m| m.write_svg(DVec3::new(0.05, 0.05, 1.0), false, true, &mut f_svg))
		.expect("write svg");
	println!("wrote {out_path} / {svg_path}");
}
