//! `compound` サブコマンド。複数の STEP ファイルを 1 枚に統合し、
//! 各 source に HSV hue を等分割で割り当てて着色する。
//! 色は `Color::from_hsv(i / N, 1.0, 1.0)` — 純色 (S=V=1)。入力既存色は上書き。

use cadrum::{Color, Solid};
use std::fs::File;
use std::path::{Path, PathBuf};

use crate::Result;

/// ファイル入力 (`inputs`) に加えて、呼び出し側で事前に構築済みの solid 群
/// (`extras: Vec<(label, Vec<Solid>)>`) を追加入力として受け取れる。
/// 全 source (N = inputs.len() + extras.len()) にまたがり hue = i/N を付ける。
pub fn run(
	inputs: &[PathBuf],
	extras: Vec<(String, Vec<Solid>)>,
	output: &Path,
) -> Result<()> {
	if inputs.is_empty() && extras.is_empty() {
		return Err("compound: at least one -i input or in-memory extra is required".into());
	}

	let n = inputs.len() + extras.len();
	let color = |i: usize| Color::from_hsv(i as f32 / n as f32, 1.0, 1.0);
	let mut all: Vec<Solid> = Vec::new();
	let mut i = 0usize;
	for path in inputs.iter() {
		let c = color(i);
		println!(
			"[{}/{}] {}  hsv({:.3}, 1, 1) = rgb({:.2}, {:.2}, {:.2})",
			i + 1,
			n,
			path.display(),
			i as f32 / n as f32,
			c.r,
			c.g,
			c.b
		);
		let solids: Vec<Solid> = cadrum::read_step(&mut File::open(path)?)
			.map_err(|e| format!("read_step {}: {:?}", path.display(), e))?;
		println!("  loaded {} solid(s)", solids.len());
		for s in solids {
			all.push(s.color(c));
		}
		i += 1;
	}
	for (label, solids) in extras {
		let c = color(i);
		println!(
			"[{}/{}] {} (in-memory)  hsv({:.3}, 1, 1) = rgb({:.2}, {:.2}, {:.2})",
			i + 1,
			n,
			label,
			i as f32 / n as f32,
			c.r,
			c.g,
			c.b
		);
		println!("  {} solid(s)", solids.len());
		for s in solids {
			all.push(s.color(c));
		}
		i += 1;
	}

	if let Some(parent) = output.parent() {
		if !parent.as_os_str().is_empty() {
			std::fs::create_dir_all(parent)?;
		}
	}

	println!(
		"Writing STEP: {} ({} solid(s) from {} source(s))",
		output.display(),
		all.len(),
		n
	);
	cadrum::write_step(all.iter(), &mut File::create(output)?)
		.map_err(|e| format!("write_step {}: {:?}", output.display(), e))?;
	println!("Done.");
	Ok(())
}
