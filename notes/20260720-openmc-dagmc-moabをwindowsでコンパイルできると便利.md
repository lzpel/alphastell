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

上流のコード変更は **1ファイル1箇所** (`openmc/lib/__init__.py` に win32 分岐を足すだけ) で済んだ。
残りはすべてビルドオプションで解決できた。詳細は
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

## 上流に還元できそうなもの

3カ月計画 W12 の「parastell に小規模 PR を送り UW-Madison に認知を作る」に対して、
**OpenMC 本体にも同じことができる**材料が手に入った。いずれも小さく、レビューしやすい。

- `openmc/lib/__init__.py` の `win32` 分岐 (3行)。これが無いと Windows では
  `Model.run()` すら動かない。`sys.platform` の分岐に1つ足すだけ
- `src/mesh.cpp` / `src/plot.cpp` / `src/external/quartic_solver.cpp` の
  `#define _USE_MATH_DEFINES` が効いていない問題。ヘッダを include する**前**に
  定義しないと意味がないが、現状はどれも先に別のヘッダを取り込んでいる。
  コメントには「Intel and MSVC compilers」向けとあり MinGW は想定外だが、
  そもそも MSVC でも同じ順序問題があるはず

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
