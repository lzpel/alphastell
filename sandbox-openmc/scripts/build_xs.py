#!/usr/bin/env python3
"""検証に必要な最小の中性子断面積ライブラリをコンテナ内で用意する。

既定 (LIB=lite): Li6/Li7 の 2 核種だけを IAEA の ENDF/B-VIII.0 個別ファイルから
取得し HDF5 化して data/lib/cross_sections.xml を書く (数 MB)。純リチウム球の
未衝突減衰の検証にはこの 2 核種で足りる。

LIB=full: ENDF/B-VIII.0 の HDF5 フルライブラリ (数 GB) を openmc.org から取得・展開する。
W7 の PbLi + 構造材ではこちらが要る。軽量ライブラリはマウント機構 (-v と
OPENMC_CROSS_SECTIONS) は検証するが、フルライブラリの取得経路は検証しない。
その切り替えを 1 変数に閉じ込めておく。

コンテナ内 openmc で実行する (makefile の data ターゲット経由):

    python scripts/build_xs.py --mode lite --out data
"""

import argparse
import io
import os
import tarfile
import urllib.request
import zipfile

import openmc.data

# ENDF/B-VIII.0 個別評価済みファイル (IAEA ミラー、0 K, ascii ENDF-6)。
# 各 URL は 1 核種の zip で、中に ENDF .dat が 1 個入っている。
IAEA_BASE = "https://www-nds.iaea.org/public/download-endf/ENDF-B-VIII.0/n"
ENDF_ZIPS = {
    "Li6": f"{IAEA_BASE}/n_0325_3-Li-6.zip",
    "Li7": f"{IAEA_BASE}/n_0328_3-Li-7.zip",
}
# IAEA サーバは既定 UA を弾く場合があるのでブラウザ風 UA を付ける。
_UA = "Mozilla/5.0 (build_xs.py)"

# NJOY 処理温度 [K]。model.py の材料温度既定と一致させる。
TEMP_K = 293.6

# フルライブラリ (HDF5, 展開後 数 GB)。openmc の公式配布。
FULL_URL = "https://anl.box.com/shared/static/uhbxlrx7hvxqw27psymfbhi7bx7s6u6a.xz"
FULL_DIRNAME = "endfb-viii.0-hdf5"


def _urlopen(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": _UA}))


def _download(url, dest):
    print(f"  download {url}")
    with _urlopen(url) as r, open(dest, "wb") as f:
        f.write(r.read())


def _download_endf_from_zip(url, dest):
    """核種 zip を取得し、中の唯一の .dat を dest に展開する。"""
    print(f"  download {url}")
    with _urlopen(url) as r:
        blob = r.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".dat"))
        with z.open(name) as src, open(dest, "wb") as f:
            f.write(src.read())


def build_lite(out):
    """Li6/Li7 の ENDF を HDF5 化し cross_sections.xml を書く。"""
    endf_dir = os.path.join(out, "endf")
    lib_dir = os.path.join(out, "lib")
    os.makedirs(endf_dir, exist_ok=True)
    os.makedirs(lib_dir, exist_ok=True)

    library = openmc.data.DataLibrary()
    for name, url in ENDF_ZIPS.items():
        endf_path = os.path.join(endf_dir, f"{name}.endf")
        if not os.path.exists(endf_path):
            _download_endf_from_zip(url, endf_path)
        print(f"  process {name} (NJOY, {TEMP_K} K)")
        # from_endf のデータは HDF5 に直接書けない (共鳴再構成・Doppler 広がり未処理)。
        # NJOY (イメージに同梱) でポイントワイズ化してから export する。
        data = openmc.data.IncidentNeutron.from_njoy(
            endf_path, temperatures=[TEMP_K], njoy_exec="njoy")
        h5_path = os.path.join(lib_dir, f"{name}.h5")
        data.export_to_hdf5(h5_path, "w")
        library.register_file(h5_path)

    xml_path = os.path.join(lib_dir, "cross_sections.xml")
    library.export_to_xml(xml_path)
    print(f"wrote {xml_path}  ({len(ENDF_ZIPS)} nuclides, {TEMP_K} K)")


def build_full(out):
    """ENDF/B-VIII.0 HDF5 フルライブラリを取得・展開する。"""
    lib_dir = os.path.join(out, "lib")
    os.makedirs(lib_dir, exist_ok=True)
    tar_path = os.path.join(out, "endfb-viii.0-hdf5.tar.xz")
    if not os.path.exists(tar_path):
        _download(FULL_URL, tar_path)
    print("  extract (数 GB, 時間がかかる)")
    with tarfile.open(tar_path, "r:xz") as tar:
        tar.extractall(lib_dir)
    src = os.path.join(lib_dir, FULL_DIRNAME, "cross_sections.xml")
    dst = os.path.join(lib_dir, "cross_sections.xml")
    # data ターゲットが期待する固定パスに cross_sections.xml を用意する。
    if os.path.abspath(src) != os.path.abspath(dst):
        rel = os.path.relpath(os.path.join(lib_dir, FULL_DIRNAME), lib_dir)
        _rewrite_xml_root(src, dst, rel)
    print(f"wrote {dst}")


def _rewrite_xml_root(src, dst, subdir):
    """フルライブラリの cross_sections.xml を lib/ 直下から参照できるよう <directory> を付ける。"""
    import xml.etree.ElementTree as ET

    tree = ET.parse(src)
    root = tree.getroot()
    d = root.find("directory")
    if d is None:
        d = ET.SubElement(root, "directory")
    d.text = subdir
    tree.write(dst)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["lite", "full"], default="lite")
    p.add_argument("--out", default="data", help="出力ディレクトリ (data)")
    args = p.parse_args()
    if args.mode == "lite":
        build_lite(args.out)
    else:
        build_full(args.out)


if __name__ == "__main__":
    main()
