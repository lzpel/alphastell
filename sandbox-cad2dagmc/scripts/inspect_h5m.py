"""生成した .h5m が DAGMC の要求する構造を満たすか、h5py で直接検査する。

cad_to_dagmc の h5py 経路は MOAB のスキーマを約450行の手書きで組み立てており、
上流 CI は ubuntu のみ (Windows で走らせた形跡が無い)。したがって
「ファイルが生成された」ことと「DAGMC が読める」ことは別問題として扱う。

閾値を外れたら非ゼロ終了する (検証として失敗する)。

実行: uv run --with h5py scripts/inspect_h5m.py --h5m results/box.h5m --cells 2 --surfaces 6
"""

import argparse
import sys

import h5py
import numpy as np

# DAGMC がジオメトリを組み立てるのに必須のタグ。
# CATEGORY で Volume/Surface/Group を判別し、GEOM_DIMENSION で次元を、
# GEOM_SENSE_2 で面の表裏 (どちらの volume に属するか) を決める。
# NAME に mat:<材料名> が入り、GLOBAL_ID が ID 空間を与える。
REQUIRED_TAGS = [
    "CATEGORY",
    "GEOM_DIMENSION",
    "GEOM_SENSE_2",
    "GLOBAL_ID",
    "NAME",
]


def decode(v):
    """MOAB の文字列タグを取り出す。

    CATEGORY / NAME は固定長32バイトの opaque 型 (h5py.opaque_dtype) で格納されており、
    numpy 側では np.void になる。bytes に落としてから NUL 終端で切る。
    """
    if isinstance(v, np.void):
        v = v.tobytes()
    if isinstance(v, np.ndarray):
        v = v.tobytes()
    if isinstance(v, bytes):
        return v.split(b"\x00")[0].decode("utf-8", "replace")
    return str(v)


def inspect(path):
    out = {"tags": [], "names": [], "counts": {}}
    with h5py.File(path, "r") as f:
        if "tstt" not in f:
            raise SystemExit(f"FAIL: tstt グループが無い ({path} は MOAB 形式ではない)")
        out["tags"] = sorted(f["tstt/tags"].keys()) if "tstt/tags" in f else []

        # CATEGORY タグの値を数えて volume/surface/group の個数を得る。
        # DAGMCUniverse.n_cells / n_surfaces と同じ情報を、OpenMC を介さずに取る。
        cat = f.get("tstt/tags/CATEGORY")
        if cat is not None and "values" in cat:
            vals = [decode(v) for v in cat["values"][()]]
            for v in vals:
                out["counts"][v] = out["counts"].get(v, 0) + 1

        nm = f.get("tstt/tags/NAME")
        if nm is not None and "values" in nm:
            out["names"] = [decode(v) for v in nm["values"][()]]
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--h5m", required=True)
    p.add_argument("--materials", nargs="*", default=None,
                   help="期待する材料タグ (mat: 接頭辞なし)")
    p.add_argument("--volumes", type=int, default=None, help="期待する Volume 数")
    p.add_argument("--reference", default=None,
                   help="比較する既知良品の .h5m (上流の Linux 生成物)")
    args = p.parse_args()

    r = inspect(args.h5m)
    print(f"h5m: {args.h5m}")
    print(f"  tags     : {r['tags']}")
    print(f"  CATEGORY : {r['counts']}")
    print(f"  NAME     : {r['names']}")

    fail = []

    missing = [t for t in REQUIRED_TAGS if t not in r["tags"]]
    if missing:
        fail.append(f"必須タグが欠落: {missing}")

    if args.volumes is not None:
        got = r["counts"].get("Volume", 0)
        if got != args.volumes:
            fail.append(f"Volume 数が不一致: 期待 {args.volumes}, 実際 {got}")

    if args.materials is not None:
        want = {f"mat:{m}" for m in args.materials}
        got = {n for n in r["names"] if n.startswith("mat:")}
        if want != got:
            fail.append(f"材料タグが不一致: 期待 {sorted(want)}, 実際 {sorted(got)}")

    # 既知良品との突き合わせ。生成経路が違う (pymoab vs h5py) ので完全一致はしないが、
    # 必須タグが片方にしか無ければ h5py 経路の取りこぼしを疑える。
    if args.reference:
        ref = inspect(args.reference)
        print(f"\nreference: {args.reference}")
        print(f"  tags     : {ref['tags']}")
        lacking = [t for t in REQUIRED_TAGS if t in ref["tags"] and t not in r["tags"]]
        if lacking:
            fail.append(f"既知良品にあって生成物に無い必須タグ: {lacking}")
        only_ref = sorted(set(ref["tags"]) - set(r["tags"]))
        only_new = sorted(set(r["tags"]) - set(ref["tags"]))
        print(f"  参照のみ : {only_ref}")
        print(f"  生成のみ : {only_new}")

    print()
    if fail:
        for m in fail:
            print(f"FAIL: {m}")
        sys.exit(1)
    print("PASS: DAGMC 必須タグと期待値をすべて満たす")


if __name__ == "__main__":
    main()
