# sandbox-cad2dagmc — STEP → DAGMC(.h5m) 変換が素の Windows + uv で成立するかの検証サンドボックス

CadQuery で作った STEP を `cad_to_dagmc` で DAGMC の `.h5m` に変換し、**conda も WSL も
Docker も使わない素の Windows + uv だけ**で成立するかを確かめる。3カ月計画 W7
「OpenMC 経路(STEP→DAGMC→TBR)」のうち、**CAD 側の入口が Windows で通るか**という
一点だけを切り出したもの。背景は
[notes/20260721-cad2dagmcがwindowsで動くか.md](../notes/20260721-cad2dagmcがwindowsで動くか.md)。

**結果: 通った。** 立方体1個 (1材料) と同心殻2個 (2材料) の両方で
STEP → `.h5m` → `openmc.DAGMCUniverse` が成立し、材料タグも volume ごとに正しく割り当たる。
`pymoab` は導入されていない (PyPI に存在しない)。

**これは本来もっと早く確かめるべき検証だった。** `.h5m` は MOAB のファイル形式で、
書き出しには従来 pymoab が要る。pymoab は conda-forge の `moab` パッケージにしか無く、
それは `skip: win` で Windows ビルドが存在しない。つまり
「cad_to_dagmc は Windows で動かない」が長らく正しい答えで、**それが正しいままなら
OpenMC/MOAB/DAGMC を Windows ネイティブで自作した意味が W7 に対して無かった**。

## 使い方

必要要件: [uv](https://docs.astral.sh/uv/)、GNU make。(3) だけ
[sandbox-openmc-source](../sandbox-openmc-source) がビルド済みであることを要求する。

```sh
make -C sandbox-cad2dagmc              # (デフォルト=verify) 生成 → 構造検査 → OpenMC 読み込み
make -C sandbox-cad2dagmc h5m          # STEP と .h5m を生成するだけ
make -C sandbox-cad2dagmc inspect      # 構造検査まで (OpenMC も核データも不要)
make -C sandbox-cad2dagmc SHAPE=shells # 2材料の同心殻で実行
make -C sandbox-cad2dagmc clean
```

検査は DAGMC 必須タグの欠落、Volume 数・材料タグの不一致で**非ゼロ終了**する。
出力: `results/{box,shells}.step` と `results/{box,shells}.h5m`。

## 検証の3段階

段を分けてあるのは、**どこで落ちたかで意味が変わる**ため。

| 段 | 内容 | 落ちたときの意味 |
|---|---|---|
| (1) 導入 | `uv run --with cad-to-dagmc` が通り `import cadquery` できる | Windows では不可。W7 は WSL2 + conda に寄せる判断になる |
| (2) 生成と構造検査 | `.h5m` が生成され、h5py 検査で DAGMC 必須タグが揃う | h5py 経路のバグ。上流 CI は Linux のみなので報告価値が高い |
| (3) OpenMC 読み込み | `DAGMCUniverse` の `n_cells` / `n_surfaces` が形状と整合 | 生成物と OpenMC の解釈のずれ。切り分けが要る |

(2) は核データも OpenMC も要らないので、先にここまで通す。

### 実測値

| 形状 | .h5m の Volume | Surface | 材料 | OpenMC の n_cells |
|---|---|---|---|---|
| `box` (立方体1個) | 1 | 6 | `mat:mat1` | 2 |
| `shells` (同心殻2個) | 2 | 18 | `mat:mat1`, `mat:mat2` | 3 |

`n_cells` が Volume より1多いのは、DAGMC が**陰的補集合 (implicit complement) を実行時に
1つ足す**ため。ファイルの中には入っていない。makefile で `SOLIDS` と `CELLS` を分けて
持っているのはこの区別のため。

## 設計判断と根拠

| 判断 | 選択 | 根拠 |
|---|---|---|
| 変換ライブラリ | `cad_to_dagmc` | 唯一 pymoab 非依存の経路を持つ。[PR #168](https://github.com/fusion-energy/cad_to_dagmc/pull/168) (2026-01-30、ブランチ名 `h5py-instead-of-moab`) で **h5py が既定バックエンド**になった。`_vertices_to_h5m_h5py` が `CATEGORY` / `GEOM_DIMENSION` / `GLOBAL_ID` / `NAME` / `GEOM_SENSE_2` / `FACETING_TOLERANCE` を手書きで組み立てる |
| `h5m_backend` | `"h5py"` を**明示** | 既定値ではあるが、上流が既定を戻したら即座に気づけるように明示する。pymoab を使わないことがこの検証の要点なので、暗黙に頼らない |
| 代替を採らない理由 | `CAD_to_OpenMC` は不可 | PyPI のメタデータには現れないが `src/CAD_to_OpenMC/assembly.py` が**トップレベルで `from pymoab import core, types`** しており、import 時点で落ちる。`vertices_to_h5m` も純 pymoab で同様 |
| テスト形状 | CadQuery で自作 | `sandbox-openfoam-cadrum` は色付き STEP を出すが `results/` が gitignore されており**コミット済みの STEP が無い**。Rust/cadrum 依存を持ち込むより、既に依存に入っている CadQuery で作る方が安い。実形状との接続は W7 本番の課題として分離する |
| STEP を経由するか | 経由する | CadQuery オブジェクトを直接渡す API もあるが、それでは**STEP リーダを検証できない**。本番 (cadrum が吐く色付き STEP) と同じ入口を踏む |
| 既知良品との比較 | 上流の `legacy/dagmc.h5m` と突き合わせ | h5py 経路は約450行の手書き HDF5 スキーマで、上流 CI は ubuntu のみ。Linux + pymoab 生成の既知良品が `sandbox-openmc-source/src/openmc/tests/` に同梱されているので、必須タグの取りこぼしを検出できる |
| OpenMC の呼び出し | venv の python を直接叩く | `make -C ../sandbox-openmc-source` を呼ばない。あちらは `.PHONY` のチェーンなので、呼ぶと**現在の makefile の設定で建て直してしまう**。DAGMC 有効ビルドを壊す事故を避ける |

## 既知の制約

- **粒子を飛ばしていない**。`.h5m` が読めるところまでで、実際の輸送計算は
  核データ (U235/H1/O16 + `c_H_in_H2O` など) が要るので未実施。
- **上流に Windows の前例が無い**。`cad_to_dagmc` の CI は `.github/workflows/*` すべて
  `ubuntu-latest`。Windows に言及した issue もゼロ。ただし `ci_with_pip_install.yml` には
  「pymoab 無しで全テストを回す」ジョブが明示的にあり、h5py 経路自体は意図的に
  サポートされている。
- **(3) は sandbox-openmc-source のビルド済み成果物に依存する**。未ビルドなら skip する
  (エラーにはしない)。かつ DAGMC 有効でビルドされている必要がある。
- 生成される `.h5m` のタグ集合は上流の pymoab 生成物と**完全一致はしない**
  (`OBB` / `GEOMETRY_RESABS` / `EXTRA_NAME*` などが無い)。DAGMC が必須とするタグは
  揃っているので読めているが、OBB ツリーが無い分だけレイトレーシングの前処理が
  実行時に走る可能性がある。性能面は未評価。

## 出典

- [cad_to_dagmc](https://github.com/fusion-energy/cad_to_dagmc) — MIT License
- [CadQuery](https://github.com/CadQuery/cadquery) — Apache 2.0
- [DAGMC の必須メタデータ](https://svalinn.github.io/DAGMC/usersguide/uw2.html) — `mat:<name>` グループ、graveyard、watertight 要件
