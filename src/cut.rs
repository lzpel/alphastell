//! `cut` サブコマンドの実装。入力 STEP を Z 軸まわりの扇形 (sector) で切り取る。
//!
//! API:
//! - `--start/-s` / `--end/-e` は **τ (= 2π) を単位とする有理数**。
//!   形式は正規表現 `^(+|-)?\d+(/\d+)?$` のみ。
//!   例: `-s 0 -e 1/3` → 0°〜120°、`-s -1/6 -e 1/6` → -60°〜+60°。
//!   `--start` 既定 0、`--end` は必須。
//! - `--cut/-c` と `--union/-u` は排他必須。前者は扇形内側 (solid ∩ wedge) を残し、
//!   後者は扇形外側 (solid - wedge) を残す。
//!
//! 実装方針:
//! - 旧 div / half-space 2 枚 intersect は div>=3 で cadrum が empty を返す不具合があり
//!   不安定だった。本実装では **line + arc + line** の閉 wire を XY 平面で組み、
//!   `Solid::extrude` で扇柱 (fan prism) を作る。あとは mode に応じて入力 solid と
//!   boolean intersect / subtract する。
//! - 扇柱の寸法は各入力 solid の `bounding_box()` から十分大きく取る。

use cadrum::{Compound, DVec3, Edge, Solid};
use regex::Regex;
use std::f64::consts::TAU;
use std::fs::File;
use std::path::Path;
use std::sync::OnceLock;

use crate::Result;

/// `(+|-)?\d+(/\d+)?` 形式の τ-fraction をラジアンに。
pub(crate) fn parse_tau_fraction(s: &str) -> std::result::Result<f64, String> {
	const RE_STR: &str = r"^(?P<sign>[+-]?)(?P<num>\d+)(?:/(?P<den>\d+))?$";
	static RE: OnceLock<Regex> = OnceLock::new();
	let re = RE.get_or_init(|| Regex::new(RE_STR).unwrap());
	let caps = re.captures(s).ok_or_else(|| format!("angle must match {}: {s:?}", RE_STR))?;
	let sign: i64 = if &caps["sign"] == "-" { -1 } else { 1 };
	let num: i64 = caps["num"].parse().ok().ok_or_else(|| format!("numerator out of range: {}", &caps["num"]))?;
	let den: i64 = match caps.name("den") {
		Some(m) => m.as_str().parse().ok().ok_or_else(|| format!("denominator out of range: {}", m.as_str()))?,
		None => 1,
	};
	if den == 0 {
		return Err("denominator must be non-zero".into());
	}
	Ok(TAU * (sign * num) as f64 / den as f64)
}

/// 入力 solid と扇柱 wedge の boolean 演算モード。
#[derive(Copy, Clone, Debug)]
pub enum Mode {
	/// `solid ∩ wedge` — 扇形の内側だけ残す (従来の `--cut` 挙動)。
	Intersect,
	/// `solid - wedge` — 扇形を取り除いて外側を残す (`--union`)。
	Subtract,
}

/// 単一 solid を Z 軸まわりの扇形 [start, end] ラジアンで切り出す / 取り除く。
///
/// 扇柱は `p0=apex`, `p1=start 端`, `p2=end 端` の 3 点から `line+arc+line` の
/// 閉 wire を組み、Z 方向に extrude したもの。弧の決定点 (arc_3pts の mid) は
/// `(start+end)/2` を呼び出しインラインで計算する。
/// `mode` に応じて wedge と intersect するか subtract するかを切り替える。
fn cut_solid(
	solid: &Solid,
	start: f64,
	end: f64,
	mode: Mode,
) -> std::result::Result<Solid, cadrum::Error> {
	let [min, max] = solid.bounding_box();
	let r = 2.0 * min.x.abs().max(max.x.abs()).hypot(min.y.abs().max(max.y.abs())) + 1.0;
	let z_margin = (max.z - min.z).abs().max(1.0);
	let z_lo = min.z - z_margin;
	let z_hi = max.z + z_margin;

	let p0 = DVec3::new(0.0, 0.0, z_lo);
	let p1 = DVec3::new(r * start.cos(), r * start.sin(), z_lo);
	let p2 = DVec3::new(r * end.cos(), r * end.sin(), z_lo);

	let mid = 0.5 * (start + end);
	let wire = [
		Edge::line(p0, p1)?,
		Edge::arc_3pts(p1, DVec3::new(r * mid.cos(), r * mid.sin(), z_lo), p2)?,
		Edge::line(p2, p0)?,
	];
	let wedge = Solid::extrude(wire.iter(), DVec3::new(0.0, 0.0, z_hi - z_lo))?;
	let result = match mode {
		Mode::Intersect => solid.intersect([&wedge])?,
		Mode::Subtract => solid.subtract([&wedge])?,
	};
	result
		.into_iter()
		.next()
		.ok_or(cadrum::Error::BooleanOperationFailed)
}

/// cut サブコマンドのエントリポイント。`start`/`end` はラジアン済み。
pub fn run(input: &Path, output: &Path, start: f64, end: f64, mode: Mode) -> Result<()> {
	let span = end - start;
	if !(span > 0.0) {
		return Err(format!("end ({}) must be greater than start ({})", end, start).into());
	}
	if span > TAU + 1e-12 {
		return Err(format!("end - start must be <= tau; got {} rad", span).into());
	}

	println!("Loading STEP: {}", input.display());
	let solids: Vec<Solid> = cadrum::read_step(&mut File::open(input)?)?;
	println!("  loaded {} solid(s)", solids.len());

	let full_turn = (span - TAU).abs() < 1e-12;
	let cut_solids: Vec<Solid> = if full_turn {
		// span = tau: wedge が 1 周を覆う。intersect なら入力そのまま、
		// subtract なら全除去で結果が空になるため、明示的にエラーで止める。
		match mode {
			Mode::Intersect => {
				println!("span = tau with --cut: pass-through");
				solids.clone()
			}
			Mode::Subtract => {
				return Err(
					"span = tau with --union subtracts the entire solid; nothing to output".into(),
				);
			}
		}
	} else {
		let op = match mode {
			Mode::Intersect => "intersect",
			Mode::Subtract => "subtract",
		};
		println!(
			"Fan sector [{:.6}, {:.6}] rad (span {:.6}), op = {}",
			start, end, span, op
		);
		solids
			.iter()
			.map(|s| cut_solid(s, start, end, mode))
			.collect::<std::result::Result<_, _>>()?
	};

	if cut_solids.is_empty() {
		return Err("boolean operation returned empty".into());
	}
	println!("  got {} solid(s) after boolean", cut_solids.len());
	println!(
		"  volume input vs output: {} -> {}",
		solids.volume(),
		cut_solids.volume()
	);

	if let Some(parent) = output.parent() {
		if !parent.as_os_str().is_empty() {
			std::fs::create_dir_all(parent)?;
		}
	}

	println!("Writing STEP: {}", output.display());
	cadrum::write_step(cut_solids.iter(), &mut File::create(output)?)?;
	println!("Done.");
	Ok(())
}

#[cfg(test)]
mod tests {
	use super::parse_tau_fraction;
	use std::f64::consts::TAU;

	fn approx(a: f64, b: f64) {
		assert!((a - b).abs() < 1e-12, "{} vs {}", a, b);
	}

	#[test]
	fn parses_integer_and_fraction() {
		approx(parse_tau_fraction("0").unwrap(), 0.0);
		approx(parse_tau_fraction("1").unwrap(), TAU);
		approx(parse_tau_fraction("1/3").unwrap(), TAU / 3.0);
		approx(parse_tau_fraction("-1/6").unwrap(), -TAU / 6.0);
		approx(parse_tau_fraction("+2/4").unwrap(), TAU / 2.0);
		approx(parse_tau_fraction("+0").unwrap(), 0.0);
		approx(parse_tau_fraction("-0/7").unwrap(), 0.0);
	}

	#[test]
	fn rejects_bad_inputs() {
		for bad in [
			"", "1.5", "1/", "/2", "1/2/3", "+", "-", " 1 ", "1 /2", "a", "1/-2",
		] {
			assert!(parse_tau_fraction(bad).is_err(), "expected error for {:?}", bad);
		}
	}

	#[test]
	fn rejects_zero_denominator() {
		assert!(parse_tau_fraction("1/0").is_err());
	}
}
