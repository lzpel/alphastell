//! `strip-netcdf` サブコマンド。NetCDF3 ファイルから `--include` で指定した
//! 変数だけを残したスリム版を書き出す。`vessel` のプリセット (`wout_*.nc`)
//! を `rmnc / zmns / xm / xn` 4 変数だけにして数百 KB に縮める用途を想定。
//!
//! 結果は **lossless** で、保持された変数のバイト列は元と完全一致する。
//! 関連する次元 (kept variables が参照する dim) と、保持される変数の
//! var attribute は引き継ぐ。global attribute も全て引き継ぐ。

use std::path::Path;

use netcdf3::{DataSet, DataType, FileReader, FileWriter, Version};

use crate::Result;

/// `input` を読み、`include` リストにある変数だけを `output` に書き出す。
/// `include` が空のときは「何もキープしない」ので、空 NetCDF が出る。
/// 通常は呼び出し側で 1 つ以上の変数名を渡すこと。
pub fn run(input: &Path, output: &Path, include: &[String]) -> Result<()> {
	let mut reader = FileReader::open(input)
		.map_err(|e| format!("open input {}: {:?}", input.display(), e))?;
	let in_ds = reader.data_set();

	// 1. キープする変数を決定。include に書いてあって、かつ実在するものだけ。
	let kept_names: Vec<String> = include
		.iter()
		.filter(|n| in_ds.get_var(n).is_some())
		.cloned()
		.collect();
	let missing: Vec<&String> = include
		.iter()
		.filter(|n| in_ds.get_var(n).is_none())
		.collect();
	if !missing.is_empty() {
		eprintln!("  [warn] requested but not found in input: {:?}", missing);
	}

	// 2. キープする変数が参照している次元名の集合を作る。
	let mut kept_dim_names: std::collections::BTreeSet<String> = Default::default();
	for name in &kept_names {
		let var = in_ds.get_var(name).unwrap();
		for d in var.get_dims() {
			kept_dim_names.insert(d.name());
		}
	}

	// 3. 出力 DataSet を組み立て: dims → global attrs → vars (+ var attrs)
	let mut out_ds = DataSet::new();
	for d in in_ds.get_dims() {
		if !kept_dim_names.contains(&d.name()) {
			continue;
		}
		out_ds
			.add_fixed_dim(d.name(), d.size())
			.map_err(|e| format!("add_fixed_dim {}: {:?}", d.name(), e))?;
	}
	for attr in in_ds.get_global_attrs() {
		copy_global_attr(in_ds, &mut out_ds, attr.name())?;
	}
	for name in &kept_names {
		let var = in_ds.get_var(name).unwrap();
		let dim_names: Vec<String> = var.get_dims().iter().map(|d| d.name()).collect();
		match var.data_type() {
			DataType::I8 => out_ds.add_var_i8(name, &dim_names),
			DataType::U8 => out_ds.add_var_u8(name, &dim_names),
			DataType::I16 => out_ds.add_var_i16(name, &dim_names),
			DataType::I32 => out_ds.add_var_i32(name, &dim_names),
			DataType::F32 => out_ds.add_var_f32(name, &dim_names),
			DataType::F64 => out_ds.add_var_f64(name, &dim_names),
		}
		.map_err(|e| format!("add_var {}: {:?}", name, e))?;

		// var attrs
		if let Some(var_attrs) = in_ds.get_var_attrs(name) {
			let attr_names: Vec<String> = var_attrs.iter().map(|a| a.name().to_string()).collect();
			for attr_name in &attr_names {
				copy_var_attr(in_ds, &mut out_ds, name, attr_name)?;
			}
		}
	}

	println!(
		"  Stripping {} → {} ({} → {} variables, {} dimensions kept)",
		input.display(),
		output.display(),
		in_ds.get_vars().len(),
		kept_names.len(),
		out_ds.get_dims().len()
	);

	// 4. ファイルを書く。データはストリームしながら型ごとに read → write。
	if let Some(parent) = output.parent() {
		std::fs::create_dir_all(parent)
			.map_err(|e| format!("create_dir_all {}: {}", parent.display(), e))?;
	}
	let mut writer = FileWriter::create_new(output)
		.map_err(|e| format!("create_new {}: {:?}", output.display(), e))?;
	writer
		.set_def(&out_ds, Version::Classic, 0)
		.map_err(|e| format!("set_def: {:?}", e))?;
	for name in &kept_names {
		let data = reader
			.read_var(name)
			.map_err(|e| format!("read {}: {:?}", name, e))?;
		// netcdf3::DataVector は型ごとにバリアント。enum マッチで型別 write へ。
		match data {
			netcdf3::DataVector::I8(v) => writer.write_var_i8(name, &v),
			netcdf3::DataVector::U8(v) => writer.write_var_u8(name, &v),
			netcdf3::DataVector::I16(v) => writer.write_var_i16(name, &v),
			netcdf3::DataVector::I32(v) => writer.write_var_i32(name, &v),
			netcdf3::DataVector::F32(v) => writer.write_var_f32(name, &v),
			netcdf3::DataVector::F64(v) => writer.write_var_f64(name, &v),
		}
		.map_err(|e| format!("write {}: {:?}", name, e))?;
	}
	writer.close().map_err(|e| format!("close: {:?}", e))?;
	Ok(())
}

fn copy_global_attr(src: &DataSet, dst: &mut DataSet, name: &str) -> Result<()> {
	let attr = src
		.get_global_attr(name)
		.ok_or_else(|| format!("missing global attr {name}"))?;
	match attr.data_type() {
		DataType::I8 => dst.add_global_attr_i8(name, attr.get_i8().unwrap_or(&[]).to_vec()),
		DataType::U8 => dst.add_global_attr_u8(name, attr.get_u8().unwrap_or(&[]).to_vec()),
		DataType::I16 => dst.add_global_attr_i16(name, attr.get_i16().unwrap_or(&[]).to_vec()),
		DataType::I32 => dst.add_global_attr_i32(name, attr.get_i32().unwrap_or(&[]).to_vec()),
		DataType::F32 => dst.add_global_attr_f32(name, attr.get_f32().unwrap_or(&[]).to_vec()),
		DataType::F64 => dst.add_global_attr_f64(name, attr.get_f64().unwrap_or(&[]).to_vec()),
	}
	.map_err(|e| format!("copy global attr {name}: {:?}", e))?;
	Ok(())
}

fn copy_var_attr(src: &DataSet, dst: &mut DataSet, var_name: &str, attr_name: &str) -> Result<()> {
	let attr = src
		.get_var_attr(var_name, attr_name)
		.ok_or_else(|| format!("missing var attr {var_name}/{attr_name}"))?;
	match attr.data_type() {
		DataType::I8 => dst.add_var_attr_i8(var_name, attr_name, attr.get_i8().unwrap_or(&[]).to_vec()),
		DataType::U8 => dst.add_var_attr_u8(var_name, attr_name, attr.get_u8().unwrap_or(&[]).to_vec()),
		DataType::I16 => dst.add_var_attr_i16(var_name, attr_name, attr.get_i16().unwrap_or(&[]).to_vec()),
		DataType::I32 => dst.add_var_attr_i32(var_name, attr_name, attr.get_i32().unwrap_or(&[]).to_vec()),
		DataType::F32 => dst.add_var_attr_f32(var_name, attr_name, attr.get_f32().unwrap_or(&[]).to_vec()),
		DataType::F64 => dst.add_var_attr_f64(var_name, attr_name, attr.get_f64().unwrap_or(&[]).to_vec()),
	}
	.map_err(|e| format!("copy var attr {var_name}/{attr_name}: {:?}", e))?;
	Ok(())
}
