# sandbox-openmc-source — OpenMC を Windows ネイティブ (MinGW-w64) でビルドするサンドボックス

OpenMC と依存の HDF5 / MOAB / DAGMC をソースから **MinGW-w64 でビルド**し、
[sandbox-openmc](../sandbox-openmc) の未衝突中性子減衰の解析解検証を **Docker なしで**
完走させる。ビルド設定・中間物・成果物はすべてこのディレクトリ内に閉じる。動機は
[notes/20260720-openmc-dagmc-moabをwindowsでコンパイルできると便利.md](../notes/20260720-openmc-dagmc-moabをwindowsでコンパイルできると便利.md)
— Docker 不要、Python/Rust バインディングへの道、OpenMC 内部の理解。

**結果: 通った。** MinGW ネイティブビルドの `openmc.exe` で sandbox-openmc の検証が PASS し
(最大相対誤差 0.115%、閾値 2%)、Docker (Linux/GCC) 版の出力との差は **最大 7.3e-10**
(統計誤差より8桁小さい) だった。**DAGMC (CAD 由来の .h5m ジオメトリ) も有効**で
(`DAGMC support: yes`)、MOAB・DAGMC・HDF5・libopenmc すべて静的なので
`openmc.exe` は非システム DLL に一切依存しない。OpenMC 公式は Windows ネイティブを未サポートで
([issue #1243](https://github.com/openmc-dev/openmc/issues/1243) は MSVC 前提、
[PR #2919](https://github.com/openmc-dev/openmc/pull/2919) は draft のまま)、
MinGW での前例は探した範囲では見つからなかった。

## 使い方

必要要件: MinGW-w64 GCC (C++17)、CMake (3.16 以上)、GNU make、git、curl/unzip/tar、
[uv](https://docs.astral.sh/uv/)、bash (Git Bash 可)。ビルドツールの自動取得は行わない。
CMake が PATH に無い場合は `make CMAKE=/path/to/cmake ...` で指定できる。

```sh
make -C sandbox-openmc-source           # (デフォルト) 全段ビルドし、環境設定ラッパーのパスを印字
make -C sandbox-openmc-source check     # openmc --version / import openmc / DAGMC / 断面積の確認
make -C sandbox-openmc-source DAGMC=0   # CSG 専用構成 (MOAB/DAGMC を建てない)
make -C sandbox-openmc-source OPENMP=OFF  # 並列を切る
make -C sandbox-openmc-source clean     # src/ build/ prefix/ venv/ を全削除
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
段1    HDF5 2.1.1 (静的、C + HL、圧縮フィルタ無し) → prefix/lib/libhdf5.a
段1.5  MOAB 5.6.0  (静的)                        → prefix/lib/libMOAB.a
段1.6  DAGMC v3.2.4 (静的)                       → prefix/lib/libdagmc.a
段2    OpenMC (develop, DAGMC + OpenMP 有効)     → prefix/bin/openmc.exe (14.7 MB, 全静的)
段3    uv venv + openmc python パッケージ         → venv/

DAGMC=0 を渡すと段1.5/1.6 を飛ばして CSG 専用構成に戻る (退路)。
```

## 設計判断と根拠

| 判断 | 選択 | 根拠 |
|---|---|---|
| ジェネレータ | `MinGW Makefiles` | 古い CMake は `sh.exe` が PATH にいるとこのジェネレータを拒否したが、3.31 では Git Bash 上でも通る (実測)。システムの make をそのまま使えるので外部ツールの取得が要らない。`MSYS Makefiles` はコンパイラ検査で落ちるので不可 |
| OpenMC の版 | `develop` (既定) | v0.15.3 は `vendor/` に `xtensor`/`xtl` を含むが develop では削除済み。テンプレート重量級の依存が減り MinGW でのリスクが小さい (実測で `.gitmodules` を確認) |
| HDF5 の版 | 2.1.1 | 2.x は autotools 廃止で CMake のみ。かつ `H5detect`/`H5make_libsettings` (ビルド時実行バイナリ) が 1.14 系で削除済みで、歴史的な最大の移植障壁が消えている |
| HDF5 のリンク形態 | 静的 (`BUILD_SHARED_LIBS=OFF`) | Windows の DLL シンボル export 問題を丸ごと回避する。OpenMC は C API と HL しか使わない (`COMPONENTS C HL`) ので C++ API は不要 |
| zlib (deflate フィルタ) | **無効** (`HDF5_ENABLE_ZLIB_SUPPORT=OFF`、HDF5 2.x の既定と同じ) | 実測で不要と確認したため (下記「zlib を無効にした根拠」)。有効にすると zlib の取得・ビルドに加え、静的 HDF5 の未解決シンボルを潰すリンク順の細工まで必要になる |
| OpenMP | **有効** (`OPENMP=ON`) | MinGW の libgomp は成熟しており `-fopenmp` がそのまま通る (MSVC 路線が `/openmp:llvm` で苦労したのとは対照的)。実測で 1→8 スレッド 4.8 倍。`OPENMP=OFF` で切れる |
| 断面積 | sandbox-openmc の既存 `data/` を再利用 | `build_xs.py` が `njoy_exec="njoy"` とハードコードしており、NJOY21 (Fortran 2008) の MinGW ビルドは別プロジェクト。既存データがあれば第一弾には不要 |
| DAGMC/MOAB のリンク形態 | 静的 | 共有にすると MOAB の `if (BUILD_SHARED_LIBS AND WIN32)` が `add_definitions(/DMOAB_DLL)` という **MSVC 構文のフラグを GCC に渡す** (GCC はファイルパスと解釈して落ちる)。静的ならこのブロックごと通らず問題が構造的に消える |
| MOAB の入手 | **git clone** (tarball 不可) | 配布 tarball は autotools の `make dist` 産物で `config/{logging,dist,distcheck}.cmake` が同梱漏れ。CMake の configure が `include could not find requested file` で即死する (実測。3ファイルとも git 側には存在) |
| `PULL_INSTALL_MOAB` | **使わない** | 未リリース (v3.2.4 に無い)、MOAB を共有に強制、MinGW で壊れたリンクパスを組む、変数名バグ2件。詳細は下記 |

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
   `is_initialized` 経由で無条件に import する。共有ライブラリを作らない構成では
   `ctypes.CDLL` が `FileNotFoundError` を投げるが、上流の `try/except` は `ImportError`
   しか捕まえないので素通りできない。上流は明らかに `openmc.lib` を任意扱いする意図で
   書いているので、`patches/openmc/lib-optional.patch` で `except (ImportError, OSError)`
   に広げる。これが DLL 無し構成を成立させている。
7. **MOAB の配布 tarball では CMake ビルドが成立しない** — `moab-5.6.0.tar.gz` は autotools の
   `make dist` 産物で、`config/{logging,dist,distcheck}.cmake` が同梱漏れしている。configure が
   `include could not find requested file: config/logging.cmake` で即死する。3ファイルとも
   git 側には存在するので、**git clone に切り替える**のが解。
8. **`-static` でも libgomp だけ動的に残る** — CMake の `FindOpenMP` は libgomp を
   **インポートライブラリの絶対パス** (`.../libgomp.dll.a`) として渡してくる。絶対パス指定は
   `-static` では覆せないので `openmc.exe` が `libgomp-1.dll` に依存してしまう
   (実測: `objdump -p` に現れる)。`OpenMP_gomp_LIBRARY` を静的版 `libgomp.a` に上書きして解決。
9. **DAGMC が静的 HDF5 を見つけられない** — `cmake/FindMOAB.cmake` は
   `CMAKE_FIND_LIBRARY_SUFFIXES` を共有側に固定して `find_package(HDF5 REQUIRED)` を呼び、
   静的パスは**文字列置換で導出**する。共有 HDF5 の存在が暗黙の前提なので、静的のみだと
   `Could NOT find HDF5 (missing: HDF5_LIBRARIES)` になる。探索する拡張子を
   `BUILD_SHARED_LIBS` に応じて切り替えるのが `patches/dagmc/static-hdf5.patch`。

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
- **DAGMC の輸送計算は未検証**。`DAGMC support: yes` になり `.h5m` のパースと
  トポロジ読み出し (`n_cells` / `n_surfaces`) までは確認済みだが、実際に粒子を飛ばす
  検証は核データ (U235 / H1 / O16 + `c_H_in_H2O`) 未取得のため未実施。
- **OpenMC 付属の DAGMC 回帰テストは使えない**。`tests/regression_tests/dagmc/*/test.py` が
  module 直下で `import openmc.lib` を呼ぶため、共有ライブラリを作らないこの構成では
  skip ではなく **collection エラー**になる。自前のテストで代替する必要がある。
- **`libMOAB.a` のアーカイブ作成が一度 `file truncated` で落ちた**。オブジェクトもコマンド長も
  健全で、再実行すると通った。原因は未特定 (一過性と判断)。
- `develop` を追うので上流の変更でいつ壊れてもおかしくない。壊れたら
  `OPENMC_REF` を効いていたコミットに固定する。

## DAGMC / MOAB について

`PULL_INSTALL_MOAB` は**使わない**。ソースを読んだ結果、この環境では原理的に動かない。

- **未リリース**。最新タグ v3.2.4 (2025-01-07) に `cmake/MOAB_PullAndMake.cmake` が存在しない
  ([PR #969](https://github.com/svalinn/DAGMC/pull/969) のマージは 2025-02-06 で、それ以降タグが無い)
- **MOAB を共有に強制**。`-DBUILD_SHARED_LIBS:BOOL=ON` がハードコードで逃げ道が無い
- **MinGW で壊れたパスを組む**。`libMOAB${CMAKE_SHARED_LIBRARY_SUFFIX}` は `lib/libMOAB.dll` を
  指すが、MinGW がリンクするのはインポートライブラリ `lib/libMOAB.dll.a` で DLL は `bin/` に入る
- **変数名バグ2件**。静的ビルド禁止のガードが `DAGMC_BUILD_STATIC_LIBS` (実際の option 名は
  `BUILD_STATIC_LIBS`) を見ているので発火せず、後段のリンクで不可解に落ちる。
  `IF (DEFINED ${EIGEN3_DIR})` も参照外し済みの値を見るので `EIGEN3_DIR` 指定が効かない

代わりに **MOAB と DAGMC を静的に自前ビルドし、`-DMOAB_DIR=` で渡す**。

### 全静的にした代償

OpenMC は `target_link_libraries(libopenmc dagmc-shared)` と**共有ライブラリ名を直書き**して
おり `dagmc-static` 分岐が無い。静的のみで建てると configure が「target が無い」で落ちる。
`patches/openmc/dagmc-static.patch` で1語だけ書き換えている。

共有にすれば OpenMC は無改造で通るが、MOAB を共有にする必要があり `/DMOAB_DLL` の
MSVC 構文フラグ問題に正面から当たる。加えて `libdagmc.dll` + `libMOAB.dll` を同梱すること
になり、スタンドアローン性を失う。**上流パッチ1枚の方が安い**と判断した。

### Eigen3 は不要

`ENABLE_EIGEN3` は既定 OFF で、`ENABLE_BLASLAPACK=OFF` と `ENABLE_TEMPESTREMAP=OFF` に
すれば要求されない。DAGMC の `moab_autobuild_check_deps` は Eigen3 を必須にしているが、
それは `PULL_INSTALL_MOAB` の経路だけなので、MOAB を単独で建てれば回避できる。

### 誰も Windows で MOAB を建てていない

conda-forge の moab-feedstock は `skip: win` を明示しパッチも無い (しかも CMake ではなく
autotools でビルドしている)。vcpkg にポートも無い。上流自身が
`# Need further work to prepare for windows` と書いている。実際に踏んだのは
`tools/` のガードと tarball の同梱漏れの2点だけだったが、前例が無い以上ここは
壊れやすいと見ておくべき。

## 出典

- [OpenMC](https://github.com/openmc-dev/openmc) — MIT License
- [HDF5](https://github.com/HDFGroup/hdf5) — BSD-style (HDF Group)
- [MOAB](https://bitbucket.org/fathomteam/moab) — LGPL v3
- [DAGMC](https://github.com/svalinn/DAGMC) — BSD 3-Clause
- [CMake](https://cmake.org/) — システム導入済みのものを使う (取得しない)
