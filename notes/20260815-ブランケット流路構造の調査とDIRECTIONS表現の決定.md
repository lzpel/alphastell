# ブランケット流路構造の調査と DIRECTIONS 表現の決定

2026-08-15、W2 の流路トポロジーを決めるために実機の液体金属ブランケット構造を調べ、流路方向の表現を確定して `al_05` で図にした記録。

## 実機の流路構造

### DCLL (Smolentsev 2015, FED 100, 44–54)

| 項目 | 値 |
|---|---|
| PbLi 流速 | ~10 cm/s |
| ダクト代表寸法 | ~20 cm(large poloidal rectangular ducts) |
| FCI | SiC、数 mm 厚 |
| Δp(US ITER TBM, outboard, B≈4–5 T) | ~0.4 MPa |
| Δp(HT DCLL, inboard, B≈10–12 T) | ~1.2 MPa |
| 5 mm SiC FCI の効果 | ポロイダルダクトで最大 2 桁減 |

- **断面は PbLi + FCI + 鋼(その中に He 冷却流路)で完全にタイリングされる**。「隙間を埋める He 管」は壁そのもの。
- **半径方向に 2 層(front / return)**。ポロイダルに上がって折り返して下がるので、断面に見える 9〜12 本は「トロイダル 3〜6 本 × 往復 2 層」の積であって独立系統ではない。
- Fig.1 にある 484 mm は **ITER TBM ハーフポートの外寸**(トロイダル 484 mm × ポロイダル 1660 mm)。つまり発電炉ではなく試験体スケールの絵。
- 上記 Δp は W6 の相関式ネットワークが出す数字の桁を照合する的に使える。

### module と segment の違い

**製造と交換の単位であって流路の単位ではない。**

- **module (ITER 型)**: ポートに挿す独立した箱。TBM がこれ。
- **segment (EU DEMO 型)**: ポロイダルに連続した巨大なバナナ状の塊を上部ポートから縦に引き抜く。小モジュール多数並置は接続部と溶接が多すぎて DEMO では放棄された。

### WCLL — MHD 圧損が生死を決めない設計

- PbLi は増殖材として溜まっているだけで**熱輸送を担わない**。流速はトリチウム回収のための緩慢な循環で DCLL の 10 cm/s よりさらに桁が小さい。
- 熱を運ぶのは PbLi 中に通した**二重壁管 (Double-Wall Tube, DWT)** の 15.5 MPa 加圧水。
- 単位は Breeding Unit (BU)。セグメント箱の中に BU を積層。
- [20260714-CTO論評](20260714-CTO論評.md) ③ が「Proxima には MHD 圧損の看板は刺さらない」と結論した構造上の理由がこれ。

### HELIAS の QTS (quasi-toroidal segmentation)

- BB セグメントを準トロイダルに切り、**PbLi を B と概ね平行に流す**ことで MHD 圧損を最大 2 桁下げ、電気絶縁層を省ける可能性がある(Palermo ら、EUROfusion)。
- 併せて CPS(Capillary Porous System)による分離型 First Wall を提案。
- **W2 v0 の「単一パス・ポロイダル」と正面から衝突する**。ステラレータの B は主にトロイダル成分なのでポロイダルダクトは圧損最大配置。[20260721-圧損スコープと第一報の方針](20260721-圧損スコープと第一報の方針.md) の選択は「下限を tight にする」ためで論理は通るが、査読・面接では必ず「なぜ QTS ではないのか」を聞かれる。

## Proxima の現在地(2026-08 時点の公開情報)

- **Stellaris は概念 + 中性子計算まで**。TBR > 1(二次情報で 1.07 目標)。液体金属増殖ブランケットは**特許出願中で構造は非公開**。セグメンテーション方向・流路本数・FCI の有無・Δp いずれも出ていない。
- **Alpha(2031 net energy 実証機)は増殖ブランケット不要**。数十グラムのトリチウムを外部調達すれば足りるのでクリティカルパス上にない。部品開発は 2026 年開始。
- **QTS かどうかは公開情報から判断できない**。QI(プラズマ配位)と QTS(ブランケット分割)は別物なので混同しないこと。
- 対照的に Type One Energy の Infinity Two は査読論文でブランケットを公開(HCPB 第一候補、DCLL は有力な代替、必要 TBR < 1.05、運転インベントリ ~675 g)。W7/W8 の TBR 当たり値と論文の比較対象に使える。
- **MHD 圧損の一次ターゲットは Renaissance Fusion**([20260714-CTO論評](20260714-CTO論評.md) ③ の再確認)。Proxima 宛には TBR・滞留時間分布・排液性で当てる。

## 流路方向の表現: DIRECTIONS を採用する

`examples/al_05_blanket_3dplot.py` の `DIRECTIONS` で、向きを (φ, θ) 平面の巻き数の組ひとつで持つ。

```python
DIRECTIONS = [
	("poloidal", (0, 1), 16),  # W2 v0: 曲がり最小・B にほぼ直交
	("toroidal", (1, 0), 14),  # QTS 相当: B とほぼ平行
	("helical", (1, 1), 14),   # 中間。iota に合わせれば field-aligned
]
```

**採用理由:**

1. **VMEC 自身の語彙**。`xm` / `xn`(poloidal / toroidal mode number)と同じ数え方で、幾何カーネルの一層下が既にこの表現で動いている。読み手に説明が要らない。
2. **設計判断を決め打ちしない**。W2 v0 のポロイダル単一パスと QTS 相当を同じデータ構造で並べられるので、どちらが正解かを主張せずに Pareto を出せる。
3. **拡張が値の追加で済む**。表現の作り直しにならない。

**al_05 の結果**(色 = 流路接線と磁力線の成す角の sin、指標 = その 2 乗の平均):

| 方向 | (n_phi, n_theta) | 平均 sin² |
|---|---|---|
| poloidal | (0, 1) | 1.00 |
| toroidal | (1, 0) | 0.21 |
| helical | (1, 1) | 0.23 |

- **トロイダル流路でも 0 にならない**のが収穫。φ を進むと断面形状そのものが捻れるため θ 一定のダクトは磁力線と平行にならない。「トロイダルに切れば圧損が落ちる」だけでは足りず、残差を潰す切り方が要る。
- ポロイダルは**本数によらず 1.00** で動かない。トロイダル/ヘリカルでは本数が θ 方向の面平均サンプリング密度として効く。

**限界:**

- **整数対は閉曲線しか表せない**。ι は一般に無理数かつ s 依存なので、真の field-aligned が原理的に書けない。`helical (1,1)` は ι = 1 を仮定した近似にすぎない。→ **ピッチを実数にする**(2 行)。
- 磁力線は `e_φ` を磁気面の接平面に射影した代用。B が磁気面に接する事実は満たすがポロイダル成分が入っていない。当初 `e_φ` を生で使って toroidal が 0.31 と出たが、これは過大評価だった。
- ピッチの空間変化・ポート/ダイバータの切り欠き・マニホールド分岐は表現できない。いずれも 3D 損失として future work に置いた範囲。

## 本数は独立変数ではない

必然なのは**タイリング恒等式**の方。

```
n × ピッチ = ポロイダル周長          ← 必然(側面に並べる限り、ただの割り算)
ピッチ = w + 2×壁厚 + FCI + 隙間      ← 設計変数
∴ n × w = 周長 × (PbLi 面積率 f)、f < 1
```

- 隙間なく埋まることが必然なのは**増殖材の被覆**(TBR は覆う立体角にほぼ比例)であって、ダクトではない。
- f < 1 の差分、つまり鋼と SiC が占める体積が **TBR を削っている当の相手**。壁を厚くすれば構造は楽になり圧損も下がるが TBR が落ちる — これが TBR–圧損トレードオフの実体。
- **README の W10 スキャン軸「流路本数・アスペクト比」は「ダクト幅 w・壁厚 t」に置き換えるべき**。n と f は従属変数。

## TODO

- `iota` の python 露出。W6 で B(r) を区間写像するのにどのみち要る。同時に真の field-aligned が描けるようになる
- ピッチの実数化(`DIRECTIONS` の整数対 → 実数 q、q = ι で field-aligned)
- 背面 s=1.08 のスプライン外挿を法線オフセットに切り替える。ParaStell 論文が s>1 の外挿はプロファイルのループを起こしうると警告している領域
- W10 のスキャン軸を本数から幅・壁厚に差し替える
- **応募**: [20260714-3カ月で作り上げる計画](20260714-3カ月で作り上げる計画.md) では W5(8/11–8/17)が送信期限。カレンダーは W5、中身は W2。同ノートに「就活は成果完成を待たない」と自分で書いてある

## 参考資料

- Smolentsev et al. (2015). Dual-coolant lead–lithium (DCLL) blanket status and R&D needs. FED 100, 44–54. https://www.fusion.ucla.edu/files/2019/08/FED-v100-Smolentsev-Dual_Coolant_Lead_Lithium_Blanket_Status2015.pdf
- Smolentsev et al. MHD flow in liquid metal blankets: major design issues, MHD guidelines and numerical analysis. https://www.osti.gov/pages/biblio/1977147 — W6 の相関式の直接の出典
- Liquid metal MHD flows in manifolds of DCLL blankets. https://www.sciencedirect.com/science/article/abs/pii/S092037961400177X
- Heat transfer correlations for buoyant liquid metal MHD flows in blanket poloidal channels. https://arxiv.org/pdf/2303.11478
- Palermo et al. Challenges towards an acceleration in stellarator reactors engineering: DCLL BB for HELIAS. https://www.sciencedirect.com/science/article/pii/S0360544223033649
- Palermo et al. Overview of the DCLL breeding blanket for HELIAS 5-B (IAEA FEC 2025). https://conferences.iaea.org/event/392/papers/35801/files/13221-Manuscript_FEC%202025_finalVersion_IPalermo_et_al.pdf
- Martelli et al. Advancements in DEMO WCLL breeding blanket design and integration. https://scipub.euro-fusion.org/wp-content/uploads/eurofusion/WPBBPR17_17326_submitted.pdf
- Arena, Del Nevo et al. (2021). The DEMO WCLL BB: Design Status at the End of the Pre-Conceptual Design Phase. Applied Sciences 11, 11592. https://www.mdpi.com/2076-3417/11/24/11592
- ParaStell: parametric modeling and neutronics support for stellarator fusion power plants. https://www.frontiersin.org/journals/nuclear-engineering/articles/10.3389/fnuen.2024.1384788/full
- Clark et al. (2025). Breeder blanket and tritium fuel cycle feasibility of the Infinity Two fusion pilot plant. JPP. https://www.cambridge.org/core/journals/journal-of-plasma-physics/article/breeder-blanket-and-tritium-fuel-cycle-feasibility-of-the-infinity-two-fusion-pilot-plant/248C49CCA0B7ABEA2F7BF7031290EDC4
- Lion et al. Stellaris: A high-field quasi-isodynamic stellarator for a prototypical fusion power plant. FED 214, 114868. https://www.sciencedirect.com/science/article/pii/S0920379625000705 — ブランケット節は未読

関連ノート: [20260714-全体構成](20260714-全体構成.md), [20260714-3カ月で作り上げる計画](20260714-3カ月で作り上げる計画.md), [20260714-CTO論評](20260714-CTO論評.md), [20260721-圧損スコープと第一報の方針](20260721-圧損スコープと第一報の方針.md)
