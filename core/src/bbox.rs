//! `bbox` サブコマンドの実装。STEP ファイル群を読み、各ファイルの軸並行
//! バウンディングボックスを `path x0 y0 z0 x1 y1 z1 dx dy dz` の形式で
//! 1 行ずつ標準出力に書き出す。

use std::fs::File;
use std::path::{Path, PathBuf};

use crate::Result;

pub fn run(inputs: &[PathBuf]) -> Result<()> {
	for path in inputs {
		let solids = read_step_file(path)?;
		// cadrum 0.8.4 で Compound::bounding_box が無くなったので各 Solid の bbox を畳み込む
		let [min, max] = solids.iter().map(|v| v.bounding_box()).reduce(|a, b| [a[0].min(b[0]), a[1].max(b[1])]).ok_or("empty STEP: no solids")?;
		let dx = max.x - min.x;
		let dy = max.y - min.y;
		let dz = max.z - min.z;
		println!(
			"{} {} {} {} {} {} {} {} {} {}",
			path.display(),
			min.x, min.y, min.z,
			max.x, max.y, max.z,
			dx, dy, dz,
		);
	}
	Ok(())
}

fn read_step_file(path: &Path) -> Result<Vec<cadrum::Solid>> {
	let mut f = File::open(path)
		.map_err(|e| format!("open {}: {}", path.display(), e))?;
	cadrum::Solid::read_step(&mut f)
		.map_err(|e| format!("read_step {}: {:?}", path.display(), e).into())
}
