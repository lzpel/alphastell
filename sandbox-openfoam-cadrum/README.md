# sandbox-openfoam-cadrum — CAD の面の色から MHD ケースを生成する検証サンドボックス

**境界条件の単一情報源を cadrum(Rust CAD カーネル)の色付き B-rep に置く**構成で、
2つのケースを生成・計算する:

1. **hartmann**(`examples/hartmann.rs`): 箱。[sandbox-openfoam](../sandbox-openfoam/) と同一設定で
   解析解により定量検証(最大相対誤差 0.127% で手書きケースと数値一致)
2. **cone**(`examples/cone.rs`): `Solid::cone − Solid::cylinder` のブーリアン差で作る
   **環状の先細流路**の MHD 計算。曲面壁への射影分類・θ 周期のラップ接続・
   中心軸特異点の回避(環状化)を実証。検証は質量保存・定常性・Hartmann 層の異方性

共通部(polyMesh writer・0/ writer・色分類)は `src/lib.rs`。
ルート README の本命「パラメトリック座標から直接生成する構造格子(polyMesh)→ epotFoam」
(`src/export_polymesh.rs` 構想)の前哨。

## 使い方

必要要件: docker, GNU make, [uv](https://docs.astral.sh/uv/), Rust (cargo — 初回は
crates.io と OCCT プレビルドの取得にネットワークが必要)

```sh
make                  # (デフォルト=paper) 両ケース生成 → 解算 → 検証 → 統合レポート PDF
make HA=10 paper      # Hartmann 数を変えて実行 (cone 側は HA_CONE=)
make compare          # hartmann の解析解比較まで (誤差 2% 超で非ゼロ終了)
make verify-cone      # cone の質量保存・定常性検証まで (超過で非ゼロ終了)
make clean            # 生成物を全削除
```

リポジトリルートからは `make -C sandbox-openfoam-cadrum` で呼べる。

## パイプライン

```
cargo run --release --example hartmann        cargo run --release --example cone
  Solid::cube 10×2×0.1                          (cone(2.0→1.2) − cylinder(0.6)).build()
  緑=流入 橙=流出 灰=壁 青=z周期(cyclic)          緑=入口環 橙=出口環 灰=壁 (θはラップ内部接続)
  ├─ results/geometry.{step,png}                ├─ results/geometry_cone.{step,png}
  ├─ hartmann/constant/polyMesh (50×80×1)       ├─ cone/constant/polyMesh (θ48×r16×x50)
  └─ hartmann/0/{U,p,PotE}                      └─ cone/0/{U,p,PotE}
        │                                             │
        └── epotFoam (ghcr.io/lzpel/openfoam) ────────┘
              ├─ hartmann → 解析解比較 (../sandbox-openfoam/scripts/compare_hartmann.py)
              └─ cone     → 質量保存・定常性・異方性 (scripts/verify_cone.py)
                    → report.tex (両結果を統合、sh report.tex で PDF)
```

## 設計判断と根拠

| 判断 | 選択 | 根拠 |
|---|---|---|
| メッシュ生成 | cadrum::Solid → **polyMesh 直接出力**(STEP → snappyHexMesh は不採用) | STEP 経由は色→パッチの受け渡しが汚く、Hartmann 層のグレーディング制御も失われる。本命パイプラインも polyMesh 直接生成なので、その writer(upper-triangular 面順序・cyclic ペア)をここで検証する |
| 境界条件の担い方 | 面の色 + 色→(パッチ, U, p, PotE) テーブル(`src/main.rs` の `PATCHES`) | CAD とケース設定の二重管理を排す。cyclic は同色2面を外向き法線の z 符号でペアに振り分け |
| 色の読み戻し | 格子境界面の中心を `Face::project` で B-rep へ射影し最近接面の色を取得 | 塗ったときの対応表を横流しせず「CAD が単一情報源」を構造的に保証。一般形状(磁気面追従ダクト)への拡張点もこの射影。曲面では多角形近似の弦誤差ぶん許容距離を緩める(cone は 0.05) |
| cone を環状にした理由 | 軸を含まない r∈[R_in, R_out(x)] の環状領域(boolean 差) | 円柱座標の構造格子を軸 r=0 まで張るとセルが楔形に退化する(面積ゼロ面・歪度発散 = **中心軸特異点**)。環状なら全セルが健全な六面体。軸まで含む円管は butterfly (O-H) マルチブロックが必要で将来課題(詳説はレポート §環状先細ダクト) |
| θ 方向の扱い | 縫い目を境界にせず**ラップ接続の内部面**(cyclic パッチ不要) | B-rep に対応する面が無い場所に人工境界を作らない。「色=境界条件」の原則の帰結 |
| cadrum 既知問題の回避 | `Face::project` は最近点がトリム境界に落ちると panic(0.8.15)→ catch して候補から除外 | 最近接面(分類対象)への射影は必ず成功するため、他面の失敗は無害。cadrum 側の修正候補として要報告 |
| 格子・数値設定 | sandbox-openfoam と同一(50×80×1、dt=2e-4、endTime=1) | 差分を「ケース生成方法だけ」に絞り、結果の完全一致で polyMesh writer の等価性を証明する(実測: 最大相対誤差 0.127% で数値レベル一致) |
| ソルバー | 焼き込み済みイメージ **ghcr.io/lzpel/openfoam**([../docker_openfoam](../docker_openfoam/) でビルド、未取得なら ghcr から自動 pull) | `docker run … epotFoam -case <case>` の1行で起動でき、wmake・環境設定・マウント合成の知識が利用側から消える。ローカルビルドは `make -C ../docker_openfoam` |
| 比較スクリプト | `../sandbox-openfoam/scripts/compare_hartmann.py` を共有 | 判定基準の重複を排し、両サンドボックスが同じ土俵で比較できる |
| レポート図2 | matplotlib 模式図ではなく cadrum レンダリング(geometry.png) | 「色付き CAD が境界条件の実物」という本サンドボックスの主張をそのまま示す |

## sandbox-openfoam との違い

| | sandbox-openfoam | sandbox-openfoam-cadrum |
|---|---|---|
| メッシュ | blockMeshDict (手書き) | src/main.rs が polyMesh を直接出力 |
| 境界条件 | 0/ を手書き | 面の色から生成 |
| 壁パッチ | lowerWall / upperWall | walls (同色なので1パッチに統合) |
| 図2 | matplotlib 模式図 | cadrum レンダリング |

## 出典

- [cadrum](https://github.com/lzpel/cadrum) — Rust CAD カーネル(OCCT 静的リンク)。crates.io から `cargo add cadrum`
- その他(epotFoam, Hartmann 解析解, OpenFOAM)は [sandbox-openfoam/README.md](../sandbox-openfoam/README.md) を参照
