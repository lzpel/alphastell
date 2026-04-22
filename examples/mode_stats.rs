//! VMEC の Fourier モード (xm, xn) の分布と、モードごとの振幅を調査する。
//!
//! 1. xm, xn が本当に整数か
//! 2. ユニーク値 (抜けなし? 整数 grid?)
//! 3. 各 (m, n) モードの rmnc/zmns 振幅 → 高 n 領域で非ゼロなら seam 誘因

use alphastell::vmec::VmecData;
use std::path::Path;

fn main() {
	let vmec = VmecData::load(Path::new("parastell/examples/wout_vmec.nc")).unwrap();
	let mnmax = vmec.mode_poloidal.len();

	let index_s = vmec.s_grid.len() - 1;
	let r_coef = &vmec.rmnc[index_s];
	let z_coef = &vmec.zmns[index_s];

	let max_m_err = vmec.mode_poloidal.iter().map(|&m| (m - m.round()).abs()).fold(0.0f64, f64::max);
	let max_n_err = vmec.mode_toroidal.iter().map(|&n| (n - n.round()).abs()).fold(0.0f64, f64::max);
	println!("integer-ness: max|xm - round(xm)| = {max_m_err:.3e}, max|xn - round(xn)| = {max_n_err:.3e}");

	let m_unique: std::collections::BTreeSet<i64> = vmec.mode_poloidal.iter().map(|&m| m.round() as i64).collect();
	let n_unique: std::collections::BTreeSet<i64> = vmec.mode_toroidal.iter().map(|&n| n.round() as i64).collect();
	println!("mnmax = {mnmax}");
	println!("unique xm ({}): {:?}", m_unique.len(), m_unique);
	println!("unique xn ({}): {:?}", n_unique.len(), n_unique);

	let mut entries: Vec<(usize, i64, i64, f64, f64)> = (0..mnmax)
		.map(|k| {
			(k, vmec.mode_poloidal[k].round() as i64, vmec.mode_toroidal[k].round() as i64, r_coef[k], z_coef[k])
		})
		.collect();

	entries.sort_by(|a, b| b.3.abs().partial_cmp(&a.3.abs()).unwrap());
	println!("\n-- top 20 modes by |rmnc| at s=1.0 --");
	println!("{:>3} {:>4} {:>5} {:>12} {:>12}", "k", "m", "n", "rmnc", "zmns");
	for e in entries.iter().take(20) {
		println!("{:>3} {:>4} {:>5} {:>12.4e} {:>12.4e}", e.0, e.1, e.2, e.3, e.4);
	}

	println!("\n-- max |rmnc|, |zmns| per |xn|  (|xn|=0..max) --");
	let mut by_n: std::collections::BTreeMap<i64, (f64, f64)> = std::collections::BTreeMap::new();
	for &(_, _, n, r, z) in &entries {
		let slot = by_n.entry(n.abs()).or_insert((0.0, 0.0));
		slot.0 = slot.0.max(r.abs());
		slot.1 = slot.1.max(z.abs());
	}
	println!("{:>4} {:>12} {:>12}", "|n|", "max|rmnc|", "max|zmns|");
	for (k, v) in by_n.iter() {
		println!("{:>4} {:>12.3e} {:>12.3e}", k, v.0, v.1);
	}

	println!("\n-- max |rmnc|, |zmns| per |xm| --");
	let mut by_m: std::collections::BTreeMap<i64, (f64, f64)> = std::collections::BTreeMap::new();
	for &(_, m, _, r, z) in &entries {
		let slot = by_m.entry(m.abs()).or_insert((0.0, 0.0));
		slot.0 = slot.0.max(r.abs());
		slot.1 = slot.1.max(z.abs());
	}
	println!("{:>4} {:>12} {:>12}", "|m|", "max|rmnc|", "max|zmns|");
	for (k, v) in by_m.iter() {
		println!("{:>4} {:>12.3e} {:>12.3e}", k, v.0, v.1);
	}
}
