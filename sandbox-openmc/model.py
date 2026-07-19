#!/usr/bin/env python3
"""14.1 MeV 等方点線源を中心に置いたリチウム球の中性子輸送 (OpenMC)。

CAD なし・メッシュなしの CSG 同心球。未衝突中性子束の空間分布を球シェルでタリーし、
輸送方程式の未衝突成分の厳密解 phi(r) = S*exp(-Sigma_t*r)/(4*pi*r^2) と比較するための
数値解を生成する。TBR (Li6(n,t)+Li7(n,n't)) は解析解のない参考値として併記する。

コンテナ内 openmc で実行する (makefile の $(OPENMC) 経由):

    python model.py --radius 20 --particles 200000 --out results

statepoint から抽出した結果を results/tally.json と results/xs.json に書く。
ホスト側の scripts/compare_attenuation.py がこの JSON を読んで解析解と比較する。
xs.json の Sigma_t は「解析解が使う断面積」であり、同じライブラリから読む
(データではなく輸送ソルバーを検証しているため)。
"""

import argparse
import json
import os

import numpy as np
import openmc


def build_material(enrichment):
    """天然 (enrichment=None) または Li6 濃縮リチウム金属。核種は Li6/Li7 のみ。"""
    li = openmc.Material(name="lithium")
    if enrichment is None:
        li.add_element("Li", 1.0)
    else:
        li.add_nuclide("Li6", enrichment)
        li.add_nuclide("Li7", 1.0 - enrichment)
    # リチウム金属の密度 [g/cm^3]。輸送は密度と断面積にしか依存しない。
    li.set_density("g/cm3", 0.534)
    return li


def shell_edges(radius, n):
    """[0, radius] を n 個の等体積球シェルに分割した境界半径。

    等体積にすると各シェルのタリー統計がそろい、壁ぎわだけ極端に粗くならない。
    """
    return radius * (np.arange(n + 1) / n) ** (1.0 / 3.0)


def build_geometry(material, edges):
    """同心球シェルのセル列を作る。最外殻のみ真空境界、内側は透過。"""
    cells = []
    prev = None
    n = len(edges) - 1
    for i in range(n):
        bt = "vacuum" if i == n - 1 else "transmission"
        surf = openmc.Sphere(r=float(edges[i + 1]), boundary_type=bt)
        region = -surf if prev is None else (-surf & +prev)
        cells.append(openmc.Cell(name=f"shell{i}", fill=material, region=region))
        prev = surf
    return cells


def macroscopic_total(material, energy):
    """材料の巨視的全断面積 Sigma_t [1/cm] を energy [eV] で評価する。

    N_i [atoms/b-cm] * sigma_t,i(E) [b] を全核種で総和。断面積は使用中の
    OPENMC_CROSS_SECTIONS ライブラリから読む (解析解の Sigma_t を数値解と同じ
    データに一致させるため)。MT=1 が全断面積。
    """
    lib = openmc.data.DataLibrary.from_xml(os.environ["OPENMC_CROSS_SECTIONS"])
    nuc_densities = material.get_nuclide_atom_densities()  # {name: atoms/b-cm}
    total = 0.0
    for name, ndens in nuc_densities.items():
        entry = lib.get_by_material(name, data_type="neutron")
        data = openmc.data.IncidentNeutron.from_hdf5(entry["path"])
        temp = next(iter(data[1].xs))  # 全断面積の 14.1 MeV は温度非依存
        sigma_t = float(data[1].xs[temp]([energy])[0])  # [barn]
        total += float(ndens) * sigma_t
    return total


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--radius", type=float, default=20.0, help="球半径 [cm]")
    p.add_argument("--particles", type=int, default=200000, help="ヒストリ数/バッチ")
    p.add_argument("--batches", type=int, default=20, help="バッチ数")
    p.add_argument("--shells", type=int, default=20, help="球シェル数 (未衝突束の空間分布)")
    p.add_argument("--enrichment", type=float, default=None, help="Li6 原子分率 (未指定で天然組成)")
    p.add_argument("--energy", type=float, default=14.1e6, help="線源エネルギー [eV]")
    p.add_argument("--out", default="results", help="出力ディレクトリ")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)

    li = build_material(args.enrichment)
    materials = openmc.Materials([li])

    edges = shell_edges(args.radius, args.shells)
    cells = build_geometry(li, edges)
    geometry = openmc.Geometry(cells)

    # --- 線源: 中心の 14.1 MeV 等方点線源 ---
    source = openmc.IndependentSource(
        space=openmc.stats.Point((0.0, 0.0, 0.0)),
        energy=openmc.stats.Discrete([args.energy], [1.0]),
        angle=openmc.stats.Isotropic(),
    )

    settings = openmc.Settings()
    settings.run_mode = "fixed source"
    settings.source = source
    settings.particles = args.particles
    settings.batches = args.batches
    # survival biasing は既定 (無効) のまま: 未衝突中性子の重み 1 を保ち、
    # CollisionFilter(bins=[0]) が素の未衝突束を与えるようにする。
    # 断面積は build_xs.py が NJOY で 293.6 K に処理済み (材料温度の既定と一致)。
    settings.temperature = {"default": 293.6, "method": "nearest", "tolerance": 1000.0}

    # --- タリー ---
    cell_filter = openmc.CellFilter(cells)
    collision0 = openmc.CollisionFilter(bins=[0])  # 未衝突 (衝突回数 0) のみ
    # 線源エネルギー近傍だけを残すエネルギー窓。14.1 MeV の未衝突源中性子は厳密に
    # 線源エネルギーのままだが、(n,2n) の二次中性子は新粒子で衝突回数 0 から始まり
    # かつ低エネルギー (<~7 MeV) なので、この窓で除ける。CollisionFilter だけだと
    # 二次中性子が未衝突束に混入し、外側シェルほど過大評価される (実測、~7%)。
    ewin = openmc.EnergyFilter([0.999 * args.energy, 1.001 * args.energy])

    t_uncollided = openmc.Tally(name="uncollided_flux")
    t_uncollided.filters = [cell_filter, collision0, ewin]
    t_uncollided.scores = ["flux"]

    t_total = openmc.Tally(name="total_flux")
    t_total.filters = [cell_filter]
    t_total.scores = ["flux"]

    # TBR: (n,Xt) = Li6(n,t)alpha + Li7(n,n't)alpha を1つのスコアで集計。
    t_tbr = openmc.Tally(name="tbr")
    t_tbr.scores = ["(n,Xt)"]

    tallies = openmc.Tallies([t_uncollided, t_total, t_tbr])

    model = openmc.Model(geometry=geometry, materials=materials,
                         settings=settings, tallies=tallies)
    sp_path = model.run(cwd=args.out)

    # --- 抽出 ---
    # flux スコア (track-length) はシェルの体積積分束 [cm/src] を返す。
    # シェル体積で割ってシェル平均束 [1/cm^2/src] にする。
    vols = (4.0 / 3.0) * np.pi * (edges[1:] ** 3 - edges[:-1] ** 3)
    with openmc.StatePoint(sp_path) as sp:
        tu = sp.get_tally(name="uncollided_flux")
        tt = sp.get_tally(name="total_flux")
        tb = sp.get_tally(name="tbr")

        uf = tu.mean.flatten() / vols
        uf_sd = tu.std_dev.flatten() / vols
        tf = tt.mean.flatten() / vols

        result = {
            "radius": args.radius,
            "energy": args.energy,
            "particles": args.particles,
            "batches": args.batches,
            "source_strength": 1.0,  # 線源 1 個/ヒストリ規格化 (per source neutron)
            "shell_edges": edges.tolist(),
            "shell_volumes": vols.tolist(),
            "uncollided_flux": uf.tolist(),
            "uncollided_flux_sd": uf_sd.tolist(),
            "total_flux": tf.tolist(),
            "tbr": float(tb.mean.flatten()[0]),
            "tbr_sd": float(tb.std_dev.flatten()[0]),
        }

    with open(os.path.join(args.out, "tally.json"), "w") as f:
        json.dump(result, f, indent=2)

    # --- 解析解が使う断面積を同じライブラリから読む ---
    sigma_t = macroscopic_total(li, args.energy)
    xs = {
        "energy": args.energy,
        "sigma_t": sigma_t,  # [1/cm]
        "library": os.environ.get("OPENMC_CROSS_SECTIONS", "(unset)"),
        "openmc_version": openmc.__version__,
    }
    with open(os.path.join(args.out, "xs.json"), "w") as f:
        json.dump(xs, f, indent=2)

    print(f"Sigma_t(14.1 MeV) = {sigma_t:.6e} /cm   mfp = {1.0 / sigma_t:.4f} cm")
    print(f"TBR = {result['tbr']:.5f} +/- {result['tbr_sd']:.5f}  (参考値)")


if __name__ == "__main__":
    main()
