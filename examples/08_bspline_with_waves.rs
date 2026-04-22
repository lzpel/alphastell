//! 08_bspline.rs を VMEC LCFS 風の Fourier stack に書き換えた再現実験。
//!
//! 目的: `Solid::bspline(grid, true)` が内部で使う
//! `GeomAPI_PointsToBSplineSurface::Interpolate` + `SetUPeriodic` パイプラインが
//! **phi=0/2π 付近で C⁰ は揃うが C¹ が揃わない surface を生成する**ことを
//! 最小構成で示す。Interpolate は not-a-knot 端条件で cubic fit し、
//! その後 SetUPeriodic が値を一致させるが導関数は周期化されない、という構造的問題。
//!
//! 再現方法: bean 型 cross-section + nfp=4 helical twist を持つ surface
//! (VMEC LCFS 上位 6 モード相当) を M=48 grid で与え、
//! `out/08_bspline_with_waves.{step,stl,svg}` を書き出す。
//! 結果の **STL を Meshlab 等で開いて phi=0 付近を拡大する**と、
//! 三角形メッシュに数 mm 級の dent (凹み) が出ているのが確認できる。
//! STL なので viewer 固有の parameter-line 描画は混入しない。
//!
//! 比較対照: 同 M=48 の `08_bspline.step` は n ≤ 2 しか持たず dent なし。
//! 本例で dent が出れば、問題は「高次周波ではなく、Interpolate+SetUPeriodic の
//! 組み合わせが周期 C¹ を保証しないこと」に帰着する。

use cadrum::{DVec3, Solid};
use std::f64::consts::TAU;

// 08_bspline.rs と同じ解像度・scale で揃える。
const M: usize = 48;
const N: usize = 24;

// phi sampling の開始点を π/4 = 45° ずらす。phi=0 は nfp=4 対称軸 + (m=0, n) 系
// モードの極値が重なる特異点で、cubic fit の境界条件が「綺麗に決まりすぎる」
// ため問題が再現しない可能性がある。π/4 は nfp=4 対称面の中間なので最も非対称。
const PHI_OFFSET: f64 = std::f64::consts::FRAC_PI_4;

// 前半: VMEC `wout_vmec.nc` の s=1.0 (LCFS) 上位モードで bean 型 cross-section を組む。
// 後半: **意図的に VMEC 実測より 5〜100 倍増幅した高周波モード**をスタックして fit を荒らす。
// xn = n·nfp = 4n 慣例 (本当の toroidal 番号は n/4)。
const RMNC: &[(f64, f64, f64)] = &[
	// --- 実 VMEC モード (bean 型 cross-section) ---
	(0.0, 0.0, 11.06),   // major radius
	(1.0, 0.0, 1.89),    // elongation
	(0.0, 4.0, 1.53),    // nfp=4 undulation
	(1.0, -4.0, -1.39),  // primary helical twist
	(1.0, 4.0, 0.58),    // secondary helical
	(2.0, -4.0, 0.26),   // bean tip
	// --- 高周波刺激 (dent を出す最小限の振幅に調整) ---
	(3.0, -8.0, 0.12),
	(4.0, -8.0, 0.10),
	(4.0, -12.0, 0.08),
	(5.0, -12.0, 0.07),
	(6.0, -16.0, 0.06),
	(8.0, -24.0, 0.05),
	(10.0, -32.0, 0.04),
	(3.0, 8.0, 0.08),
	(6.0, 16.0, 0.06),
];
const ZMNS: &[(f64, f64, f64)] = &[
	(1.0, 0.0, 1.94),
	(0.0, 4.0, 1.24),
	(1.0, -4.0, 0.67),
	(1.0, 4.0, 0.53),
	(2.0, -4.0, 0.04),
	(3.0, -8.0, 0.10),
	(4.0, -8.0, 0.08),
	(4.0, -12.0, 0.07),
	(5.0, -12.0, 0.06),
	(6.0, -16.0, 0.06),
	(8.0, -24.0, 0.05),
	(10.0, -32.0, 0.04),
	(3.0, 8.0, 0.07),
	(6.0, 16.0, 0.05),
];

fn point(i: usize, j: usize) -> DVec3 {
	let phi = TAU * (i as f64) / (M as f64) + PHI_OFFSET;
	let theta = TAU * (j as f64) / (N as f64);

	let mut r = 0.0;
	for &(m, n, amp) in RMNC {
		r += amp * (m * theta - n * phi).cos();
	}
	let mut z = 0.0;
	for &(m, n, amp) in ZMNS {
		z += amp * (m * theta - n * phi).sin();
	}

	let (sp, cp) = phi.sin_cos();
	DVec3::new(r * cp, r * sp, z)
}

fn main() {
	let example_name = "out/".to_string()
		+ std::path::Path::new(file!()).file_stem().unwrap().to_str().unwrap();

	let grid: [[DVec3; N]; M] = std::array::from_fn(|i| std::array::from_fn(|j| point(i, j)));
	let plasma = Solid::bspline(grid, true).expect("bspline with VMEC-like modes should succeed");
	let objects = [plasma.color("cyan")];

	let mut f = std::fs::File::create(format!("{example_name}.step")).unwrap();
	cadrum::write_step(&objects, &mut f).unwrap();

	// STL — viewer 依存を完全排除した tessellation ダンプ。
	// phi=0 付近に dent が出るか Meshlab 等で確認する用。
	let mut fstl = std::fs::File::create(format!("{example_name}.stl")).unwrap();
	cadrum::mesh(&objects, 0.1)
		.and_then(|m| m.write_stl(&mut fstl))
		.unwrap();

	let mut fsvg = std::fs::File::create(format!("{example_name}.svg")).unwrap();
	cadrum::mesh(&objects, 0.1)
		.and_then(|m| m.write_svg(DVec3::new(0.05, 0.05, 1.0), false, true, &mut fsvg))
		.unwrap();

	println!(
		"wrote {example_name}.{{step,stl,svg}}  (M={M}, N={N}, {} rmnc + {} zmns modes)",
		RMNC.len(),
		ZMNS.len()
	);
}
