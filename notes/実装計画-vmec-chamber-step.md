# 実装計画: VMEC → chamber.step Rust 実装

## Context

現行 `src/main.rs` は cadrum で 2 周期トーラスを生成するデモにすぎず、実データとの接続が無い。これを parastell 同等機能を目指す第一歩として、**実際の VMEC 出力 `wout_vmec.nc` を読み取り、任意の `s` (LCFS s=1.0 および外挿 s=1.08 を含む) のフラックス面を全周 (0→2π) の B-spline サーフェスで STEP ファイル出力する**コマンドに書き直す。これにより以降の工程 (first_wall / breeder / shield / vacuum_vessel 層の追加、周期境界化) に順次拡張できる足場が整う。

CLI は `cargo run -- --input parastell/examples/wout_vmec.nc --output out/chamber.step [--s 1.0]` 形式 (`--s` 既定 1.0、1.08 などの `wall_s` に対応)。profile 数は parastell デフォルト (num_ribs=61, num_rib_pts=61) を参考にしつつ全周換算で拡大する。

## Approach

### ファイル構成
単一 `src/main.rs` (見積 ~220 行)。関数分割:
- `Args { input, output, s }` : `clap::Parser` derive 構造体
- `load_vmec(path) -> VmecData` : netCDF を開いて全 `ns` 行の Fourier 係数と mode 番号、s 軸を返す
- `natural_cubic_spline(xs, ys) -> [poly_coeffs; n-1]` / `eval_spline(..., x)` : 60 行の自前実装
- `interp_coeffs_at_s(vmec, s) -> (rmnc_at_s, zmns_at_s)` : 全 179 mode を s で内挿 (外挿対応)
- `eval_rz(rmnc_at_s, zmns_at_s, xm, xn, theta, phi) -> (f64, f64)` : Fourier 和
- `main()` : CLI→load→s 内挿→grid 構築→`Solid::bspline`→`write_step`

### 数学

任意の `s` でフラックス面を評価:
```
1. 各 mn について s_grid (ns 点) vs rmnc[:, mn] に natural cubic spline 作成
2. target s で評価 → rmnc_at_s[mn] (mnmax 要素)、zmns_at_s[mn] 同様
3. R(θ,φ) = Σ_mn rmnc_at_s[mn] · cos(xm[mn]·θ - xn[mn]·φ)
   Z(θ,φ) = Σ_mn zmns_at_s[mn] · sin(xm[mn]·θ - xn[mn]·φ)
4. x = R·cos(φ),  y = R·sin(φ),  z = Z
```

`s > 1.0` (例: wall_s = 1.08) では natural cubic spline の末端ポリノミアルを延長して外挿。parastell `read_vmec.py:859-886` (scipy CubicSpline) と数値的にほぼ同等。scipy の既定は 'not-a-knot' 境界だが、LCFS 外 8% 程度の小さな外挿では natural との差は無視可能。内部値 (s ≤ 1.0) では差は 0。

**自前 natural cubic spline** (60 行程度):
- 入力: `xs[n]` (昇順), `ys[n]`
- tridiagonal 連立: `h_i = x_{i+1} - x_i`, `μ_i = h_i / (h_i + h_{i+1})`, `λ_i = 1 - μ_i`, `d_i = 6((y_{i+1}-y_i)/h_{i+1} - (y_i-y_{i-1})/h_i) / (h_{i-1}+h_i)`
- 境界: `M_0 = M_{n-1} = 0` (natural)
- Thomas algorithm で `M_i` を解く
- 各区間 `[x_i, x_{i+1}]` の 3 次多項式係数を返す
- 評価: 二分探索で区間特定 → 3 次展開。外挿は最初/最後の区間の多項式を延長

### グリッド & cadrum 呼び出し

`cadrum::Solid::bspline<const M, const N>(grid: [[DVec3; N]; M], periodic: bool)` (solid.rs:278, `M>=2, N>=3` 必須)。`periodic=true` で両方向 closed B-spline サーフェスとしてトーラスを構築。

**推奨サイズ: `M=240 (toroidal ribs), N=64 (poloidal rib_pts)`**
- `nfp=4` の倍数 240 で周期対称性と整合 (244=61×4 はプライム 61 で扱いにくい)
- N=64 は parastell の 61 に近い 2 のべき
- 計算量 15k 点で OCCT 処理は秒オーダに収まる見込み
- 角度はいずれも `[0, 2π)` 開区間で populate (閉じ点重複なし、cadrum 内部 periodic basis が閉曲面化)

### 依存関係変更 (`Cargo.toml`)

- **削除**: `mandolin = "0.4.7"` (OpenAPI→Axum サーバ生成ツール、用途外)
- **追加**:
  - `netcdf = "0.10"` — VMEC ファイル読み込み
  - `clap = { version = "4", features = ["derive"] }` — CLI パーサ (`--input`, `--output`, `--s`)
  - `anyhow = "1"` — エラー伝搬簡略化
- `cadrum = "0.6.5"` はそのまま
- natural cubic spline は自前実装 (依存追加せず)

### ビルド時の libnetcdf 解決

`libnetcdf.so` は `~/miniforge3/envs/parastell_env/lib/` のみに存在 (base には無し)。ビルド・実行時に以下の env を設定する必要:

```bash
export NETCDF_DIR=$HOME/miniforge3/envs/parastell_env
cargo build
cargo run -- --input parastell/examples/wout_vmec.nc --output out/chamber.step
```

README に 3 行追記で対応 (`build.rs` 化は過剰)。

### 出力ディレクトリ

`std::fs::create_dir_all(output.parent().unwrap_or(Path::new(".")))` で `out/` の自動作成。既存 SVG 出力ロジックは削除 (chamber.step 単目的)。必要なら将来 `--svg` オプションで再導入可能。

### 将来拡張を見据えた構造

- 今回の実装で `interp_coeffs_at_s(s)` が既に s 任意対応なので、wall_s > 1 (例 1.08) はそのまま動く (CLI `--s` で切替可能)
- grid 構築は `(theta, phi) -> DVec3` クロージャを取る汎用関数にしておけば、offset (厚み法線方向) を加算するだけで first_wall / breeder など他コンポーネントへ転用可能
- 内側→外側の複数層 (first_wall, breeder, ...) への拡張時は、パラストラ同様に各層の厚みを法線方向に累積加算する offset_mat を導入

## Critical Files

- `/home/smith/alphastell/src/main.rs` — 全面書き換え
- `/home/smith/alphastell/Cargo.toml` — 依存変更 (mandolin 削除、netcdf/anyhow 追加)
- `/home/smith/alphastell/parastell/examples/wout_vmec.nc` — 読み取り入力 (変更しない)
- 参考: `/home/smith/.cargo/registry/src/index.crates.io-*/cadrum-0.6.2/src/occt/solid.rs:278` — `Solid::bspline` シグネチャ
- 参考: `/home/smith/miniforge3/envs/parastell_env/lib/python3.12/site-packages/parastell/pystell/read_vmec.py:859-886` — Fourier 評価の参照実装

## Verification

1. **ビルド確認**:
   ```bash
   NETCDF_DIR=$HOME/miniforge3/envs/parastell_env cargo build --release
   ```
   warning 0 / error 0 を確認。

2. **実行確認 (LCFS, s=1.0)**:
   ```bash
   NETCDF_DIR=$HOME/miniforge3/envs/parastell_env cargo run --release -- \
     --input parastell/examples/wout_vmec.nc --output out/chamber.step
   ```
   `out/chamber.step` が生成されること、ファイルサイズが数 MB オーダ (parastell の `chamber.step` と同程度) であることを確認。

2b. **外挿確認 (s=1.08)**:
   ```bash
   NETCDF_DIR=$HOME/miniforge3/envs/parastell_env cargo run --release -- \
     --input parastell/examples/wout_vmec.nc --output out/wall_surface.step --s 1.08
   ```
   chamber.step より一回り大きい閉曲面が生成されること。FreeCAD で重ね表示して chamber を包んでいることを確認。

3. **妥当性チェック** (目視):
   - FreeCAD で `out/chamber.step` を開く
   - 4 回対称性 (nfp=4) の "bean" 型断面が 4 回繰り返されていること
   - parastell の `examples/chamber.step` (1 周期) と比較して、同じ 1 セグメントが 4 つ連結された形状であること

4. **数値チェック** (簡易):
   - `rmax_surf`, `rmin_surf`, `zmax_surf` を netCDF から別途読んで、生成した点群の極値がそれらにおおよそ一致することを確認 (オプション)

5. **エッジケース**:
   - 存在しない入力パス → エラーメッセージで exit
   - 出力ディレクトリが深くネスト (`out/sub/dir/x.step`) → `create_dir_all` が機能
