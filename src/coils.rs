//! `coils.example` (MAKEGRID 形式) のパーサ。
//!
//! フォーマット:
//! ```text
//! periods   4
//! begin filament
//! mirror NIL
//!   <x1>  <y1>  <z1>  <current>         (各数値は科学記法の f64、単位 [m] / [A])
//!   ...
//!   <xN>  <yN>  <zN>  0.000000E+00  <coil_id> <label>   ← 4 列目 = 0 でフィラメント終端
//!   <x1>  <y1>  <z1>  <current>                            ← 次フィラメント開始
//!   ...
//! end
//! ```
//!
//! 本 repo の `coils.example` は **40 フィラメント** (5 本のユニーク Fourier 曲線 ×
//! nfp=4 周期 × 対称反射 2) で、ステラレータのコイル群を成す。

use anyhow::{Context, Result, bail};
use cadrum::DVec3;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

/// `coils.example` から読んだフィラメント集合。座標は **[m]** のまま (変換なし)。
pub struct Filaments {
	/// `periods` の値 (ステラレータ対称の field period 数、nfp)
	pub nfp: u32,
	/// 各フィラメントの芯線点列。`coils[i]` は i 番目コイルの連続点の列。
	/// 入力ファイルで 4 列目 = 0 の行 (終端マーカー) の座標も含めて保持する。
	pub coils: Vec<Vec<DVec3>>,
}

/// `coils.example` を開いて [`Filaments`] を返す。
///
/// パース規則:
/// 1. 先頭 3 行: `periods N` / `begin filament` / `mirror NIL` をヘッダ扱い
///    - `periods` の N を `nfp` に格納
/// 2. データ行は空白区切り。先頭 4 フィールドを f64 として読む
///    - 5 列目以降に `<coil_id> <label>` が付く行があるが無視
/// 3. 4 列目 (current) が 0.0 のとき: その行までを 1 フィラメントとして push、次から新フィラメント
/// 4. `end` 行で終了
pub fn parse(path: &Path) -> Result<Filaments> {
	let file = File::open(path).with_context(|| format!("open {}", path.display()))?;
	let reader = BufReader::new(file);

	let mut nfp: Option<u32> = None;
	let mut coils: Vec<Vec<DVec3>> = Vec::new();
	let mut current: Vec<DVec3> = Vec::new();
	let mut header_seen = 0; // periods / begin filament / mirror を数える

	for (line_num, line_res) in reader.lines().enumerate() {
		let line = line_res.with_context(|| format!("read line {}", line_num + 1))?;
		let trimmed = line.trim();

		// 空行はスキップ
		if trimmed.is_empty() {
			continue;
		}

		// 終端
		if trimmed.starts_with("end") {
			break;
		}

		// ヘッダ判定 (先頭 3 行だけチェック)
		if header_seen < 3 {
			if let Some(rest) = trimmed.strip_prefix("periods") {
				nfp = Some(
					rest.trim()
						.parse::<u32>()
						.with_context(|| format!("parse nfp at line {}", line_num + 1))?,
				);
				header_seen += 1;
				continue;
			}
			if trimmed.starts_with("begin filament") || trimmed.starts_with("mirror") {
				header_seen += 1;
				continue;
			}
		}

		// データ行: 空白区切りの先頭 4 フィールド
		let fields: Vec<&str> = trimmed.split_whitespace().collect();
		if fields.len() < 4 {
			bail!(
				"line {}: expected at least 4 fields, got {}",
				line_num + 1,
				fields.len()
			);
		}
		let x: f64 = fields[0]
			.parse()
			.with_context(|| format!("parse x at line {}", line_num + 1))?;
		let y: f64 = fields[1]
			.parse()
			.with_context(|| format!("parse y at line {}", line_num + 1))?;
		let z: f64 = fields[2]
			.parse()
			.with_context(|| format!("parse z at line {}", line_num + 1))?;
		let i: f64 = fields[3]
			.parse()
			.with_context(|| format!("parse current at line {}", line_num + 1))?;

		current.push(DVec3::new(x, y, z));

		// 終端マーカー
		if i == 0.0 {
			coils.push(std::mem::take(&mut current));
		}
	}

	// 残った未 push のフィラメント (想定外、防御的に)
	if !current.is_empty() {
		coils.push(current);
	}

	let nfp = nfp.context("no 'periods' header found")?;
	Ok(Filaments { nfp, coils })
}
