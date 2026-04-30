//! `vessel` / `magnet` が生成する STEP solid + GLB mesh + CSV 点群を
//! 一括で扱うための共通 record。

use cadrum::{DVec3, Solid};
use std::io::Write;
use std::path::Path;

use crate::Result;

/// Meshing tolerance [出力単位]。vessel/magnet の `--scale 100` (cm) 想定で
/// モデル全長 ~2000 cm に対して 10 cm = 0.5 % の粗さ。デモ視認用にバランスを取った値。
const MESH_TOL: f64 = 10.0;

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

	/// GLB (glTF binary) を `Vec<u8>` で取得。`solids` を `MESH_TOL` で tessellate し、
	/// 色グループ別 primitive + edge データ込みで GLB 化する。
	pub fn glb_bytes(&self) -> Result<Vec<u8>> {
		let mesh = cadrum::mesh(self.solids.iter(), MESH_TOL)
			.map_err(|e| format!("mesh failed: {:?}", e))?;
		mesh_to_glb(&self.solids, &mesh).map_err(|e| format!("mesh_to_glb failed: {:?}", e).into())
	}

	/// header 無し `x,y,z` CSV を `Vec<u8>` で取得。
	pub fn csv_bytes(&self) -> Vec<u8> {
		let mut buf = Vec::new();
		for p in &self.points {
			writeln!(buf, "{},{},{}", p.x, p.y, p.z).expect("write to Vec<u8> never fails");
		}
		buf
	}

	/// `<out_dir>/<name>.{step,glb,csv}` を書き出す。
	pub fn write(&self, out_dir: &Path, name: &str) -> Result<()> {
		std::fs::create_dir_all(out_dir)
			.map_err(|e| format!("create_dir_all {}: {}", out_dir.display(), e))?;
		for (ext, bytes) in [
			("step", self.step_bytes()?),
			("glb", self.glb_bytes()?),
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

use gltf_json as json;

/// Mesh と Shape から GLB (GLTF Binary) を生成する。
/// shape.colormap が空の場合はグレー単色プリミティブ、
/// 色情報がある場合は色グループ別プリミティブを生成する。
pub fn mesh_to_glb(shape: &[Solid], mesh: &cadrum::Mesh) -> std::result::Result<Vec<u8>, cadrum::Error> {
	// Rgb は Hash 未実装なので bits() でキー化
	fn rgb_key(rgb: cadrum::Color) -> (u32, u32, u32) {
		(rgb.r.to_bits(), rgb.g.to_bits(), rgb.b.to_bits())
	}

	// 三角形を色グループ別インデックスリストに振り分ける
	// face_ids.len() == indices.len() / 3
	let mut groups: std::collections::HashMap<
		(u32, u32, u32),
		(Option<cadrum::Color>, Vec<usize>),
	> = std::collections::HashMap::new();

	for (tri_idx, &face_id) in mesh.face_ids.iter().enumerate() {
		let rgb = mesh.colormap.get(&face_id).copied();
		let key = rgb.map(rgb_key).unwrap_or((0, 0, 0));
		let entry = groups.entry(key).or_insert((rgb, Vec::new()));
		entry
			.1
			.extend_from_slice(&mesh.indices[tri_idx * 3..tri_idx * 3 + 3]);
	}

	let groups: Vec<(Option<cadrum::Color>, Vec<usize>)> = groups.into_values().collect();

	build_glb(shape, mesh, &groups)
}

/// 色グループ別プリミティブの GLB を組み立てる。
/// 頂点バッファは全グループで共有し、インデックスバッファだけ色ごとに分ける。
fn build_glb(
	shape: &[Solid],
	mesh: &cadrum::Mesh,
	groups: &[(Option<cadrum::Color>, Vec<usize>)],
) -> std::result::Result<Vec<u8>, cadrum::Error> {
	use json::validation::Checked::Valid;

	let positions: Vec<[f32; 3]> = mesh
		.vertices
		.iter()
		.map(|v| [v.x as f32, v.y as f32, v.z as f32])
		.collect();

	let mut pos_min = [f32::INFINITY; 3];
	let mut pos_max = [f32::NEG_INFINITY; 3];
	for p in &positions {
		for i in 0..3 {
			pos_min[i] = pos_min[i].min(p[i]);
			pos_max[i] = pos_max[i].max(p[i]);
		}
	}

	let mut root = json::Root::default();
	root.buffers.push(json::Buffer {
		byte_length: json::validation::USize64(0),
		name: None,
		uri: None,
		extensions: None,
		extras: Default::default(),
	});

	let mut buffer: Vec<u8> = Vec::new();

	// 頂点バッファ（全グループ共有）
	let pos_bytes = unsafe {
		std::slice::from_raw_parts(positions.as_ptr() as *const u8, positions.len() * 12)
	};
	let pos_view = root.buffer_views.len() as u32;
	buffer.extend_from_slice(pos_bytes);
	root.buffer_views.push(json::buffer::View {
		buffer: json::Index::new(0),
		byte_length: json::validation::USize64(pos_bytes.len() as u64),
		byte_offset: Some(json::validation::USize64(0)),
		byte_stride: None,
		name: None,
		target: Some(Valid(json::buffer::Target::ArrayBuffer)),
		extensions: None,
		extras: Default::default(),
	});
	let pos_accessor = root.accessors.len() as u32;
	root.accessors.push(json::Accessor {
		buffer_view: Some(json::Index::new(pos_view)),
		byte_offset: Some(json::validation::USize64(0)),
		count: json::validation::USize64(positions.len() as u64),
		component_type: Valid(json::accessor::GenericComponentType(
			json::accessor::ComponentType::F32,
		)),
		type_: Valid(json::accessor::Type::Vec3),
		extensions: None,
		extras: Default::default(),
		min: Some(serde_json::json!([pos_min[0], pos_min[1], pos_min[2]])),
		max: Some(serde_json::json!([pos_max[0], pos_max[1], pos_max[2]])),
		name: None,
		normalized: false,
		sparse: None,
	});

	// 色グループごとにインデックスバッファ + プリミティブを生成
	let mut primitives: Vec<json::mesh::Primitive> = Vec::new();
	let mut materials: Vec<serde_json::Value> = Vec::new();

	for (color, indices) in groups {
		let idx_count = indices.len();
		let (idx_bytes, idx_component_type) = if positions.len() <= 65535 {
			let v: Vec<u16> = indices.iter().map(|&i| i as u16).collect();
			let bytes = unsafe { std::slice::from_raw_parts(v.as_ptr() as *const u8, v.len() * 2) }
				.to_vec();
			(bytes, json::accessor::ComponentType::U16)
		} else {
			let v: Vec<u32> = indices.iter().map(|&i| i as u32).collect();
			let bytes = unsafe { std::slice::from_raw_parts(v.as_ptr() as *const u8, v.len() * 4) }
				.to_vec();
			(bytes, json::accessor::ComponentType::U32)
		};

		let idx_view = root.buffer_views.len() as u32;
		let idx_offset = buffer.len();
		buffer.extend_from_slice(&idx_bytes);
		while buffer.len() % 4 != 0 {
			buffer.push(0);
		}
		root.buffer_views.push(json::buffer::View {
			buffer: json::Index::new(0),
			byte_length: json::validation::USize64(idx_bytes.len() as u64),
			byte_offset: Some(json::validation::USize64(idx_offset as u64)),
			byte_stride: None,
			name: None,
			target: Some(Valid(json::buffer::Target::ElementArrayBuffer)),
			extensions: None,
			extras: Default::default(),
		});
		let idx_accessor = root.accessors.len() as u32;
		root.accessors.push(json::Accessor {
			buffer_view: Some(json::Index::new(idx_view)),
			byte_offset: Some(json::validation::USize64(0)),
			count: json::validation::USize64(idx_count as u64),
			component_type: Valid(json::accessor::GenericComponentType(idx_component_type)),
			type_: Valid(json::accessor::Type::Scalar),
			extensions: None,
			extras: Default::default(),
			min: None,
			max: None,
			name: None,
			normalized: false,
			sparse: None,
		});

		let material_index = materials.len() as u32;
		let (r, g, b) = color
			.map(|c| (c.r as f64, c.g as f64, c.b as f64))
			.unwrap_or((0.8, 0.8, 0.8));
		materials.push(serde_json::json!({
			"extensions": { "KHR_materials_unlit": {} },
			"pbrMetallicRoughness": {
				"baseColorFactor": [r, g, b, 1.0],
				"metallicFactor": 0.0,
				"roughnessFactor": 1.0
			},
			"alphaMode": "OPAQUE",
			"doubleSided": true
		}));

		primitives.push(json::mesh::Primitive {
			attributes: {
				let mut map = std::collections::BTreeMap::new();
				map.insert(
					Valid(json::mesh::Semantic::Positions),
					json::Index::new(pos_accessor),
				);
				map
			},
			indices: Some(json::Index::new(idx_accessor)),
			extensions: None,
			extras: Default::default(),
			material: Some(json::Index::new(material_index)),
			mode: Valid(json::mesh::Mode::Triangles),
			targets: None,
		});
	}

	// エッジデータ
	let mut edge_data: Vec<f32> = Vec::new();
	for solid in shape {
		for edge in solid.iter_edge() {
			let segments = edge.approximation_segments(0.1);
			for w in segments.windows(2) {
				edge_data.extend_from_slice(&[
					w[0].x as f32,
					w[0].y as f32,
					w[0].z as f32,
					w[1].x as f32,
					w[1].y as f32,
					w[1].z as f32,
				]);
			}
		}
	}
	let edge_accessor_index = if !edge_data.is_empty() {
		let edge_bytes = unsafe {
			std::slice::from_raw_parts(edge_data.as_ptr() as *const u8, edge_data.len() * 4)
		};
		let edge_view = root.buffer_views.len() as u32;
		let edge_offset = buffer.len();
		buffer.extend_from_slice(edge_bytes);
		root.buffer_views.push(json::buffer::View {
			buffer: json::Index::new(0),
			byte_length: json::validation::USize64(edge_bytes.len() as u64),
			byte_offset: Some(json::validation::USize64(edge_offset as u64)),
			byte_stride: None,
			name: None,
			target: Some(Valid(json::buffer::Target::ArrayBuffer)),
			extensions: None,
			extras: Default::default(),
		});
		let accessor_index = root.accessors.len() as u32;
		root.accessors.push(json::Accessor {
			buffer_view: Some(json::Index::new(edge_view)),
			byte_offset: Some(json::validation::USize64(0)),
			count: json::validation::USize64((edge_data.len() / 3) as u64),
			component_type: Valid(json::accessor::GenericComponentType(
				json::accessor::ComponentType::F32,
			)),
			type_: Valid(json::accessor::Type::Vec3),
			extensions: None,
			extras: Default::default(),
			min: None,
			max: None,
			name: None,
			normalized: false,
			sparse: None,
		});
		Some(accessor_index)
	} else {
		None
	};

	root.buffers[0].byte_length = json::validation::USize64(buffer.len() as u64);

	root.meshes.push(json::Mesh {
		extensions: None,
		extras: Default::default(),
		name: None,
		primitives,
		weights: None,
	});
	root.nodes.push(json::Node {
		mesh: Some(json::Index::new(0)),
		..Default::default()
	});
	root.scenes.push(json::Scene {
		extensions: None,
		extras: Default::default(),
		name: None,
		nodes: vec![json::Index::new(0)],
	});
	root.scene = Some(json::Index::new(0));

	// JSON 組み立て・マテリアル注入・GLB バイナリ出力
	let json_string =
		json::serialize::to_string(&root).map_err(|e| cadrum::Error::Unknown(e.to_string()))?;
	let mut json_val: serde_json::Value =
		serde_json::from_str(&json_string).map_err(|e| cadrum::Error::Unknown(e.to_string()))?;

	json_val["extensionsUsed"] = serde_json::json!(["KHR_materials_unlit"]);
	json_val["materials"] = serde_json::Value::Array(materials);
	if let Some(idx) = edge_accessor_index {
		json_val["extras"] = serde_json::json!({ "edgeAccessor": idx });
	}

	let json_string =
		serde_json::to_string(&json_val).map_err(|e| cadrum::Error::Unknown(e.to_string()))?;
	let mut json_bytes = json_string.into_bytes();
	while json_bytes.len() % 4 != 0 {
		json_bytes.push(b' ');
	}

	let mut glb = Vec::new();
	let total_size = 12 + 8 + json_bytes.len() + 8 + buffer.len();
	glb.write_all(b"glTF").unwrap();
	glb.write_all(&2u32.to_le_bytes()).unwrap();
	glb.write_all(&(total_size as u32).to_le_bytes()).unwrap();
	glb.write_all(&(json_bytes.len() as u32).to_le_bytes())
		.unwrap();
	glb.write_all(b"JSON").unwrap();
	glb.write_all(&json_bytes).unwrap();
	glb.write_all(&(buffer.len() as u32).to_le_bytes()).unwrap();
	glb.write_all(b"BIN\0").unwrap();
	glb.write_all(&buffer).unwrap();

	Ok(glb)
}