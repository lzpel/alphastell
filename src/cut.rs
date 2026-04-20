//! `cut` サブコマンドの実装。入力 STEP を Z 軸まわりのウェッジで切り取って片側だけ残す。
//!
//! 用途:
//! - BREP_WITH_VOIDS 形式の中空 shell solid (`first_wall.step` 等) を Fusion 360
//!   など一部 CAD で可視化できない問題に対し、実際に切って内部を見えるようにする
//! - nfp=4 のステラレータで **1 周期 (div=4)** を取り出して parastell 出力 (1 周期分)
//!   との**単位長比較**にも使える
//!
//! 実装:
//! - `div = 1`: 切らずにそのまま出力
//! - `div = 2`: 1 枚の half space (法線 +Y、原点通過) と intersect
//! - `div ≥ 3`: 2 枚の half space を連続 intersect して `2π/div` 角度のウェッジを作る
//!   - h1: 法線 +Y で φ ∈ [0, π] を残す
//!   - h2: 法線 (sin(2π/div), -cos(2π/div), 0) で φ ≤ 2π/div を残す
//!   - 合成: φ ∈ [0, 2π/div] のウェッジ

use anyhow::{Context, Result};
use cadrum::{Compound, DVec3, Solid};
use std::f64::consts::TAU;
use std::fs::File;
use std::path::Path;

/// cut サブコマンドのエントリポイント。
///
/// # 引数
/// - `input`: 切りたい STEP のパス
/// - `output`: 出力 STEP のパス
/// - `div`: Z 軸まわりの N 等分ウェッジ (N=2 なら半分、N=4 なら 1/4、N=1 は no-op)
pub fn run(input: &Path, output: &Path, div: u32) -> Result<()> {
	println!("Loading STEP: {}", input.display());
	let mut f = File::open(input)
		.with_context(|| format!("open {}", input.display()))?;
	let step1: Vec<Solid> = cadrum::read_step(&mut f)
		.map_err(|e| anyhow::anyhow!("read_step {}: {:?}", input.display(), e))?;
	println!("  loaded {} solid(s)", step1.len());

	let step2 = match div {
		0 => {
			anyhow::bail!("div must be >= 1");
		}
		1 => {
			println!("div = 1: no cut");
			step1.clone()
		}
		n => {
			// ウェッジ幅 w = 2π/n を作りたい。h1 (+Y 法線) の 180° 幅から h2 で削り、
			// h1 の境界 (φ=0) と h2 の境界 (φ=2π/n) で挟まれた領域を残す。
			// h2 の内向き法線は +Y を (π − 2π/n) だけ CCW 回転した方向にとる。
			// → 結果: 合成ウェッジ幅 = π − (π − 2π/n) = 2π/n ✓
			// (素朴に TAU/n だけ回すと幅は π − TAU/n になり、n=4 でだけ偶然 2π/4 = π/2 と一致する)
			
			let h1 = Solid::half_space(DVec3::ZERO, DVec3::Y);
			println!("Intersect solids with half-space #1 (normal = +Y)...");
			let h=if n == 2 {
				h1
			} else {
				let alpha = std::f64::consts::PI - TAU / n as f64; // = π(n-2)/n
				let h2 = Solid::half_space(DVec3::ZERO, DVec3::Y).rotate_z(alpha);
				println!(
					"Intersect with half-space #2 (rotated by π - 2π/{} = {:.4} rad around Z, wedge width = 2π/{} = {:.4} rad)...",
					n,
					alpha,
					n,
					TAU / n as f64
				);
				h1.intersect([&h2]).map_err(|e| anyhow::anyhow!("boolean_intersect 2 failed: {:?}", e))?[0].clone()
			};
			step1
				.intersect([&h])
				.map_err(|e| anyhow::anyhow!("boolean_intersect 1 failed: {:?}", e))?
		}
	};

	if step2.is_empty() {
		anyhow::bail!("intersect #1 returned empty");
	}
	println!("  got {} solid(s) after cut", step2.len());
	println!("  volume input vs output: {} -> {}", step1.volume(), step2.volume());


	if let Some(parent) = output.parent() {
		if !parent.as_os_str().is_empty() {
			std::fs::create_dir_all(parent)
				.with_context(|| format!("create_dir_all {}", parent.display()))?;
		}
	}

	println!("Writing STEP: {}", output.display());
	let colored: Vec<Solid> = step2.into_iter().map(|s| s.color("cyan")).collect();
	let mut out_f = File::create(output)
		.with_context(|| format!("create {}", output.display()))?;
	cadrum::write_step(colored.iter(), &mut out_f)
		.map_err(|e| anyhow::anyhow!("write_step failed: {:?}", e))?;
	println!("Done.");
	Ok(())
}
