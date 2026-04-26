//! `compound` サブコマンド。複数の STEP ファイルを 1 枚の STEP にまとめる。
//!
//! 色:
//! - ファイル入力 (`inputs`): `#ee7800` (内側 chamber) から `#ffffff` (外側 vacuum_vessel)
//!   への線形 RGB 補間で順番に塗る。
//! - `extras`: 呼び出し側で事前着色済みとみなし preserve (例: magnet::build_sector の
//!   コイル per-index rainbow)。
//!
//! 同時に、STEP と同名の SVG (拡張子だけ置換) も書き出す。`cadrum::mesh` で
//! tessellate してから `Mesh::write_svg(view=-Y, up=+Z)` で投影。
//! stellarator の鉛直軸 Z を画面の上方向に取り、-Y 方向から側面を見る構図。
//! 隠線 off、shading on。

use cadrum::{Color, DVec3, Solid};
use std::fs::File;
use std::path::{Path, PathBuf};

use crate::Result;

/// compound 出力 SVG の meshing tolerance。vessel 由来の cm 単位想定で
/// モデル全長 ~2000 cm。tolerance 200 cm (= 2 m、モデル全長の約 10%) で
/// 荒い外形プレビューが素早く出る。
const SVG_MESH_TOL: f64 = 200.0;

/// グラデーションの両端。`#ee7800` (内側: オレンジ) → `#ffffff` (外側: 白)。
const GRAD_START: Color = Color {
	r: 0xEE as f32 / 255.0,
	g: 0x78 as f32 / 255.0,
	b: 0x00 as f32 / 255.0,
};
const GRAD_END: Color = Color { r: 1.0, g: 1.0, b: 1.0 };

fn lerp_color(a: Color, b: Color, t: f32) -> Color {
	Color {
		r: a.r + (b.r - a.r) * t,
		g: a.g + (b.g - a.g) * t,
		b: a.b + (b.b - a.b) * t,
	}
}

/// ファイル入力 (`inputs`) に加えて、呼び出し側で事前に構築済みの solid 群
/// (`extras: Vec<(label, Vec<Solid>)>`) を追加入力として受け取れる。
/// - file 入力: chamber→vacuum_vessel グラデで上書き着色
/// - extras: 事前 `.color()` を preserve
pub fn run(
	inputs: &[PathBuf],
	extras: Vec<(String, Vec<Solid>)>,
	output: &Path,
) -> Result<()> {
	if inputs.is_empty() && extras.is_empty() {
		return Err("compound: at least one -i input or in-memory extra is required".into());
	}

	let n = inputs.len() + extras.len();
	let n_inputs = inputs.len();
	let color = |i: usize| {
		let t = if n_inputs <= 1 {
			0.0
		} else {
			i as f32 / (n_inputs - 1) as f32
		};
		lerp_color(GRAD_START, GRAD_END, t)
	};
	let mut all: Vec<Solid> = Vec::new();
	let mut i = 0usize;
	for path in inputs.iter() {
		let c = color(i);
		let t = if n_inputs <= 1 {
			0.0
		} else {
			i as f32 / (n_inputs - 1) as f32
		};
		println!(
			"[{}/{}] {}  t={:.3} rgb=({:.2}, {:.2}, {:.2})",
			i + 1,
			n,
			path.display(),
			t,
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
		println!(
			"[{}/{}] {} (in-memory, preserve colors)",
			i + 1,
			n,
			label
		);
		println!("  {} solid(s)", solids.len());
		for s in solids {
			all.push(s);
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

	// 同名 SVG を書き出す。view=-Y (側面から)、up=+Z (stellarator の鉛直軸を画面上に)。
	// 隠線 off、shading on。
	let svg_path = output.with_extension("svg");
	let stl_path = output.with_extension("stl");
	println!(
		"Writing SVG/STL: {} (mesh tol = {}, view=-Y, up=+Z)",
		svg_path.display(),
		SVG_MESH_TOL
	);
	let mesh = cadrum::mesh(all.iter(), SVG_MESH_TOL)
		.map_err(|e| format!("mesh failed: {:?}", e))?;
	let mut svg_file = File::create(&svg_path)
		.map_err(|e| format!("create {}: {}", svg_path.display(), e))?;
	mesh.write_svg(DVec3::ONE, DVec3::Z, false, true, &mut svg_file)
		.map_err(|e| format!("write_svg failed: {:?}", e))?;
	let mut stl_file = File::create(&stl_path)
		.map_err(|e| format!("create {}: {}", stl_path.display(), e))?;
	mesh.write_stl(&mut stl_file)
		.map_err(|e| format!("write_stl failed: {:?}", e))?;

	println!("Done.");
	Ok(())
}
