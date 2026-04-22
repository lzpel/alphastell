//! `generate` サブコマンド。VMEC LCFS の外側に parastell 互換の 6 層 in-vessel
//! 構造を `VmecData::mesh()` ベースで構築し、個別の STEP ファイルとして書き出す。
//!
//! # 層構造 (内側 → 外側)
//!
//! | index | ファイル            | 厚み [cm] | 役割                       |
//! |-------|---------------------|-----------|----------------------------|
//! | 0     | chamber.step        | —         | プラズマ / 真空領域        |
//! | 1     | first_wall.step     | 5         | プラズマ対向壁 (FW)        |
//! | 2     | breeder.step        | 50 (*)    | トリチウム増殖ブランケット |
//! | 3     | back_wall.step      | 5         | 構造背壁                   |
//! | 4     | shield.step         | 50        | 中性子遮蔽                 |
//! | 5     | vacuum_vessel.step  | 10        | 真空容器 (VV)              |
//!
//! (*) parastell 標準の 25〜75 cm poloidal 変動は本実装では 50 cm 固定で近似。
//!     poloidal matrix 版は `mesh()` を offset-per-(θ,φ) に拡張してから対応予定。
//!
//! # アルゴリズム
//!
//! wall_s (既定 1.08) を基準面として、`VmecData::mesh(..., offset, Planar)` を
//! 呼んで 6 枚の offset 曲面を得る。各曲面から閉 B-spline solid (filled) を作り、
//! 隣接 2 solid の **boolean subtract** で殻層を切り出す。chamber は一番内側の
//! filled solid をそのまま使う。
//!
//! shell API (`cadrum::Solid::shell`) は使わない。代わりに法線方向オフセットを
//! `mesh()` の `NormalKind::Planar` (parastell 互換、constant-φ 断面内法線) に
//! 委ねる。

use cadrum::{DVec3, Solid};
use std::fs::File;
use std::path::Path;

use crate::Result;
use crate::vmec::{NormalKind, VmecData};

/// トーラス方向 (φ 軸) のリブ本数。nfp=4 の倍数にして周期対称性と揃える。
const M_TORO: usize = 240;
/// 断面方向 (θ 軸) のリブ 1 本あたりの点数。parastell の num_rib_pts=61 に近い 2 のべき。
const N_POLO: usize = 64;

// 層の厚み [m] (VMEC ネイティブ単位)
const THICK_FW_M: f64 = 0.05;
const THICK_BREEDER_M: f64 = 0.50;
const THICK_BACK_WALL_M: f64 = 0.05;
const THICK_SHIELD_M: f64 = 0.50;
const THICK_VV_M: f64 = 0.10;

/// 出力ファイル名と可視化カラー (内側 → 外側)。
const LAYERS: [(&str, &str); 6] = [
	("chamber", "cyan"),
	("first_wall", "red"),
	("breeder", "orange"),
	("back_wall", "gold"),
	("shield", "green"),
	("vacuum_vessel", "blue"),
];

/// generate サブコマンドのエントリポイント。
///
/// # 引数
/// - `wall_s`: 基準磁束面 (parastell 既定 1.08)。
/// - `scale` : VMEC の m 単位から出力単位への倍率 (100 → cm)。
pub fn run(input: &Path, output_dir: &Path, wall_s: f64, scale: f64) -> Result<()> {
	println!("Loading VMEC: {}", input.display());
	let vmec = VmecData::load(input)?;
	println!(
		"  ns = {}, mnmax = {}, s_max in grid = {}",
		vmec.s_grid.len(),
		vmec.mode_poloidal.len(),
		vmec.s_grid.last().unwrap()
	);

	std::fs::create_dir_all(output_dir)
		.map_err(|e| format!("create_dir_all {}: {}", output_dir.display(), e))?;

	// wall_s 基準面からの累積 offset [m]。index 0 が chamber 外周 = FW 内周。
	let offsets_m: [f64; 6] = [
		0.0,
		THICK_FW_M,
		THICK_FW_M + THICK_BREEDER_M,
		THICK_FW_M + THICK_BREEDER_M + THICK_BACK_WALL_M,
		THICK_FW_M + THICK_BREEDER_M + THICK_BACK_WALL_M + THICK_SHIELD_M,
		THICK_FW_M + THICK_BREEDER_M + THICK_BACK_WALL_M + THICK_SHIELD_M + THICK_VV_M,
	];

	// 各 offset で filled solid を構築。mesh → const-size grid → bspline。
	println!(
		"Building {} nested filled solids (wall_s = {}, scale = {}, grid = {}×{})...",
		offsets_m.len(),
		wall_s,
		scale,
		M_TORO,
		N_POLO
	);
	let mut full_solids: Vec<Solid> = Vec::with_capacity(offsets_m.len());
	for (i, &o) in offsets_m.iter().enumerate() {
		println!("  [{}] offset = {:.3} m", i, o);
		let mesh = vmec.mesh(N_POLO, M_TORO, wall_s, o, NormalKind::Planar);
		let grid = to_const_grid(&mesh, scale);
		let solid = Solid::bspline(grid, true)
			.map_err(|e| format!("bspline #{}: {:?}", i, e))?;
		full_solids.push(solid);
	}

	// 6 層を書き出し。chamber は filled、それ以外は outer.subtract([inner])。
	for (i, (name, color)) in LAYERS.iter().enumerate() {
		println!("Building layer: {}", name);
		let solids: Vec<Solid> = if i == 0 {
			vec![full_solids[0].clone()]
		} else {
			full_solids[i]
				.subtract([&full_solids[i - 1]])
				.map_err(|e| format!("subtract {}: {:?}", name, e))?
		};
		if solids.is_empty() {
			return Err(format!("layer {} produced no solid", name).into());
		}
		let path = output_dir.join(format!("{}.step", name));
		let colored: Vec<Solid> = solids.into_iter().map(|s| s.color(*color)).collect();
		write_step(&colored, &path)?;
	}

	println!("Done.");
	Ok(())
}

/// `mesh()` の出力 (`[phi_idx][theta_idx]`) を scale 倍して `Solid::bspline` の
/// 定数サイズ配列に詰め替える。
fn to_const_grid(mesh: &[Vec<[f64; 3]>], scale: f64) -> [[DVec3; N_POLO]; M_TORO] {
	std::array::from_fn(|i| {
		std::array::from_fn(|j| {
			let p = &mesh[i][j];
			DVec3::new(p[0] * scale, p[1] * scale, p[2] * scale)
		})
	})
}

fn write_step(solids: &[Solid], output: &Path) -> Result<()> {
	println!("  Writing STEP: {}", output.display());
	let mut f = File::create(output)
		.map_err(|e| format!("create {}: {}", output.display(), e))?;
	cadrum::write_step(solids.iter(), &mut f)
		.map_err(|e| format!("write_step failed: {:?}", e))?;
	Ok(())
}
