//! VMEC の最終閉磁気面 (またはその少し外) を全周サンプリングして STEP に書き出す CLI。
//!
//! 使い方:
//! ```bash
//! cargo run --release -- --input parastell/examples/wout_vmec.nc \
//!                        --output out/chamber.step \
//!                        [--s 1.0]
//! ```
//!
//! 主なモジュール構成:
//! - `vmec` : VMEC ファイル読み込みと (θ, φ) での (R, Z) 評価を担当 (詳細は vmec.rs 参照)
//! - `main` : CLI + 点群生成 + cadrum での B-spline サーフェス化 + STEP 出力

mod vmec;

use anyhow::{Context, Result};
use cadrum::{DVec3, Solid};
use clap::Parser;
use std::f64::consts::TAU;
use std::path::PathBuf;

use vmec::{eval_rz, interp_coeffs_at_s, load_vmec};

/// トーラス方向 (φ 軸) のリブ本数。nfp=4 の倍数にしておくと周期対称性と整合する。
const M_TORO: usize = 240;
/// 断面方向 (θ 軸) のリブ 1 本あたりの点数。parastell の num_rib_pts=61 に近い 2 のべき。
const N_POLO: usize = 64;

#[derive(Parser, Debug)]
#[command(about = "VMEC wout_*.nc から任意 s の磁束面を全周 B-spline STEP に出力")]
struct Args {
	#[arg(long)]
	input: PathBuf,
	#[arg(long)]
	output: PathBuf,
	/// 規格化磁束座標 s。1.0 が LCFS (プラズマの最外縁)、1.08 等で wall_s 相当を評価可。
	#[arg(long, default_value_t = 1.0)]
	s: f64,
}

fn main() -> Result<()> {
	let args = Args::parse();

	// 1. VMEC ファイルを読み込む
	println!("Loading VMEC: {}", args.input.display());
	let vmec = load_vmec(&args.input)?;
	println!(
		"  ns = {}, mnmax = {}, s_max in grid = {}",
		vmec.s_grid.len(),
		vmec.xm.len(),
		vmec.s_grid.last().unwrap()
	);

	// 2. 目的の s での Fourier 係数を内挿で求める (s は以後の処理で「焼き込み」)
	println!("Interpolating Fourier coefficients at s = {}", args.s);
	let (r_at_s, z_at_s) = interp_coeffs_at_s(&vmec, args.s);

	// 3. (φ, θ) グリッドを走査して 3D 点群を作る
	//    std::array::from_fn でコンパイル時固定サイズの 2D 配列を直接 populate
	//    (cadrum の Solid::bspline は const-generic 配列を要求する)
	println!("Building {} x {} grid over full torus...", M_TORO, N_POLO);
	let grid: [[DVec3; N_POLO]; M_TORO] = std::array::from_fn(|i| {
		// トーラス周方向の角度 φ。全周 [0, 2π) を M_TORO 等分 (endpoint を含めず開区間)
		let phi = TAU * (i as f64) / (M_TORO as f64);
		let (sinp, cosp) = phi.sin_cos();
		std::array::from_fn(|j| {
			// 断面方向の角度 θ。同じく [0, 2π) 開区間
			let theta = TAU * (j as f64) / (N_POLO as f64);
			// VMEC は円柱座標 (R, Z, φ) で値を返すので直交座標 (x, y, z) に変換
			let (r, z) = eval_rz(&r_at_s, &z_at_s, &vmec.xm, &vmec.xn, theta, phi);
			DVec3::new(r * cosp, r * sinp, z)
		})
	});

	// 4. 点群から cadrum の B-spline サーフェスを構築
	//    periodic=true で両方向 (poloidal, toroidal) を閉曲面として閉じる
	println!("Constructing B-spline solid via cadrum...");
	let solid = Solid::bspline(grid, true)
		.map_err(|e| anyhow::anyhow!("cadrum bspline failed: {:?}", e))?;

	// 5. 出力ディレクトリを作成 (必要なら)
	if let Some(parent) = args.output.parent() {
		if !parent.as_os_str().is_empty() {
			std::fs::create_dir_all(parent)
				.with_context(|| format!("create_dir_all {}", parent.display()))?;
		}
	}

	// 6. STEP ファイルに書き出し
	println!("Writing STEP: {}", args.output.display());
	let mut f = std::fs::File::create(&args.output)
		.with_context(|| format!("create {}", args.output.display()))?;
	cadrum::write_step(&[solid.color("cyan")], &mut f)
		.map_err(|e| anyhow::anyhow!("write_step failed: {:?}", e))?;

	println!("Done.");
	Ok(())
}
