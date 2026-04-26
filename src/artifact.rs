//! `vessel` / `magnet` が生成する STEP solid + CSV 点群のペアを
//! 一括で扱うための共通 record。
//!
//! `name` は意図的に持たせない。書き出し基底名は呼び出し側が
//! `write(out_dir, name)` の第 2 引数で渡す。

use cadrum::{DVec3, Solid};
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::Path;

use crate::Result;

pub struct Artifact {
	pub name: String,
	/// 出力する solids。色は構築側で適用済み。
	pub solids: Vec<Solid>,
	/// 可視化用の点群 (header 無し `x,y,z` CSV にダンプ)。
	pub points: Vec<DVec3>,
}

impl Artifact {
	/// `<out_dir>/<name>.step` と `<out_dir>/<name>.csv` を書き出す。
	pub fn write(&self, out_dir: &Path, name: &str) -> Result<()> {
		std::fs::create_dir_all(out_dir)
			.map_err(|e| format!("create_dir_all {}: {}", out_dir.display(), e))?;

		let step_path = out_dir.join(format!("{}.step", name));
		println!("  Writing STEP: {}", step_path.display());
		let mut step_file = File::create(&step_path)
			.map_err(|e| format!("create {}: {}", step_path.display(), e))?;
		cadrum::write_step(self.solids.iter(), &mut step_file)
			.map_err(|e| format!("write_step failed: {:?}", e))?;

		let csv_path = out_dir.join(format!("{}.csv", name));
		println!("  Writing CSV: {}", csv_path.display());
		let csv_file = File::create(&csv_path)
			.map_err(|e| format!("create {}: {}", csv_path.display(), e))?;
		let mut csv = BufWriter::new(csv_file);
		for p in &self.points {
			writeln!(csv, "{},{},{}", p.x, p.y, p.z)
				.map_err(|e| format!("write csv: {}", e))?;
		}
		csv.flush().map_err(|e| format!("flush csv: {}", e))?;
		Ok(())
	}
}
