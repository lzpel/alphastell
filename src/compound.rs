//! `compound` サブコマンド。複数の STEP ファイルを読み込み、各ファイルに
//! HSV 色相を等分割で割り当てて 1 つの STEP にまとめて出力する。
//!
//! 色は `Color::from_hsv(i/N, 0.8, 0.95)` で生成。N ファイル目の色相は
//! 0, 1/N, 2/N, …, (N-1)/N と等分割され、彩度 0.8 / 明度 0.95 で
//! CAD ビューワで見やすい範囲に落とす。既存の色情報は上書きする。

use cadrum::{Color, Solid};
use std::fs::File;
use std::path::{Path, PathBuf};

use crate::Result;

pub fn run(inputs: &[PathBuf], output: &Path) -> Result<()> {
	if inputs.is_empty() {
		return Err("compound: at least one -i input is required".into());
	}

	let n = inputs.len();
	let mut all: Vec<Solid> = Vec::new();
	for (i, path) in inputs.iter().enumerate() {
		let h = i as f32 / n as f32;
		let color = Color::from_hsv(h, 0.8, 0.95);
		println!(
			"[{}/{}] {}  hsv=({:.3}, 0.80, 0.95) rgb=({:.2}, {:.2}, {:.2})",
			i + 1,
			n,
			path.display(),
			h,
			color.r,
			color.g,
			color.b
		);
		let solids: Vec<Solid> = cadrum::read_step(&mut File::open(path)?)
			.map_err(|e| format!("read_step {}: {:?}", path.display(), e))?;
		println!("  loaded {} solid(s)", solids.len());
		for s in solids {
			all.push(s.color(color));
		}
	}

	if let Some(parent) = output.parent() {
		if !parent.as_os_str().is_empty() {
			std::fs::create_dir_all(parent)?;
		}
	}

	println!(
		"Writing STEP: {} ({} solid(s) from {} file(s))",
		output.display(),
		all.len(),
		n
	);
	cadrum::write_step(all.iter(), &mut File::create(output)?)
		.map_err(|e| format!("write_step {}: {:?}", output.display(), e))?;
	println!("Done.");
	Ok(())
}
