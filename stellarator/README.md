# stellarator — VMEC 平衡から磁気面形状を評価する幾何カーネル

VMEC 平衡ファイル `wout_*.nc` を読み、任意の磁束座標 (s, θ, φ) で磁気面の (R, Z) と
その θ/φ 偏導関数を返す純粋な数学カーネル。`alphastell` の `core/src/vmec.rs` を移植した。
**CAD カーネル (cadrum) には依存しない** — 依存は netCDF-3 リーダ 1 つだけで、C ツールチェインも
HDF5 も要らず、Windows で `cargo test` がそのまま通る。3カ月計画 W1「vmec.rs 移植・wout.nc で
表面点群」に対応し、これがパイプラインの最上流 (wout → 流路ジオメトリ) を埋める。流路生成
(W2, `mesh` を使ったダクト分割) と cadrum による STEP 出力はここには入れない。
背景は [../notes/20260714-全体構成.md](../notes/20260714-全体構成.md)、
計画は [../notes/20260714-3カ月で作り上げる計画.md](../notes/20260714-3カ月で作り上げる計画.md)。

## 使い方

必要要件: Rust (edition 2024), GNU make, [uv](https://docs.astral.sh/uv/) (判定スクリプトの numpy/matplotlib/scipy 用)

```sh
make                                     # (デフォルト=test) wout 取得 → cargo test → 点群 CSV → 図と定量判定
make clean                               # 生成物を削除 (out/ の wout は残す)
make PATH_WMEC=/path/to/wout.nc test     # 別の wout で回す
```

リポジトリルートからは `make -C stellarator` で呼べる。
`make test` は無ければ release `resource-v1` から `wout_vmec.nc` を curl で `out/` に取得し、
環境変数 `PATH_WMEC` を設定して `cargo test` を回し、点群 CSV を出し、
`scripts/plot_surface.py` で形状の妥当性 C1–C6 を判定する。1 つでも違反すると **非ゼロ終了**する。
出力: `results/surface.png` (図)、`results/report.txt` (判定レポート)、`results/values.tex` (LaTeX マクロ)、
`results/surface_points.csv` (点群)。

> **注**: リポジトリが private の間は curl での取得が 404 になる (release アセットも認証が要る)。
> 公開後は curl が通る。それまでは `out/wout_vmec.nc` を手動で置くか `PATH_WMEC` で別パスを渡す。

`cargo test` を素で叩くと (`PATH_WMEC` 未設定)、wout を要するテストは skip し、純数学のテスト
(スプライン・対称性) だけがオフラインで走る。判定スクリプトが参照する nfp / Rmajor_p / Aminor_p は
wout ファイルから直接読む (Rust の移植コードは rmnc/zmns/xm/xn しか読まないので独立性は保たれる)。

## 何を検証するか

`export_point_cloud_csv` テストが 4 枚の磁気面 s ∈ {0.25, 0.50, 1.00, 1.08} を φ 72 × θ 48 で走査し、
点群を CSV に書く。`plot_surface.py` が 3 パネルの図 (LCFS の 3D 散布 / φ 断面の形状変化 /
入れ子面) を描き、次の 6 判定を課す。実測値 (このリポジトリの nfp=4 フィクスチャ):

| # | 判定 | 意義 | 実測 |
|---|------|------|------|
| C1 | 点群から求めた大半径・小半径を、ファイル内の `Rmajor_p` / `Aminor_p` と比較 | **最強**。移植コードが一度も読まない変数と突き合わせる。断面積・体積の VMEC 定義で計算 (R の大域 max/min ではない — 断面が φ で動くため) | R: 相対 0.01%、a: 相対 0.13% |
| C2 | 磁場周期対称性 `max｜R(φ)−R(φ+2π/nfp)｜` | `xn` に nfp が畳み込まれている扱いの検証 (nfp で割る典型ミスを検出) | 1.4e-14 m |
| C3 | θ シームの閉合 | 半開区間 [0,2π) sweep の契約 | wrap 段差 ≤ 内部差 |
| C4 | φ シームの閉合 | W3 の構造格子が依存 | wrap 段差 ≤ 内部差 |
| C5 | 面の入れ子性 (断面多角形の包含関係) | スプライン外挿のオーバーシュート検出 | 216 対すべて入れ子 |
| C6 | 解析 ∂R/∂θ vs スペクトル微分 (FFT) | 帯域完全解像なので FFT 微分は厳密。解析導関数の独立検証 | 9.9e-14 |

C6 で有限差分を使わないのは、mpol=11 の高波数に対し θ=48 点の差分打ち切り誤差 (4 次でも ~3e-3) が
解析導関数の誤差を埋めて判別力を失うため。R(θ) は次数 mpol の三角多項式で θ=48 点は帯域
(最大 xm=10 < Nyquist=24) を完全に解像しているので、FFT スペクトル微分が丸め誤差まで厳密になる。

## 設計判断と根拠

| 判断 | 選択 | 根拠 |
|------|------|------|
| netCDF リーダ | `netcdf3` (純 Rust, CDF-1/2) | VMEC の wout は CDF-2 (実測 `CDF\002`)。HDF5 ベースの netCDF-4 とは別系統で、libnetcdf/libhdf5 の C ライブラリも FFI も不要。Windows でツールチェイン無しに `cargo test` が通ることをブランケット評価器の前提にできる |
| 移植範囲 | `vmec.rs` のみ。`vessel.rs` 以下の 6 層シェル系 (`VesselBuilder` / `magnet` / `artifact` …) は不採用 | 全体構成の方針「cadrum 結合は W2 まで持ち込まない」。vmec.rs は cadrum 非依存で完結している |
| `interpolate`/`mesh` を残す | 移植する | 純粋な数学で cadrum 非依存。W2 の流路生成が `mesh(div_phi, div_theta, s, offset, Surface)` をそのまま使うので、落とすと二週間後に書き直しになる |
| API 改変 | しない (upstream verbatim) | alphastell との diff が永続的に取れる状態を最優先。変更は陳腐化 doc コメント削除・出自コメント・crate `Result` 別名の 3 点のみ |
| フィクスチャ | release アセット `resource-v1` + makefile が curl で `out/` に取得、git には入れない | 8.3 MB のバイナリを履歴に載せない。公開後は curl で通る (private の間は 404、README の注参照) |
| 参照値 (nfp/Rmajor/Aminor) | makefile に定数で持たず、判定スクリプトが wout から直読 | 別 wout に差し替えても値が自動追随する。Rust は rmnc/zmns/xm/xn しか読まないので C1/C2 の独立性は保たれる |
| テスト欠落時 | `PATH_WMEC` 未設定なら skip、設定済みで読めなければ panic | 素の `cargo test` はオフラインで通り、`make test` は必ず `PATH_WMEC` を設定するので本番判定が無言で skip されない |
| 検証の置き場 | 純数学 (スプライン・周期/ステラレータ対称性) は Rust の `#[test]`、幾何の妥当性は Python + `sys.exit` | リポジトリ既存の「Python が解析解と比較して非ゼロ終了」様式を維持しつつ、閉じた数学は Rust 側で assert する。規約の拡張であって破壊ではない |
| C6 の微分検証 | 有限差分ではなく FFT スペクトル微分 | θ=48 点は帯域を完全解像するので FFT 微分は厳密。有限差分だと打ち切り誤差が解析導関数の誤差を埋めて判別力が消える |
| 平衡ファイル | nfp=4, R=11.08 m の炉級 4 周期配位 (**W7-X ではない**) | alphastell 由来の実測フィクスチャ。W7-X は nfp=5, R≈5.5 m。幾何カーネルは配位を選ばないので W1 はこれで足り、実際の配位比較は W9 |

## 既知の落とし穴

- **非対称平衡 (`lasym=T`) は無言で誤る**: 現行コードは `rmnc`/`zmns` (cos/sin) のみを読み、`rmns`/`zmnc` があっても無視する。ステラレータ対称配位ではこれで厳密に正しいが、非対称平衡を食わせると「もっともらしいが誤った」表面を返す。upstream から引き継いだ性質で、コードでは防いでいない。このフィクスチャは `lasym=0` で `rmns`/`zmnc` 不在なので実害はない。

## 出典

- 移植元: [lzpel/alphastell](https://github.com/lzpel/alphastell) `core/src/vmec.rs` (MIT, Satoshi Misumi)
- フィクスチャ: alphastell `resource/wout_vmec.nc` を本リポジトリの release `resource-v1` に再配布
