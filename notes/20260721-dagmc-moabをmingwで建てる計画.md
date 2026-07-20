# dagmc/moab を mingw で建てる計画

> **結果 (2026-07-21): 建った。** `openmc --version` が `DAGMC support: yes` を出し、
> MOAB・DAGMC・HDF5・libopenmc すべて静的で `openmc.exe` (14.5 MB) は非システム DLL に
> 依存しない。上流の legacy テストモデルで `n_cells=5` / `n_surfaces=21` を確認済み
> (検証(1)(2) 通過)。輸送計算の検証(3) は核データ未取得のため未実施。
>
> **実際に詰まったのは事前調査で予見できていなかった2点**だった。計画で山場と見ていた
> MOAB のコンパイル自体は `tools/` を飛ばすパッチ1枚で素直に通った。
>
> 1. **MOAB の配布 tarball が壊れている** — autotools の `make dist` 産物で
>    `config/{logging,dist,distcheck}.cmake` が同梱漏れ。configure が即死する。git clone に切替
> 2. **DAGMC が静的 HDF5 を見つけられない** — `FindMOAB.cmake` が探索拡張子を共有側に固定し、
>    静的パスを文字列置換で導出する設計。共有 HDF5 の存在が暗黙の前提になっている
>
> `libMOAB.a` のアーカイブ作成が一度 `file truncated` で落ちたが、オブジェクトもコマンド長も
> 健全で再実行すると通った。原因未特定。

第一弾 (CSG のみの OpenMC を MinGW ネイティブでビルド) はマージ済み
([PR #8](https://github.com/lzpel/mhd-tbr-stell/pull/8) /
[#9](https://github.com/lzpel/mhd-tbr-stell/pull/9) /
[#10](https://github.com/lzpel/mhd-tbr-stell/pull/10))。
現状は `openmc.exe` 単体で完結する全静的構成 (`liblibopenmc.a`、DLL 0個)。

第二弾は **CAD 由来ジオメトリ (.h5m) を読める OpenMC** を建てる。3カ月計画の W7 に相当。
`cad_to_dagmc` 相当 (STEP → .h5m 変換) は**スコープ外**で、「既にある .h5m を OpenMC が
読んで輸送計算できる」ところまで。

到達点は `openmc --version` が `DAGMC support: yes` を出し、既知の .h5m で既知の答えが出ること。

関連: [20260720-openmc-dagmc-moabをwindowsでコンパイルできると便利](20260720-openmc-dagmc-moabをwindowsでコンパイルできると便利.md),
[20260714-3カ月で作り上げる計画](20260714-3カ月で作り上げる計画.md)

---

## 依存関係 (第一弾で .a 化したので図が変わった)

```
openmc.exe  (全静的、DLL 0個)
└─ liblibopenmc.a
   ├─ libhdf5.a / libhdf5_hl.a   【必須】断面積・出力の I/O
   ├─ libdagmc.a                 【任意・コンパイル時】← 今回追加
   │  └─ libMOAB.a               メッシュ DB
   │     └─ libhdf5.a            (.h5m も HDF5 形式。第一弾のものを共用)
   ├─ libfmt.a / libpugixml.a    vendored
   └─ (MPI は使わない)
```

Python 側は XML 生成と結果読み出しのみで、どちらも純 Python。`openmc.lib` は `.a` 構成では
読めないが `lib-optional.patch` により `Model.run()` は素通りする。

---

## PULL_INSTALL_MOAB は使わない

当初は「まず試す」つもりだったが、ソースを読んだ結果**この環境では原理的に動かない**と判断した。

- **未リリース**。最新タグ `v3.2.4` (2025-01-07) に `cmake/MOAB_PullAndMake.cmake` が
  存在しない (404)。develop 限定の機能
- **MOAB を共有ライブラリに強制**する。`-DBUILD_SHARED_LIBS:BOOL=ON` がハードコードで
  逃げ道が無い
- **MinGW で壊れたパスを組む**。`libMOAB${CMAKE_SHARED_LIBRARY_SUFFIX}` は
  `lib/libMOAB.dll` を指すが、MinGW がリンクするのはインポートライブラリ
  `lib/libMOAB.dll.a` で、DLL 自体は `bin/` に入る。二重に誤り
- **変数名バグが2件生きている**
  - 静的ビルド禁止のガードが `DAGMC_BUILD_STATIC_LIBS` を見ている。実際の option 名は
    `BUILD_STATIC_LIBS` なので**発火せず**、後段のリンクで不可解に落ちる
  - `IF (DEFINED ${EIGEN3_DIR})` が参照外し済みの値を見るので `EIGEN3_DIR` 指定が効かない

---

## 方針: 全静的 + OpenMC を1語パッチ

OpenMC の `CMakeLists.txt:536` は

```cmake
target_link_libraries(libopenmc dagmc-shared)
```

と**共有ライブラリ名を直書き**しており `dagmc-static` 分岐が無い。DAGMC 側の target 名は
`BUILD_SHARED_LIBS` / `BUILD_STATIC_LIBS` に応じて `dagmc-shared` / `dagmc-static` が
作られるので、静的のみで建てると OpenMC の configure が「target が無い」で落ちる。

対処は2案あり、**OpenMC を1語パッチして全静的**を採る。

| | 全静的 (採用) | 共有+静的の両建て |
|---|---|---|
| MOAB | `BUILD_SHARED_LIBS=OFF` | `ON` が必要 |
| OpenMC | 1語パッチ | 無改造 |
| 成果物 | `openmc.exe` 単体 | + `libdagmc.dll` + `libMOAB.dll` |

決め手は MOAB 側のバグ。`if (BUILD_SHARED_LIBS AND WIN32)` の中で

```cmake
add_definitions(/DMOAB_DLL)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /D_USE_MATH_DEFINES")
```

と **MSVC 構文のフラグを GCC に渡している**。GCC はこれをファイルパスと解釈するので
`cc1plus: error: /DMOAB_DLL: No such file or directory` になる。
静的ならこのブロックごと通らないので、**問題が構造的に消える**。第一弾で得た
スタンドアローン性を維持できるのも大きい。代償は上流パッチが1つ増えること。

---

## ビルド構成

### MOAB 5.6.0 (静的) — 山場

入手は Bitbucket が現役だが、**tarball を使う** (git clone 不要)。
`https://web.cels.anl.gov/projects/sigma/downloads/moab/moab-5.6.0.tar.gz`
sha256 `8d24a38619eb9fd326c7bdf9fdb01466149a0ab7dc3ef1caffda728858bf5a85`

```
-DBUILD_SHARED_LIBS=OFF          ← /DMOAB_DLL バグを構造的に回避
-DENABLE_HDF5=ON -DHDF5_ROOT=<prefix>
-DENABLE_BLASLAPACK=OFF          ← 既定 ON。FIND_PACKAGE(BLAS REQUIRED) で即死するので必須
-DENABLE_FORTRAN=OFF             ← 既定 ON
-DENABLE_TESTING=OFF             ← 既定 ON
-DENABLE_PYMOAB=OFF -DENABLE_NETCDF=OFF -DENABLE_MPI=OFF
-DENABLE_METIS=OFF -DENABLE_ZOLTAN=OFF -DENABLE_TEMPESTREMAP=OFF
-DENABLE_CGNS=OFF -DENABLE_CPM=OFF
```

**Eigen3 は不要**。`ENABLE_EIGEN3` は既定 OFF で、有効化しても optional 扱い。
BLASLAPACK と TempestRemap を切れば要求されない。

**要パッチ**: `CMakeLists.txt` の

```cmake
if (NOT WIN32 OR MSYS OR MINGW) # Need further work to prepare for windows
  add_subdirectory( tools )
```

は MSVC を除外する意図だが、MinGW では `MINGW` が真になるため**かえって `tools/` が建つ**。
`tools/` は最も移植性の低いサブツリー (POSIX の getopt/unistd を使う) で、DAGMC は
`libMOAB` しか要らない。`if (NOT WIN32)` に狭めて丸ごと飛ばす。

### DAGMC v3.2.4 (静的)

develop の唯一の差分が使わない `PULL_INSTALL_MOAB` なので、タグ付きリリースを使う。

```
-DMOAB_DIR=<prefix>              ← install prefix。FindMOAB が ${MOAB_DIR}/lib*/cmake/MOAB を glob
-DBUILD_STATIC_LIBS=ON -DBUILD_SHARED_LIBS=OFF
-DBUILD_UWUW=OFF -DBUILD_TALLY=OFF        ← 既定 ON。OpenMC は使わない
-DBUILD_BUILD_OBB=OFF -DBUILD_MAKE_WATERTIGHT=OFF -DBUILD_OVERLAP_CHECK=OFF
-DBUILD_TESTS=OFF -DBUILD_CI_TESTS=OFF
-DBUILD_EXE=OFF -DBUILD_STATIC_EXE=OFF -DBUILD_RPATH=OFF
-DDOUBLE_DOWN=OFF -DPULL_INSTALL_MOAB=OFF
```

`DAGMCConfig.cmake` は `@CMAKE_INSTALL_PREFIX@` を焼き込むので**再配置不可**。
最終的な場所に直接インストールする。

### OpenMC

```
-DOPENMC_USE_DAGMC=ON -DOPENMC_USE_UWUW=OFF
-DCMAKE_PREFIX_PATH=<prefix>
```

`OPENMC_USE_UWUW` は OFF のまま。DAGMC 側を `BUILD_UWUW=OFF` で建てるので、ON にすると
`DAGMC_BUILD_UWUW` が OFF で `FATAL_ERROR` になる。

### patches/ の再編

現状は `patches/*.patch` を**全部 `src/openmc` に当てる**実装。MOAB にもパッチが要るので
当て先ごとに分ける。

```
patches/
  openmc/ lib-optional.patch      (既存、リネーム)
          static-lib.patch        (既存、リネーム)
          dagmc-static.patch      (新規: dagmc-shared → dagmc-static)
  moab/   skip-tools.patch        (新規)
```

MOAB は tarball 展開で git 管理外なので `git apply` ではなく `patch -p1` を使う。

---

## 検証

**OpenMC 付属の pytest 回帰テストは使えない。** `tests/regression_tests/dagmc/*/test.py` が
module 直下で `import openmc.lib` と `openmc.lib._dagmc_enabled()` を呼ぶため、`.a` 構成では
skip ではなく **FileNotFoundError で collection エラー**になる。

一方で**検証用の .h5m は既に手元にある** (実測確認済み)。

| ファイル | サイズ | 状態 |
|---|---|---|
| `tests/regression_tests/dagmc/legacy/dagmc.h5m` | 1,233,364 B | HDF5 実体 |
| `tests/regression_tests/dagmc/refl/dagmc.h5m` | 1,251,162 B | HDF5 実体 |
| `tests/regression_tests/dagmc/universes/dagmc.h5m` | 1,233,488 B | HDF5 実体 |
| `tests/unit_tests/dagmc/dagmc.h5m` | 45 B | **symlink 破損** (テキスト) |
| `tests/regression_tests/dagmc/external/dagmc.h5m` | 19 B | **symlink 破損** (テキスト) |

`core.symlinks=false` のため一部がポインタのテキストになっている。今回使う3つは実体なので
影響しないが、踏むと「HDF5 が開けない」という分かりにくいエラーになる。

### 3段階

**(1) ビルド確認** — `openmc.exe --version` が `DAGMC support: yes`

**(2) 構造確認 (核データ不要、まずここを通す)**

`DAGMCUniverse.n_cells` / `n_surfaces` は `_n_geom_elements` が **h5py で .h5m を直接読む**
実装なので `openmc.lib` に触れない (`openmc/dagmc.py` を読んで確認済み。`openmc.lib` を
使うのは `sync_dagmc_cells` だけで、これは in-memory API 用なので使わない)。

```python
u = openmc.DAGMCUniverse(".../legacy/dagmc.h5m")
assert u.n_cells == 5      # 燃料2 + 水 + graveyard + implicit complement
assert u.n_surfaces == 21  # 円柱3本(9) + 外周立方殻(12)
```

これが通れば MOAB/DAGMC のリンクと .h5m のパースが成立している。

**(3) 輸送計算 (legacy 相当を自作)**

`legacy/test.py` を `openmc.lib` 非依存に書き直す。期待値は同ディレクトリの
`results_true.dat`:

```
k-combined: 1.083415E+00 ± 5.991738E-02
tally 1:    8.862860E+00, 1.602117E+01
```

5 batches × 100 particles、線源は `Box([-4,-4,-4],[4,4,4])`。材料は U235 (11 g/cc, id=40) と
水 (1.0 g/cc, id=41) で、**名前経由 (`mat:no-void fuel`) と ID 経由 (`mat:41`) の両方**の
材料バインドを踏む。

必要な核データは U235 / H1 / O16 + `c_H_in_H2O` (熱中性子散乱則)。現在の
`sandbox-openmc/data/` は Li6/Li7 のみなので**別途取得が要る**。FENDL は S(α,β) を
持たないので、ENDF/B-VIII.0 から該当核種を取るか `openmc_data_downloader` で核種指定で落とす。

置き場所は `sandbox-openmc-source/tests/` (sandbox-openmc は CSG 検証専用のまま)。

---

## 撤退基準

3カ月計画のリスク欄「OpenMC/DAGMC の環境構築が重い場合、TBR は W8 時点では均一組成の
簡易モデルで代替し、W10 で本計算に戻す」に従う。

**MOAB の静的ビルドに2週を超えて詰まったら中断**し、W7 の CAD→中性子経路は
WSL2 + conda-forge (`openmc=*=dagmc_nompi_*`、ParaStell と同一構成) に退避する。
第一弾の成果 (ネイティブ CSG OpenMC) はそれとは独立に残る。

判断を早めるため、**MOAB を最初に単独で通す**。DAGMC と OpenMC は MOAB さえ通れば
比較的素直なはずで、どちらも上流に MSVC 向けの足場があり MinGW との差分が小さい。

### 楽観しない理由

**MOAB を Windows でパッケージした前例が皆無**である。

- conda-forge の moab-feedstock は `skip: win` を明示し、パッチも1枚も無い
  (しかも CMake ではなく autotools でビルドしている)
- vcpkg にポートが無い (`ports/moab`、`ports/dagmc` とも 404)
- 上流自身が `# Need further work to prepare for windows` と書いている

第一弾で OpenMC が通ったのは依存が薄かったから (必須外部依存が HDF5 だけ、POSIX 依存が
ほぼ皆無)。MOAB はそれとは事情が違う。

---

## 実施順序

1. `patches/` をプロジェクト別に再編、`APPLY_PATCHES` を一般化 (既存2パッチのリネーム含む)
2. MOAB を単独で通す ← **山場。ここで止まるなら早く判断する**
3. DAGMC
4. OpenMC に `OPENMC_USE_DAGMC=ON` + `dagmc-static.patch`
5. 検証 (1)(2) — 核データ不要なのでここまで先に通す
6. 核データを取得して検証 (3)
7. README/notes 更新、PR
