# sandbox-openmc — OpenMC (openmc-anywhere wheel) による未衝突中性子減衰の解析解検証サンドボックス

OpenMC([openmc-anywhere](https://pypi.org/project/openmc-anywhere/) wheel、uv 管理)で 14.1 MeV
等方点線源 + リチウム球の中性子輸送を計算し、未衝突中性子束の
空間分布を輸送方程式の厳密解 φ(r)=S·exp(−Σt·r)/(4πr²) と比較する。**CAD もメッシュも使わず**、
CSG(構成立体幾何)の同心球だけで体系を組む。3カ月計画 W7「OpenMC 経路(STEP→DAGMC→TBR)」の
前哨であり、DAGMC・PbLi・STEP という重い依存に進む前にモンテカルロ輸送の土台を先に固める素振り場。
sandbox-openfoam が Hartmann 流で epotFoam を検証したのと同じ「解析解の錨」の中性子版。
背景は [notes/20260718-ncから中性子輸送まで.md](../notes/20260718-ncから中性子輸送まで.md)。

## 使い方

必要要件: GNU make, [uv](https://docs.astral.sh/uv/)。docker は `make paper` の
texlive(report.tex のビルド)にだけ要る。OpenMC 本体は uv が openmc-anywhere wheel
(openmc 実行ファイル・libopenmc・njoy 同梱、DAGMC 有効)を初回実行時に取ってくる
(取得元は PyPI、issue #16)。

```sh
make                      # (デフォルト=paper) data → 解算 → 解析解比較 → レポート PDF
make data                 # 検証用の軽量断面積ライブラリを生成 (Li6/Li7、初回のみ DL)
make R=40 PARTICLES=500000 paper   # 半径・ヒストリ数を変えて再実行
make LIB=full data        # ENDF/B-VIII.0 フルライブラリ (数GB) に切り替え (W7 の PbLi 用)
make clean                # 生成物を削除 (data/ の断面積は残す)
```

リポジトリルートからは `make -C sandbox-openmc` で呼べる。
比較は最大相対誤差が閾値(既定 2%)を超えるか、統計的外れ値(3σ 超)のシェルがあると
**非ゼロ終了**する(検証として失敗する)。
出力: `results/attenuation.png`(プロット)、`results/report.txt`(誤差レポート)、
`results/tally.json` / `results/xs.json`(数値解と使用断面積)。
`make paper` は texlive/texlive:latest(初回 pull 約5GB)で `report.tex` を LuaLaTeX ビルドする。

## 何を検証するか

中心 r=0 に強度 S の 14.1 MeV 等方点線源を置いた半径 R のリチウム球。輸送方程式の
**未衝突成分**(一度も衝突していない中性子)は散乱源がゼロになり、厳密に解ける:

$$\phi(r) = \frac{S\,e^{-\Sigma_t r}}{4\pi r^2},\qquad
L = e^{-\Sigma_t R}\ (\text{表面漏洩}),\qquad
C = 1 - e^{-\Sigma_t R}\ (\text{初回衝突総数})$$

Σt は 14.1 MeV での巨視的全断面積(単一の数)。未衝突中性子はエネルギーを変えないので
**近似ではなく厳密**。球シェル [r₁,r₂] の体積平均も厳密で、タリーはこの体積平均と比較する
(点値ではなく):

$$\langle\phi\rangle = \frac{S\,(e^{-\Sigma_t r_1}-e^{-\Sigma_t r_2})}{\Sigma_t\,V},\qquad
V=\tfrac{4}{3}\pi(r_2^3-r_1^3)$$

OpenMC の未衝突束(`CollisionFilter=0`)を等体積シェルでタリーし、上式との最大/RMS 相対誤差と
統計的整合(nσ 超のシェル数)を判定する。TBR(Li6(n,t)+Li7(n,n't))は**解析解のない参考値**として
併記する — 純リチウム球は実機ではなく、本番 TBR は W7 以降に PbLi+DAGMC で計算する。

## 設計判断と根拠

| 判断 | 選択 | 根拠 |
|---|---|---|
| 検証ケース | 14.1 MeV 点線源 + Li 球の**未衝突**減衰 | 輸送方程式の未衝突成分は散乱源が消えて厳密解 φ=S·e^{−Σt·r}/4πr² を持つ。CSG 球1個で組めて CAD 不要。Hartmann 流が epotFoam の解析解検証だったのと同じ役割を中性子側で果たす |
| CAD を使わない | CSG 同心球のみ | issue #4 の「CAD 無しの解析解がある実験」。DAGMC/STEP の重い依存を持ち込まずに輸送エンジン単体を検証する。CAD 経路(段2)は W7 以降 |
| 未衝突束の抽出 | `CollisionFilter(bins=[0])` × 線源エネルギー窓 × 飛跡長 flux | 衝突回数 0 = 未衝突。ただし CollisionFilter だけだと (n,2n) の二次中性子(新粒子・衝突回数 0 から始まる)が混入し外側シェルほど過大評価される(実測 ~7%)。未衝突源中性子は厳密に 14.1 MeV のままなので、線源エネルギー ±0.1% の `EnergyFilter` を併用すると低エネルギーの二次中性子が除け、厳密解と 0.1% 台で一致する |
| 断面積の処理 | ENDF → **NJOY**(openmc-anywhere wheel 同梱)→ HDF5、293.6 K | `IncidentNeutron.from_endf` のデータは共鳴再構成・Doppler 広がり未処理で HDF5 に直接書けない。wheel が venv に置く `njoy` で `from_njoy` を通しポイントワイズ化する(以前は docker イメージ同梱の njoy に依存していた)。処理温度 293.6 K を材料温度の既定と一致させる |
| シェル分割 | 等体積 R·(i/n)^{1/3} | 各シェルのタリー統計をそろえる(等半径幅だと外側シェルほど体積大で誤差が偏る)。点値でなく式(体積平均)と比較しビン化バイアスを除く |
| 解析解の Σt | **数値解と同じライブラリ**から読む | データではなく輸送ソルバーを検証している。model.py の `macroscopic_total()` が cross_sections.xml の同じ HDF5 から 14.1 MeV の Σt を評価し、xs.json に出す。ライブラリ差を検証誤差に混入させない |
| 合格判定 | 最大相対誤差 < 2% **かつ** 全シェル 3σ 以内 | モンテカルロは統計誤差 σ を持つ(決定論の Hartmann との違い)。相対誤差だけだと統計ゆらぎを実装バグと誤検出/見逃すため、σ 整合を併用。ヒストリ数を上げれば σ は 1/√N で縮む |
| 断面積ライブラリ | 既定 lite(Li6/Li7 の2核種、数MB)。`LIB=full` で ENDF/B-VIII.0 フル(数GB) | 純リチウム球の検証に必要な核種は2つだけ。軽量ライブラリはマウント機構(`-v` と `OPENMC_CROSS_SECTIONS`)を検証する。フルライブラリの取得経路は別で、切り替えを1変数に閉じ込めた。W7 の PbLi+構造材では full が要る |
| ライブラリ生成 | IAEA の核種 zip → ENDF → `from_njoy` → HDF5 | IAEA-NDS ミラーは核種ごとの zip(`n_0325_3-Li-6.zip` 等)で配布。既定 UA を弾くのでブラウザ風 UA を付ける。中の ENDF を NJOY で処理して HDF5 化する |
| データの置き場 | `sandbox-openmc/data/`(gitignore、clean で消さない) | 断面積は大きく git 管理外。実行時に `OPENMC_CROSS_SECTIONS` で渡す。`make clean` でも残し再DLを避ける。サンドボックス内で自己完結 |
| OpenMC の供給 | **openmc-anywhere wheel + uv**(2026-07-23 に docker から移行、issue #16) | `OPENMC = OPENMC_CROSS_SECTIONS=... uv run` の接頭辞1箇所に集約。uv run が venv の Scripts/bin を PATH に前置するので `openmc`/`njoy` の literal 解決が通る。docker 時代の `MSYS_NO_PATHCONV`/`USERSPEC` ノブは不要になった(texlive は report.tex 側で対処済み) |
| パラメータ注入 | model.py の CLI 引数 + params.stamp | OpenMC は Python API でモデルを組むのが自然で、XML を sed するのは退化。R/PARTICLES を stamp ファイルに記録し、値が変われば tally.json が再生成される(sandbox-openfoam の .template+cmp と同じ「変わったときだけ再実行」) |
| 実験レポート | `report.tex`(自己ビルド式・LuaLaTeX 日本語)+ `make paper` | ルート paper.tex / sandbox-openfoam と同じ「`sh report.tex` でビルドできる polyglot + 出力先 report/」規約。図(fig01: 減衰プロット、fig02: 体系模式図)と数値(values.tex マクロ、compare_attenuation.py --tex が生成)は make paper が results/ からコピーし本文にハードコードしない |
| docker_openmc の要否 | **今は作らない。ただし W7(DAGMC)では必要** | issue #4 の前提「標準イメージで回るなら docker_openmc は作らない」。`make env` の実測(下記)で、本サンドボックス(CSG のみ)は標準イメージで回ると確認。一方、標準イメージは **DAGMC 非対応**なので、STEP→DAGMC 経路(W7)では docker_openmc が要ると判明した |

### `make env` の実測(2026-07-18、docker_openmc 要否の判断根拠)

`make env` を `openmc/openmc:latest` に対して実行した結果:

- **OpenMC 版**: 0.15.3(commit 27e38e8)。`latest` タグは存在し、`import openmc` も CLI も動く。
- **断面積**: `OPENMC_CROSS_SECTIONS` は実行時マウントで解決(issue #4 の方針どおり)。イメージに標準ライブラリは同梱されず、`make data` で用意する。
- **DAGMC 非対応(重要)**: `ldd libopenmc.so` に MOAB/DAGMC/embree/double-down のリンクは**無く**、イメージ内にも `libMOAB`/`libdagmc` は存在しない(あるのはテスト用 `.h5m` 断面だけ)。`libopenmc.so` には
  `"DAGMC Universes are present but OpenMC was not configured with DAGMC"` というガード文字列が焼き込まれており、DAGMC ユニバースを渡すとこのエラーで停止する。すなわち標準イメージの DAGMC は**機能しない**。

**結論**:
- 本サンドボックスは **CSG のみ**なので標準イメージで完結する → **docker_openmc は作らない**(issue #4 の1本目の答え)。
- ただし W7 の **STEP→DAGMC→OpenMC** 経路には DAGMC 対応ビルドが要る → その時点で `docker_openmc/`(`docker_openfoam` と同形: Dockerfile + makefile + README、`ghcr.io/lzpel/openmc`、DAGMC/MOAB を焼き込み)を別途用意する。あるいは DAGMC を含む別イメージ/タグを `IMAGE` 変数で指す。

## ライセンス注意

OpenMC(MIT)を Docker で外部ソルバーとして呼ぶだけで、ソルバーコードは含まない。
断面積データ(ENDF/B-VIII.0)は配布元の利用条件に従う。本ディレクトリのスクリプトは
リポジトリ全体と同じ MIT。

## 出典

- Romano et al. (2015), "OpenMC: A state-of-the-art Monte Carlo code for research and development",
  Annals of Nuclear Energy 82, 90–97.
- ENDF/B-VIII.0 — Brown et al. (2018), Nuclear Data Sheets 148, 1–142。
  個別評価済みファイルは [IAEA-NDS](https://www-nds.iaea.org/) ミラーから取得。
- [ParaStell](https://github.com/svalinn/parastell) — STEP → DAGMC → OpenMC のステラレータ中性子ワークフロー(段2 の参考)。
- Lewis & Miller (1993), *Computational Methods of Neutron Transport* — 未衝突束・輸送方程式。
