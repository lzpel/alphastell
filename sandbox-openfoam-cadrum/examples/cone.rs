//! 環状の先細流路 (cone − cylinder の boolean 差) の MHD ケース生成。
//!
//! Solid の内側 = 流体領域。外形の円錐台から内棒(円柱)が占める空間をくり抜いた
//! ドーナツ断面の流路で、面の色が境界条件になる:
//!   緑 = 流入 (x=0 の環)、橙 = 流出 (x=L の環)、灰 = 壁 (外円錐面・内円柱面)
//!
//! 格子は (θ, r, x) の構造格子。θ 方向は B-rep に対応する面が無い「縫い目」を
//! 境界にせず、ラップ接続の内部面として扱う (cyclic パッチ不要)。
//!
//! 出力:
//!   cone/constant/polyMesh/…  cone/0/{U,p,PotE}
//!   out/geometry_cone.step  out/geometry_cone.png
//!
//! 実行: cargo run --release --example cone

use cadrum::{Color, DVec3, SceneOption, Solid};
use hartmann_case::{
    color_at, graded, write_case_fields, write_polymesh, BoundaryFace, InternalFace, PatchDef,
    COL_INLET, COL_OUTLET, COL_WALL,
};
use std::fs;

// ---- 形状 (軸 = x) ----
const LEN: f64 = 5.0; // 流路長
const R_OUT0: f64 = 2.0; // 外半径 (入口)
const R_OUT1: f64 = 1.2; // 外半径 (出口) — 先細
const R_IN: f64 = 0.6; // 内棒半径 (一定)

// ---- 格子 ----
const NTH: usize = 48; // θ 分割 (ラップ接続)
const NR: usize = 16; // 半径方向 (両側グレーディング)
const NX: usize = 50; // 軸方向
const EXPANSION: f64 = 4.0; // 壁→中央のセル幅拡大率

const PATCHES: [PatchDef; 3] = [
    PatchDef { name: "inlet", kind: "patch", neighbour: None, u: "fixedValue;\n        value           uniform (1 0 0)", p: "zeroGradient", pot_e: "zeroGradient" },
    PatchDef { name: "outlet", kind: "patch", neighbour: None, u: "zeroGradient", p: "fixedValue;\n        value           uniform 0", pot_e: "zeroGradient" },
    PatchDef { name: "walls", kind: "wall", neighbour: None, u: "noSlip", p: "zeroGradient", pot_e: "zeroGradient" },
];

fn patch_of(color: Color) -> &'static str {
    if color == Color::from(COL_INLET) {
        "inlet"
    } else if color == Color::from(COL_OUTLET) {
        "outlet"
    } else if color == Color::from(COL_WALL) {
        "walls"
    } else {
        panic!("unpainted face color: {color:?}")
    }
}

/// 外半径 (x に線形)
fn r_out(x: f64) -> f64 {
    R_OUT0 + (R_OUT1 - R_OUT0) * x / LEN
}

/// 環状先細ダクトを boolean 差で作り、面ごとにプローブ点で同定して色を塗る
fn build_colored_duct() -> Result<Solid, cadrum::Error> {
    let outer = Solid::cone(R_OUT0, R_OUT1, DVec3::X * LEN);
    let inner = Solid::cylinder(R_IN, DVec3::X * LEN);
    let mut duct = (&outer - &inner).build()?;

    // 各境界面上に確実に載るプローブ点 → 色
    let r_mid_in = (R_IN + R_OUT0) / 2.0;
    let r_mid_out = (R_IN + R_OUT1) / 2.0;
    let probes: [(DVec3, &str); 4] = [
        (DVec3::new(0.0, r_mid_in, 0.0), COL_INLET),           // 入口環 (x=0)
        (DVec3::new(LEN, r_mid_out, 0.0), COL_OUTLET),         // 出口環 (x=L)
        (DVec3::new(LEN / 2.0, R_IN, 0.0), COL_WALL),          // 内円柱面
        (DVec3::new(LEN / 2.0, r_out(LEN / 2.0), 0.0), COL_WALL), // 外円錐面
    ];
    let paint: Vec<(u64, Color)> = hartmann_case::with_silent_panics(|| {
        duct.iter_face()
            .map(|f| {
                let color = probes
                    .iter()
                    .find(|(p, _)| {
                        // トリム外射影でパニックする組はスキップ (該当プローブは必ず成功)
                        hartmann_case::try_project_distance(f, *p).is_some_and(|d| d < 1e-6)
                    })
                    .map(|(_, c)| *c)
                    .unwrap_or_else(|| panic!("face {} matches no probe", f.id()));
                (f.id(), Color::from(color))
            })
            .collect()
    });
    for (id, c) in paint {
        duct.colormap_mut().insert(id, c);
    }
    Ok(duct)
}

// 点番号: θ は nθ 個で重複なし (ラップ)、r は NR+1、x は NX+1
fn pid(it: usize, jr: usize, ix: usize) -> usize {
    (it % NTH) + NTH * (jr + (NR + 1) * ix)
}

fn cid(it: usize, jr: usize, ix: usize) -> usize {
    it + NTH * (jr + NR * ix)
}

fn main() -> Result<(), cadrum::Error> {
    let duct = build_colored_duct()?;

    // ---- CAD 出力 ----
    fs::create_dir_all("out").unwrap();
    Solid::write_step([&duct], &mut fs::File::create("out/geometry_cone.step").unwrap())?;
    let mesh = Solid::mesh([&duct], Default::default())?;
    let scene = mesh.scene(SceneOption {
        view: DVec3::new(-1.0, 1.2, 0.8),
        up: DVec3::Z,
        ..Default::default()
    });
    scene.write_png([1280, 720], &mut fs::File::create("out/geometry_cone.png").unwrap())?;

    // ---- 節点: (x, r cosθ, r sinθ)。r は内外壁両側グレーディングの無次元列 t を半径に写像 ----
    let xs: Vec<f64> = (0..=NX).map(|i| LEN * i as f64 / NX as f64).collect();
    let half = graded(0.0, 0.5, NR / 2, EXPANSION);
    let mut ts = half.clone();
    for j in (0..NR / 2).rev() {
        ts.push(1.0 - half[j]);
    }
    let thetas: Vec<f64> = (0..NTH).map(|k| 2.0 * std::f64::consts::PI * k as f64 / NTH as f64).collect();
    let mut points = vec![DVec3::ZERO; NTH * (NR + 1) * (NX + 1)];
    for ix in 0..=NX {
        let ro = r_out(xs[ix]);
        for jr in 0..=NR {
            let r = R_IN + ts[jr] * (ro - R_IN);
            for it in 0..NTH {
                points[pid(it, jr, ix)] = DVec3::new(xs[ix], r * thetas[it].cos(), r * thetas[it].sin());
            }
        }
    }

    // ---- 内部面: セル昇順、各セルの高インデックス隣接を neighbour 昇順で emit ----
    // 隣接候補: +θ (c+1)、θラップ (c+NTH-1, iθ=0 のみ)、+r (c+NTH)、+x (c+NTH*NR)
    // この順は常に昇順なのでソート不要。面の向きは owner→neighbour。
    let mut internal: Vec<InternalFace> = Vec::new();
    for ix in 0..NX {
        for jr in 0..NR {
            for it in 0..NTH {
                let c = cid(it, jr, ix);
                if it + 1 < NTH {
                    // +θ 面 (θ_{it+1} 平面): x→r の順で +e_θ 向き
                    internal.push((
                        [pid(it + 1, jr, ix), pid(it + 1, jr, ix + 1), pid(it + 1, jr + 1, ix + 1), pid(it + 1, jr + 1, ix)],
                        c,
                        cid(it + 1, jr, ix),
                    ));
                }
                if it == 0 && NTH > 2 {
                    // θ ラップ面 (θ=0 平面): owner=iθ0, neighbour=iθ_{NTH-1}, 向きは −e_θ (r→x の順)
                    internal.push((
                        [pid(0, jr, ix), pid(0, jr + 1, ix), pid(0, jr + 1, ix + 1), pid(0, jr, ix + 1)],
                        c,
                        cid(NTH - 1, jr, ix),
                    ));
                }
                if jr + 1 < NR {
                    // +r 面 (r_{jr+1} 面): θ→x の順で +e_r 向き
                    internal.push((
                        [pid(it, jr + 1, ix), pid(it + 1, jr + 1, ix), pid(it + 1, jr + 1, ix + 1), pid(it, jr + 1, ix + 1)],
                        c,
                        cid(it, jr + 1, ix),
                    ));
                }
                if ix + 1 < NX {
                    // +x 面: r→θ の順で +e_x 向き
                    internal.push((
                        [pid(it, jr, ix + 1), pid(it, jr + 1, ix + 1), pid(it + 1, jr + 1, ix + 1), pid(it + 1, jr, ix + 1)],
                        c,
                        cid(it, jr, ix + 1),
                    ));
                }
            }
        }
    }

    // ---- 境界面 ----
    let mut boundary: Vec<BoundaryFace> = Vec::new();
    for jr in 0..NR {
        for it in 0..NTH {
            // 入口 (x=0): θ→r の順で −e_x 向き
            boundary.push(BoundaryFace {
                quad: [pid(it, jr, 0), pid(it + 1, jr, 0), pid(it + 1, jr + 1, 0), pid(it, jr + 1, 0)],
                owner: cid(it, jr, 0),
                outward: -DVec3::X,
            });
            // 出口 (x=NX): r→θ の順で +e_x 向き
            boundary.push(BoundaryFace {
                quad: [pid(it, jr, NX), pid(it, jr + 1, NX), pid(it + 1, jr + 1, NX), pid(it + 1, jr, NX)],
                owner: cid(it, jr, NX - 1),
                outward: DVec3::X,
            });
        }
    }
    for ix in 0..NX {
        for it in 0..NTH {
            // 内壁 (jr=0): x→θ の順で −e_r 向き
            boundary.push(BoundaryFace {
                quad: [pid(it, 0, ix), pid(it, 0, ix + 1), pid(it + 1, 0, ix + 1), pid(it + 1, 0, ix)],
                owner: cid(it, 0, ix),
                outward: DVec3::ZERO, // 分類は色のみで行う
            });
            // 外壁 (jr=NR): θ→x の順で +e_r 向き
            boundary.push(BoundaryFace {
                quad: [pid(it, NR, ix), pid(it + 1, NR, ix), pid(it + 1, NR, ix + 1), pid(it, NR, ix + 1)],
                owner: cid(it, NR - 1, ix),
                outward: DVec3::ZERO,
            });
        }
    }

    // ---- 分類: 面中心を B-rep へ射影して色を読み戻す (曲面の弦誤差ぶん tol を緩める) ----
    let mut per_patch: Vec<(&str, Vec<BoundaryFace>)> =
        PATCHES.iter().map(|p| (p.name, Vec::new())).collect();
    for f in boundary {
        let center = f.quad.iter().fold(DVec3::ZERO, |acc, &q| acc + points[q]) / 4.0;
        let name = patch_of(color_at(&duct, center, 0.05));
        per_patch.iter_mut().find(|(n, _)| *n == name).unwrap().1.push(f);
    }
    for (name, faces) in &per_patch {
        assert!(!faces.is_empty(), "patch {name} got no faces");
    }

    write_polymesh("cone/constant/polyMesh", &points, &internal, &per_patch, &PATCHES, NTH * NR * NX).unwrap();
    write_case_fields("cone", &PATCHES).unwrap();

    let area_in = std::f64::consts::PI * (R_OUT0 * R_OUT0 - R_IN * R_IN);
    let area_out = std::f64::consts::PI * (R_OUT1 * R_OUT1 - R_IN * R_IN);
    println!(
        "cone generated: {} points, {} cells, {} internal faces; patches: {}; area ratio in/out = {:.4}",
        points.len(),
        NTH * NR * NX,
        internal.len(),
        per_patch.iter().map(|(n, v)| format!("{n}:{}", v.len())).collect::<Vec<_>>().join(" "),
        area_in / area_out
    );
    Ok(())
}
