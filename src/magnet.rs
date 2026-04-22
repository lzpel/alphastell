//! `magnet` サブコマンドの実装。`coils.example` から 40 本のフィラメントを読み、
//! 各コイルを長方形断面で sweep して STEP に書き出す。
//!
//! 全体の流れ:
//! 1. `coils::parse` でフィラメント点列 (単位 m) を取得
//! 2. 各フィラメントに対し:
//!    a. 点列を m のまま spine 点として扱う (単位変換なし)
//!    b. 最終点 (閉ループ終端マーカー) を落として周期 B-spline で spine を作成
//!    c. ローカル XY 平面の長方形 profile を作成
//!    d. `spine.start_tangent()` / `start_point()` で配置基準を取り
//!       `profile.align_z(tangent, origin).translate(origin)` で spine 始点に合わせる
//!    e. `Solid::sweep(profile, spine, ProfileOrient::Up(DVec3::Z))` で solid 化
//! 3. 全コイルを集めて STEP 出力

use cadrum::{BSplineEnd, DVec3, ProfileOrient, Solid, Wire};
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

use crate::Result;
use crate::coils;

/// magnet サブコマンドのエントリポイント。
///
/// # 引数
/// - `input`: `coils.example` パス
/// - `output`: `magnet_set.step` パス
/// - `width`: 矩形断面の幅 [m]
/// - `thickness`: 矩形断面の厚み [m]
/// - `toroidal_extent`: [deg]。360.0 で全コイル、<360 で将来的にコイル間引き (本 PR では未実装、値だけログ出力)
pub fn run(
	input: &Path,
	output: &Path,
	width: f64,
	thickness: f64,
	toroidal_extent: f64,
) -> Result<()> {
	println!("Parsing coils: {}", input.display());
	let filaments = coils::parse(input)?;
	println!(
		"  Parsed {} filaments (nfp={})",
		filaments.coils.len(),
		filaments.nfp
	);
	if toroidal_extent < 360.0 {
		println!(
			"  [note] --toroidal-extent {} specified but coil filtering not implemented in this version",
			toroidal_extent
		);
	}

	println!(
		"Building {} coil solids (width = {} m, thickness = {} m)...",
		filaments.coils.len(),
		width,
		thickness
	);
	let mut solids: Vec<Solid> = Vec::with_capacity(filaments.coils.len());
	let mut coil_points: Vec<Vec<DVec3>> = Vec::with_capacity(filaments.coils.len());
	for (idx, raw_pts) in filaments.coils.iter().enumerate() {
		match build_one(raw_pts, width, thickness) {
			Ok((s, pts)) => {
				solids.push(s);
				coil_points.push(pts);
			}
			Err(e) => {
				eprintln!("  [warn] coil #{} sweep failed: {}", idx, e);
			}
		}
	}
	println!("  {} / {} coils succeeded", solids.len(), filaments.coils.len());

	if solids.is_empty() {
		return Err("no coil solids produced".into());
	}

	// 出力ディレクトリ作成
	if let Some(parent) = output.parent() {
		if !parent.as_os_str().is_empty() {
			std::fs::create_dir_all(parent)
				.map_err(|e| format!("create_dir_all {}: {}", parent.display(), e))?;
		}
	}

	println!("Writing STEP: {}", output.display());
	let colored: Vec<Solid> = solids.into_iter().map(|s| s.color("orange")).collect();
	let mut f = File::create(output)
		.map_err(|e| format!("create {}: {}", output.display(), e))?;
	cadrum::write_step(colored.iter(), &mut f)
		.map_err(|e| format!("write_step failed: {:?}", e))?;

	// 可視化用 CSV: STEP と同名で拡張子だけ .csv。中身は header 無し、
	// 1 行 = "x,y,z" (m)。コイルごとに profile 4 点 → spine n 点の順で並ぶ。
	let csv_path = output.with_extension("csv");
	println!("Writing CSV: {}", csv_path.display());
	let csv_file = File::create(&csv_path)
		.map_err(|e| format!("create {}: {}", csv_path.display(), e))?;
	let mut csv = BufWriter::new(csv_file);
	for pts in &coil_points {
		for p in pts {
			writeln!(csv, "{},{},{}", p.x, p.y, p.z)
				.map_err(|e| format!("write csv: {}", e))?;
		}
	}
	csv.flush().map_err(|e| format!("flush csv: {}", e))?;
	println!("Done.");
	Ok(())
}

/// 1 本のコイルを長方形断面で sweep して Solid にする。
///
/// 戻り値の `Vec<DVec3>` は可視化用の点列 (m, ワールド座標):
/// - 先頭 4 点: 配置後 profile の 4 コーナー (start_point() × 4 辺)
/// - 残り n 点: spine 点列 (= raw_pts そのまま、m 単位)
fn build_one(raw_pts: &[DVec3], width: f64, thickness: f64) -> Result<(Solid, Vec<DVec3>)> {
	use cadrum::Edge;

	if raw_pts.len() < 4 {
		return Err(format!("too few points ({})", raw_pts.len()).into());
	}

	// (a) 点列は m のまま使う (coils::parse は [m] 単位で返す)
	let spine_pts: Vec<DVec3> = raw_pts.to_vec();

	let spine = Edge::bspline(&spine_pts, BSplineEnd::NotAKnot)
		.map_err(|e| format!("bspline failed: {:?}", e))?;

	// (b') aux spine: コイル COM を中心に spine を径方向に一様拡大したループ。
	// 各点 P_i に対応する aux 点は COM + (P_i - COM) * AUX_SCALE で、
	// spine → aux の方向は常に P_i - COM (= コイルループの外向き) と一致する。
	// sweep 中、profile の tracked axis がこの方向を追うため、parastell の
	// 「全点で COM 基準の normal/binormal を構築」と等価なフレーム制御になる。
	// AUX_SCALE は向きの決定には無関係 (>1 であればよい); 数値安定性のため 1.1。
	const AUX_SCALE: f64 = 1.1;
	let com: DVec3 = spine_pts.iter().copied().sum::<DVec3>() / (spine_pts.len() as f64);
	let aux_pts: Vec<DVec3> = spine_pts
		.iter()
		.map(|p| com + (*p - com) * AUX_SCALE)
		.collect();
	let aux_spine = Edge::bspline(&aux_pts, BSplineEnd::NotAKnot)
		.map_err(|e| format!("aux bspline failed: {:?}", e))?;

	// (c) ローカル XY 平面の長方形 profile (中心 = 原点)
	// 点順は +X+Y → +X-Y → -X-Y → -X+Y の **時計回り** (+Z から見て)。
	// 反時計回りで渡すと sweep の結果が反転 solid になり shape_volume が -0 を返す。
	let w = width;
	let t = thickness;
	let profile = Edge::polygon(&[
		DVec3::new(w / 2.0, t / 2.0, 0.0),
		DVec3::new(w / 2.0, -t / 2.0, 0.0),
		DVec3::new(-w / 2.0, -t / 2.0, 0.0),
		DVec3::new(-w / 2.0, t / 2.0, 0.0),
	])
	.map_err(|e| format!("polygon failed: {:?}", e))?;

	// (d) spine から配置基準を取り出して profile を回転 + 平行移動
	let tangent = spine.start_tangent();
	let origin = spine.start_point();
	// x_hint はコイル COM から origin への外向きベクトル。Auxiliary の
	// aux_spine 方向 (= 外向き) と一致させて、sweep 開始点でフレームが
	// 再整列しないようにしておく。
	let outward = origin - com;
	let profile = profile.align_z(tangent, outward).translate(origin);

	// 可視化用ダンプ: profile 4 コーナー (各辺 Edge の start_point) + spine n 点。
	// すべてワールド座標 (m)。`start_point` は Wire trait 経由で Edge に生えている。
	let mut dump_pts: Vec<DVec3> = Vec::with_capacity(profile.len() + spine_pts.len());
	for e in profile.iter() {
		dump_pts.push(e.start_point());
	}
	dump_pts.extend_from_slice(&spine_pts);

	// (e) sweep。Auxiliary(aux_spine) で profile の tracked axis を各点で
	// 「コイル COM → spine 点」方向に向ける。Torsion (Frenet-Serret) が
	// 変曲点で不安定になる問題を避け、parastell 準拠の径方向基準フレームを
	// 全点で維持する。
	let coil = Solid::sweep(
		profile.iter(),
		std::iter::once(&spine),
		ProfileOrient::Torsion
		//ProfileOrient::Auxiliary(&[aux_spine]),
	)
	.map_err(|e| format!("sweep failed: {:?}", e))?;

	Ok((coil, dump_pts))
}
