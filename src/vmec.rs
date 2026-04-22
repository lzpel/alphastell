//! VMEC ファイル (wout_*.nc) を読み込んで磁束面の (R, Z) を評価するモジュール。
//!
//! # このモジュールが扱う世界
//!
//! **ステラレータ** は核融合炉の一種で、ねじれたドーナツ (トーラス) 型の容器の中に
//! 強力な磁場で**プラズマ**(電離した高温ガス)を閉じ込めます。核融合反応を起こすには
//! プラズマを温度 1 億度、圧力十数気圧まで持ち上げる必要があり、物質の壁で閉じ込める
//! ことはできないので、**磁場の籠** で宙に浮かせておきます。
//!
//! プラズマの形を知らないと炉の設計 (ブランケットの厚み、コイルの位置、etc) が
//! できません。そこで **VMEC** というシミュレータが登場します。VMEC は
//! 「この形のコイルを配置したら、プラズマはこうなります」という**平衡計算**を行い、
//! 結果を `wout_*.nc` という netCDF ファイルに書き出します。
//!
//! # プラズマ座標 (s, θ, φ) とは？
//!
//! ドーナツ型のプラズマ内の点を指定するのに、直交座標 (x, y, z) ではなく
//! **磁束座標** (s, θ, φ) を使います。
//!
//! - `s` : 「プラズマの中心 (磁気軸) からどれくらい外側か」を 0〜1 で表す値。
//!         s=0 が中心、s=1 が **LCFS** (Last Closed Flux Surface = プラズマの最外縁)。
//!         水に浮かんだ玉ねぎを想像して、皮の層番号を 0 (芯) 〜 1 (外皮) で表すのに似ている。
//! - `θ` (theta): 玉ねぎの**断面**をぐるっと一周する角度 (0〜2π)。「上下左右のどこ」か。
//! - `φ` (phi): トーラスの**周**をぐるっと一周する角度 (0〜2π)。「ドーナツを上から見て
//!               時計の何時の位置か」に対応。
//!
//! 本 repo の `wout_vmec.nc` は **4 周期対称** (nfp=4) なステラレータで、
//! φ を 90° ずつ進めると同じ形が出てきます。
//!
//! # なぜ Fourier 級数?
//!
//! プラズマの形 `R(θ, φ)`, `Z(θ, φ)` は複雑な 2 次元の波です。VMEC はこれを
//! **サイン・コサインの足し算** (= Fourier 級数) で表現してファイルに保存します。
//! 高校で習う三角関数の足し算だけで、複雑な曲面がコンパクトに書ける、というのが
//! Fourier 級数の強みです。
//!
//! ```text
//!   R(θ, φ) = Σ rmnc[k] × cos(m[k] × θ − n[k] × φ)
//!   Z(θ, φ) = Σ zmns[k] × sin(m[k] × θ − n[k] × φ)
//! ```
//!
//! 係数 `rmnc`, `zmns` と波の周期を決める整数 `m`, `n` を netCDF から読むのが
//! このモジュールの仕事です。
//!
//! # このモジュールの API (全部 VmecData のメソッド)
//!
//! 1. [`VmecData::load`] — netCDF ファイルを開いて [`VmecData`] を作る
//! 2. [`VmecData::index_rz`] — s グリッド上の離散点 `s_grid[index_s]` で (R, Z) を計算
//! 3. [`VmecData::interpolate_rz`] — 任意の s で (R, Z) を計算 (Fourier 係数を s 方向にスプライン)
//!
//! generate / first_wall は `interpolate_rz(s, θ, φ)` を (θ, φ) 走査しながら呼べばよい。
//! 内部ヘルパーとして `eval_rz(r_coeff, z_coeff, θ, φ)` (private) が Fourier 和だけを担当する。

use crate::Result;
use netcdf3::FileReader;
use std::path::Path;
use std::sync::OnceLock;

// ================================================================
// VmecData — 必要な変数だけ抽出したプラズマデータ
// ================================================================

/// VMEC が出した `wout_*.nc` ファイルから、プラズマ形状を評価するのに必要な
/// **最小セット**だけを抜き出して保持する構造体。
///
/// # フィールドの意味
///
/// - `s_grid`:  規格化磁束座標 s の離散グリッド (0, 1/(ns-1), 2/(ns-1), ..., 1.0)。
///              長さ `ns` (例: 201 点)。
/// - `rmnc`:    R の Fourier 係数。`rmnc[i][k]` = 「s_grid[i] の磁束面における
///              k 番目のモードの振幅」。外側の Vec の長さは ns、内側は mnmax。
/// - `zmns`:    Z の Fourier 係数。構造は rmnc と同じ。
/// - `mode_poloidal`: 各モードの **poloidal モード数 m** (断面方向の波が何周期か)。
///                    VMEC ファイル内の名前は `xm`。
/// - `mode_toroidal`: 各モードの **toroidal モード数 n** (周方向の波が何周期か)。
///                    VMEC ファイル内の名前は `xn`。
///                    `(mode_poloidal, mode_toroidal)` の組 = `(m, n)` で 1 つの波。
///
/// 例: `mode_poloidal=[0, 1, 0, 1, ...]`, `mode_toroidal=[0, 0, 4, 4, ...]`, `mnmax=179` 個。
pub struct VmecData {
	/// 規格化磁束座標 s の配列 (長さ ns)
	pub s_grid: Vec<f64>,
	/// R の Fourier 係数 (rmnc[s 軸 index][mode 番号])
	pub rmnc: Vec<Vec<f64>>,
	/// Z の Fourier 係数 (zmns[s 軸 index][mode 番号])
	pub zmns: Vec<Vec<f64>>,
	/// poloidal モード数 m (長さ mnmax)。ファイル上の名前は `xm`。
	pub mode_poloidal: Vec<f64>,
	/// toroidal モード数 n (長さ mnmax)。ファイル上の名前は `xn`。
	pub mode_toroidal: Vec<f64>,
	/// `interpolate_rz` が初回に構築して以降使い回すスプライン群。(r_splines, z_splines) で
	/// 各 Vec の長さは mnmax。[`OnceLock`] により再計算されない (計算結果は VmecData に
	/// 紐づく遅延フィールド)。
	splines: OnceLock<(Vec<NaturalSpline>, Vec<NaturalSpline>)>,
}

impl VmecData {
	// --------------------------------------------------------------
	// load — netCDF から VmecData を作る (コンストラクタ)
	// --------------------------------------------------------------

	/// netCDF ファイル (wout_*.nc) を開いて、このモジュールで使う変数だけ読み出す。
	///
	/// netCDF は **科学技術計算でよく使われるバイナリ形式**で、中身は「変数名と
	/// 多次元配列のペア」の集まりです。HDF5 という別規格の上に乗っているので、
	/// 読むには libnetcdf と libhdf5 の両方が必要で、Rust 側では `netcdf` クレート
	/// がその FFI をしてくれます。
	///
	/// VMEC の wout ファイルには何十もの変数が入っていますが、今回プラズマ表面を
	/// 描くのに必要なのは `rmnc`, `zmns`, `xm`, `xn` の 4 つだけです
	/// (Rust 側の名前はそれぞれ `rmnc`, `zmns`, `mode_poloidal`, `mode_toroidal`)。
	pub fn load(path: &Path) -> Result<Self> {
		// netCDF-3 (Classic / 64-bit offset) ファイルを pure-Rust で読む。
		// VMEC の wout は `CDF\x02` (64-bit offset) なので HDF5 は不要。
		//
		// netcdf3 の ReadError は内部に Rc を持つので !Send。エラーメッセージを
		// 文字列化してから Box<dyn Error> に載せる。
		let mut file = FileReader::open(path)
			.map_err(|e| format!("open {}: {:?}", path.display(), e))?;

		// rmnc の shape を DataSet から取る (ns × mnmax)
		let shape: Vec<usize> = file
			.data_set()
			.get_var("rmnc")
			.ok_or("missing rmnc")?
			.get_dims()
			.iter()
			.map(|d| d.size())
			.collect();
		let ns = shape[0]; // 放射方向 (s 軸) のグリッド点数
		let mnmax = shape[1]; // Fourier mode の個数

		// 値を実際に読む。read_var は DataVector を返すので f64 スライスを取り出す。
		let read_f64 = |f: &mut FileReader, name: &str| -> Result<Vec<f64>> {
			f.read_var(name)
				.map_err(|e| format!("read {}: {:?}", name, e))?
				.get_f64_into()
				.map_err(|_| format!("{} is not f64", name).into())
		};
		let rmnc_flat = read_f64(&mut file, "rmnc")?;
		let zmns_flat = read_f64(&mut file, "zmns")?;
		let mode_poloidal = read_f64(&mut file, "xm")?;
		let mode_toroidal = read_f64(&mut file, "xn")?;

		// netCDF から来たのは 1 次元に潰れた配列 (長さ ns*mnmax)。
		// これを `[ns][mnmax]` の入れ子 Vec に作り直す方が後段のコードで扱いやすい。
		let rmnc: Vec<Vec<f64>> = (0..ns)
			.map(|i| rmnc_flat[i * mnmax..(i + 1) * mnmax].to_vec())
			.collect();
		let zmns: Vec<Vec<f64>> = (0..ns)
			.map(|i| zmns_flat[i * mnmax..(i + 1) * mnmax].to_vec())
			.collect();

		// VMEC の慣例: s の離散点は 0, 1/(ns-1), 2/(ns-1), ..., 1.0 の一様分布。
		// ファイルに書いてないので自分で構築する。
		let s_grid: Vec<f64> = (0..ns).map(|i| i as f64 / (ns - 1) as f64).collect();

		Ok(Self {
			s_grid,
			rmnc,
			zmns,
			mode_poloidal,
			mode_toroidal,
			splines: OnceLock::new(),
		})
	}

	// --------------------------------------------------------------
	// eval_rz — s グリッド点ちょうどで Fourier 級数の和を計算
	// --------------------------------------------------------------

	/// s グリッド上の離散点 `s_grid[index_s]` における (R, Z) を Fourier 級数の和で計算する。
	///
	/// ```text
	///   R(θ, φ) = Σ_k  rmnc[index_s][k] · cos(mode_poloidal[k] · θ − mode_toroidal[k] · φ)
	///   Z(θ, φ) = Σ_k  zmns[index_s][k] · sin(mode_poloidal[k] · θ − mode_toroidal[k] · φ)
	/// ```
	///
	/// **スプライン不要**。任意 s で評価したい場合は [`Self::spline_rz`] を使うこと。
	///
	/// # なぜ R は cos で Z は sin ?
	///
	/// VMEC の wout ファイルは「**ステラレータ対称**」な平衡を前提にしていて
	/// (`lasym=0`)、上下 (Z の向き) を反転すると元と同じ形になる。この対称性のもと
	/// では R は偶関数、Z は奇関数に分解でき、それぞれ cos 成分 (rmnc)、sin 成分
	/// (zmns) だけで書ける。左右非対称なプラズマを扱う場合は rmns, zmnc が足されるが、
	/// 本 example の wout は対称なので不要。
	///
	/// # なぜ `m·θ − n·φ` という 1 つの角度にまとめるのか
	///
	/// ステラレータの磁力線はトーラスの周りをぐるぐる**らせん状**に巻く。θ と φ を
	/// 独立に変えるのではなく「m 回 θ 方向に進み、n 回 φ 方向に進む」という**らせん
	/// 角** `m·θ − n·φ` を考えると、個々のモードがそのまま磁力線の 1 種類の
	/// ヘリカル構造に対応するので自然。
	///
	/// # 各モードの物理的意味 (本 repo の `wout_vmec.nc` で実測した LCFS 例)
	///
	/// ```text
	/// (m, n)    振幅[m]    意味
	/// (0, 0)   +11.06      ★ R の定常成分 = トーラスの major radius そのもの
	///                        (Z 軸からトーラス中心軸まわりの「平均距離」)
	/// (1, 0)    +1.89      断面が θ 方向に楕円化 (上下方向に引き伸ばす形状補正)
	/// (0, 4)    +1.53      φ 方向に nfp=4 回のうねり
	///                        (断面が φ に応じて膨らんだり引っ込んだり)
	/// (1, -4)   -1.39      ヘリカルな捻じり (θ と φ のカップリング、
	///                        ステラレータらしさの本体)
	/// (1, +4)   +0.58      副次ヘリカル
	/// ```
	///
	/// - **(m=0, n=0) モード**は定数 cos(0) = 1 なので、`rmnc[(0,0)]` がそのまま R の
	///   平均値、つまり **トーラスの major radius** を意味する。本 wout では約 **11 m**。
	/// - 残りのモードは「円形から歪ませる形状補正」で、ステラレータ特有の bean 型
	///   断面と nfp=4 のヘリカル構造をこの数モードだけで再現できる。
	///
	/// # Shafranov シフト (補足)
	///
	/// 磁気軸 (s=0) と LCFS (s=1) で (0,0) モードの値が微妙に違う:
	///
	/// ```text
	/// s=0 (磁気軸) :  rmnc[(0,0)] = 11.28 m
	/// s=1 (LCFS)   :  rmnc[(0,0)] = 11.06 m
	///      差       :  磁気軸が LCFS 中心より 22 cm **外側 (大 R 側)** にずれている
	/// ```
	///
	/// これは **Shafranov シフト**と呼ばれる現象で、プラズマ圧力によって磁気軸が
	/// 低磁場側 (外側) に押し出される効果。この wout が高 β な定常状態を表している
	/// ことを数値的に確認できる。
	///
	/// # Z 側には定常成分は実質無い
	///
	/// `zmns` は sin 展開なので (m=0, n=0) モードは `sin(0) = 0` で寄与ゼロ。
	/// 上下対称なプラズマなら Z のオフセットは自動的に 0 になる。
	fn eval_rz(&self, r_coeff: &[f64], z_coeff: &[f64], theta: f64, phi: f64) -> (f64, f64) {
		let mnmax = self.mode_poloidal.len();
		let mut r = 0.0;
		let mut z = 0.0;
		for k in 0..mnmax {
			// m·θ − n·φ は「その点でのらせん位相」
			let angle = self.mode_poloidal[k] * theta - self.mode_toroidal[k] * phi;
			r += r_coeff[k] * angle.cos();
			z += z_coeff[k] * angle.sin();
		}
		(r, z)
	}

	#[allow(dead_code)] // API として公開; 現在は tests からのみ使用
	pub fn index_rz(&self, index_s: usize, theta: f64, phi: f64) -> (f64, f64) {
		self.eval_rz(&self.rmnc[index_s], &self.zmns[index_s], theta, phi)
	}

	pub fn interpolate_rz(&self, s: f64, theta: f64, phi: f64) -> (f64, f64) {
		// 各モードごとの s 軸方向スプラインは (s, θ, φ) に依存しないので、VmecData の
		// ライフタイムで 1 回だけ構築してメモ化する。初回呼び出しで lazy 初期化。
		let (r_splines, z_splines) = self.splines.get_or_init(|| {
			let mnmax = self.mode_poloidal.len();
			let mut r_splines = Vec::with_capacity(mnmax);
			let mut z_splines = Vec::with_capacity(mnmax);
			for k in 0..mnmax {
				let r_col: Vec<f64> = self.rmnc.iter().map(|row| row[k]).collect();
				let z_col: Vec<f64> = self.zmns.iter().map(|row| row[k]).collect();
				r_splines.push(NaturalSpline::new(&self.s_grid, &r_col));
				z_splines.push(NaturalSpline::new(&self.s_grid, &z_col));
			}
			(r_splines, z_splines)
		});
		// 以降は eval だけでよい (スプライン構築コストがかからない)
		let mnmax = self.mode_poloidal.len();
		let r_at_s: Vec<f64> = (0..mnmax).map(|k| r_splines[k].eval(s)).collect();
		let z_at_s: Vec<f64> = (0..mnmax).map(|k| z_splines[k].eval(s)).collect();
		self.eval_rz(&r_at_s, &z_at_s, theta, phi)
	}
}

// ================================================================
// NaturalSpline — 自然 3 次スプライン (内部 helper)
// ================================================================

/// スプライン補間のための内部構造体。**このモジュール外には公開しない** (pub なし)。
///
/// # スプライン補間って何?
///
/// 離散的な点 (x₁, y₁), (x₂, y₂), ..., (xₙ, yₙ) が手元にあって、点と点の
/// **間の値** を滑らかに埋めたいときに使う手法。1 次関数で繋ぐと折れ線になって
/// しまうので、区間ごとに **3 次多項式** で繋いでなめらか (2 階微分まで連続) に
/// する、というのが「3 次スプライン」。
///
/// ## どう滑らかにするか
///
/// 区間 [xᵢ, xᵢ₊₁] の多項式を `y(x) = aᵢ + bᵢ(x-xᵢ) + cᵢ(x-xᵢ)² + dᵢ(x-xᵢ)³`
/// と置くと、各区間に 4 つの係数で合計 4(n-1) 個の未知数。
/// 繋ぎ目での値・1 階微分・2 階微分の連続性と、両端での境界条件で方程式を立て、
/// Thomas algorithm (三重対角連立方程式専用の高速解法) で O(n) で解く。
///
/// ## "natural" とは
///
/// 両端で 2 階微分 = 0 という境界条件を選ぶ形。直感的には「両端で**曲がりが最小**
/// になるように」つなぐ。物理的に根拠がある選び方ではないが、端点でのふるまいが
/// おだやかで、範囲外 (外挿) でも暴れにくい。
///
/// ## なぜこれを使うのか
///
/// VMEC の Fourier 係数は s 軸上に 201 点だけ離散的に格納されている。プラズマ境界
/// (s=1.0) の少し外 (s=1.08 など) を評価したいとき、離散データの間を補間するために
/// スプラインが必要。
struct NaturalSpline {
	/// x 軸上のサンプル点 (昇順)
	xs: Vec<f64>,
	/// 各区間の 3 次多項式係数 (y = a + b·dx + c·dx² + d·dx³)
	a: Vec<f64>,
	b: Vec<f64>,
	c: Vec<f64>,
	d: Vec<f64>,
}

impl NaturalSpline {
	/// (xs, ys) のデータからスプラインを構築する。
	///
	/// 手順:
	/// 1. 各区間の幅 h[i] を計算
	/// 2. 2 階微分 M[i] を解く三重対角連立方程式を立てる
	/// 3. Thomas algorithm で前進消去 → 後退代入
	/// 4. 解いた M[i] と h[i], y[i] から各区間の 3 次多項式係数 a, b, c, d を作る
	fn new(xs: &[f64], ys: &[f64]) -> Self {
		let n = xs.len();
		assert_eq!(ys.len(), n);
		assert!(n >= 2, "スプライン構築には最低 2 点必要");

		// h[i] = xs[i+1] - xs[i]  (各区間の幅)
		let h: Vec<f64> = (0..n - 1).map(|i| xs[i + 1] - xs[i]).collect();

		// 2 階微分 M[i] を格納する配列。自然スプラインなので両端は 0 固定。
		let mut m = vec![0.0; n];

		if n >= 3 {
			// 内部の n-2 個の M を解くための三重対角連立方程式:
			//   h[i]   * M[i]
			// + 2(h[i] + h[i+1]) * M[i+1]  <- これが対角
			// + h[i+1] * M[i+2]
			// = 6 * ((y[i+2] - y[i+1])/h[i+1] - (y[i+1] - y[i])/h[i])
			let mut diag = vec![0.0; n - 2]; // 対角成分
			let mut upper = vec![0.0; n - 2]; // 上三角成分
			let mut rhs = vec![0.0; n - 2]; // 右辺
			for i in 0..n - 2 {
				diag[i] = 2.0 * (h[i] + h[i + 1]);
				if i < n - 3 {
					upper[i] = h[i + 1];
				}
				rhs[i] = 6.0
					* ((ys[i + 2] - ys[i + 1]) / h[i + 1]
						- (ys[i + 1] - ys[i]) / h[i]);
			}

			// 前進消去: 行 i を使って行 i+1 の対角左隣を 0 にする
			for i in 1..n - 2 {
				let w = h[i] / diag[i - 1];
				diag[i] -= w * upper[i - 1];
				rhs[i] -= w * rhs[i - 1];
			}

			// 後退代入: 末尾の行から順に M の値を決めていく
			let mut m_inner = vec![0.0; n - 2];
			m_inner[n - 3] = rhs[n - 3] / diag[n - 3];
			for i in (0..n - 3).rev() {
				m_inner[i] = (rhs[i] - upper[i] * m_inner[i + 1]) / diag[i];
			}

			// m_inner は内部のみ (index 1..n-1)。両端の M[0] = M[n-1] = 0 は据え置き。
			for i in 0..n - 2 {
				m[i + 1] = m_inner[i];
			}
		}

		// 各区間の 3 次多項式係数を生成
		//   y = a + b·(x - xᵢ) + c·(x - xᵢ)² + d·(x - xᵢ)³
		//   a = yᵢ
		//   b = (yᵢ₊₁ - yᵢ)/hᵢ - hᵢ·(2Mᵢ + Mᵢ₊₁)/6
		//   c = Mᵢ / 2
		//   d = (Mᵢ₊₁ - Mᵢ) / (6·hᵢ)
		let mut a = Vec::with_capacity(n - 1);
		let mut b = Vec::with_capacity(n - 1);
		let mut c = Vec::with_capacity(n - 1);
		let mut d = Vec::with_capacity(n - 1);
		for i in 0..n - 1 {
			let hi = h[i];
			a.push(ys[i]);
			b.push((ys[i + 1] - ys[i]) / hi - hi * (2.0 * m[i] + m[i + 1]) / 6.0);
			c.push(m[i] / 2.0);
			d.push((m[i + 1] - m[i]) / (6.0 * hi));
		}

		NaturalSpline {
			xs: xs.to_vec(),
			a,
			b,
			c,
			d,
		}
	}

	/// 指定の x での y 値を計算する。
	///
	/// 範囲外の x が来た場合は、最初または最後の区間の多項式をそのまま延長して
	/// **外挿**する (= extrapolate)。VMEC の wall_s = 1.08 など、LCFS (s=1)
	/// の少し外でも値が欲しい場合に使う。
	fn eval(&self, x: f64) -> f64 {
		let n = self.xs.len();
		// どの区間の多項式を使うか決める
		let idx = if x <= self.xs[0] {
			// x が左端より小さい: 最初の区間の多項式で外挿
			0
		} else if x >= self.xs[n - 1] {
			// x が右端より大きい: 最後の区間の多項式で外挿
			n - 2
		} else {
			// 範囲内: 二分探索で適切な区間を見つける
			match self.xs.binary_search_by(|v| v.partial_cmp(&x).unwrap()) {
				Ok(i) => i.min(n - 2),  // 完全一致
				Err(i) => i - 1,          // 挿入位置 - 1 が含む区間
			}
		};
		// y = a + b·(x-xᵢ) + c·(x-xᵢ)² + d·(x-xᵢ)³
		let dx = x - self.xs[idx];
		self.a[idx] + self.b[idx] * dx + self.c[idx] * dx.powi(2) + self.d[idx] * dx.powi(3)
	}
}

// ================================================================
// ベンチマーク用のテスト
// ================================================================

#[cfg(test)]
mod tests {
	use super::*;
	use std::time::Instant;

	/// 1000 点を interpolate_rz で計算したときの実時間を測って、generate の現実的なコスト感を掴む。
	/// `cargo test --release -- --nocapture bench_interpolate_rz_1000pts` で測定推奨。
	#[test]
	fn bench_interpolate_rz_1000pts() {
		let path = Path::new("parastell/examples/wout_vmec.nc");
		if !path.exists() {
			eprintln!("skip: {} not found", path.display());
			return;
		}
		let vmec = VmecData::load(path).expect("load vmec");

		const N: usize = 1000;
		let mut checksum = 0.0f64;
		let start = Instant::now();
		for i in 0..N {
			let t = i as f64 / N as f64;
			// s は LCFS 内外を織り交ぜる (0.2〜1.08)、θ・φ は非自明な数列にして
			// コンパイラに定数最適化されないようにする。
			let s = 0.2 + 0.88 * t;
			let theta = 0.037 * i as f64;
			let phi = 0.041 * i as f64;
			let (r, z) = vmec.interpolate_rz(s, theta, phi);
			checksum += r + z;
		}
		let elapsed = start.elapsed();
		eprintln!(
			"interpolate_rz × {}pts: {:?} ({:.2} us/pt), checksum={:.6}",
			N,
			elapsed,
			elapsed.as_secs_f64() * 1e6 / N as f64,
			checksum
		);
	}

	/// グリッド点 `s_grid[i]` における index_rz と interpolate_rz の返値が一致することを確認する。
	/// スプライン補間がノード上で元データを通ることを検証する健全性チェックでもある。
	#[test]
	fn index_rz_matches_interpolate_rz_on_grid() {
		let path = Path::new("parastell/examples/wout_vmec.nc");
		if !path.exists() {
			eprintln!("skip: {} not found", path.display());
			return;
		}
		let vmec = VmecData::load(path).expect("load vmec");
		// LCFS (s=1.0) と磁気軸寄り (s=0.5) と中央 (s=0.5 付近の index) を抜き打ち確認。
		for &i in &[0, vmec.s_grid.len() / 2, vmec.s_grid.len() - 1] {
			let s = vmec.s_grid[i];
			for (theta, phi) in [(0.0, 0.0), (0.37, 1.29), (1.0, 0.5)] {
				let (r_idx, z_idx) = vmec.index_rz(i, theta, phi);
				let (r_int, z_int) = vmec.interpolate_rz(s, theta, phi);
				let tol = 1e-9;
				assert!(
					(r_idx - r_int).abs() < tol,
					"R mismatch at i={i}, θ={theta}, φ={phi}: idx={r_idx}, int={r_int}"
				);
				assert!(
					(z_idx - z_int).abs() < tol,
					"Z mismatch at i={i}, θ={theta}, φ={phi}: idx={z_idx}, int={z_int}"
				);
			}
		}
	}
}
