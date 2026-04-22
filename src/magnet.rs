//! `magnet` サブコマンドの実装。`coils.example` から 40 本のフィラメントを読み、
//! 各コイルを長方形断面で sweep して STEP に書き出す。
//!
//! 全体の流れ:
//! 1. `coils::parse` でフィラメント点列 (単位 m) を取得
//! 2. 各フィラメントに対し:
//!    a. 点列を mm にスケール (× 1000)
//!    b. 最終点 (閉ループ終端マーカー) を落として周期 B-spline で spine を作成
//!    c. ローカル XY 平面の長方形 profile を作成
//!    d. `spine.start_tangent()` / `start_point()` で配置基準を取り
//!       `profile.align_z(tangent, origin).translate(origin)` で spine 始点に合わせる
//!    e. `Solid::sweep(profile, spine, ProfileOrient::Up(DVec3::Z))` で solid 化
//! 3. 全コイルを集めて STEP 出力

use cadrum::{BSplineEnd, DVec3, ProfileOrient, Solid, Wire};
use std::fs::File;
use std::path::Path;

use crate::Result;
use crate::coils;

/// magnet サブコマンドのエントリポイント。
///
/// # 引数
/// - `input`: `coils.example` パス
/// - `output`: `magnet_set.step` パス
/// - `width`: 矩形断面の幅 [mm]
/// - `thickness`: 矩形断面の厚み [mm]
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
		"Building {} coil solids (width = {} mm, thickness = {} mm)...",
		filaments.coils.len(),
		width,
		thickness
	);
	let mut solids: Vec<Solid> = Vec::with_capacity(filaments.coils.len());
	for (idx, raw_pts) in filaments.coils.iter().enumerate() {
		match build_one(raw_pts, width, thickness) {
			Ok(s) => solids.push(s),
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
	println!("Done.");
	Ok(())
}

/// 1 本のコイルを長方形断面で sweep して Solid にする。
fn build_one(raw_pts: &[DVec3], width: f64, thickness: f64) -> Result<Solid> {
	use cadrum::Edge;

	if raw_pts.len() < 4 {
		return Err(format!("too few points ({})", raw_pts.len()).into());
	}

	// (a) 点列を mm に変換
	let mut spine_pts: Vec<DVec3> = raw_pts.iter().map(|p| *p * 1000.0).collect();

	// (b) 閉ループ終端マーカーは最終点が始点と重複しているので落とす
	//     (BSplineEnd::Periodic は first == last を弾く)
	if spine_pts
		.last()
		.map(|p| (*p - spine_pts[0]).length() < 1e-6)
		.unwrap_or(false)
	{
		spine_pts.pop();
	}

	// spine を周期 B-spline で閉ループ化
	let spine = Edge::bspline(&spine_pts, BSplineEnd::Periodic)
		.map_err(|e| format!("bspline failed: {:?}", e))?;

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
	// x_hint はコイル COM から origin への外向きベクトル。
	// start_point 自体を使うと、コイルが世界原点から遠い・かつ start 接線が動径方向に
	// 近い配置で start_tangent と (start_point - 0) が平行になり align_z が
	// panic することがある。COM 基準なら接線に対しほぼ直交するので堅牢。
	let com: DVec3 = spine_pts.iter().copied().sum::<DVec3>() / (spine_pts.len() as f64);
	let outward = origin - com;
	let profile = profile.align_z(tangent, outward).translate(origin);

	// (e) sweep。Torsion (Frenet-Serret frame) で曲線の捻じれに自然追従させる。
	// Up(+Z) や Up(外向き) だと一部のコイル (特に start 接線が Up 軸に近いもの) で
	// OCCT の sweep が失敗する。Torsion は変曲点で定義困難な場合もあるが、
	// 本 example のコイルはなめらかな閉曲線なので問題は出にくい。
	let coil = Solid::sweep(
		profile.iter(),
		std::iter::once(&spine),
		ProfileOrient::Torsion,
	)
	.map_err(|e| format!("sweep failed: {:?}", e))?;

	Ok(coil)
}
