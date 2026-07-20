# sandbox-openmc-source — OpenMC を Windows ネイティブ (MinGW-w64) でビルドするサンドボックス

OpenMC と依存の HDF5 をソースから **MinGW-w64 でビルド**し、[sandbox-openmc](../sandbox-openmc) の
未衝突中性子減衰の解析解検証を **Docker なしで**完走させる。ビルド設定・中間物・成果物は
すべてこのディレクトリ内に閉じる。動機は
[notes/20260720-openmc-dagmc-moabをwindowsでコンパイルできると便利.md](../notes/20260720-openmc-dagmc-moabをwindowsでコンパイルできると便利.md)
— Docker 不要、Python/Rust バインディングへの道、OpenMC 内部の理解。

**結果: 通った。** MinGW ネイティブビルドの `openmc.exe` で sandbox-openmc の検証が PASS し
(最大相対誤差 0.115%、閾値 2%)、Docker (Linux/GCC) 版の出力との差は **最大 7.3e-10**
(統計誤差より8桁小さい) だった。OpenMC 公式は Windows ネイティブを未サポートで
([issue #1243](https://github.com/openmc-dev/openmc/issues/1243) は MSVC 前提、
[PR #2919](https://github.com/openmc-dev/openmc/pull/2919) は draft のまま)、
MinGW での前例は探した範囲では見つからなかった。

## 使い方

必要要件: MinGW-w64 GCC (C++17)、CMake (3.16 以上)、GNU make、git、curl/unzip/tar、
[uv](https://docs.astral.sh/uv/)、bash (Git Bash 可)。ビルドツールの自動取得は行わない。
CMake が PATH に無い場合は `make CMAKE=/path/to/cmake ...` で指定できる。

```sh
make -C sandbox-openmc-source build     # 段1〜3 を通してビルド (初回は 15〜30 分)
make -C sandbox-openmc-source check     # openmc --version / import openmc / 断面積の確認
make -C sandbox-openmc-source clean     # build/ prefix/ venv/ を削除 (src/ は残す)
```

sandbox-openmc をこのビルドで回す (`epotFoam` と同じ「サブ makefile が toolchain を所有し、
親にはラッパーのパスを渡す」イディオム):

```sh
cd sandbox-openmc
make compare OPENMC="$(make -s --no-print-directory -C ../sandbox-openmc-source WORK=$(pwd))"
```

`sandbox-openmc/makefile` は**一切変更していない**。切り替えは `OPENMC` 変数の上書きだけで
済むので、Docker 経路は無傷で残る (失敗時の退路)。

## ビルドの段

```
段1  HDF5 2.1.1 (静的、C + HL、圧縮フィルタ無し)  → prefix/lib/libhdf5.a
段2  OpenMC (develop, CSG のみ / DAGMC なし)   → prefix/bin/openmc.exe + libopenmc.dll
段3  uv venv + openmc python パッケージ         → venv/
```

## 設計判断と根拠

| 判断 | 選択 | 根拠 |
|---|---|---|
| ジェネレータ | `MinGW Makefiles` | 古い CMake は `sh.exe` が PATH にいるとこのジェネレータを拒否したが、3.31 では Git Bash 上でも通る (実測)。システムの make をそのまま使えるので外部ツールの取得が要らない。`MSYS Makefiles` はコンパイラ検査で落ちるので不可 |
| OpenMC の版 | `develop` (既定) | v0.15.3 は `vendor/` に `xtensor`/`xtl` を含むが develop では削除済み。テンプレート重量級の依存が減り MinGW でのリスクが小さい (実測で `.gitmodules` を確認) |
| HDF5 の版 | 2.1.1 | 2.x は autotools 廃止で CMake のみ。かつ `H5detect`/`H5make_libsettings` (ビルド時実行バイナリ) が 1.14 系で削除済みで、歴史的な最大の移植障壁が消えている |
| HDF5 のリンク形態 | 静的 (`BUILD_SHARED_LIBS=OFF`) | Windows の DLL シンボル export 問題を丸ごと回避する。OpenMC は C API と HL しか使わない (`COMPONENTS C HL`) ので C++ API は不要 |
| zlib (deflate フィルタ) | **無効** (`HDF5_ENABLE_ZLIB_SUPPORT=OFF`、HDF5 2.x の既定と同じ) | 実測で不要と確認したため (下記「zlib を無効にした根拠」)。有効にすると zlib の取得・ビルドに加え、静的 HDF5 の未解決シンボルを潰すリンク順の細工まで必要になる |
| OpenMP | まず OFF | 段階的に切り分けるため。MinGW の libgomp は成熟しているので後から ON にできる (MSVC 路線が `/openmp:llvm` で苦労したのとは対照的) |
| 断面積 | sandbox-openmc の既存 `data/` を再利用 | `build_xs.py` が `njoy_exec="njoy"` とハードコードしており、NJOY21 (Fortran 2008) の MinGW ビルドは別プロジェクト。既存データがあれば第一弾には不要 |
| DAGMC/MOAB | 第一弾では扱わない | CSG のみの sandbox-openmc には不要。第二弾の方針は下記 |

## 詰まった点と対処 (すべて実測)

上流のコード変更は `patches/openmc-lib-windows.patch` の1件だけで済んだ。残りは
ビルドオプションで解決できる。

1. **`CC ?= gcc` が効かない** — GNU Make は `CC`/`CXX` に組み込みデフォルト (`cc`,
   `x86_64-w64-mingw32-g++`) を持つので `?=` は発火しない。存在しない `cc` を掴んで
   configure が落ちる。`=` にする (コマンドライン指定は依然優先される)。
2. **HDF5 初回ビルドが8並列で全滅** (Ninja 使用時) — 出力ディレクトリ作成とコンパイルが
   競合し `opening dependency file ...obj.d: No such file or directory` になった。
   ディレクトリさえ出来れば2回目は素通りする。**`MinGW Makefiles` に移行してからは
   再現しない**ので、ジェネレータの変更がそのまま対処になっている
   (一時的に入れていたリトライ処理は削除した)。
3. **`M_PI` が未宣言** — MinGW の `math.h` は strict ANSI だと `M_PI` を隠し、OpenMC は
   `CMakeLists.txt:599` の `CXX_EXTENSIONS OFF` で `-std=c++17` を選ぶ。`src/mesh.cpp:6` は
   `_USE_MATH_DEFINES` を定義しているが、1行目の `openmc/mesh.h` から `math.h` が先に
   読まれるため手遅れ (コメントどおり Intel/MSVC 向けの対処で MinGW は想定外)。
   `-D_USE_MATH_DEFINES` をコマンドラインで渡す。
4. **`openmc.exe` が無言で終了コード 127** — `libopenmc.dll` が依存する
   `libstdc++-6` / `libgcc_s_seh-1` / `libwinpthread-1` の解決失敗。DLL 解決は Windows の
   ローダ段階なので stderr に何も残らない。ラッパーが MinGW の bin を PATH に足す。
   なお `-static-libgcc -static-libstdc++` で畳む案は使えない: MinGW の ld が DLL の
   全シンボルを自動エクスポートするため `_Unwind_Resume` が二重定義になる。
5. **起動プレフィックスの1行渡しが壊れる** — Windows の PATH には `/c/Program Files/...` の
   ように空白を含む要素があり、コマンド置換の結果は引用符が再解釈されないのでクォートでは
   防げない。**空白を含まないラッパーのパス1個**を渡す形にした
   (`epotFoam` が `openfoam.sh` を渡しているのと同じ形)。
6. **`openmc.lib` は「使わなければ関係ない」ものではない** — `Model.run()` が
   `is_initialized` 経由で無条件に import する。`openmc/lib/__init__.py` は共有ライブラリの
   拡張子を darwin なら `dylib`、それ以外は `so` と決め打ちで `win32` 分岐が無いので
   パッチを当てる。さらに Python 3.8 以降の `ctypes.CDLL` は PATH を DLL 検索に使わないため、
   `libopenmc.dll` と MinGW ランタイム DLL を `site-packages/openmc/lib/` に**隣接配置**する
   (絶対パス指定時は `LOAD_WITH_ALTERED_SEARCH_PATH` で DLL 自身のディレクトリが探索される)。

## zlib を無効にした根拠

当初は「配布ライブラリが deflate 済みかもしれない」という懸念から zlib を有効化していたが、
**実測の結果その懸念は外れていた**ので無効化した。

| 対象 | データセット数 | 圧縮 | チャンク化 |
|---|---|---|---|
| FENDL 3.2 全 253 ファイル | 115,827 | **0** | **0** |
| 手元の Li6/Li7 断面積 | 402 | 0 | 0 |
| OpenMC の statepoint / summary 出力 | 301 | 0 | 0 |

理由も明快で、**OpenMC のツールチェーンは圧縮を書く経路を持たない** —
`openmc.data` の `create_dataset` に `compression=` 引数が無く、
`src/hdf5_interface.cpp` にも `H5Pset_deflate` の呼び出しが無い。
HDF5 のフィルタはチャンク化が前提なので、チャンク化ゼロは「フィルタが構造的に使われ得ない」
ことも意味する。

有効化のコストは小さくなかった。zlib のソース取得とビルドに加え、静的 HDF5 が要求する
`inflateEnd` 等を解決するために **`CMAKE_CXX_STANDARD_LIBRARIES` へ渡してリンク行の末尾に
置く**という細工が要る (`CMAKE_{EXE,SHARED}_LINKER_FLAGS` だとリンク行の前方に展開され、
GNU ld は静的ライブラリを左から右に一度しか走査しないので捨てられる)。
ビルド設定で一番ややこしい部分が zlib のためだけに存在していた。

未検証: ENDF/B-VIII.0 フル、TENDL、`h5repack` で再圧縮された第三者ファイル。
必要になったら `HDF5_ENABLE_ZLIB_SUPPORT=ON` + `ZLIB_USE_EXTERNAL=ON` +
`HDF5_ALLOW_EXTERNAL_SUPPORT=TGZ` の3点セットに戻して再ビルドする (約20分)。
なお 2.x でオプション名が `HDF5_ENABLE_Z_LIB_SUPPORT` → `HDF5_ENABLE_ZLIB_SUPPORT` に
改名されており、**旧綴りはエラーにならず黙って無視される**点に注意。

## 既知の制約

- **`make -C sandbox-openmc data` は通らない**。`build_xs.py` が `njoy` 実行ファイルを要求する
  (`njoy_exec="njoy"`)。既存の `data/` を再利用するか、断面積生成だけ Docker で回すか、
  `LIB=full` (NJOY 不要、数GB ダウンロード) を使う。
- **版はクローンの深さに依存する**。`--depth 1` だけだとタグが無く `git describe` が
  失敗し、`openmc --version` が `0.0.0` になる。makefile はクローン後に
  `git fetch --tags --deepen=2000` を追加で走らせてこれを回避している
  (実測: C++ 側 `0.15.4-dev211` / Python 側 `0.15.4.dev211+g05d01274a`)。
  なお `version.h` は CMake のキャッシュ経由で生成されるため、後から履歴を深くしても
  `build/openmc` を消さないと版が更新されない。
- **OpenMP は無効**。段階的な切り分けのため OFF にしてある。
- **DAGMC 無効** (`DAGMC support: no`)。CSG のみ。
- `develop` を追うので上流の変更でいつ壊れてもおかしくない。壊れたら
  `OPENMC_REF` を効いていたコミットに固定する。

## 第二弾 (DAGMC + MOAB) の方針

当初案の `-DPULL_INSTALL_MOAB=<version>` は**採らない**。調査の結果:

- [PR #969](https://github.com/svalinn/DAGMC/pull/969) のマージ (2025-02-06) は最新リリース
  v3.2.4 (2025-01-07) より後で、**どのタグ付きリリースにも入っていない develop 限定機能**
- `cmake/MOAB_PullAndMake.cmake` は静的ライブラリと併用すると `FATAL_ERROR` で落ち、
  MOAB に `BUILD_SHARED_LIBS=ON` を強制する。一方 MOAB の MinGW 唯一の成功報告
  ([Bitbucket #127](https://bitbucket.org/fathomteam/moab/issues/127/moab-and-mingw64-msys2), MOAB 5.2.1) は**静的ビルド**で、共有ビルドは
  `__imp__ZN4moab...` の未定義参照で失敗している。**両者はほぼ排他**
- 同ファイルはリンク先を `libMOAB${CMAKE_SHARED_LIBRARY_SUFFIX}` とハードコードしており、
  MinGW では `libMOAB.dll.a` にリンクする必要があるためこの経路自体が壊れている

→ **MOAB を静的に自前ビルドし、DAGMC に `-DMOAB_DIR=` で渡す**。撤退基準は
[3カ月計画](../notes/20260714-3カ月で作り上げる計画.md)のリスク欄に従い、MOAB に2週を超えて
詰まったら WSL2 + conda-forge (`openmc=*=dagmc_nompi_*`, ParaStell と同一構成) に退避する。
第一弾の成果はそれとは独立に残る。

## 出典

- [OpenMC](https://github.com/openmc-dev/openmc) — MIT License
- [HDF5](https://github.com/HDFGroup/hdf5) — BSD-style (HDF Group)
- [CMake](https://cmake.org/) — システム導入済みのものを使う (取得しない)
