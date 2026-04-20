//! `generate` サブコマンドの実装。VMEC の磁束面を B-spline サーフェスとして STEP 出力する。
//!
//! 処理の流れ:
//! 1. VMEC ファイル (netCDF) を読み込み
//! 2. 指定された磁束ラベル s で Fourier 係数を内挿
//! 3. (φ, θ) グリッドを走査して 3D 点群 (内側境界) を作る
//! 4. cadrum の B-spline で閉 solid を構築
//! 5. `thickness > 0` なら `Solid::shell` で外向きオフセットして殻にする (first_wall 用)
//! 6. STEP ファイルに書き出し

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
/// # 引数
/// - `s`        : 内側境界の規格化磁束座標 (1.0 = LCFS、1.08 = wall_s など)
/// - `scale`    : VMEC の m 単位から出力の単位への線形倍率 (100 で cm)
/// - `thickness`: 0 なら単一 solid (chamber / plasma) をそのまま出力。
///                >0 なら `Solid::shell(thickness, [])` で外向きオフセットして殻化
///                (first_wall など)。単位は `scale` と同じ (= cm)。
pub fn run(input: &Path, output: &Path, s: f64, scale: f64, thickness: f64) -> Result<()> {
	// 1. VMEC ファイルを読み込む
	println!("Loading VMEC: {}", input.display());
	let vmec = VmecData::load(input)?;
	println!(
		"  ns = {}, mnmax = {}, s_max in grid = {}",
		vmec.s_grid.len(),
		vmec.xm.len(),
		vmec.s_grid.last().unwrap()
	);

	// 2. 目的の s での Fourier 係数を内挿で求める
	println!("Interpolating Fourier coefficients at s = {}", s);
	let (r_at_s, z_at_s) = vmec.interp_coeffs_at_s(s);

	// 3. (φ, θ) グリッドを走査して 3D 点群を作る
	println!(
		"Building {} x {} grid over full torus (scale = {})...",
		M_TORO, N_POLO, scale
	);
	let grid = build_grid(&vmec, &r_at_s, &z_at_s, scale);

	// 4. 閉 solid を構築
	println!("Constructing B-spline solid via cadrum...");
	let inner_solid = Solid::bspline(grid, true)
		.map_err(|e| anyhow::anyhow!("cadrum bspline failed: {:?}", e))?;

	// 5. thickness > 0 なら殻化
	let final_solid = if thickness > 0.0 {
		println!("Offsetting into shell via Solid::shell (thickness = {})...", thickness);
		// open_faces 空の shell は「元の閉 solid を内側ボイドとする密閉殻」を返す
		// (cadrum ドキュメント参照: BRepOffsetAPI_MakeOffsetShape にフォールバック)
		let shell = inner_solid
			.shell(thickness, std::iter::empty())
			.map_err(|e| anyhow::anyhow!("Solid::shell failed: {:?}", e))?;
		let v = shell.volume();
		println!("  shell volume = {:.6e}", v);
		shell
	} else {
		inner_solid
	};

	// 6. STEP 出力
	write_step(std::slice::from_ref(&final_solid), output)
}

/// VMEC の Fourier 係数と (θ, φ) グリッドを走査して 3D 点群を構築する。
fn build_grid(
	vmec: &VmecData,
	r_at_s: &[f64],
	z_at_s: &[f64],
	scale: f64,
) -> [[DVec3; N_POLO]; M_TORO] {
	std::array::from_fn(|i| {
		// トーラス周方向の角度 φ。全周 [0, 2π) を M_TORO 等分 (endpoint を含めず開区間)
		let phi = TAU * (i as f64) / (M_TORO as f64);
		let (sinp, cosp) = phi.sin_cos();
		std::array::from_fn(|j| {
			// 断面方向の角度 θ。同じく [0, 2π) 開区間
			let theta = TAU * (j as f64) / (N_POLO as f64);
			// VMEC は円柱座標 (R, Z, φ) で値を返すので直交座標 (x, y, z) に変換
			let (r, z) = vmec.eval_rz(r_at_s, z_at_s, theta, phi);
			DVec3::new(r * cosp * scale, r * sinp * scale, z * scale)
		})
	})
}

/// 指定した solid 群を STEP ファイルに書き出す。
fn write_step(solids: &[Solid], output: &Path) -> Result<()> {
	if let Some(parent) = output.parent() {
		if !parent.as_os_str().is_empty() {
			std::fs::create_dir_all(parent)
				.with_context(|| format!("create_dir_all {}", parent.display()))?;
		}
	}
	println!("Writing STEP: {}", output.display());
	let mut f = std::fs::File::create(output)
		.with_context(|| format!("create {}", output.display()))?;
	let colored: Vec<Solid> = solids.iter().map(|s| s.clone().color("cyan")).collect();
	cadrum::write_step(colored.iter(), &mut f)
		.map_err(|e| anyhow::anyhow!("write_step failed: {:?}", e))?;
	println!("Done.");
	Ok(())
}
