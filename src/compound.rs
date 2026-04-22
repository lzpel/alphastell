//! `compound` サブコマンド。複数の STEP ファイルを 1 枚の STEP にまとめる。
//!
//! 色:
//! - ファイル入力 (`inputs`): `#ee7800` (内側 chamber) から `#ffffff` (外側 vacuum_vessel)
//!   への線形 RGB 補間で順番に塗る。
//! - `extras`: 呼び出し側で事前着色済みとみなし preserve (例: magnet::build_sector の
//!   コイル per-index rainbow)。
//!
//! 同時に、STEP と同名の SVG (拡張子だけ置換) も書き出す。`cadrum::mesh` で
//! tessellate してから `Mesh::write_svg` で投影。鉛直軸 (Z) を X 軸まわり -π/2 で
//! Y へ倒して (Y/Z swap 相当)、-Y 方向から俯瞰する構図。隠線 off、shading on。

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

	// 同名 SVG を書き出す。X 軸まわり -π/2 で Y/Z を入れ替え (Z → +Y)、
	// その上で -Y 方向 (新「上」方向) から俯瞰。隠線 off、shading on。
	let svg_path = output.with_extension("svg");
	println!(
		"Writing SVG: {} (mesh tol = {}, rotate_x(-π/2), view=-Y)",
		svg_path.display(),
		SVG_MESH_TOL
	);
	let rotated: Vec<Solid> = all
		.into_iter()
		.map(|s| s.rotate_x(-std::f64::consts::FRAC_PI_2))
		.collect();
	let mesh = cadrum::mesh(rotated.iter(), SVG_MESH_TOL)
		.map_err(|e| format!("mesh failed: {:?}", e))?;
	let mut svg_file = File::create(&svg_path)
		.map_err(|e| format!("create {}: {}", svg_path.display(), e))?;
	mesh.write_svg(-DVec3::Y, false, true, &mut svg_file)
		.map_err(|e| format!("write_svg failed: {:?}", e))?;

	println!("Done.");
	Ok(())
}
