use cadrum::{DQuat, DVec3, Solid};
use std::f64::consts::TAU;

const M: usize = 48;
const N: usize = 24;
const RING_R: f64 = 6.0;

fn point(i: usize, j: usize) -> DVec3 {
	let phi = TAU * (i as f64) / (M as f64);
	let theta = TAU * (j as f64) / (N as f64);
	let two_phi = 2.0 * phi;
	let a = 1.8 + 0.6 * two_phi.sin();
	let b = 1.0 + 0.4 * two_phi.cos();
	let psi = two_phi;
	let z_shift = 1.0 * two_phi.sin();
	let local_raw = DVec3::X * (a * theta.cos()) + DVec3::Z * (b * theta.sin());
	let local_twisted = DQuat::from_axis_angle(DVec3::Y, psi) * local_raw;
	let local_shifted = local_twisted + DVec3::Z * z_shift;
	let translated = local_shifted + DVec3::X * RING_R;
	DQuat::from_axis_angle(DVec3::Z, phi) * translated
}

fn main() {
	let example_name = std::path::Path::new(file!()).file_stem().unwrap().to_str().unwrap();

	let grid: [[DVec3; N]; M] = std::array::from_fn(|i| std::array::from_fn(|j| point(i, j)));
	let plasma = Solid::bspline(grid, true).expect("2-period bspline torus should succeed");
	let objects = [plasma.color("cyan")];
	let mut f = std::fs::File::create(format!("{example_name}.step")).unwrap();
	cadrum::write_step(&objects, &mut f).unwrap();
	let mut f_svg = std::fs::File::create(format!("{example_name}.svg")).unwrap();
	cadrum::mesh(&objects, 0.1).and_then(|m| m.write_svg(DVec3::new(0.05, 0.05, 1.0), false, true, &mut f_svg)).unwrap();
	println!("wrote {example_name}.step / {example_name}.svg");
}
