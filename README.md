# mhd-tbr-stell

**ステラレータ液体金属ブランケットの成立性を、VMEC 平衡(`wout.nc`)から分単位で判定するオープンソースパイプライン。**

プラズマ境界を入力すると、磁気面に追従する液体金属流路を生成し、次の3つのプラント判定スカラーと設計図面を返す:

1. **TBR(トリチウム増殖比)** — ≥ 1.1〜1.15 で燃料サイクルが閉じるか
2. **MHD 総圧損 → ポンプ動力の対核融合出力比** — 液体金属ブランケットの生死を決める数字
3. **最高壁温度 / 構造材界面温度** — 材料寿命と腐食限界

きれいな 3D 可視化は副産物であって製品ではない。製品は「この磁場配位・この流路トポロジーで、ブランケットとして成立するか」への Yes/No と、TBR–圧損の Pareto フロントである。

> **Status: pre-alpha.** コードはまだない。設計文書([notes/](notes/))とプレプリント草稿([paper.tex](paper.tex)、現状モック結果)が先行している。

Python からの入口 (issue #5 の連携経路): `uv run examples/hello.py` が rust 製
[stellarator](stellarator/) カーネルを pyo3/maturin 経由で呼ぶ最小例。

## なぜ作るか

トカマク向けブランケット設計手法は EU で確立済みだが、**ステラレータの 3D にねじれた磁気面へ液体金属流路を配置する問題は未解決**であり、各社・各機関の内部資料に留まっている。ジオメトリ側は [ParaStell][parastell] が均一厚シェル+中性子計算の基盤を提供しているが、その内側を流れる**液体金属の MHD 圧損と TBR を連成して評価する公開ツールは存在しない**。本プロジェクトは既存 OSS(OpenMC, epotFoam)を配管し、未実施の計算を最初に実行する。

## パイプライン

```
wout.nc (VMEC 平衡)
   │  フーリエ評価・解析導関数・オフセット面
   ▼
流路ジオメトリ生成(磁気面追従ダクト・マニホールド)
   │
   ├─▶ 材料色付き STEP ──▶ DAGMC / OpenMC ──▶ 中性子束・核発熱・TBR
   │      (cadrum: B-rep, boolean, sweep)
   │
   ├─▶ 相関式 MHD 圧損ネットワーク(1D ダクト網)──▶ 総Δp・ポンプ動力比   ← 高速スキャン(分単位)
   │      B(r) を各ダクト区間に写像、Miyazaki/Smolentsev 系相関式
   │
   └─▶ パラメトリック座標から直接生成する構造格子(polyMesh)
          └─▶ epotFoam (OpenFOAM) ──▶ フル MHD CFD                    ← 検証の錨(代表ダクトのみ)
```

- **高速系(相関式ネットワーク)が主力**: 設計案を1日に何十件も回すための分単位の判定機
- **フル CFD は検証専用**: Hartmann 層を解像した代表計算で相関式との一致(目標: 数%)を示す
- CAD カーネルは [cadrum][cadrum](OCCT 静的リンクの Rust ライブラリ、STEP のソリッド色=材料タグ)

## 検証方針

ツールの妥当性は既知の解析解・実験で事前に証明する:

| ケース | 内容 | 出典 |
|--------|------|------|
| Hartmann flow | 一様磁場下の平行平板流 | Hartmann 1937 |
| Shercliff flow | 矩形ダクト・非導体壁 | Shercliff 1953 |
| Hunt flow | 矩形ダクト・導体/非導体混合壁 | Hunt 1965 |

新規性の主張は「ソルバーを作った」ではなく「**検証済みツール群をステラレータ 3D 磁場に最初に適用した**」に置く。

## 関連プロジェクト

| プロジェクト | 役割 |
|---|---|
| [ParaStell][parastell] | ステラレータ炉内構造のパラメトリック CAD + OpenMC 中性子計算(上流) |
| [OpenMC][openmc] | モンテカルロ中性子輸送 — TBR・核発熱 |
| epotFoam (OpenFOAM) | 低磁気レイノルズ数 MHD の標準実装 — 検証用フル CFD |
| [cadrum][cadrum] | Rust CAD カーネル(OCCT 静的リンク・WASM 対応)— B-rep / STEP 出力 |
| alphastell | VMEC フーリエ評価カーネルの移植元(6層シェル生成はスコープ外として引き継がない) |

## ドキュメント

- [notes/20260714-全体構成.md](notes/20260714-全体構成.md) — レイヤー分業とリポジトリ構成
- [notes/20260714-3カ月で作り上げる計画.md](notes/20260714-3カ月で作り上げる計画.md) — 週次マイルストーン
- [notes/20260714-CTO論評.md](notes/20260714-CTO論評.md) — 製品定義に至った戦略論評の記録
- [paper.tex](paper.tex) — arXiv 用プレプリント草稿(`sh paper.tex` で Docker/texlive がビルド。**現状の数値・図はすべてモック**)

## License

MIT

[parastell]: https://github.com/svalinn/parastell
[openmc]: https://github.com/openmc-dev/openmc
[cadrum]: https://github.com/lzpel/cadrum
