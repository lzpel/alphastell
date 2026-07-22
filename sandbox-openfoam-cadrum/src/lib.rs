//! 色付き cadrum::Solid から OpenFOAM ケースを生成する共通ツールキット。
//!
//! - Solid の内側 = 流体領域。面の色が境界条件の単一情報源
//! - 格子境界面の中心を B-rep へ射影して最近接面の色を読み戻す (`color_at`)
//! - polyMesh writer (`write_polymesh`) と 0/ フィールド writer (`write_field`)
//!
//! 使い方は examples/hartmann.rs (箱) と examples/cone.rs (環状先細ダクト) を参照。

use cadrum::{Color, DVec3, Solid};
use std::fs;

// ---- 色 → 境界条件の色定数 (examples 共通) ----
pub const COL_INLET: &str = "#2ca02c"; // 緑
pub const COL_OUTLET: &str = "#ff7f0e"; // 橙
pub const COL_WALL: &str = "#7f7f7f"; // 灰
pub const COL_CYCLIC: &str = "#1f77b4"; // 青

/// パッチ定義。polyMesh boundary と 0/ boundaryField の出力順はこのリスト順。
pub struct PatchDef {
    pub name: &'static str,
    pub kind: &'static str,              // boundary の type: patch | wall | cyclic
    pub neighbour: Option<&'static str>, // cyclic の相手
    pub u: &'static str,
    pub p: &'static str,
    pub pot_e: &'static str,
}

/// 格子境界面 (quad は点番号4つ、outward は外向き法線)
pub struct BoundaryFace {
    pub quad: [usize; 4],
    pub owner: usize,
    pub outward: DVec3,
}

/// 内部面: (quad, owner, neighbour)。owner < neighbour、法線は owner→neighbour。
pub type InternalFace = ([usize; 4], usize, usize);

/// パニックを黙らせて f を実行する (探索ループ用)。
/// cadrum 0.8.15 の Face::project は最近点が面のトリム境界上に落ちると
/// BRepExtrema_ExtPF 失敗でパニックする既知問題があるため、
/// 「その面は候補から外す」目的で catch する。
pub fn with_silent_panics<T>(f: impl FnOnce() -> T) -> T {
    let prev = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {}));
    let r = f();
    std::panic::set_hook(prev);
    r
}

/// Face::project の距離。トリム境界に落ちてパニックする面は None。
pub fn try_project_distance(f: &cadrum::Face, p: DVec3) -> Option<f64> {
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let (closest, _) = f.project(p);
        (closest - p).length()
    }))
    .ok()
}

/// 点を B-rep へ射影し、最近接面の色を読み戻す。
/// tol: 面中心が B-rep 上に載っているとみなす許容距離
/// (平面なら 1e-6、多角形近似した曲面なら弦誤差ぶん緩める)。
pub fn color_at(solid: &Solid, point: DVec3, tol: f64) -> Color {
    let best = with_silent_panics(|| {
        let mut best: Option<(f64, u64)> = None;
        for f in solid.iter_face() {
            // 射影が面のトリム外に落ちる面はスキップ (最近接面は必ず成功する)
            if let Some(d) = try_project_distance(f, point) {
                if best.is_none_or(|(bd, _)| d < bd) {
                    best = Some((d, f.id()));
                }
            }
        }
        best
    });
    let (d, id) = best.expect("no face accepted the projection");
    assert!(d < tol, "boundary face center {point} is not on the B-rep (d={d}, tol={tol})");
    *solid
        .colormap()
        .get(&id)
        .unwrap_or_else(|| panic!("face {id} has no color"))
}

pub fn foamfile_header(class: &str, location: &str, object: &str, note: Option<&str>) -> String {
    let note = note.map_or(String::new(), |n| format!("    note        \"{n}\";\n"));
    format!(
        "/*--------------------------------*- C++ -*----------------------------------*\\\n\
         | 生成物: cadrum 色付き B-rep から examples/*.rs が出力 (手で編集しない)      |\n\
         \\*---------------------------------------------------------------------------*/\n\
         FoamFile\n{{\n    version     2.0;\n    format      ascii;\n    class       {class};\n{note}    location    \"{location}\";\n    object      {object};\n}}\n\
         // * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n\n"
    )
}

/// polyMesh 一式 (points/faces/owner/neighbour/boundary) を書き出す。
/// internal は upper-triangular 順 (セル昇順、各セル内で neighbour 昇順) であること。
pub fn write_polymesh(
    dir: &str,
    points: &[DVec3],
    internal: &[InternalFace],
    patch_faces: &[(&str, Vec<BoundaryFace>)],
    patches: &[PatchDef],
    n_cells: usize,
) -> std::io::Result<()> {
    fs::create_dir_all(dir)?;
    let n_internal = internal.len();
    let n_faces = n_internal + patch_faces.iter().map(|(_, v)| v.len()).sum::<usize>();
    let note = format!(
        "nPoints:{} nCells:{} nFaces:{} nInternalFaces:{}",
        points.len(),
        n_cells,
        n_faces,
        n_internal
    );

    let mut out = foamfile_header("vectorField", "constant/polyMesh", "points", None);
    out += &format!("{}\n(\n", points.len());
    for p in points {
        out += &format!("({} {} {})\n", p.x, p.y, p.z);
    }
    out += ")\n";
    fs::write(format!("{dir}/points"), out)?;

    let mut out = foamfile_header("faceList", "constant/polyMesh", "faces", None);
    out += &format!("{n_faces}\n(\n");
    for (quad, _, _) in internal {
        out += &format!("4({} {} {} {})\n", quad[0], quad[1], quad[2], quad[3]);
    }
    for (_, faces) in patch_faces {
        for f in faces {
            out += &format!("4({} {} {} {})\n", f.quad[0], f.quad[1], f.quad[2], f.quad[3]);
        }
    }
    out += ")\n";
    fs::write(format!("{dir}/faces"), out)?;

    let mut out = foamfile_header("labelList", "constant/polyMesh", "owner", Some(&note));
    out += &format!("{n_faces}\n(\n");
    for (_, owner, _) in internal {
        out += &format!("{owner}\n");
    }
    for (_, faces) in patch_faces {
        for f in faces {
            out += &format!("{}\n", f.owner);
        }
    }
    out += ")\n";
    fs::write(format!("{dir}/owner"), out)?;

    let mut out = foamfile_header("labelList", "constant/polyMesh", "neighbour", Some(&note));
    out += &format!("{n_internal}\n(\n");
    for (_, _, neighbour) in internal {
        out += &format!("{neighbour}\n");
    }
    out += ")\n";
    fs::write(format!("{dir}/neighbour"), out)?;

    let mut out = foamfile_header("polyBoundaryMesh", "constant/polyMesh", "boundary", None);
    out += &format!("{}\n(\n", patch_faces.len());
    let mut start = n_internal;
    for (name, faces) in patch_faces {
        let p = patches.iter().find(|p| p.name == *name).unwrap();
        out += &format!("    {name}\n    {{\n        type            {};\n", p.kind);
        if p.kind == "cyclic" {
            out += "        inGroups        1(cyclic);\n";
            out += &format!("        neighbourPatch  {};\n", p.neighbour.unwrap());
        }
        out += &format!(
            "        nFaces          {};\n        startFace       {start};\n    }}\n",
            faces.len()
        );
        start += faces.len();
    }
    out += ")\n";
    fs::write(format!("{dir}/boundary"), out)?;
    Ok(())
}

/// 0/<object> を色→境界条件テーブル (PatchDef) から生成する。
pub fn write_field(
    case_dir: &str,
    object: &str,
    class: &str,
    dimensions: &str,
    internal: &str,
    patches: &[PatchDef],
    bc_of: impl Fn(&PatchDef) -> &'static str,
) -> std::io::Result<()> {
    fs::create_dir_all(format!("{case_dir}/0"))?;
    let mut out = foamfile_header(class, "0", object, None);
    out += &format!("dimensions      {dimensions};\n\ninternalField   {internal};\n\nboundaryField\n{{\n");
    for p in patches {
        out += &format!("    {}\n    {{\n        type            {};\n    }}\n\n", p.name, bc_of(p));
    }
    out += "}\n";
    fs::write(format!("{case_dir}/0/{object}"), out)
}

/// 0/{U,p,PotE} をまとめて生成する。
pub fn write_case_fields(case_dir: &str, patches: &[PatchDef]) -> std::io::Result<()> {
    write_field(case_dir, "U", "volVectorField", "[0 1 -1 0 0 0 0]", "uniform (1 0 0)", patches, |p| p.u)?;
    write_field(case_dir, "p", "volScalarField", "[0 2 -2 0 0 0 0]", "uniform 0", patches, |p| p.p)?;
    write_field(case_dir, "PotE", "volScalarField", "[1 2 -3 0 0 -1 0]", "uniform 0", patches, |p| p.pot_e)?;
    Ok(())
}

/// 幾何級数グレーディングの節点列: 区間 [a,b] を n セル、両端セル幅比 = expansion
/// (expansion > 1 で a 側が細かい)。
pub fn graded(a: f64, b: f64, n: usize, expansion: f64) -> Vec<f64> {
    let l = b - a;
    let r = expansion.powf(1.0 / (n as f64 - 1.0));
    let d0 = l * (r - 1.0) / (r.powi(n as i32) - 1.0);
    let mut v = vec![a];
    let mut d = d0;
    for _ in 0..n {
        v.push(v.last().unwrap() + d);
        d *= r;
    }
    v[n] = b;
    v
}
