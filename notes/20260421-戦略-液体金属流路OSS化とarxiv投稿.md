# 戦略: 液体金属流路 OSS 化 + arXiv 投稿 → 核融合業界リクルート

alphastell を「ステラレータ 3D 磁場上の液体金属ブランケット流路設計ツール」に育て、OSS 公開 + 論文投稿で核融合スタートアップ/研究室に認知されるための方針メモ。

## なぜこの筋が良いか

- **トカマク向けブランケット (WCLL/DCLL/HCLL) は EU で設計手法が確立済み** → 今から参入しても埋もれる
- **ステラレータの 3D ねじれ磁気面に液体金属流路を貼る問題は未解決** → IPP / Proxima / Renaissance でも内部資料レベル
- **parastell がジオメトリ側の入口を既に提供している** → 下流 (MHD/熱/トリチウム) を埋めれば初の end-to-end OSS パイプラインになる

## OSS スタック (全部既存コードで連成可能)

```
  alphastell (geometry, this repo)
      ↓
  OpenMC ──→ 中性子束 / 発熱分布 / トリチウム生成率
      ↓                                    ↓
  epotFoam (OpenFOAM) ←── 熱源 ─── TMAP8 / FESTIM
      ↓       ↑                            ↑
   速度/温度場  ←── B(r) from VMEC+coils ─┘
      ↓
   MHD 圧損 / TBR / トリチウム透過
```

- **OpenMC** (MIT) — 中性子輸送。parastell で既に連携済み
- **epotFoam** (OpenFOAM ベース, GPL) — 低 Rm MHD の事実上の標準。Tassone 版 (Sapienza/EPFL) が無難
  - 低磁気レイノルズ数の電位方程式 `∇·(σ∇φ) = ∇·(σ v × B)` を解く定式化
  - 標準同梱の `mhdFoam` は高 Rm 向け (太陽プラズマ) で fusion blanket には不適
- **MOOSE / BlueCRAB / Cardinal** (INL, ORNL) — FEM マルチフィジックス。論文通しやすさは OpenFOAM より上だが学習コスト高
- **TMAP8** (INL, MOOSE ベース) または **FESTIM** (CEA, FEniCS ベース) — トリチウム透過・蓄積
- 自作が必要なのは **VMEC 平衡 B(s,θ,ζ) → OpenFOAM の volVectorField へのラッパー** のみ (数百行)

## 新規性の取り方

「自作流体コードで新発見」ではなく **既存 OSS を配管して誰もやっていなかった計算を最初に行う** タイプを狙う。MHD ソルバー自体は枯れた OSS の蓄積に乗れるので、流体計算の信憑性を担保しつつ、寄与を 3D 連成と最適化に絞れる。

論文テーマ候補:

1. VMEC 平衡 + epotFoam + OpenMC でステラレータ DCLL モジュールの MHD 圧損分布を初計算
2. ヘリオトロン配位 (LHD) とモジュラー配位 (W7-X) で液体金属流路の MHD 圧損を比較 ← Helical Fusion に直撃
3. 3D 磁場のリップル成分が FCI 設計に与える影響
4. TBR と MHD 圧損の Pareto 最適化 (thickness_matrix を設計変数に)
5. ドレイン性を制約条件に入れた流路トポロジー探索

## 妥当性検証 (査読対策)

MHD 流路は解析解が揃っているので先にベンチマークを通す。

| ケース | 内容 | 出典 |
|---|---|---|
| Hartmann flow | 一様磁場下の平行平板 | Hartmann 1937 |
| Hunt flow | 矩形ダクト、導体/非導体壁混合 | Hunt 1965 |
| Shercliff flow | 矩形ダクト非導体壁 | Shercliff 1953 |
| MaPLE (UCLA) | Pb-Li 実液 MHD 圧損+熱伝達 | Smolentsev et al. |
| HELIBLI (KIT) | ヘリカル流路 MHD | Bühler et al. |

これらを epotFoam で再現し誤差数 % で一致させておけば「ツールの妥当性は既存解析解で検証済み、新規性はステラレータ 3D 磁場への適用」と言い切れる。

## 計算スケール上の注意

- Hartmann 層 (厚さ ∝ 1/Ha) の解像度が必要。Ha = 10⁴ オーダーで full 3D は 10⁸ セル級
- **モジュール 1 セクタ (1/N_fp) だけで Ha = 10³ 程度に落とせばワークステーションで回る**。論文にはこれで十分
- Pb-Li でなく純 Li にするなら物性だけ切替え (粘度・電気伝導率・熱伝導率)

## リクルートにつながる現実経路

arXiv 単体では DM は来ない。ただし以下のルートで実質的な接点が生まれる。

| ルート | 期待値 |
|---|---|
| arXiv → リクルーター直接 DM | ほぼ無い |
| GitHub スター → parastell/openmc 本体メンテナの目に留まる | 中 |
| Twitter/X で fusion コミュニティに拡散 | 中 |
| 学会 (ISFNT, SOFT, Stellarator Symposium) で顔を売る | 高 |
| arXiv → 引用 → 共同研究依頼 → 雇用 | 高 |

## 接触対象

**スタートアップ (OSS 好意的、採用活発)**
- **Renaissance Fusion** (仏 Grenoble) — 液体金属第一壁が主戦場。最も刺さる
- **Proxima Fusion** (独 Munich) — W7-X 系 QI ステラレータ、blanket engineer 募集開始
- **Type One Energy** (米/英) — HTS + QI ステラレータ、UW FTI 人脈
- **Helical Fusion** (東京) — **日本在住なら最短距離**。ヘリオトロン型 + FLiBe 液体ブランケット、CTO 宮澤氏 (元 NIFS) は OSS 文化に理解あり

**アカデミア**
- IPP Greifswald (W7-X 本家)
- UW-Madison FTI (parastell 本家)
- NIFS (土岐、LHD)
- 京大エネ研 / 阪大 ILE

## アクションプラン

1. **parastell 本体に小さい PR を複数送る** (マテリアルタグ、バグ修正、テスト)。これだけで UW FTI に認知される
2. **流路拡張は alphastell 側に fork として実装** (本体マージは時間がかかるため)
3. **VMEC B(r) → OpenFOAM ラッパー実装** — 唯一自作が必要な接着部分
4. **Hartmann/Hunt/Shercliff ベンチマークを epotFoam で再現** → README に貼る
5. **モジュール 1 セクタスケールで MHD 圧損マップを生成** → 最初の論文の主要図
6. **arXiv 投稿前に Fusion Engineering and Design または Nuclear Fusion への submit と並行** (「submitted to ...」と書けると権威が一段上がる)
7. **ISFNT / Stellarator Symposium にライトニングトーク応募** — ポスター可
8. **Helical Fusion に日本語で直接メール** (技術ブログ + GitHub 添付)
9. **X で fusion コミュニティ (Proxima/Renaissance 社員, @Fusion_Startups 周辺) をフォロー + 要所で reply**

## 期待値

- 1 年本気: ポスドク/スタートアップ面接に進める確率 7-8 割
- 論文+OSS 出して座って待つ: リクルートは 1 割以下
- 王道パターン: 学会で飲みに誘われる → 共同研究の話 → ポジションの話 (3 段階)

**「最適化結果を arXiv に出す」より「最適化ツールを OSS にしてそれをネタに人と話す」方が何倍も効率がいい。** alphastell を「自分の代わりに営業してくれる OSS」に育てる発想がこの戦略の核心。
