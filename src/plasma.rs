//! `plasma` サブコマンド。VMEC LCFS (s=1.0) の曲面を **スプライン補間を使わず**
//! `index_rz` で直接評価し、複数の (M, N) 解像度で個別 STEP ファイルを出力する。
//!
//! # 目的
//!
//! chamber.step の phi=0/2π seam 問題が Nyquist aliasing によるものかを切り分ける
//! ための**診断用**サブコマンド。入力 VMEC の `xn_max` ≈ 32 に対し、M が小さいと
//! phi 方向で aliasing が起きて B-spline が周期的に閉じない。M を段階的に上げた
//! STEP を並べて viewer で比較すれば seam の解像度依存が一目で分かる。
//!
//! # 設計
//!
//! - `s = 1.0` 固定 (VMEC s グリッドの末端、補間不要) → `index_rz(ns-1, θ, φ)` で
//!   Fourier 和のみ評価。`CubicSpline` 構築コストゼロ。
//! - (M, N) は **nfp=4 対称と整合する 4 の倍数** を並べる。M=32〜240 で aliasing
//!   領域と安全領域の両方をカバー。
//! - 各 pair につき `out/plasma_M<m>_N<n>.step` を書き出す。
//! - `Solid::bspline` は const-generic なので、M, N は compile-time に決まる
//!   必要がある。`for_each_pair!` マクロで固定リストを展開している。

use cadrum::{DVec3, Solid};
use std::f64::consts::TAU;
use std::fs::File;
use std::path::{Path, PathBuf};

use crate::Result;
use crate::vmec::VmecData;

/// 各 (M, N) で **periodic=true / periodic=false の 2 種類**の plasma STEP を書き出す。
/// `Solid::bspline` は const generics 要求のため、compile-time に M, N を固定する。
///
/// - `_periodic.step`    : `Solid::bspline(grid, true)` — cadrum が phi 方向に row 0 を
///   内部複製して周期 B-spline を構築。閉じたトーラス。
/// - `_nonperiodic.step` : `Solid::bspline(grid, false)` — phi 方向の augment なし。
///   cadrum は phi=0 と phi=(M-1)·2π/M に**キャップ面**を貼る。phi=(M-1)·2π/M〜2π
///   の区間 (1 step 分) は欠けたまま、開いた tube っぽい形状になる。
///   periodic 化のずれが seam の原因か切り分ける用途。
macro_rules! emit {
	($vmec:expr, $index_s:expr, $scale:expr, $output_dir:expr, [$(($m:literal, $n:literal)),* $(,)?]) => {{
		$(
			for &(periodic, tag) in &[(true, "periodic"), (false, "nonperiodic")] {
				let path = $output_dir.join(format!("plasma_M{}_N{}_{}.step", $m, $n, tag));
				println!(
					"Building plasma at M={}, N={}, periodic={} → {}",
					$m, $n, periodic, path.display()
				);
				let solid = build::<$m, $n>($vmec, $index_s, $scale, periodic)?;
				write_step(&solid, &path)?;
			}
		)*
	}};
}

pub fn run(input: &Path, output_dir: &Path, scale: f64) -> Result<()> {
	println!("Loading VMEC: {}", input.display());
	let vmec = VmecData::load(input)?;
	let index_s = vmec.s_grid.len() - 1;
	let s_lcfs = vmec.s_grid[index_s];
	println!(
		"  ns = {}, mnmax = {}, using index_s = {} (s = {})",
		vmec.s_grid.len(),
		vmec.mode_poloidal.len(),
		index_s,
		s_lcfs
	);
	let (min_n, max_n) = vmec
		.mode_toroidal
		.iter()
		.fold((f64::INFINITY, f64::NEG_INFINITY), |(lo, hi), &x| {
			(lo.min(x), hi.max(x))
		});
	let (min_m, max_m) = vmec
		.mode_poloidal
		.iter()
		.fold((f64::INFINITY, f64::NEG_INFINITY), |(lo, hi), &x| {
			(lo.min(x), hi.max(x))
		});
	println!(
		"  xn range [{min_n}, {max_n}] → phi Nyquist requires M ≥ {}",
		2.0 * max_n.abs().max(min_n.abs())
	);
	println!(
		"  xm range [{min_m}, {max_m}] → theta Nyquist requires N ≥ {}",
		2.0 * max_m.abs().max(min_m.abs())
	);

	std::fs::create_dir_all(output_dir)
		.map_err(|e| format!("create_dir_all {}: {}", output_dir.display(), e))?;

	// (M, N) リスト。M は nfp=4 の倍数。
	// xn_max=32 → phi Nyquist = 64。M=32/48 は aliasing 圏、M>=64 が安全圏。
	// (240, 60) は parastell example の num_ribs=61, num_rib_pts=61 を 4 周期に
	// 展開したフル torus 等価 (≈ 60·4 = 240 toroidal slices, 60 poloidal pts)。
	emit!(
		&vmec,
		index_s,
		scale,
		output_dir,
		[
			(32, 16),
			(48, 24),
			(64, 32),
			(128, 48),
			(240, 60),
			(480, 60),
		]
	);

	println!("Done.");
	Ok(())
}

/// s=1.0 LCFS 上の点群を (M, N) グリッドで構築し、B-spline solid を返す。
/// `index_rz` を使うのでスプライン構築コストなし (Fourier 和だけ)。
/// `periodic` で phi 方向の周期閉じ (true) / キャップ (false) を切り替える。
fn build<const M: usize, const N: usize>(
	vmec: &VmecData,
	index_s: usize,
	scale: f64,
	periodic: bool,
) -> Result<Solid> {
	let grid: [[DVec3; N]; M] = std::array::from_fn(|i| {
		let phi = TAU * (i as f64) / (M as f64);
		let (sp, cp) = phi.sin_cos();
		std::array::from_fn(|j| {
			let theta = TAU * (j as f64) / (N as f64);
			let rz = vmec.index_rz(index_s, theta, phi);
			DVec3::new(rz.r * cp * scale, rz.r * sp * scale, rz.z * scale)
		})
	});
	Solid::bspline(grid, periodic)
		.map_err(|e| format!("bspline M={M}, N={N}, periodic={periodic}: {:?}", e).into())
}

fn write_step(solid: &Solid, output: &Path) -> Result<()> {
	let colored = solid.clone().color("cyan");
	let mut f = File::create(output)
		.map_err(|e| format!("create {}: {}", output.display(), e))?;
	cadrum::write_step(std::iter::once(&colored), &mut f)
		.map_err(|e| format!("write_step {}: {:?}", output.display(), e))?;

	// 同名 .stl も書き出す。STL は OCCT の BRepMesh によるテッセレーション結果だけを
	// 素の三角形として保存する形式なので、viewer 固有の「parameter-space seam line」
	// 描画が混入しない。browser / Meshlab / any STL viewer で開けば、phi=0/2π 付近
	// に実際の幾何的段差があるかを viewer 非依存で確認できる。
	let stl_path: PathBuf = output.with_extension("stl");
	let mut fstl = File::create(&stl_path)
		.map_err(|e| format!("create {}: {}", stl_path.display(), e))?;
	let objects = [colored];
	cadrum::mesh(&objects, 0.1)
		.and_then(|m| m.write_stl(&mut fstl))
		.map_err(|e| format!("write stl {}: {:?}", stl_path.display(), e))?;
	Ok(())
}
