//! alphastell — VMEC 由来のステラレータ CAD を生成・検証する CLI。
//!
//! サブコマンド:
//! - `generate` : VMEC `wout_*.nc` から任意の磁束面 s を全周 B-spline STEP として出力
//! - `validate` : 2 つの STEP ファイルの体積と Union 体積を比較し、形状整合を検査
//!
//! 使い方:
//! ```bash
//! # VMEC から LCFS (s=1.0) を全周で STEP 化
//! cargo run --release -- generate \
//!     --input parastell/examples/wout_vmec.nc \
//!     --output out/plasma.step
//!
//! # Rust 出力と parastell 出力 (1 周期分) を照合
//! cargo run --release -- validate \
//!     out/plasma.step \
//!     parastell/examples/alphastell_full/plasma.step
//! ```
//!
//! モジュール構成:
//! - `vmec`     : VMEC ファイル読み込みと (θ, φ) での (R, Z) 評価
//! - `generate` : generate サブコマンド本体
//! - `validate` : validate サブコマンド本体

mod coils;
mod cut;
mod generate;
mod magnet;
mod validate;
mod vmec;

use anyhow::Result;
use clap::{Parser, Subcommand};
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(about = "alphastell — VMEC 由来の CAD 生成と検証")]
struct Cli {
	#[command(subcommand)]
	command: Command,
}

#[derive(Subcommand, Debug)]
enum Command {
	/// VMEC `wout_*.nc` から磁束面を全周 B-spline STEP として出力する。
	Generate {
		#[arg(long)]
		input: PathBuf,
		#[arg(long)]
		output: PathBuf,
		/// 規格化磁束座標 s。1.0 が LCFS、1.08 等で wall_s 相当を評価可能。
		#[arg(long, default_value_t = 1.0)]
		s: f64,
		/// 単位スケール。VMEC は m なので 100 を掛けると cm になり parastell 既定と揃う。
		#[arg(long, default_value_t = 100.0)]
		scale: f64,
		/// 殻の厚み。0 なら単一 solid (chamber / plasma)、>0 なら法線方向に
		/// オフセットして殻 (first_wall など) を生成。単位は scale と同じ (= cm)。
		#[arg(long, default_value_t = 0.0)]
		thickness: f64,
	},
	/// 入力 STEP を Z 軸まわりのウェッジで切って片側/一部分だけ残した STEP を出力する。
	/// BREP_WITH_VOIDS の内部可視化や、nfp=4 の 1 周期分を切り出すのに使える。
	Cut {
		/// 切りたい STEP のパス
		input: PathBuf,
		/// 出力 STEP のパス
		output: PathBuf,
		/// Z 軸まわりの N 等分ウェッジ。1 = no-op、2 = 半分 (単一 halfspace)、
		/// 4 = 1/4 周期 (nfp=4 の 1 field period)、6 = 1/6 等。
		#[arg(long, default_value_t = 2)]
		div: u32,
	},
	/// `coils.example` から 40 本のフィラメントを読み、長方形断面 sweep で
	/// parastell 互換の magnet_set.step を出力する。座標単位は mm。
	Magnet {
		#[arg(long)]
		input: PathBuf,
		#[arg(long)]
		output: PathBuf,
		/// 矩形断面の幅 [mm]。既定 400 mm = 40 cm (parastell 既定と物理寸法一致)
		#[arg(long, default_value_t = 400.0)]
		width: f64,
		/// 矩形断面の厚み [mm]。既定 500 mm = 50 cm
		#[arg(long, default_value_t = 500.0)]
		thickness: f64,
		/// コイル間引き toroidal 範囲 [deg]。360 で全コイル。<360 は将来用 (本 PR では未実装)
		#[arg(long, default_value_t = 360.0)]
		toroidal_extent: f64,
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
		Command::Generate {
			input,
			output,
			s,
			scale,
			thickness,
		} => generate::run(&input, &output, s, scale, thickness),
		Command::Cut {
			input,
			output,
			div,
		} => cut::run(&input, &output, div),
		Command::Magnet {
			input,
			output,
			width,
			thickness,
			toroidal_extent,
		} => magnet::run(&input, &output, width, thickness, toroidal_extent),
		Command::Validate {
			a,
			b,
			max_ratio,
			tol,
			union,
		} => validate::run(&a, &b, max_ratio, tol, union),
	}
}
