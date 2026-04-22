//! alphastell — VMEC 由来のステラレータ CAD を生成・検証する CLI。
//!
//! サブコマンド:
//! - `vessel`   : VMEC `wout_*.nc` から 6 層 in-vessel build を STEP として出力
//! - `validate` : 2 つの STEP ファイルの体積と Union 体積を比較し、形状整合を検査
//!
//! 使い方:
//! ```bash
//! # VMEC から 6 層 in-vessel build を STEP 化 (chamber / first_wall / ... / vacuum_vessel)
//! cargo run --release -- vessel \
//!     --input parastell/examples/wout_vmec.nc \
//!     --output out/
//!
//! # Rust 出力と parastell 出力 (1 周期分) を照合
//! cargo run --release -- validate \
//!     out/chamber.step \
//!     parastell/examples/alphastell_full/plasma.step
//! ```
//!
//! モジュール構成:
//! - `vmec`     : VMEC ファイル読み込みと (θ, φ) での (R, Z) 評価
//! - `vessel`   : vessel サブコマンド本体
//! - `validate` : validate サブコマンド本体

mod coils;
mod compound;
mod cut;
mod magnet;
mod plasma;
mod validate;
mod vessel;
mod vmec;

use clap::{Parser, Subcommand};
use std::path::PathBuf;

/// 本クレート共通の Result 型。`Box<dyn Error>` なので !Send なエラー
/// (例: netcdf3 の ReadError) もそのまま保持できる。
pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

#[derive(Parser, Debug)]
#[command(about = "alphastell — VMEC 由来の CAD 生成と検証")]
struct Cli {
	#[command(subcommand)]
	command: Command,
}

#[derive(Subcommand, Debug)]
enum Command {
	/// VMEC `wout_*.nc` から 6 層の in-vessel 構造 (chamber / first_wall / breeder /
	/// back_wall / shield / vacuum_vessel) を生成し、`output` ディレクトリに
	/// 6 つの STEP ファイルとして書き出す。層厚は parastell 例に準拠。
	Vessel {
		#[arg(long)]
		input: PathBuf,
		/// 出力先ディレクトリ (6 枚の *.step ファイルが作成される)。
		#[arg(long)]
		output: PathBuf,
		/// 基準磁束面 wall_s。parastell 既定 1.08 (LCFS の外側に少し広げた面)。
		#[arg(long, default_value_t = 1.08)]
		wall_s: f64,
		/// 単位スケール。VMEC は m なので 100 を掛けると cm になり parastell 既定と揃う。
		#[arg(long, default_value_t = 100.0)]
		scale: f64,
	},
	/// 入力 STEP を Z 軸まわりの扇形 (sector) で切って一部分だけ残した STEP を出力する。
	/// BREP_WITH_VOIDS の内部可視化や、nfp=4 の 1 周期分 (-s 0 -e 1/4) を切り出すのに使える。
	/// 角度は τ (= 2π) を単位とする有理数、形式は `(+|-)?\d+(/\d+)?` のみ。
	/// `--cut` と `--union` のどちらか一方を必須 (両方指定はエラー)。
	#[command(group(
		clap::ArgGroup::new("op")
			.required(true)
			.multiple(false)
			.args(["cut", "union"])
	))]
	Cut {
		/// 切りたい STEP のパス
		#[arg(short = 'i', long)]
		input: PathBuf,
		/// 出力 STEP のパス
		#[arg(short = 'o', long)]
		output: PathBuf,
		/// 扇形の開始角 (τ 単位)。例: "0", "-1/6", "1/3"。既定 0。
		#[arg(short = 's', long, default_value = "0", value_parser = cut::parse_tau_fraction)]
		start: f64,
		/// 扇形の終了角 (τ 単位)。例: "1/3", "1/6", "1/2", "1" (= 1 周・no-op)。
		#[arg(short = 'e', long, value_parser = cut::parse_tau_fraction)]
		end: f64,
		/// 扇形の内側を残す (solid ∩ wedge)。`--union` と排他。
		#[arg(short = 'c', long)]
		cut: bool,
		/// 扇形を除去する (solid - wedge、扇形の外側だけ残す)。`--cut` と排他。
		#[arg(short = 'u', long)]
		union: bool,
	},
	/// `coils.example` から 40 本のフィラメントを読み、長方形断面 sweep で
	/// parastell 互換の magnet_set.step を出力する。座標単位は m。
	Magnet {
		#[arg(long)]
		input: PathBuf,
		#[arg(long)]
		output: PathBuf,
		/// 矩形断面の幅 [m]。既定 0.4 m = 40 cm (parastell 既定と物理寸法一致)
		#[arg(long, default_value_t = 0.4)]
		width: f64,
		/// 矩形断面の厚み [m]。既定 0.5 m = 50 cm
		#[arg(long, default_value_t = 0.5)]
		thickness: f64,
		/// コイル間引き toroidal 範囲 [deg]。360 で全コイル。<360 は将来用 (本 PR では未実装)
		#[arg(long, default_value_t = 360.0)]
		toroidal_extent: f64,
	},
	/// 診断: VMEC LCFS (s=1.0) を複数の (M, N) 解像度で B-spline STEP 化。
	/// `index_rz` 直接 (スプライン補間なし) で、`output` ディレクトリに
	/// `plasma_M<m>_N<n>.step` を一括出力する。
	/// Nyquist aliasing が seam の原因かを resolution 依存で切り分ける用途。
	Plasma {
		#[arg(long)]
		input: PathBuf,
		/// 出力先ディレクトリ (複数の plasma_M*_N*.step が作成される)。
		#[arg(long)]
		output: PathBuf,
		/// 単位スケール。既定 1.0 = m (生 VMEC 単位)。100 で cm。
		#[arg(long, default_value_t = 1.0)]
		scale: f64,
	},
	/// 複数の STEP ファイルを 1 つにまとめ、各ファイルに均等な HSV 色相で
	/// 識別しやすい色を割り当てて出力する。
	/// 例: `compound -i a.step -i b.step -i c.step -o out.step`
	Compound {
		/// 入力 STEP のパス (複数回指定可)
		#[arg(short = 'i', long = "input")]
		inputs: Vec<PathBuf>,
		/// 出力 STEP のパス
		#[arg(short = 'o', long)]
		output: PathBuf,
	},
	/// 2 つの STEP ファイルを体積と Union 体積で照合する。
	Validate {
		/// 比較対象 A (例: out/plasma.step)
		a: PathBuf,
		/// 比較対象 B (例: parastell/examples/alphastell_full/plasma.step)
		b: PathBuf,
		/// 整数比チェックの最大期待値 (既定 4 = nfp)
		#[arg(long, default_value_t = 4)]
		max_ratio: u32,
		/// 相対許容誤差 (既定 1%)
		#[arg(long, default_value_t = 0.01)]
		tol: f64,
		/// Union (boolean) 体積チェックも実行する。大きな STEP では 10 分以上かかる。
		#[arg(long, default_value_t = false)]
		union: bool,
	},
}

fn main() -> Result<()> {
	let cli = Cli::parse();
	match cli.command {
		Command::Vessel {
			input,
			output,
			wall_s,
			scale,
		} => vessel::run(&input, &output, wall_s, scale),
		Command::Cut {
			input,
			output,
			start,
			end,
			cut,
			union,
		} => {
			let mode = if cut {
				cut::Mode::Intersect
			} else {
				debug_assert!(union, "clap ArgGroup guarantees exactly one of --cut / --union");
				cut::Mode::Subtract
			};
			cut::run(&input, &output, start, end, mode)
		}
		Command::Magnet {
			input,
			output,
			width,
			thickness,
			toroidal_extent,
		} => magnet::run(&input, &output, width, thickness, toroidal_extent),
		Command::Plasma {
			input,
			output,
			scale,
		} => plasma::run(&input, &output, scale),
		Command::Compound { inputs, output } => compound::run(&inputs, &output),
		Command::Validate {
			a,
			b,
			max_ratio,
			tol,
			union,
		} => validate::run(&a, &b, max_ratio, tol, union),
	}
}
