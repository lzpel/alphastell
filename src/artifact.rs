//! `vessel` / `magnet` が生成する STEP solid + STL mesh + CSV 点群を
//! 一括で扱うための共通 record。

use cadrum::{DVec3, Solid};
use std::io::Write;
use std::path::Path;

use crate::Result;

/// STL meshing tolerance [出力単位]。vessel/magnet の `--scale 100` (cm) 想定で
/// モデル全長 ~2000 cm に対して 10 cm = 0.5 % の粗さ。デモ視認用にバランスを取った値。
const STL_MESH_TOL: f64 = 10.0;

pub struct Artifact {
	pub name: String,
	/// 出力する solids。色は構築側で適用済み。
	pub solids: Vec<Solid>,
	/// 可視化用の点群 (header 無し `x,y,z` CSV にダンプ)。
	pub points: Vec<DVec3>,
}

impl Artifact {
	/// STEP バイナリを `Vec<u8>` で取得。
	pub fn step_bytes(&self) -> Result<Vec<u8>> {
		let mut buf = Vec::new();
		cadrum::write_step(self.solids.iter(), &mut buf)
			.map_err(|e| format!("write_step failed: {:?}", e))?;
		Ok(buf)
	}

	/// バイナリ STL を `Vec<u8>` で取得。`solids` を `STL_MESH_TOL` で tessellate。
	pub fn stl_bytes(&self) -> Result<Vec<u8>> {
		let mesh = cadrum::mesh(self.solids.iter(), STL_MESH_TOL)
			.map_err(|e| format!("mesh failed: {:?}", e))?;
		let mut buf = Vec::new();
		mesh.write_stl(&mut buf)
			.map_err(|e| format!("write_stl failed: {:?}", e))?;
		Ok(buf)
	}

	/// header 無し `x,y,z` CSV を `Vec<u8>` で取得。
	pub fn csv_bytes(&self) -> Vec<u8> {
		let mut buf = Vec::new();
		for p in &self.points {
			writeln!(buf, "{},{},{}", p.x, p.y, p.z).expect("write to Vec<u8> never fails");
		}
		buf
	}

	/// `<out_dir>/<name>.{step,stl,csv}` を書き出す。
	pub fn write(&self, out_dir: &Path, name: &str) -> Result<()> {
		std::fs::create_dir_all(out_dir)
			.map_err(|e| format!("create_dir_all {}: {}", out_dir.display(), e))?;
		for (ext, bytes) in [
			("step", self.step_bytes()?),
			("stl", self.stl_bytes()?),
			("csv", self.csv_bytes()),
		] {
			let path = out_dir.join(format!("{}.{}", name, ext));
			println!("  Writing {}: {}", ext.to_uppercase(), path.display());
			std::fs::write(&path, bytes)
				.map_err(|e| format!("write {}: {}", path.display(), e))?;
		}
		Ok(())
	}
}
