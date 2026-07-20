# cad2dagmc が windows で動くか

**結論: 動いた。** conda も WSL も Docker も使わない素の Windows + uv だけで
STEP → `.h5m` → `openmc.DAGMCUniverse` が成立する。検証は
[sandbox-cad2dagmc](../sandbox-cad2dagmc/README.md)。

関連: [20260721-dagmc-moabをmingwで建てる計画](20260721-dagmc-moabをmingwで建てる計画.md),
[20260720-openmc-dagmc-moabをwindowsでコンパイルできると便利](20260720-openmc-dagmc-moabをwindowsでコンパイルできると便利.md)

---

## これは順序を誤った検証だった

`.h5m` は MOAB のファイル形式で、書き出しには従来 **pymoab** が要る。pymoab は
conda-forge の `moab` パッケージにしか無く、それは `skip: win` で Windows ビルドが存在
しない。つまり長らく「cad_to_dagmc は Windows で動かない」が正しい答えだった。

**それが正しいままなら、OpenMC / MOAB / DAGMC を Windows ネイティブで自作した意味が
W7 に対して無かった。** `wout.nc → 流路 CAD → 色付き STEP → .h5m → OpenMC → TBR` の
パイプラインは、CAD 側の入口が塞がっていれば solver 側だけ整えても繋がらない。

本来これを**最初に**確かめるべきだった。第一弾 (CSG OpenMC)、第二弾 (DAGMC+MOAB) を
建ててから気づいた。

## ただし「早くやれば正解だった」わけでもない

皮肉なことに、**数ヶ月前に検証していたら「pymoab 必須 → Windows 不可」という
誤った結論に至っていた**可能性が高い。

`cad_to_dagmc` は [PR #168](https://github.com/fusion-energy/cad_to_dagmc/pull/168)
(2026-01-30、ブランチ名 `h5py-instead-of-moab`) で **pymoab 依存を外し、h5py で MOAB の
HDF5 スキーマを直接書く経路を既定にした**。

```python
def export_dagmc_h5m_file(..., h5m_backend: str = "h5py")   # 既定が h5py
```

pymoab の import は遅延かつ try/except 内で、例外メッセージ自身が
「pymoab is not available on PyPI ... use the h5py backend (the default)」と述べている。

教訓は「早く検証しろ」ではなく、**前提が変わっていないかを確かめてから判断しろ**、
の方だと思う。古い前提のまま「不可能」と結論すると、その時点で探索が止まる。

## 実測

### PyPI の状況

| パッケージ | Windows |
|---|---|
| `cad-to-dagmc` 0.11.9 | `py3-none-any` |
| `cad-to-dagmc-mesher` 0.1.6 | **`cp310-abi3-win_amd64` あり** (唯一のコンパイル済み依存) |
| `cadquery-ocp` 7.9.3.1.1 | **`win_amd64` あり** |
| `cadquery` 2.8.0 / `gmsh` / `h5py` | あり |
| `pymoab` / `moab` | **PyPI に存在しない (404)** — だが依存リストに無い |

`uv pip install cad-to-dagmc` は追加のインデックス指定なしで完走し、`import cadquery`
(OCCT の DLL ロード、典型的な失敗点) も通った。

### 生成物

| 形状 | .h5m の Volume | Surface | 材料 | OpenMC の n_cells |
|---|---|---|---|---|
| 立方体1個 | 1 | 6 | `mat:mat1` | 2 |
| 同心殻2個 | 2 | 18 | `mat:mat1`, `mat:mat2` | 3 |

`n_cells` が Volume より1多いのは DAGMC が**陰的補集合を実行時に足す**ため。
ファイルには入っていない。ここを取り違えて最初の検査が落ちた。

### 上流の既知良品との差

生成物のタグ集合は上流 (Linux + pymoab) の `legacy/dagmc.h5m` と**完全一致はしない**。

- 両方にある: `CATEGORY` `GEOM_DIMENSION` `GEOM_SENSE_2` `GLOBAL_ID` `NAME`
  `DIRICHLET_SET` `MATERIAL_SET` `NEUMANN_SET`
- 上流のみ: `OBB` `GEOMETRY_RESABS` `EXTRA_NAME0/1` `FACETING_TOL`
  `GEOM_SENSE_N_ENTS` `GEOM_SENSE_N_SENSES`
- 生成のみ: `FACETING_TOLERANCE` (上流は `FACETING_TOL`、名前が違う)

DAGMC が必須とするタグは揃っているので読める。ただし **`OBB` (バウンディングボリューム
階層) が無い**ので、レイトレーシングの前処理が実行時に走る可能性がある。性能は未評価。

## まだやっていないこと

**粒子を飛ばしていない。** `.h5m` が読めるところまでで、実際の輸送計算は核データが要る。
これは第二弾から持ち越している宿題と同じ。

## リスク

**上流に Windows の前例が無い。** `cad_to_dagmc` の CI は `.github/workflows/*` すべて
`ubuntu-latest` で、Windows に言及した issue もゼロ。h5py 経路は約450行の手書き HDF5
スキーマで、まだ半年しか経っていない。

ただし `ci_with_pip_install.yml` には「pymoab 無しで全テストを回す」ジョブが明示的にあり、
h5py 経路自体は意図的にサポートされている。生成物を信用せず検査する方針
(sandbox の `inspect_h5m.py`) はこの状況への対処。

## W7 への含意

CAD 側の入口が Windows で通ったので、**パイプライン全体が Windows ネイティブで
繋がる見通しが立った**。残るのは cadrum が吐く色付き STEP を `cad_to_dagmc` に食わせる
部分で、これは「ソリッドの色 = 材料タグ」の対応付けをどう渡すかという実装の問題。

`cad_to_dagmc` の `add_stp_file(material_tags=[...])` はソリッドの順序で材料を割り当てる
ので、cadrum 側で色と順序の対応を保証できれば繋がるはず。色情報を直接読む API があるかは
未調査。
