# 法線 offset 手法の厚み補正と parastell 比較

VMEC LCFS の外側にオフセット層 (first wall / breeder / shield / VV など) を張るとき、どの方向に
`offset` だけ進めるかで「層の形」と「層の厚み」が両方変わる。alphastell は現在 2 種類の法線
(`NormalKind::Planar` / `NormalKind::Surface`) を提供するが、両者の間に **3 つ目の選択肢**
(Planar + cos 補正) が存在し、parastell を含む既存実装はこの補正を行わない。論文で比較する
場合の材料として整理しておく。

## 記号

プラズマ座標 (s, θ, φ) に対する VMEC の Fourier 評価結果を以下で書く。

- `R(θ, φ)`, `Z(θ, φ)`: 磁束面の (R, Z) (実装: `src/vmec.rs` `eval_rz`)
- `t_θ = (∂R/∂θ, 0, ∂Z/∂θ)`: φ=0 断面での θ 接線 (3D)
- `t_φ_true = (∂R/∂φ, R, ∂Z/∂φ)`: φ=0 での φ 接線 (3D)
- `y_hat = (0, 1, 0)`: φ=0 での φ 単位方向 (constant-φ 半平面に垂直)
- `J = (∂Z/∂φ)(∂R/∂θ) − (∂R/∂φ)(∂Z/∂θ)`: φ 方向の形状変化を表すヘリカル項
	- 軸対称 (単純トーラス) なら `∂R/∂φ = ∂Z/∂φ = 0` で `J = 0`
- `|n_P| = sqrt((∂R/∂θ)² + (∂Z/∂θ)²)`: θ 接線の長さ

## 3 方式

### A. Planar (parastell 互換, alphastell の既定)

```text
n_P = cross(y_hat, t_θ) = (∂Z/∂θ, 0, −∂R/∂θ)
p_offset = p + offset · n_P / |n_P|
```

**性質:**
- offset ベクトルが φ 成分を持たないので、offset 後の点は **元と同じ constant-φ 半平面に留まる**。
- `grid[phi_idx]` が常に同じ φ で並ぶため B-spline 格子が綺麗 (`Solid::bspline(grid, periodic=true)`
	に渡しても φ 方向の順序は保たれる)。
- 一方、真の曲面法線とのなす角だけ offset がずれているため **実効厚み = offset · cos(ズレ角) < offset**。
	ヘリカル度が強い領域ほど層が薄くなる。

**parastell 実装 (`parastell/parastell/invessel_build.py:1203-1222`):**

```python
plane_norm = np.array([-np.sin(self.phi), np.cos(self.phi), 0])
normals = np.cross(plane_norm, tangents)
return normalize(normals)
...
self.rib_loci += self.offset_list[:, np.newaxis] * self._normals()
```

`plane_norm` は y_hat を φ 回転させたもの、`cross(plane_norm, tangents)` を正規化してそのまま
offset_list に掛けている。**補正は一切無い**。つまり parastell もヘリカル領域で厚みが薄くなる
artifact を受容している。

### B. Surface (真の 3D 曲面法線)

```text
n_T = cross(t_φ_true, t_θ)
p_offset = p + offset · n_T / |n_T|
```

**性質:**
- 局所的に厚みは (1 次で) 均一。
- offset ベクトルが **φ 成分 (y 成分) を持つ**ため、offset 後の点が constant-φ 半平面から外れる。
	`grid[phi_idx]` の各点の実 φ 座標が idx に対して単調でなくなり、強くヘリカルな断面では
	**φ_idx 順序が入れ替わる** / **同じ φ に 2 点が射影される** 状態に近づく。
- 結果として `Solid::bspline` に渡した格子が折り畳まれ、spline 曲面が乱れる
	(`src/vmec.rs` tests `mesh_phi_seam_matches_row0` は seam 回帰試験)。
- 軸対称なら A と一致。

### C. Planar-Compensated (提案)

A の方向を使いつつ、offset を `1/cos(ズレ角)` 倍する。

**cos(ズレ角) の閉形式導出:**

```text
n_P · n_T = R · |n_P|²   (解析的に綺麗に閉じる)
|n_T|     = sqrt(R² |n_P|² + J²)
cos(θ_err) = (n_P · n_T) / (|n_P| · |n_T|)
           = R · |n_P| / sqrt(R² |n_P|² + J²)
           = 1 / sqrt(1 + (J / (R |n_P|))²)
```

**補正係数:**

```text
1 / cos(θ_err) = sqrt(1 + (J / (R |n_P|))²)
```

軸対称なら `J=0` で補正なし、ヘリカル度が上がるほど補正係数が大きくなり offset を伸ばしてくれる。

**性質:**
- A の格子整合性 (constant-φ 半平面に留まる, φ_idx 単調性) を **完全に維持**。
- 実効厚みが 1 次で一致する (`= offset`)。Surface と A の良いとこ取り。
- 代償として **parastell との体積一致が悪化**する (parastell は A 同等なので)。
- 点同士の対応 `[i][j]` ↔ `[i][j]` は依然として真の曲面法線上には乗らない (= 内外層の
	同名点を結ぶベクトルは真の法線ではない)。多くの用途 (体積, 遮蔽厚) では影響なし。
- 2 次以降の曲率効果は補正しない。

## トレードオフ表

| 方式                | 格子整合 | 厚み均一性 | parastell 互換 | 実装コスト |
| ------------------- | -------- | ---------- | -------------- | ---------- |
| A. Planar           | ◎        | ×          | ◎              | 既実装     |
| B. Surface          | ×        | ◎          | ×              | 既実装     |
| C. Planar-Compensated | ◎      | ○ (1次)    | △              | 数行追加   |

## 実装スケッチ (`src/vmec.rs` の `mesh()` Planar 分岐)

```rust
NormalKind::PlanarCompensated => {
	let t_theta = [rz.dr_dtheta, 0.0, rz.dz_dtheta];
	let y_hat   = [0.0, 1.0, 0.0];
	let n_p_sq  = rz.dr_dtheta.powi(2) + rz.dz_dtheta.powi(2);
	let j       = rz.dz_dphi * rz.dr_dtheta - rz.dr_dphi * rz.dz_dtheta;
	let corr    = (1.0 + (j * j) / (rz.r * rz.r * n_p_sq)).sqrt();
	[t_theta, y_hat, corr]  // 呼び出し側で offset に corr を掛ける
}
```

必要な値 (`dr_dθ, dz_dθ, dr_dφ, dz_dφ, R`) は既に `RZ` 構造体に揃っているので
`interpolate_rz` / `eval_rz` の変更は不要。

## 論文で主張し得るポイント

1. **先行研究との差分**: parastell は constant-φ 2D 法線を正規化してそのまま offset に使う
	(`invessel_build.py:1218-1222`)。論文でこれを「parastell convention」として定式化し、
	ヘリカル領域での厚み過少 (= 有効中性子遮蔽厚の過少) を**定量化**できる。
2. **補正提案の新規性**: `J/(R|n_P|)` という無次元量を導入し、`sqrt(1 + (J/(R|n_P|))²)` で
	補正する解析式は軽く (1 点あたり乗算数回)、追加データを持たない。VMEC の Fourier 評価
	結果そのものから閉形式で得られる点が実装的にも綺麗。
3. **格子整合性との両立**: Surface 法線は厚みは合うが B-spline 曲面が乱れるという数値幾何上の
	病理を示せる (`mesh_phi_seam_matches_row0` がその兆候)。Planar-Compensated はこれを回避
	しながら厚みを確保する、という **ハイブリッド**の提案として位置づけられる。
4. **検証経路**: `make validate --tol=...` で parastell との体積差を測る既存の検証フレームが
	あるので、三方式の体積ずれを同じ土俵で比較できる (ただし「parastell が基準」とすると
	Planar-Compensated の評価は「ずれるほど正しい」という逆転が起きる点は注意)。
	より良いのは **解析的な最大内接球 / 最小層厚** を計算して三方式を評価することだが、
	これは別途必要。

## 未解決 / 要検証

- 補正後の `p_offset` は元の磁束面と **exactly parallel ではない** (2 次誤差)。層厚が層の
	曲率半径に近い場合 (VV の 10 cm は OK、架空の厚い shield はアウト) の誤差評価。
- offset が複数層に累積するとき、各層で Jacobian ベースの補正を独立に適用して累積誤差は
	線形で済むか、2 次で発散するか、要数値実験。
- `|n_P| → 0` (θ 方向に点が縮退) や `R → 0` (磁気軸付近) での数値安定性。プラズマ形状では
	どちらも現実的にはありえない (s ≥ 0 で R > 0 かつ θ 接線は nonzero) が、境界ケースの
	アサートは要る。

## 関連コード参照

- `src/vmec.rs:107-118` — `NormalKind` 定義
- `src/vmec.rs:294-355` — `mesh()` 本体
- `src/vmec.rs:320-347` — Planar / Surface 分岐 (補正を足す箇所)
- `parastell/parastell/invessel_build.py:1203-1222` — parastell の `Rib._normals`
- `parastell/parastell/invessel_build.py:1232-1233` — parastell の offset 適用
- `src/vessel.rs` — 6 層 in-vessel build (`mesh(..., Planar)` を使用)
- `src/validate.rs` — parastell 体積との整合チェック

## 投稿戦略: 「バグ修正」として出すか、contribution として出すか

> 素朴な疑問: 「改善というよりバグ修正みたいだが、これで arXiv や JOSS に投稿して良いのか？」

投稿媒体で審査基準が違うため、**どこを狙うかで「バグ修正かどうか」の問題性が変わる**。

### 媒体別の相性

**JOSS (Journal of Open Source Software) — 相性◎ (本命)**

- JOSS は "novel research" ではなく **「有用で、きちんと engineering された OSS」** を審査する媒体。
	500〜1000 語の短い論文に short scholarly justification を付けるだけ。
- alphastell 全体 (VMEC→STEP の Rust 実装、parastell 互換、かつ改良オプション) なら十分投稿可能。
	法線補正はその中の 1 セリングポイント扱いで OK。
- 審査の関門は:
	- テスト (ある程度ある)
	- CI (要整備)
	- ドキュメント (doc コメント豊富だが README も必要)
	- statement of need (「なぜ既存の parastell ではなく alphastell が要るか」を 1 段落で書ける)
	- OSI 互換ライセンス (要確認・付与)
- **"バグ修正かどうか" は問われない**。機能として並列に出せるので呼びやすい。

**arXiv — 相性○ (preprint として併用)**

- 査読なし、受理基準は「科学的に整っているか」程度。
- 「補正を提案した」**単発で出すのは薄い**。JOSS や査読誌と**合わせた** preprint として出すのが王道。
- カテゴリは `physics.plasm-ph` か `physics.comp-ph`。

**査読誌 (Fusion Eng. Design / Computer Physics Communications 等) — 条件付き**

- 単なる補正では弱い。
- 但し **下流影響の定量化**を付ければ立派な論文になる:
	- 「parastell の constant-φ 近似が実効厚みを X% 過少にし、これが TBR / 中性子遮蔽性能を
		Y% 変える」
	- W7-X や HSX のような実機ジオメトリで三方式を比較
	- 中性子輸送 (OpenMC) まで通して TBR 差を出せれば、「**fusion CAD パイプラインに潜む
		系統誤差の同定と補正**」という骨太のストーリーになる。

### 推奨ルート

**狙う順序: JOSS を本命 → arXiv に preprint → 余裕があれば査読誌**

JOSS なら「バグ修正」ではなく **「Rust で書き直した alphastell は parastell 互換モードと補正
モードを両方提供する」と機能として並列に出せる**ので、手番的にも呼びやすい。

論文中で以下のように書けば、「単なる bug fix」ではなく立派な contribution claim になる:

> parastell の既定式 (`invessel_build.py:1218-1222`) は `J=0` の軸対称極限で厳密、一般ステラ
> レータでは `sqrt(1 + (J/(R|n_P|))²)` の系統因子で層が薄くなる。本実装はこれを閉形式で定量化
> し、格子整合性を保ったまま補正するオプションを提供する。

すなわち **「既存コンベンションの限界を閉形式で定量化し、格子整合性を保ったまま補正する」**
という位置づけ。

### フレーミングの要点

- ❌ 「parastell のバグを直した」 — 小さく聞こえる + 角が立つ
- ⭕ 「parastell convention の systematic bias を解析的に特徴づけ、格子整合性を犠牲にしない
	補正を提案」 — 同じ内容でも contribution として成立

### 未整備 / 次の作業

- `LICENSE` (MIT or Apache-2.0) の付与・確認
- `README.md` に statement of need セクション
- CI (GitHub Actions で `cargo check` + `cargo test`)
- `notes/戦略-液体金属流路OSS化とarxiv投稿.md` との整合 (別トピックで arxiv 計画があるので
	投稿時期や抱き合わせの有無を要調整)
