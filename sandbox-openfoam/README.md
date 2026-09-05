# sandbox-openfoam — Docker + epotFoam による Hartmann 流の検証サンドボックス

OpenFOAM(Docker)と epotFoam(電気ポテンシャル定式化の低磁気レイノルズ数 MHD ソルバー)で
平行平板 Hartmann 流を計算し、速度分布を解析解と比較する。
3カ月計画 W4「epotFoam 環境構築(Docker)。Hartmann ケースを流し解析解と比較」の前哨。
本格的な検証スイート(Hartmann / Shercliff / Hunt)は将来 `benchmarks/` に置く構想
([notes/20260714-全体構成.md](../notes/20260714-全体構成.md))で、ここはその素振り場。

## 使い方

必要要件: docker, GNU make, [uv](https://docs.astral.sh/uv/)(比較スクリプトの numpy/matplotlib 用)

```sh
make              # (デフォルト=paper) ビルド → メッシュ → 解算 → 解析解比較 → レポート PDF
make HA=10 paper  # Hartmann 数を変えて実行 (deltaT ≲ 0.08/Ha², controlDict 参照)
make compare      # レポートを作らず解析解比較まで
make clean        # 生成物を全削除
```

リポジトリルートからは `make -C sandbox-openfoam` で呼べる。
比較は最大相対誤差が 2% を超えると非ゼロ終了する(検証として失敗する)。
出力: `out/hartmann_Ha20.png`(プロット)、`out/report_Ha20.txt`(誤差レポート)。
`make paper` は texlive/texlive:latest(初回 pull 約5GB)で `report.tex` を LuaLaTeX ビルドする。

### Ha=1000 ケース (`hartmann_hi/`)

ルート `paper.tex` の Hartmann 検証行は Ha=10³ を要求する。既定の `hartmann/` (Ha=20、
50×80 格子) では Ha=10³ の Hartmann 層 δ=1/Ha=0.001 に格子が入らず解が出ないため、
**別ケース `hartmann_hi/`** を用意した。`hartmann/` は無傷で、両方回せる。

`hartmann_hi/` の Ha=20 からの差分:

| 項目 | hartmann | hartmann_hi | 理由 |
|---|---|---|---|
| Ha | 20 | 1000 | paper の表と一致させる |
| y 格子 | 80、grading 8 | 200、grading 211 | 第1セル≈0.00025 で δ=0.001 内に約4セル |
| deltaT | 2e-4 | 1.5e-8 | 強グレーディングの最小セルで拡散数 D=νΔt/Δy²<0.5 を満たす |
| endTime | 1 | 2e-4 | Hartmann 層の発達時間は磁気制動時間 1/Ha²=1e-6。実測で t≈2e-4 に速度残差 3.6e-9 の完全定常 |

makefile は `hartmann_hi/` を扱わない (HA 変数が template を Ha=20 に上書きしてしまうため)。
手動で回す:

```sh
cd sandbox-openfoam
PFX=$(MSYS_NO_PATHCONV=1 make -s --no-print-directory -C epotFoam)
MSYS_NO_PATHCONV=1 $PFX blockMesh -case hartmann_hi
MSYS_NO_PATHCONV=1 $PFX epotFoam  -case hartmann_hi
uv run --with numpy --with matplotlib scripts/compare_hartmann.py --ha 1000 \
  --profile "$(ls -d hartmann_hi/postProcessing/sample/*/ | sort -V | tail -1)centreProfile_U.xy" \
  --plot out/fig02.png --report out/report_Ha1000.txt --tex out/values_Ha1000.tex
```

実測: **最大相対誤差 0.385%** (閾値 2%)、約13000 ステップ。この PNG が paper の fig02。

**注意**: `dt=8e-8` (= 0.08/Ha² の目安) では強グレーディング格子の最小セルで拡散数が
D=1.28 になり浮動小数点例外で発散する。安定には D<0.5、つまり dt≲1.5e-8 が要る。
Ha を上げるほど層が薄くなり格子・dt とも厳しくなる悪循環で、Ha∼10⁴ 級は現実的でない
(paper Discussion が「10⁸ セル要」と述べているのはこのため)。

## 何を検証するか

一様磁場 B₀ŷ 下の平行平板間(半幅 a、絶縁壁)定常流の解析解
(Hartmann 1937、バルク速度 ū 正規化):

$$u(y)/\bar{u} = \frac{\mathrm{Ha}}{\mathrm{Ha}-\tanh\mathrm{Ha}}\left(1-\frac{\cosh(\mathrm{Ha}\,y/a)}{\cosh\mathrm{Ha}}\right),\qquad \mathrm{Ha}=B_0 a\sqrt{\sigma/(\rho\nu)}$$

ケースは a=ρ=ν=σ=1 の無次元設定なので Ha = B₀y。epotFoam の計算結果を
発達領域 x=8 でサンプリングし、上式との最大/RMS 相対誤差を判定する。

## 設計判断と根拠

| 判断 | 選択 | 根拠 |
|---|---|---|
| epotFoam の入手 | イメージ内 icoFoam (v2412) を土台に Tassone レポート付録の差分を転記 | epotFoam に正準リポジトリは無く、一次ソースは Tassone (Chalmers OS_CFD 2016) レポート付録のみ。PDF からの機械的転記はコード破損と OF4→v2412 API ドリフトのリスクがあるため、動作保証のある icoFoam 骨格 + 付録の追加行(約30行)で再構成し、pdftotext で付録と照合した |
| Docker イメージ | `opencfd/openfoam-default:2412` (ESI) | 保守が活発で icoFoam・チュートリアル同梱。イメージは初回 `docker run` 時に自動 pull される。Foundation 系 (openfoam10) に切り替える場合は makefile の image/bashrc の2行を書き換える |
| コンテナ実行 | `--user $(id -u):$(id -g)` + `HOME=/work` | root 所有ファイルをリポジトリに残さない |
| ソルバービルド | `make -C epotFoam` で自己完結、バイナリは `epotFoam/epotFoam` に生成 | ビルドを epotFoam/ 内に閉じる(`FOAM_USER_APPBIN=/work` で wmake の出力先が同ディレクトリ直下になる)。マウント先なのでバイナリと中間物(`Make/linux*`)が docker run をまたいで永続化され再コンパイル不要。親 makefile に solver ターゲットは無く、`foam` プレフィックスの前提条件として必要時に自動ビルドされる |
| OpenFOAM 起動設定の集約 | `$$($(MAKE) -s --no-print-directory -C epotFoam) <コマンド>` | epotFoam/makefile のデフォルトターゲット `foam` が docker run プレフィックスを出力(バイナリが前提条件なので未ビルドなら先にビルド、ビルド出力は stderr へ逃がして置換を汚さない)。コンテナ内の環境設定(bashrc・PATH)は `epotFoam/openfoam.sh` に集約し、親 makefile は docker/OpenFOAM の詳細を一切持たない。プレフィックスは引用符を含まない1行なのでシェルのコマンド置換で安全に展開できる(`--no-print-directory` は Entering directory 行の混入防止)。`WORK=<dir>` でマウント元を差し替えられ、sandbox-openfoam-cadrum など他ディレクトリのケースからも同じソルバーを共有できる(ソルバー本体は /opt/epotFoam に固定マウント) |
| z 方向(電流方向) | **1 セル + cyclic**(empty 不可) | 電気ポテンシャル定式化では誘導電流が z に流れる。empty だと面フラックス電流再構成で J_z が消え Lorentz 力がゼロになり発散する(実測)。Tassone レポート 5.2 節も epotFoam 系では empty を除去して 3D 化している。cyclic は E_z=0(短絡)条件に相当し、圧力勾配は絶縁条件と定数分ずれるが**正規化速度分布 u(y)/ū は解析解と厳密に同形** |
| 境界条件(自作) | 壁: U noSlip / PotE zeroGradient。inlet: U 一様 (1 0 0)。outlet: p 固定 0 | PotE zeroGradient = 壁法線電流ゼロ = 電気的絶縁壁(解析解の仮定)。inlet 一様流により質量保存から ū=1 が全断面で保証され、バルク正規化の解析解と直接比較できる |
| メッシュ | 50×80×1、y 両側グレーディング(拡大率8) | 第1セル高さ ≈0.0074 で Hartmann 層 δ=a/Ha(Ha=20 で 0.05)内に約6セル。Ha≳60 では要増解像。Re=1 では入口発達長が O(δ²/ν·ū)≪1 と短く流路長 10 で十分 |
| 時間刻み | dt = 2e-4(≈ 0.08/Ha²)、endTime = 1 | Lorentz 項は陽解法(Tassone 原典どおり)。名目安定限界 2ρ/(σB₀²)=2/Ha² に対し、壁近傍セルでは電流再構成で実効係数が数倍大きく dt=0.4/Ha² でも発散した(実測)。速度分布は磁気制動時間 1/Ha² で局所発達するため endTime=1 で残差 ~1e-9 の完全定常(t=0.5 と 1.0 の書き出しで確認可能) |
| サンプリング | controlDict の functions に `sets` 関数オブジェクトを #include | `postProcess -func` の関数名解決に依存せず、解算中に自動出力される |
| 比較スクリプト | `uv run --with numpy --with matplotlib` | ホスト python に numpy が無い環境でも uv だけで動く。数値解・解析解ともサンプル区間のバルク速度で正規化し、切り欠きバイアスを対称に除去。解析解の cosh 比は指数形で計算し Ha~10³ でも桁溢れしない |
| 合格閾値 | 最大相対誤差 2% | README(リポジトリルート)の検証方針「相関式との一致目標: 数%」に整合。このメッシュ・Ha=20 では <1% を期待 |
| 実験レポート | `report.tex`(/tex 規約の自己ビルド式・LuaLaTeX 日本語)+ `make paper` で計算から PDF まで自動化 | ルートの paper.tex と同じ「`sh report.tex` でビルドできる polyglot + 出力先 `report/`」規約に統一。図 (fig01: 比較プロット、fig02: 境界条件の 3D 模式図 = `scripts/visualize_condition.py` が生成) と誤差数値 (values.tex の LaTeX マクロ、compare_hartmann.py --tex が生成) は `make paper` が out/ からコピーし、本文にハードコードしない — レポートの数値が常に直近の計算と一致することを保証する。fig01/fig02/values.tex/PDF は生成物なので report/.gitignore で管理外 |

## ライセンス注意

`epotFoam/` は OpenFOAM (GPLv3) の icoFoam から派生しているため **GPLv3**。
リポジトリ全体の MIT とは異なる(サンドボックス内限定。将来 `benchmarks/` に昇格させる際も同様の扱いが必要)。

## 出典

- Tassone, A., "Magnetic induction and electric potential solvers for incompressible MHD flows",
  Proceedings of CFD with OpenSource Software, Chalmers, 2016.
  [レポート PDF](https://www.tfd.chalmers.se/~hani/kurser/OS_CFD_2016/AlessandroTassone/report_Tassone.pdf)(付録に epotFoam 全文)
- OpenFOAM 同梱チュートリアル `tutorials/electromagnetics/mhdFoam/hartmann`(ケース辞書の雛形)
- Ni et al. (2007) — 電流密度の保存的セル中心再構成(epotFoam が採用)
