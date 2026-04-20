"""
CAD -> cad_to_dagmc バックエンドで、現行 parastell の **ジオメトリ系機能を可能な限り** 使うフルデモ。

取り込んでいる機能:
  [in-vessel]
    - 5 層のラジアルビルド (first_wall / breeder / back_wall / shield / vacuum_vessel)
    - breeder のみ 2D thickness_matrix (toroidal×poloidal で変化)
    - wall_s > 1.0 + split_chamber=True でプラズマ / SOL を分離
    - 独自の 'chamber' エントリで SOL のマテリアルタグをカスタム化
    - 全コンポーネントに mat_tag を明示
    - plasma_mat_tag / sol_mat_tag を明示 (Vacuum 以外のタグを付与)
    - num_ribs / num_rib_pts は parastell 既定 (61) を明示
    - scale を明示指定 (m -> cm)
    - MOAB と Gmsh の 2 系統で in-vessel メッシュ H5M を出力

  注意: 以下のパラメータは OCCT の bool cut 安定性のため保守的に設定している。
    - wall_s = 1.08 (1.15 以上に攻めると Null TopoDS で落ちる)
    - chamber_thickness = 一定 4 cm (poloidal 変動を付けると plasma と接近して退化)
    - num_ribs = num_rib_pts = 61 (既定より上げると loft/cut の負荷が急増)
  [magnets]
    - construct_magnets_from_filaments + case_thickness>0 でコイルケーシングをモデリング
    - mat_tag をケーシング用と巻線用の 2 値で渡す
    - sample_mod でフィラメント点引き
    - Gmsh で magnet mesh を "inner"/"outer"/"both" の 3 パターン出力
  [source]
    - 独自 plasma_conditions / reaction_rate を渡して反応率分布をカスタム化
  [dagmc]
    - build_cad_to_dagmc_model で OSS パスのみで DAGMC を生成
    - min_mesh_size / max_mesh_size を明示

意図的に外したもの:
    - use_pydagmc=True (本 example は cad_to_dagmc 固定)
    - export_*_cubit / build_cubit_model (Cubit 商用ライセンス必要)
    - ribs_from_kisslinger_format (テストデータが repo に無い)
    - add_magnets_from_geometry (Cubit import 経由)
    - repeat>0 (ランタイムが長くなるため; 1 周期で足りる)
"""

import os

import numpy as np

import parastell.parastell as ps


export_dir = "alphastell_full"
os.makedirs(export_dir, exist_ok=True)
vmec_file = "wout_vmec.nc"

stellarator = ps.Stellarator(vmec_file)

# --------------------------------------------------------------------
# In-vessel build
# --------------------------------------------------------------------
toroidal_angles = [0.0, 11.25, 22.5, 33.75, 45.0, 56.25, 67.5, 78.75, 90.0]
poloidal_angles = [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0, 360.0]
# wall_s は LCFS 直上をわずかに外挿する値 (parastell の既定的な 1.08)。
# ここを 1.15 以上に攻めると OCCT の bool cut が Null TopoDS を返して落ちる
# (invessel_build.py:547 の outer.cut(interior) が退化形状で失敗) ため抑えめに。
wall_s = 1.08

uniform = np.ones((len(toroidal_angles), len(poloidal_angles)))

# SOL 厚み (chamber)。独自 chamber による SOL カスタム化の例示として一定厚を使う。
# poloidal で厚みを揺らすと、chamber と plasma が接近する箇所で OCCT の bool cut が
# 退化し Null TopoDS を返すため、example ではフラット 4 cm 固定。
chamber_thickness = uniform * 4.0

radial_build_dict = {
    # split_chamber=True + 独自 chamber で SOL 厚みをカスタム化
    "chamber": {
        "thickness_matrix": chamber_thickness,
        "mat_tag": "sol_custom",
    },
    "first_wall": {
        "thickness_matrix": uniform * 5,
        "mat_tag": "tungsten_fw",
    },
    "breeder": {
        # 2D thickness_matrix で breeder 厚みを toroidal x poloidal で変える
        "thickness_matrix": np.array(
            [
                [75.0, 75.0, 75.0, 25.0, 25.0, 25.0, 75.0, 75.0, 75.0],
                [75.0, 75.0, 75.0, 25.0, 25.0, 75.0, 75.0, 75.0, 75.0],
                [75.0, 75.0, 25.0, 25.0, 75.0, 75.0, 75.0, 75.0, 75.0],
                [65.0, 25.0, 25.0, 65.0, 75.0, 75.0, 75.0, 75.0, 65.0],
                [45.0, 45.0, 75.0, 75.0, 75.0, 75.0, 75.0, 45.0, 45.0],
                [65.0, 75.0, 75.0, 75.0, 75.0, 65.0, 25.0, 25.0, 65.0],
                [75.0, 75.0, 75.0, 75.0, 75.0, 25.0, 25.0, 75.0, 75.0],
                [75.0, 75.0, 75.0, 75.0, 25.0, 25.0, 75.0, 75.0, 75.0],
                [75.0, 75.0, 75.0, 25.0, 25.0, 25.0, 75.0, 75.0, 75.0],
            ]
        ),
        "mat_tag": "flibe_breeder",
    },
    "back_wall": {
        "thickness_matrix": uniform * 5,
        "mat_tag": "eurofer_back",
    },
    "shield": {
        "thickness_matrix": uniform * 50,
        "mat_tag": "wc_shield",
    },
    "vacuum_vessel": {
        "thickness_matrix": uniform * 10,
        "mat_tag": "ss316_vv",
    },
}

stellarator.construct_invessel_build(
    toroidal_angles,
    poloidal_angles,
    wall_s,
    radial_build_dict,
    split_chamber=True,
    plasma_mat_tag="dt_plasma",
    sol_mat_tag="sol_vac",
    # parastell 既定の 61x61。これ以上に上げると OCCT loft + 後続 bool cut の
    # 組み合わせで時間が膨らむ・失敗確率が上がるため example は既定値に固定。
    num_ribs=61,
    num_rib_pts=61,
    scale=100.0,
)

stellarator.export_invessel_build_step(export_dir=export_dir)

invessel_components = [
    "plasma",
    "chamber",
    "first_wall",
    "breeder",
    "back_wall",
    "shield",
    "vacuum_vessel",
]

# 2 系統のメッシュ H5M を出力。
# MOAB は surface point cloud から直接テトラを張るので robust。先に実行する。
stellarator.export_invessel_build_mesh_moab(
    invessel_components,
    filename="invessel_mesh_moab",
    export_dir=export_dir,
)

# Gmsh は CadQuery の spline surface をトライアングル化→テトラ化するが、
# 複雑な spline 面で "PLC Error: A segment and a facet intersect" を起こしがち
# (並走する面が近接すると Piecewise Linear Complex が退化する)。
# example の下流処理 (磁石 / source / DAGMC) を落とさないよう best-effort にする。
try:
    stellarator.export_invessel_build_mesh_gmsh(
        invessel_components,
        filename="invessel_mesh_gmsh",
        min_mesh_size=5.0,
        max_mesh_size=20.0,
        algorithm=1,
        export_dir=export_dir,
    )
except Exception as e:
    print(f"[warn] Gmsh in-vessel mesh failed ({type(e).__name__}): {e}")
    print("[warn] continuing without Gmsh in-vessel mesh")

# --------------------------------------------------------------------
# Magnets (filaments + casing)
# --------------------------------------------------------------------
coils_file = "coils.example"
width = 40.0
thickness = 50.0
toroidal_extent = 90.0
case_thickness = 5.0  # コイルケーシングを有効化 (PR #246)

stellarator.construct_magnets_from_filaments(
    coils_file,
    width,
    thickness,
    toroidal_extent,
    case_thickness=case_thickness,
    sample_mod=6,
    mat_tag=["coil_case_ss316", "coil_winding_nb3sn"],
)

stellarator.export_magnets_step(
    filename="magnet_set", export_dir=export_dir
)

for volumes_to_mesh in ("inner", "outer", "both"):
    try:
        stellarator.export_magnet_mesh_gmsh(
            filename=f"magnet_mesh_{volumes_to_mesh}",
            min_mesh_size=5.0,
            max_mesh_size=20.0,
            algorithm=1,
            volumes_to_mesh=volumes_to_mesh,
            export_dir=export_dir,
        )
    except Exception as e:
        print(f"[warn] Gmsh magnet mesh ({volumes_to_mesh}) failed ({type(e).__name__}): {e}")

# --------------------------------------------------------------------
# Source mesh with custom plasma conditions / reaction rate
# --------------------------------------------------------------------
def custom_plasma_conditions(s):
    # s は 0..1 の規格化磁束面ラベル、中心で温度/密度ピーク
    T_i_keV = 20.0 * (1.0 - s**2) ** 2
    n_i_m3 = 1.0e20 * (1.0 - s**2)
    return n_i_m3, T_i_keV


def custom_reaction_rate(n_i, T_i):
    # 簡易 D-T 近似: <sigma v> ~ T^2 に比例、単位は任意
    return n_i * n_i * T_i**2


cfs_values = np.linspace(0.0, 1.0, num=11)
sm_poloidal = np.linspace(0.0, 360.0, num=61)
sm_toroidal = np.linspace(0.0, 90.0, num=61)

stellarator.construct_source_mesh(
    cfs_values,
    sm_poloidal,
    sm_toroidal,
    plasma_conditions=custom_plasma_conditions,
    reaction_rate=custom_reaction_rate,
)
stellarator.export_source_mesh(filename="source_mesh", export_dir=export_dir)

# --------------------------------------------------------------------
# DAGMC export via cad_to_dagmc (内部で Gmsh が動く)
# --------------------------------------------------------------------
stellarator.build_cad_to_dagmc_model()
try:
    stellarator.export_cad_to_dagmc(
        filename="dagmc",
        export_dir=export_dir,
        min_mesh_size=10.0,
        max_mesh_size=40.0,
        algorithm=1,
    )
except Exception as e:
    print(f"[warn] cad_to_dagmc DAGMC export failed ({type(e).__name__}): {e}")
    print("[warn] STEP / MOAB mesh / source mesh は既に出力済み")
