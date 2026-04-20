//! `generate` サブコマンドの実装。VMEC の磁束面を B-spline サーフェスとして STEP 出力する。
//!
//! 処理の流れ:
//! 1. VMEC ファイル (netCDF) を読み込み
//! 2. 指定された磁束ラベル s で Fourier 係数を内挿
//! 3. (φ, θ) グリッドを走査して 3D 点群を作る
//! 4. cadrum の B-spline サーフェスに流し込む
//! 5. STEP ファイルに書き出し

use anyhow::{Context, Result};
use cadrum::{DVec3, Solid};
use std::f64::consts::TAU;
use std::path::Path;

use crate::vmec::VmecData;

/// トーラス方向 (φ 軸) のリブ本数。nfp=4 の倍数にしておくと周期対称性と整合する。
const M_TORO: usize = 240;
/// 断面方向 (θ 軸) のリブ 1 本あたりの点数。parastell の num_rib_pts=61 に近い 2 のべき。
const N_POLO: usize = 64;

/// generate サブコマンドのエントリポイント。
///
/// `scale` は VMEC の単位 (m) からの線形スケール。parastell 既定が 100 (m→cm) なので
/// DAGMC neutronics や parastell 出力との体積比較をしたいときは 100 のままが便利。
pub fn run(input: &Path, output: &Path, s: f64, scale: f64) -> Result<()> {
	// 1. VMEC ファイルを読み込む
	println!("Loading VMEC: {}", input.display());
	let vmec = VmecData::load(input)?;
	println!(
		"  ns = {}, mnmax = {}, s_max in grid = {}",
		vmec.s_grid.len(),
		vmec.xm.len(),
		vmec.s_grid.last().unwrap()
	);

	// 2. 目的の s での Fourier 係数を内挿で求める (s は以後の処理で「焼き込み」)
	println!("Interpolating Fourier coefficients at s = {}", s);
	let (r_at_s, z_at_s) = vmec.interp_coeffs_at_s(s);

	// 3. (φ, θ) グリッドを走査して 3D 点群を作る
	//    std::array::from_fn でコンパイル時固定サイズの 2D 配列を直接 populate
	//    (cadrum の Solid::bspline は const-generic 配列を要求する)
	println!(
		"Building {} x {} grid over full torus (scale = {})...",
		M_TORO, N_POLO, scale
	);
	let grid: [[DVec3; N_POLO]; M_TORO] = std::array::from_fn(|i| {
		// トーラス周方向の角度 φ。全周 [0, 2π) を M_TORO 等分 (endpoint を含めず開区間)
		let phi = TAU * (i as f64) / (M_TORO as f64);
		let (sinp, cosp) = phi.sin_cos();
		std::array::from_fn(|j| {
			// 断面方向の角度 θ。同じく [0, 2π) 開区間
			let theta = TAU * (j as f64) / (N_POLO as f64);
			// VMEC は円柱座標 (R, Z, φ) で値を返すので直交座標 (x, y, z) に変換
			let (r, z) = vmec.eval_rz(&r_at_s, &z_at_s, theta, phi);
			// scale を掛けて単位変換 (m → cm など)
			DVec3::new(r * cosp * scale, r * sinp * scale, z * scale)
		})
	});

	// 4. 点群から cadrum の B-spline サーフェスを構築
	//    periodic=true で両方向 (poloidal, toroidal) を閉曲面として閉じる
	println!("Constructing B-spline solid via cadrum...");
	let solid = Solid::bspline(grid, true)
		.map_err(|e| anyhow::anyhow!("cadrum bspline failed: {:?}", e))?;

	// 5. 出力ディレクトリを作成 (必要なら)
	if let Some(parent) = output.parent() {
		if !parent.as_os_str().is_empty() {
			std::fs::create_dir_all(parent)
				.with_context(|| format!("create_dir_all {}", parent.display()))?;
		}
	}

	// 6. STEP ファイルに書き出し
	println!("Writing STEP: {}", output.display());
	let mut f = std::fs::File::create(output)
		.with_context(|| format!("create {}", output.display()))?;
	cadrum::write_step(&[solid.color("cyan")], &mut f)
		.map_err(|e| anyhow::anyhow!("write_step failed: {:?}", e))?;

	println!("Done.");
	Ok(())
}
