//! magnet2 — magnet の再実装試作。
//! 現段階ではフィラメントの読み込み確認のみ。出力は未実装。

use std::io::Write;
use std::path::Path;

use cadrum::DVec3;

use crate::Result;
use crate::coils;

pub fn run(input: &Path, output: &Path) -> Result<()> {
	let coils = load_coils(input)?;
	let coils_phi: Vec<DVec3> = coils.iter().map(|v| v.iter()).flatten().cloned().collect();
	let mut f=std::fs::File::create(output)?;
	for i in coils_phi {
		let j=phi_convert(i);
		writeln!(f, "{}, {}, {}, {}, {}, {}", i.x, i.y, i.z, j.x, j.y, j.z)?;
	}
	Ok(())
}
pub fn load_coils(input: &Path)->Result<Vec<Vec<DVec3>>>{
	let f = coils::parse(input)?;
	println!("magnet2: loaded {}", input.display());
	println!("  nfp         = {}", f.nfp);
	println!("  filaments   = {}", f.coils.len());
	let total_points: usize = f.coils.iter().map(|c| c.len()).sum();
	println!("  total points= {}", total_points);
	if let (Some(min), Some(max)) = (
		f.coils.iter().map(|c| c.len()).min(),
		f.coils.iter().map(|c| c.len()).max(),
	) {
		println!("  points/coil = [{}, {}]", min, max);
	}
	Ok(f.coils)
}
pub fn phi_convert(v: DVec3)->DVec3{
	let x=DVec3::X;
	let y=DVec3::Y;
	let z=DVec3::Z;
	let phi=f64::atan2(v.dot(x), v.dot(y));
	let high=v.dot(z);
	let r=(v-high*z).length();
	DVec3::new(phi, r, high)
}
