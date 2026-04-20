//! `validate` サブコマンドの実装。2 つの STEP ファイル A / B が同じ形状を
//! (別々のトロイダル幅で) 表しているかを体積ベースで照合する。
//!
//! 検査項目:
//! 1. **体積比の整数倍チェック** (既定で必須実行): Rust は全周 (4 周期分)、parastell は
//!    既定で 1 周期だけ生成するので、体積比 max(V_A, V_B) / min(V_A, V_B) は 4 に近い
//!    整数のはず。
//! 2. **Union 体積の非膨張チェック** (`--union` 指定時のみ): 小さい方が大きい方に
//!    空間的に含まれていれば Union(A, B) 体積は max(V_A, V_B) と一致する。
//!    ただし parastell 側の STEP は面数が大きく (数十 MB)、OCCT の bool union が
//!    10 分以上かかるため既定では off。形状の空間的な包含まで厳密に確認したい
//!    ときだけ opt-in する。

use anyhow::{Result, bail};
use cadrum::{Compound, Solid};
use std::fs::File;
use std::path::Path;

/// validate サブコマンドのエントリポイント。
pub fn run(a: &Path, b: &Path, max_ratio: u32, tol: f64, union: bool) -> Result<()> {
	println!("Loading STEP: {}", a.display());
	let solids_a = read_step_file(a)?;
	println!("Loading STEP: {}", b.display());
	let solids_b = read_step_file(b)?;

	// Vec<Solid> は Compound trait 経由で .volume() を持つ (複数ソリッドなら合算)
	let v_a = solids_a.volume();
	let v_b = solids_b.volume();
	println!("V_A = {:.6e}, V_B = {:.6e}", v_a, v_b);

	if v_a <= 0.0 || v_b <= 0.0 {
		bail!("non-positive volume detected: V_A={}, V_B={}", v_a, v_b);
	}

	// --- 1. 整数倍チェック ---
	let (small, large) = if v_a < v_b { (v_a, v_b) } else { (v_b, v_a) };
	let ratio = large / small;
	let k = ratio.round();
	let rel_err_ratio = ((ratio - k) / k).abs();
	let within_int = (1.0..=max_ratio as f64).contains(&k) && rel_err_ratio < tol;
	println!(
		"ratio = {:.6} (≈ {}, rel err {:.3}%) {}",
		ratio,
		k as u32,
		rel_err_ratio * 100.0,
		if within_int { "OK" } else { "FAIL" }
	);

	// --- 2. Union 体積の非膨張チェック (opt-in) ---
	let within_union = if union {
		println!("Running boolean_union (may take several minutes on large STEPs)...");
		let (union_solids, _metadata) =
			Solid::boolean_union(solids_a.iter(), solids_b.iter())
				.map_err(|e| anyhow::anyhow!("boolean_union failed: {:?}", e))?;
		let v_union = union_solids.volume();
		let rel_err_union = ((v_union - large) / large).abs();
		let ok = rel_err_union < tol;
		println!(
			"V_union = {:.6e}, expected ≈ V_max = {:.6e} (rel err {:.3}%) {}",
			v_union,
			large,
			rel_err_union * 100.0,
			if ok { "OK" } else { "FAIL" }
		);
		ok
	} else {
		println!("Union check skipped (pass --union to enable)");
		true
	};

	if !within_int || !within_union {
		bail!(
			"validation failed (integer-ratio={}, union-non-growth={})",
			within_int,
			within_union
		);
	}
	println!("validate: PASS");
	Ok(())
}

/// 単一の STEP ファイルを cadrum の Solid Vec として読み込む。
fn read_step_file(path: &Path) -> Result<Vec<Solid>> {
	let mut f = File::open(path)
		.map_err(|e| anyhow::anyhow!("open {}: {}", path.display(), e))?;
	cadrum::read_step(&mut f)
		.map_err(|e| anyhow::anyhow!("read_step {}: {:?}", path.display(), e))
}
