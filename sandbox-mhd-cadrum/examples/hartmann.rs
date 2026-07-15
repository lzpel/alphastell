//! Hartmann 流ケース: 色付きの箱 (Solid の内側 = 流体領域) から OpenFOAM ケースを生成。
//!
//!   緑 = 流入 (inlet)、橙 = 流出 (outlet)、灰 = 壁 (粘着・電気的絶縁)、青 = z 周期 (cyclic)
//!
//! 出力:
//!   hartmann/constant/polyMesh/{points,faces,owner,neighbour,boundary}
//!   hartmann/0/{U,p,PotE}
//!   results/geometry.step  results/geometry.png  (色=境界条件の可視化)
//!
//! 実行: cargo run --release --example hartmann

use cadrum::{Color, DVec3, SceneOption, Solid};
use hartmann_case::{
    color_at, graded, write_case_fields, write_polymesh, BoundaryFace, InternalFace, PatchDef,
    COL_CYCLIC, COL_INLET, COL_OUTLET, COL_WALL,
};
use std::fs;

// ---- 領域と格子 (sandbox-mhd の blockMeshDict と同一) ----
const X: [f64; 2] = [0.0, 10.0];
const Y: [f64; 2] = [-1.0, 1.0];
const Z: [f64; 2] = [0.0, 0.1];
const NX: usize = 50;
const NY: usize = 80; // 両側グレーディング (半区間 40 セル・拡大率 8)
const NZ: usize = 1;
const EXPANSION: f64 = 8.0; // 壁→中心のセル幅拡大率。第1セル高さ ≈ 0.0074

/// パッチ出力順 (polyMesh boundary と 0/ の boundaryField で共通)
const PATCHES: [PatchDef; 5] = [
    PatchDef { name: "inlet", kind: "patch", neighbour: None, u: "fixedValue;\n        value           uniform (1 0 0)", p: "zeroGradient", pot_e: "zeroGradient" },
    PatchDef { name: "outlet", kind: "patch", neighbour: None, u: "zeroGradient", p: "fixedValue;\n        value           uniform 0", pot_e: "zeroGradient" },
    PatchDef { name: "walls", kind: "wall", neighbour: None, u: "noSlip", p: "zeroGradient", pot_e: "zeroGradient" },
    PatchDef { name: "back", kind: "cyclic", neighbour: Some("front"), u: "cyclic", p: "cyclic", pot_e: "cyclic" },
    PatchDef { name: "front", kind: "cyclic", neighbour: Some("back"), u: "cyclic", p: "cyclic", pot_e: "cyclic" },
];

/// 色 + 外向き法線からパッチ名を決める (青は法線の z 符号で cyclic ペアを振り分け)
fn patch_of(color: Color, outward: DVec3) -> &'static str {
    if color == Color::from(COL_INLET) {
        "inlet"
    } else if color == Color::from(COL_OUTLET) {
        "outlet"
    } else if color == Color::from(COL_WALL) {
        "walls"
    } else if color == Color::from(COL_CYCLIC) {
        if outward.z < 0.0 { "back" } else { "front" }
    } else {
        panic!("unpainted face color: {color:?}")
    }
}

/// 箱を作り、6 面を外向き法線で同定して色を塗る
fn build_colored_box() -> Solid {
    let mut solid = Solid::cube(
        DVec3::new(X[0], Y[0], Z[0]),
        DVec3::new(X[1], Y[1], Z[1]),
    );
    let center = solid.center();
    let paint: Vec<(u64, Color)> = solid
        .iter_face()
        .map(|f| {
            let (_, normal) = f.project(center); // 面中心近傍の外向き法線
            let color = if normal.x.abs() > 0.9 {
                if normal.x < 0.0 { COL_INLET } else { COL_OUTLET }
            } else if normal.y.abs() > 0.9 {
                COL_WALL
            } else {
                COL_CYCLIC
            };
            (f.id(), Color::from(color))
        })
        .collect();
    for (id, c) in paint {
        solid.colormap_mut().insert(id, c);
    }
    solid
}

fn pid(i: usize, j: usize, k: usize) -> usize {
    i + (NX + 1) * (j + (NY + 1) * k)
}

fn cid(i: usize, j: usize, k: usize) -> usize {
    i + NX * (j + NY * k)
}

fn main() -> Result<(), cadrum::Error> {
    let solid = build_colored_box();

    // ---- CAD 出力 (STEP + PNG レンダリング: 色=境界条件の可視化) ----
    fs::create_dir_all("results").unwrap();
    Solid::write_step([&solid], &mut fs::File::create("results/geometry.step").unwrap())?;
    let mesh = Solid::mesh([&solid], Default::default())?;
    let scene = mesh.scene(SceneOption {
        view: DVec3::new(-1.0, 1.6, 0.9),
        up: DVec3::Z,
        ..Default::default()
    });
    scene.write_png([1280, 720], &mut fs::File::create("results/geometry.png").unwrap())?;

    // ---- 節点 (y は両側マルチグレーディング: 下半分を graded、上半分は鏡映) ----
    let xs: Vec<f64> = (0..=NX).map(|i| X[0] + (X[1] - X[0]) * i as f64 / NX as f64).collect();
    let half = graded(Y[0], 0.0, NY / 2, EXPANSION);
    let mut ys = half.clone();
    for j in (0..NY / 2).rev() {
        ys.push(-half[j]);
    }
    let zs: Vec<f64> = (0..=NZ).map(|k| Z[0] + (Z[1] - Z[0]) * k as f64 / NZ as f64).collect();
    let mut points = Vec::with_capacity((NX + 1) * (NY + 1) * (NZ + 1));
    for k in 0..=NZ {
        for j in 0..=NY {
            for i in 0..=NX {
                points.push(DVec3::new(xs[i], ys[j], zs[k])); // 並びは pid() と一致 (i が最内)
            }
        }
    }

    // ---- 内部面: セル昇順、各セルから +x, +y, +z 隣接の順 (upper-triangular) ----
    let mut internal: Vec<InternalFace> = Vec::new();
    for k in 0..NZ {
        for j in 0..NY {
            for i in 0..NX {
                let c = cid(i, j, k);
                if i + 1 < NX {
                    // 法線 +x = owner→neighbour
                    internal.push((
                        [pid(i + 1, j, k), pid(i + 1, j + 1, k), pid(i + 1, j + 1, k + 1), pid(i + 1, j, k + 1)],
                        c,
                        cid(i + 1, j, k),
                    ));
                }
                if j + 1 < NY {
                    // 法線 +y
                    internal.push((
                        [pid(i, j + 1, k), pid(i, j + 1, k + 1), pid(i + 1, j + 1, k + 1), pid(i + 1, j + 1, k)],
                        c,
                        cid(i, j + 1, k),
                    ));
                }
                if k + 1 < NZ {
                    // 法線 +z
                    internal.push((
                        [pid(i, j, k + 1), pid(i + 1, j, k + 1), pid(i + 1, j + 1, k + 1), pid(i, j + 1, k + 1)],
                        c,
                        cid(i, j, k + 1),
                    ));
                }
            }
        }
    }

    // ---- 境界面 (外向き法線)。cyclic ペアは back/front を同一 (j,i) 順で生成し面順序を対応させる ----
    let mut boundary: Vec<BoundaryFace> = Vec::new();
    for k in 0..NZ {
        for j in 0..NY {
            boundary.push(BoundaryFace { quad: [pid(0, j, k), pid(0, j, k + 1), pid(0, j + 1, k + 1), pid(0, j + 1, k)], owner: cid(0, j, k), outward: -DVec3::X });
            boundary.push(BoundaryFace { quad: [pid(NX, j, k), pid(NX, j + 1, k), pid(NX, j + 1, k + 1), pid(NX, j, k + 1)], owner: cid(NX - 1, j, k), outward: DVec3::X });
        }
    }
    for k in 0..NZ {
        for i in 0..NX {
            boundary.push(BoundaryFace { quad: [pid(i, 0, k), pid(i + 1, 0, k), pid(i + 1, 0, k + 1), pid(i, 0, k + 1)], owner: cid(i, 0, k), outward: -DVec3::Y });
            boundary.push(BoundaryFace { quad: [pid(i, NY, k), pid(i, NY, k + 1), pid(i + 1, NY, k + 1), pid(i + 1, NY, k)], owner: cid(i, NY - 1, k), outward: DVec3::Y });
        }
    }
    for j in 0..NY {
        for i in 0..NX {
            boundary.push(BoundaryFace { quad: [pid(i, j, 0), pid(i, j + 1, 0), pid(i + 1, j + 1, 0), pid(i + 1, j, 0)], owner: cid(i, j, 0), outward: -DVec3::Z });
        }
    }
    for j in 0..NY {
        for i in 0..NX {
            boundary.push(BoundaryFace { quad: [pid(i, j, NZ), pid(i + 1, j, NZ), pid(i + 1, j + 1, NZ), pid(i, j + 1, NZ)], owner: cid(i, j, NZ - 1), outward: DVec3::Z });
        }
    }

    // ---- 分類: 面中心を B-rep へ射影して色を読み戻す ----
    let mut per_patch: Vec<(&str, Vec<BoundaryFace>)> =
        PATCHES.iter().map(|p| (p.name, Vec::new())).collect();
    for f in boundary {
        let center = f.quad.iter().fold(DVec3::ZERO, |acc, &q| acc + points[q]) / 4.0;
        let name = patch_of(color_at(&solid, center, 1e-6), f.outward);
        per_patch.iter_mut().find(|(n, _)| *n == name).unwrap().1.push(f);
    }
    for (name, faces) in &per_patch {
        assert!(!faces.is_empty(), "patch {name} got no faces");
    }

    write_polymesh("hartmann/constant/polyMesh", &points, &internal, &per_patch, &PATCHES, NX * NY * NZ).unwrap();
    write_case_fields("hartmann", &PATCHES).unwrap();

    println!(
        "hartmann generated: {} points, {} cells, {} internal faces; patches: {}",
        points.len(),
        NX * NY * NZ,
        internal.len(),
        per_patch.iter().map(|(n, v)| format!("{n}:{}", v.len())).collect::<Vec<_>>().join(" ")
    );
    Ok(())
}
