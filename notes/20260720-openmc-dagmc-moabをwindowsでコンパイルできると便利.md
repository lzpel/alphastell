# sandbox_openmc_source openmc/dagmc/moab を windows でコンパイルできると便利

Docker不要、pythonやrustバインディングにすることも可能
openmcへの理解が深まる

## 全体構成

import openmc
- libopenmc.so(conda経由でライブラリが入る、尚openmcは実行ファイルもライブラリも両方存在)
  - libhdf5 【必須】断面積/出力の I/O
  - libmpich     並列
  - libdagmc 【任意・コンパイル時】
    - libMOAB   メッシュDB
      - libhdf5  (.h5mも HDF5 形式)

疑問：登場人物 hdf5 mpich dagmc moab は openmcシミュレーション時にopenmc以外の経路から呼び出す可能性があるのか？つまり一度ビルドが通ってしまえばopenmcのフロントエンドはopenmcだけなので内部に何が組み込まれているのか気にしなくていいのか

## 設計判断 核種はFENDL-3.1dを使う

ParaStell も FENDL を使っています
Frontiers 論文（doi:10.3389/fnuen.2024.1384788）に OpenMC+DAGMC で FENDL-3.1d を使ったと明記されています。fusion-energy 系のツールも FENDL-3.1d 既定です。

---

## 結論: OpenMC (CSG) の MinGW ネイティブビルドは通った

2026-07-20 に実施。`sandbox-openmc-source/` に構成を置いた。
MinGW-w64 GCC 14.2.0 でビルドした `openmc.exe` で `sandbox-openmc` の未衝突中性子減衰の
解析解検証が **PASS** (最大相対誤差 0.115%、閾値 2%)。Docker (Linux/GCC) 版の出力との差は
**最大 7.3e-10** で、統計誤差より8桁小さい。事実上の同一性が取れている。

ビルドを通すのに必要な上流のコード変更は **1ファイル1箇所** だけだった
(`openmc/lib/__init__.py` に win32 分岐を足す = 下記 PR2)。残りはビルドオプションで解決。
なお別途見つけた `_USE_MATH_DEFINES` の不具合 (PR #4023) は、こちらが
`-D_USE_MATH_DEFINES` を渡して回避していたので、ビルドを通すだけなら必須ではない。詳細は
[sandbox-openmc-source/README.md](../sandbox-openmc-source/README.md) の
「詰まった点と対処」。

## なぜ思ったより通ったのか

事前の想定より障壁がずっと低かった。理由は3つ。

1. **OpenMC の POSIX 依存がほぼ皆無**。`unistd.h` は `isatty` のため、`dlfcn.h` は
   custom source library のためだけで、**どちらも既に `#ifdef` でガードされ非POSIX
   フォールバックがある**。ハードにコンパイルが壊れるファイルはゼロだった。
   `mcpl_interface.cpp` と `ncrystal_load.cpp` に至っては `LoadLibraryA`/`GetProcAddress` の
   Windows 実装が既に書かれている。
2. **必須外部依存が HDF5 だけ**。`find_package(HDF5 REQUIRED COMPONENTS C HL)` が唯一の
   無条件 `find_package` で、しかも C API と HL のみ (C++ API 不要)。
   `vendor/` の submodule は pugixml/fmt/Catch2 の3つで、**xtensor/xtl/gsl-lite は
   develop から削除済み**。テンプレート重量級の依存が消えたのが大きい。
3. **HDF5 2.x で `H5detect`/`H5make_libsettings` が消えた**。ビルド時に実行される
   生成バイナリが無くなり、HDF5 を移植困難にしていた歴史的な最大要因が解消している。
   2.x は autotools を捨てて CMake のみになったのも Windows では有利。

つまり「Windows ネイティブが無いのは技術的に無理だから」ではなく、
**単に誰もやっていないから**だった。OpenMC 側の姿勢も否定的ではなく、
[issue #1243](https://github.com/openmc-dev/openmc/issues/1243) で Paul Romano 自身が
「C++ と Python だけなので動かない理由は無い」と書いている。ただし議論は MSVC 前提で、
[PR #2919](https://github.com/openmc-dev/openmc/pull/2919) は draft のまま止まっている。
MinGW の前例は探した範囲では見つからなかった。

## 上流への還元 (実績)

### PR #4023 — 提出済み (2026-07-20, OPEN)

[openmc-dev/openmc#4023](https://github.com/openmc-dev/openmc/pull/4023)
`Fix M_PI being unavailable where _USE_MATH_DEFINES comes too late`
(fork: `lzpel:pr1-alt-use-pi` → `develop`、3ファイル +8/-10)

[PR #3238](https://github.com/openmc-dev/openmc/pull/3238) が
`mesh.cpp` / `plot.cpp` / `quartic_solver.cpp` に `#define _USE_MATH_DEFINES` を足したが、
**3ファイルとも定義位置が最初の include より下**にあり、その時点で `<cmath>` 経由で
`math.h` が読まれ済みなので効いていない。

| ファイル | MSVC 19.51 | MinGW GCC 14.2 | 対処 |
|---|---|---|---|
| `src/mesh.cpp` | 2 errors | 2 errors | `constants.h` の `PI` を使う |
| `src/plot.cpp` | 1 error | 1 error | 同上 |
| `src/external/quartic_solver.cpp` | 3 errors | ok | vendored なので `#define` を先頭へ移動 |

`quartic_solver.cpp` だけ結果が割れるのは、MSVC の `<algorithm>` が `math.h` に推移的に
到達し MinGW の libstdc++ は到達しないため。**どのヘッダが最初に到達するかは処理系定義**
なので、`mesh.cpp` / `plot.cpp` は `#define` を動かすのではなくマクロ依存自体を捨てた。

Linux GCC は無傷で、今後も無傷。g++ が `_GNU_SOURCE` を定義するので
`_USE_MATH_DEFINES` の有無に関わらず `M_PI` が見える。**だから CI は緑のままで、
この不具合は誰にも気づかれなかった。**

検証: MSVC 19.51.36248 と MinGW GCC 14.2.0 の両方で修正前後をコンパイル。
clang-format 18.1.8 で差分なし。`-D_USE_MATH_DEFINES` 無しの全体ビルドと
sandbox-openmc の解析解検証 (PASS、数値不変) も通した。

**教訓**: 当初は「MSVC でも壊れているはず」と推論で書こうとしていた。手元に MSVC が
無いまま断定するのは上流に対して不誠実で、指摘を受けて Visual Studio を入れて実測した。
結果は推論どおりだったが、**測る前に断定していたら信用を失っていた**。
さらに実測して初めて `quartic_solver.cpp` の MSVC/MinGW 差が判明し、PR の範囲が
2ファイルから3ファイルに広がった。推論のままなら1ファイル取りこぼしていた。

## 上流への還元 (計画)

### PR2 — ブランチ準備済み・未提出

`lzpel:pr2-windows-dll-suffix` (`openmc/lib/__init__.py` +2/-0)

共有ライブラリの拡張子を darwin なら `dylib`、それ以外は `so` と決め打ちしており
`win32` 分岐が無い。`Model.run()` が `is_initialized` 経由で `openmc.lib` を無条件に
import するので、**CSG 計算ですら Windows では動かない**。

出すのは PR #4023 がマージされてから。理由は2つ。

- 初回コントリビューターは GitHub Actions がメンテナ承認待ちになる。1本目で信用を作る
- この変更は [PR #2919](https://github.com/openmc-dev/openmc/pull/2919) (Windows 対応、
  draft のまま停止) に既に含まれている。独立に有用な一部の切り出しであることを説明し、
  `@HunterBelanger` をタグする必要がある

**未確認**: #2919 は `os.add_dll_directory` も追加している。こちらの構成では
ランタイム DLL を `libopenmc.dll` の隣に置くことで不要になった (`ctypes.CDLL` は
絶対パスなら `LOAD_WITH_ALTERED_SEARCH_PATH` で開くため) が、MSVC ビルドでは
事情が違う可能性がある。PR 本文でこの実測と限界を明示する。

### 3カ月計画 W12 との関係

W12 の「parastell に小規模 PR を送り UW-Madison に認知を作る」は**未達成**。
#4023 の送り先は OpenMC (MIT 発祥、主要メンテナは Argonne) であって
UW-Madison CNERG (ParaStell / DAGMC / Svalinn) ではない。系統が違う。

ただし上位の狙いである「外部コミュニティに実在の貢献者として認識される」は、
予定の 9/8–10/5 に対し **W1 時点で前倒し着手できた**。MinGW ビルドの副産物。
本来の W12 は W7 で DAGMC 経路に入るときに回収する。

## 次: DAGMC + MOAB (第二弾)

当初は `-DPULL_INSTALL_MOAB=<version>` を試す想定だったが、調査の結果**採らない**。
未リリースの develop 限定機能で、かつ MOAB に共有ビルドを強制するため、MinGW で唯一
成功報告のある静的ビルドと排他になる。MOAB を静的に自前ビルドして
`-DMOAB_DIR=` で渡す方針に変更した。根拠と撤退基準は
[sandbox-openmc-source/README.md](../sandbox-openmc-source/README.md) の「第二弾の方針」。

MOAB は OpenMC より確実に難しい。OpenMC が通ったのは依存が薄かったからで、
MOAB は HDF5 に加えて自前の export マクロ問題を抱えている。楽観はしない。

関連: [20260718-ncから中性子輸送まで](20260718-ncから中性子輸送まで.md),
[20260714-3カ月で作り上げる計画](20260714-3カ月で作り上げる計画.md)
