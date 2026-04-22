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
use std::f64::consts::TAU;
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
	splines: OnceLock<(Vec<CubicSpline>, Vec<CubicSpline>)>,
}

pub struct RZ {
	pub r: f64,
	pub z: f64,
	pub dr_dtheta: f64,
	pub dr_dphi: f64,
	pub dz_dtheta: f64,
	pub dz_dphi: f64,
}

/// [`VmecData::mesh`] の `offset != 0` 時に使う法線の定義。
#[derive(Clone, Copy, Debug)]
#[allow(dead_code)] // バリアント列挙、呼び出し側は後続 PR で追加予定
pub enum NormalKind {
	/// **parastell 互換**。constant-φ 断面内の 2D 法線。
	/// (R, Z) 断面内で θ 接線 `(dR/dθ, dZ/dθ)` を 90° 回した `(dZ/dθ, -dR/dθ)` を、
	/// φ で Z 軸まわりに回転して 3D に埋め込む。φ 方向の形状変化は無視される。
	Planar,
	/// 真の 3D 曲面法線 `∂p/∂φ × ∂p/∂θ` を外向きに正規化したもの。
	/// φ 方向の形状変化も反映するため、ヘリカル成分が強い領域で Planar と向きがずれる。
	Surface,
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
	fn eval_rz(&self, r_coeff: &[f64], z_coeff: &[f64], theta: f64, phi: f64) -> RZ {
		let mnmax = self.mode_poloidal.len();
		let mut res = RZ {
			r: 0.0,
			z: 0.0,
			dr_dtheta: 0.0,
			dr_dphi: 0.0,
			dz_dtheta: 0.0,
			dz_dphi: 0.0,
		};
		for k in 0..mnmax {
			// m·θ − n·φ は「その点でのらせん位相」
			let angle = self.mode_poloidal[k] * theta - self.mode_toroidal[k] * phi;
			res.r += r_coeff[k] * angle.cos();
			res.z += z_coeff[k] * angle.sin();
			// ∂(cos α)/∂x = (-sin α)·(∂α/∂x), ∂(sin α)/∂x = (cos α)·(∂α/∂x)
			let dangle_dtheta = self.mode_poloidal[k];
			let dangle_dphi = -self.mode_toroidal[k];
			res.dr_dtheta += r_coeff[k] * (-angle.sin()) * dangle_dtheta;
			res.dr_dphi += r_coeff[k] * (-angle.sin()) * dangle_dphi;
			res.dz_dtheta += z_coeff[k] * angle.cos() * dangle_dtheta;
			res.dz_dphi += z_coeff[k] * angle.cos() * dangle_dphi;
		}
		res
	}

	#[allow(dead_code)] // API として公開; 現在は tests からのみ使用
	pub fn index_rz(&self, index_s: usize, theta: f64, phi: f64) -> RZ {
		self.eval_rz(&self.rmnc[index_s], &self.zmns[index_s], theta, phi)
	}

	/// (θ, φ) を等分した格子で磁束面 (または `offset` だけ離れた平行面) の 3D 点を返す。
	///
	/// - 角度範囲は `[0, 2π)` の半開区間。θ=0 と θ=2π は同一点なので終点は含めない。
	/// - `offset` の単位は VMEC ネイティブの **m**。スケール変換は呼び出し側で行う。
	/// - 戻り値は `result[phi_idx][theta_idx]` で `div_phi × div_theta` の行列。
	/// - `offset == 0.0` なら法線計算はスキップする。
	#[allow(dead_code)] // API として公開; 呼び出し側は後続 PR で導入予定
	pub fn mesh(
		&self,
		div_theta: usize,
		div_phi: usize,
		s: f64,
		offset: f64,
		normal: NormalKind,
	) -> Vec<Vec<[f64; 3]>> {
		fn cross(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
			[
				a[1] * b[2] - a[2] * b[1],
				a[2] * b[0] - a[0] * b[2],
				a[0] * b[1] - a[1] * b[0],
			]
		}

		let mut grid: Vec<Vec<[f64; 3]>> = Vec::with_capacity(div_phi);
		for i in 0..div_phi {
			let phi = TAU * (i as f64) / (div_phi as f64);
			let (sp, cp) = phi.sin_cos();
			let mut row: Vec<[f64; 3]> = Vec::with_capacity(div_theta);
			for j in 0..div_theta {
				let theta = TAU * (j as f64) / (div_theta as f64);
				let rz = self.interpolate_rz(s, theta, phi);
				// まず φ=0 の断面で点と法線を組み立てる (x=R, y=0, z=Z の 2D ライクな座標系)。
				// ∂R/∂φ, ∂Z/∂φ はこの座標系では「隣の断面がどう変わるか」の成分として残る。
				let mut p = [rz.r, 0.0, rz.z];
				if offset != 0.0 {
					let n = {
						let [t_theta, t_phi] = match normal {
							NormalKind::Planar => {
								// θ 接線 (Surface と共通) と、constant-φ 面の法線 (φ=0 で y_hat)。
								// cross(y_hat, t_θ) が parastell `_normals()` と同じ断面内 2D 外向き法線。
								[
									[rz.dr_dtheta, 0.0, rz.dz_dtheta],
									[0.0, 1.0, 0.0],
								]
							}
							NormalKind::Surface => {
								// φ=0 での接線: ∂p/∂θ = (dR/dθ, 0, dZ/dθ), ∂p/∂φ = (dR/dφ, R, dZ/dφ)
								// cross(t_φ, t_θ) が外向き 3D 曲面法線 (t_θ × t_φ は内向きになる)。
								[
									[rz.dr_dtheta, 0.0, rz.dz_dtheta],
									[rz.dr_dphi, rz.r, rz.dz_dphi],
								]
							}
						};
						cross(t_phi, t_theta)
					};
					let inv_len = 1.0 / (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]).sqrt();
					p[0] += offset * n[0] * inv_len;
					p[1] += offset * n[1] * inv_len;
					p[2] += offset * n[2] * inv_len;
				}
				// 最後に Z 軸まわり φ 回転で実際の (x, y, z) に持ち上げる。
				// (x, y, z) → (x cosφ − y sinφ, x sinφ + y cosφ, z)
				row.push([p[0] * cp - p[1] * sp, p[0] * sp + p[1] * cp, p[2]]);
			}
			grid.push(row);
		}
		grid
	}

	pub fn interpolate_rz(&self, s: f64, theta: f64, phi: f64) -> RZ {
		// 各モードごとの s 軸方向スプラインは (s, θ, φ) に依存しないので、VmecData の
		// ライフタイムで 1 回だけ構築してメモ化する。初回呼び出しで lazy 初期化。
		let (r_splines, z_splines) = self.splines.get_or_init(|| {
			let mnmax = self.mode_poloidal.len();
			let mut r_splines = Vec::with_capacity(mnmax);
			let mut z_splines = Vec::with_capacity(mnmax);
			for k in 0..mnmax {
				let r_col: Vec<f64> = self.rmnc.iter().map(|row| row[k]).collect();
				let z_col: Vec<f64> = self.zmns.iter().map(|row| row[k]).collect();
				// デフォルトは Natural。NotAKnot (scipy 互換) も実装済みだが、現状の
				// cadrum `Solid::shell` (3D 表面 offset) と組み合わせると s=1.08 の
				// 外挿でアグレッシブに延びた波 (max ΔR ≈ 17cm) が shell 操作で
				// 増幅されて first_wall 体積が parastell 比 +81% に膨らむ。Natural は
				// 外挿が線形に近く、現 shell 実装との相性がよい。
				// (cadrum を 2D poloidal offset に切り替える日が来たら NotAKnot 推奨)
				r_splines.push(CubicSpline::new(&self.s_grid, &r_col, BoundaryCondition::Natural));
				z_splines.push(CubicSpline::new(&self.s_grid, &z_col, BoundaryCondition::Natural));
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
// CubicSpline — 3 次スプライン (境界条件を選べる内部 helper)
// ================================================================

/// 境界条件 (両端で何を固定するか) の指定。
///
/// ## Natural (自由端)
///
/// 両端で **2 階微分 = 0**。「両端で曲がりが最小」になるように繋ぐ。端点のふるまい
/// がおだやかで外挿が暴れにくい一方、元データに対応する物理的根拠は弱い。
///
/// ## NotAKnot (not-a-knot / ノットなし)
///
/// **scipy `CubicSpline` のデフォルト**。最初の 2 区間と最後の 2 区間で **3 階微分**
/// が連続、すなわち「最初の 2 区間を 1 本の 3 次式でつなぐ、末尾も同様」という条件。
/// 内側にも端点にも余計な制約をかけない分、元データに素直に追従する。
/// parastell (scipy 依存) との一致を取りたいときはこちら。
///
/// # 両者の違いが出る場所
///
/// - データ範囲内 (補間) はどちらもほぼ一致 (10⁻⁴ オーダ)
/// - データ範囲外 (外挿) で差が出る:
///   - Natural: 端で曲率 0 に引き込まれるので直線的に延びる
///   - NotAKnot: 最終区間の 3 次式をそのまま延長する
///
/// VMEC の s=1.08 のような**外挿**を使うなら NotAKnot の方が scipy と一致する。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BoundaryCondition {
	Natural,
	NotAKnot,
}

/// スプライン補間のための内部構造体。**このモジュール外には公開しない**。
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
/// 境界条件は [`BoundaryCondition`] で切り替え。
///
/// ## なぜこれを使うのか
///
/// VMEC の Fourier 係数は s 軸上に 201 点だけ離散的に格納されている。プラズマ境界
/// (s=1.0) の少し外 (s=1.08 など) を評価したいとき、離散データの間を補間するために
/// スプラインが必要。
struct CubicSpline {
	/// x 軸上のサンプル点 (昇順)
	xs: Vec<f64>,
	/// 各区間の 3 次多項式係数 (y = a + b·dx + c·dx² + d·dx³)
	a: Vec<f64>,
	b: Vec<f64>,
	c: Vec<f64>,
	d: Vec<f64>,
}

impl CubicSpline {
	/// (xs, ys) のデータと境界条件からスプラインを構築する。
	///
	/// 手順:
	/// 1. 各区間の幅 h[i] を計算
	/// 2. 2 階微分 M[i] を解く三重対角連立方程式を立てる (境界条件で第 1・最終行が変化)
	/// 3. Thomas algorithm で前進消去 → 後退代入
	/// 4. NotAKnot の場合は M[0] と M[n-1] を境界条件式から復元
	/// 5. 解いた M[i] と h[i], y[i] から各区間の 3 次多項式係数 a, b, c, d を作る
	fn new(xs: &[f64], ys: &[f64], bc: BoundaryCondition) -> Self {
		let n = xs.len();
		assert_eq!(ys.len(), n);
		assert!(n >= 2, "スプライン構築には最低 2 点必要");

		// h[i] = xs[i+1] - xs[i]  (各区間の幅)
		let h: Vec<f64> = (0..n - 1).map(|i| xs[i + 1] - xs[i]).collect();

		// M[i] = 2 階微分 (= 2·c[i]) を全ノードで持つ配列
		let mut m = vec![0.0; n];

		// 点が 2 点だけの場合は直線、3 点の場合は NotAKnot も事実上 Natural と同じ扱い
		// になる (BC1 と BC2 が同じ条件に縮退するため)。安全のため n<4 では Natural に
		// フォールバック。
		let effective_bc = if n < 4 {
			BoundaryCondition::Natural
		} else {
			bc
		};

		if n >= 3 {
			// 内部の n-2 個の M (= M[1], M[2], ..., M[n-2]) を解く三重対角系。
			// 内部方程式 (i = 1..n-2, ここでは row index = i-1 = 0..n-3):
			//   h[i-1] * M[i-1] + 2(h[i-1]+h[i]) * M[i] + h[i] * M[i+1]
			//   = 6 * ((y[i+1]-y[i])/h[i] - (y[i]-y[i-1])/h[i-1])
			//
			// 境界条件で行 0 と行 n-3 の係数が書き換えられる。明示的に lower/diag/upper
			// の 3 本の Vec を持ち、Thomas アルゴリズムはこれらを使って前進消去する。
			let k = n - 2; // 内部方程式の本数 = 内部 M の個数
			let mut lower = vec![0.0; k]; // 下三角 (row i の M[i-1] 相当の列)
			let mut diag = vec![0.0; k]; // 対角
			let mut upper = vec![0.0; k]; // 上三角
			let mut rhs = vec![0.0; k];

			// まず内部行の係数を組む (row index r = 0..k-1 ↔ 内部 M index i = r+1)
			for r in 0..k {
				let i = r + 1;
				lower[r] = h[i - 1];
				diag[r] = 2.0 * (h[i - 1] + h[i]);
				upper[r] = h[i];
				rhs[r] = 6.0 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1]);
			}

			match effective_bc {
				BoundaryCondition::Natural => {
					// M[0] = 0 と M[n-1] = 0 を代入するので、lower[0] と upper[k-1] の
					// 項は消える。元々 Thomas の先頭・末尾では使わない値なので実質無操作。
					lower[0] = 0.0;
					upper[k - 1] = 0.0;
				}
				BoundaryCondition::NotAKnot => {
					// BC1: h[1]·M[0] - (h[0]+h[1])·M[1] + h[0]·M[2] = 0
					//      ↔ M[0] = ((h[0]+h[1])·M[1] - h[0]·M[2]) / h[1]
					// これを row 0 (M[1] の内部式) に代入すると:
					//   diag[0] += h[0]·(h[0]+h[1])/h[1]  →  (h[0]+h[1])·(h[0]+2h[1])/h[1]
					//   upper[0] -= h[0]²/h[1]            →  (h[1]² - h[0]²)/h[1]
					//   lower[0] は消える (M[0] を吸収)
					//   rhs[0] は変わらず
					let h0 = h[0];
					let h1 = h[1];
					diag[0] = (h0 + h1) * (h0 + 2.0 * h1) / h1;
					upper[0] = (h1 * h1 - h0 * h0) / h1;
					lower[0] = 0.0;

					// BC2 (末尾側、対称):
					//   M[n-1] = ((h[n-3]+h[n-2])·M[n-2] - h[n-2]·M[n-3]) / h[n-3]
					// これを row k-1 (M[n-2] の内部式) に代入:
					//   lower[k-1] -= h[n-2]²/h[n-3]     →  (h[n-3]² - h[n-2]²)/h[n-3]
					//   diag[k-1]  += h[n-2]·(h[n-3]+h[n-2])/h[n-3]
					//                                   →  (h[n-3]+h[n-2])·(h[n-2]+2h[n-3])/h[n-3]
					//   upper[k-1] は消える (M[n-1] を吸収)
					let ha = h[n - 3];
					let hb = h[n - 2];
					lower[k - 1] = (ha * ha - hb * hb) / ha;
					diag[k - 1] = (ha + hb) * (hb + 2.0 * ha) / ha;
					upper[k - 1] = 0.0;
				}
			}

			// Thomas 前進消去
			for r in 1..k {
				let w = lower[r] / diag[r - 1];
				diag[r] -= w * upper[r - 1];
				rhs[r] -= w * rhs[r - 1];
			}

			// Thomas 後退代入
			let mut m_inner = vec![0.0; k];
			m_inner[k - 1] = rhs[k - 1] / diag[k - 1];
			for r in (0..k - 1).rev() {
				m_inner[r] = (rhs[r] - upper[r] * m_inner[r + 1]) / diag[r];
			}

			// 内部 M を全体配列に反映 (M[1..n-1] = m_inner)
			for r in 0..k {
				m[r + 1] = m_inner[r];
			}

			// 境界の M[0] と M[n-1] を復元 (Natural は 0 のまま、NotAKnot は BC から逆算)
			if effective_bc == BoundaryCondition::NotAKnot {
				m[0] = ((h[0] + h[1]) * m[1] - h[0] * m[2]) / h[1];
				m[n - 1] =
					((h[n - 3] + h[n - 2]) * m[n - 2] - h[n - 2] * m[n - 3]) / h[n - 3];
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

		CubicSpline {
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

	/// phi=0 と phi=2π で (R, Z) および全偏導関数が厳密一致することを確認する。
	///
	/// - 値の一致 → **C⁰ 連続** (seam で飛びがない)
	/// - ∂R/∂θ, ∂Z/∂θ, ∂R/∂φ, ∂Z/∂φ の一致 → **C¹ 微分可能**
	///   (φ 方向の tangent vector 連続性 + θ 方向の tangent が seam 両側で一致)
	///
	/// 前提: xm, xn が整数 (そうでないと cos/sin 位相が 2π で一致しない)。
	/// この 2 条件が満たされていれば B-spline 側が seam を乱す場合の原因は
	/// 入力データではなく cadrum / OCCT の surface construction or subtract 側にある。
	#[test]
	fn interpolate_rz_periodic_and_differentiable_at_phi_seam() {
		let path = Path::new("parastell/examples/wout_vmec.nc");
		if !path.exists() {
			eprintln!("skip: {} not found", path.display());
			return;
		}
		let vmec = VmecData::load(path).expect("load vmec");

		// --- 前提: xm, xn が整数であること ---
		let xn_nonint = vmec
			.mode_toroidal
			.iter()
			.enumerate()
			.find(|&(_, &n)| (n - n.round()).abs() > 1e-10);
		let xm_nonint = vmec
			.mode_poloidal
			.iter()
			.enumerate()
			.find(|&(_, &m)| (m - m.round()).abs() > 1e-10);
		assert!(xn_nonint.is_none(), "xn non-integer at {:?}", xn_nonint);
		assert!(xm_nonint.is_none(), "xm non-integer at {:?}", xm_nonint);

		// --- 値と全偏導関数を (s, θ) の広い範囲で phi=0 vs phi=TAU で比較 ---
		let tol = 1e-9;
		let mut max_diff_r = 0.0f64;
		let mut max_diff_z = 0.0f64;
		let mut max_diff_dr_dtheta = 0.0f64;
		let mut max_diff_dz_dtheta = 0.0f64;
		let mut max_diff_dr_dphi = 0.0f64;
		let mut max_diff_dz_dphi = 0.0f64;
		for &s in &[0.25, 0.5, 1.0, 1.08] {
			// θ は 64 点で sweep (mesh と同じ粒度)
			for j in 0..64 {
				let theta = std::f64::consts::TAU * (j as f64) / 64.0;
				let a = vmec.interpolate_rz(s, theta, 0.0);
				let b = vmec.interpolate_rz(s, theta, std::f64::consts::TAU);
				let d_r = (a.r - b.r).abs();
				let d_z = (a.z - b.z).abs();
				let d_dr_dt = (a.dr_dtheta - b.dr_dtheta).abs();
				let d_dz_dt = (a.dz_dtheta - b.dz_dtheta).abs();
				let d_dr_dp = (a.dr_dphi - b.dr_dphi).abs();
				let d_dz_dp = (a.dz_dphi - b.dz_dphi).abs();
				assert!(d_r < tol, "s={s} θ={theta}: R mismatch {} vs {}", a.r, b.r);
				assert!(d_z < tol, "s={s} θ={theta}: Z mismatch {} vs {}", a.z, b.z);
				assert!(d_dr_dt < tol, "s={s} θ={theta}: ∂R/∂θ mismatch");
				assert!(d_dz_dt < tol, "s={s} θ={theta}: ∂Z/∂θ mismatch");
				assert!(d_dr_dp < tol, "s={s} θ={theta}: ∂R/∂φ mismatch");
				assert!(d_dz_dp < tol, "s={s} θ={theta}: ∂Z/∂φ mismatch");
				max_diff_r = max_diff_r.max(d_r);
				max_diff_z = max_diff_z.max(d_z);
				max_diff_dr_dtheta = max_diff_dr_dtheta.max(d_dr_dt);
				max_diff_dz_dtheta = max_diff_dz_dtheta.max(d_dz_dt);
				max_diff_dr_dphi = max_diff_dr_dphi.max(d_dr_dp);
				max_diff_dz_dphi = max_diff_dz_dphi.max(d_dz_dp);
			}
		}
		eprintln!(
			"seam @ phi=0 vs phi=TAU (across 4×64 = 256 sample points):\n  \
			 max|ΔR|       = {max_diff_r:.3e}\n  \
			 max|ΔZ|       = {max_diff_z:.3e}\n  \
			 max|Δ∂R/∂θ|   = {max_diff_dr_dtheta:.3e}\n  \
			 max|Δ∂Z/∂θ|   = {max_diff_dz_dtheta:.3e}\n  \
			 max|Δ∂R/∂φ|   = {max_diff_dr_dphi:.3e}\n  \
			 max|Δ∂Z/∂φ|   = {max_diff_dz_dphi:.3e}"
		);
	}

	/// mesh() の最終行 (i = div_phi-1) と、もし i = div_phi で計算した場合に期待される
	/// 複製行 (= row 0) との差が、cadrum の phi-direction internal augment が成立する
	/// だけの精度 (Precision::Confusion() ~ 1e-7) を満たすか確認する。
	#[test]
	fn mesh_phi_seam_matches_row0() {
		let path = Path::new("parastell/examples/wout_vmec.nc");
		if !path.exists() {
			eprintln!("skip: {} not found", path.display());
			return;
		}
		let vmec = VmecData::load(path).expect("load vmec");
		let div_theta = 64;
		let div_phi = 240;
		let s = 1.08;
		for (offset, kind) in [(0.0, NormalKind::Planar), (0.05, NormalKind::Planar), (0.05, NormalKind::Surface)] {
			let grid = vmec.mesh(div_theta, div_phi, s, offset, kind);
			// 行 0 (phi=0)
			let row0 = &grid[0];
			// 手計算で phi=TAU の虚構行を再構築 (mesh と同じロジックを phi=TAU で)
			let phi = std::f64::consts::TAU;
			let (sp, cp) = phi.sin_cos();
			let mut virt: Vec<[f64; 3]> = Vec::with_capacity(div_theta);
			for j in 0..div_theta {
				let theta = std::f64::consts::TAU * (j as f64) / (div_theta as f64);
				let rz = vmec.interpolate_rz(s, theta, phi);
				let mut p = [rz.r, 0.0, rz.z];
				if offset != 0.0 {
					let (a, b) = match kind {
						NormalKind::Planar => (
							[rz.dr_dtheta, 0.0, rz.dz_dtheta],
							[0.0_f64, 1.0, 0.0],
						),
						NormalKind::Surface => (
							[rz.dr_dtheta, 0.0, rz.dz_dtheta],
							[rz.dr_dphi, rz.r, rz.dz_dphi],
						),
					};
					let n = [
						b[1] * a[2] - b[2] * a[1],
						b[2] * a[0] - b[0] * a[2],
						b[0] * a[1] - b[1] * a[0],
					];
					let inv_len = 1.0 / (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]).sqrt();
					p[0] += offset * n[0] * inv_len;
					p[1] += offset * n[1] * inv_len;
					p[2] += offset * n[2] * inv_len;
				}
				virt.push([p[0] * cp - p[1] * sp, p[0] * sp + p[1] * cp, p[2]]);
			}
			// row0 と virt (phi=2π) の差を集計
			let mut max_diff = 0.0f64;
			for j in 0..div_theta {
				let dx = row0[j][0] - virt[j][0];
				let dy = row0[j][1] - virt[j][1];
				let dz = row0[j][2] - virt[j][2];
				max_diff = max_diff.max((dx * dx + dy * dy + dz * dz).sqrt());
			}
			eprintln!(
				"offset={offset:.3} kind={:?}: max |row0 - virt(phi=TAU)| = {max_diff:.3e}",
				kind
			);
			assert!(max_diff < 1e-6, "seam too large");
		}
	}

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
			let rz = vmec.interpolate_rz(s, theta, phi);
			checksum += rz.r + rz.z;
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
				let idx = vmec.index_rz(i, theta, phi);
				let int = vmec.interpolate_rz(s, theta, phi);
				let tol = 1e-9;
				assert!(
					(idx.r - int.r).abs() < tol,
					"R mismatch at i={i}, θ={theta}, φ={phi}: idx={}, int={}",
					idx.r, int.r
				);
				assert!(
					(idx.z - int.z).abs() < tol,
					"Z mismatch at i={i}, θ={theta}, φ={phi}: idx={}, int={}",
					idx.z, int.z
				);
			}
		}
	}

	/// どの境界条件でもスプラインはグリッド点を**正確に通る** (補間性) ことを確認する。
	#[test]
	fn cubic_spline_passes_through_data_points() {
		let xs = [0.0, 0.1, 0.3, 0.6, 1.0, 1.5, 2.1];
		let ys = [0.0, 0.5, -0.2, 0.8, 0.3, -0.1, 1.2];
		for bc in [BoundaryCondition::Natural, BoundaryCondition::NotAKnot] {
			let sp = CubicSpline::new(&xs, &ys, bc);
			for (i, &x) in xs.iter().enumerate() {
				let y = sp.eval(x);
				assert!(
					(y - ys[i]).abs() < 1e-10,
					"bc={bc:?} i={i}: eval({x}) = {y}, expected {}",
					ys[i]
				);
			}
		}
	}

	/// x² (純粋な 2 次関数) は not-a-knot 3 次スプラインで**厳密に再現**される
	/// (3 次係数 d=0、M_i=2 が正解)。計算結果と比較して実装が正しいことを確認する。
	#[test]
	fn not_a_knot_reproduces_quadratic_exactly() {
		let xs: Vec<f64> = (0..5).map(|i| i as f64).collect();
		let ys: Vec<f64> = xs.iter().map(|&x| x * x).collect();
		let sp = CubicSpline::new(&xs, &ys, BoundaryCondition::NotAKnot);
		// 内挿点と外挿点 (x=6) の両方で y = x² を厳密に再現することを確認
		for &x in &[0.5, 1.5, 2.5, 3.5, 4.5, 6.0, -1.0] {
			let y = sp.eval(x);
			let expected = x * x;
			assert!(
				(y - expected).abs() < 1e-9,
				"not-a-knot should reproduce x²: eval({x}) = {y}, expected {expected}"
			);
		}
	}

	/// VMEC の s=1.08 外挿で natural vs not-a-knot の (R, Z) 差をサンプルして目視確認する。
	/// 実装バグの診断用。`cargo test -- --nocapture vmec_s108_natural_vs_not_a_knot`
	#[test]
	fn vmec_s108_natural_vs_not_a_knot() {
		let path = Path::new("parastell/examples/wout_vmec.nc");
		if !path.exists() {
			eprintln!("skip: {} not found", path.display());
			return;
		}
		let vmec = VmecData::load(path).expect("load vmec");
		let mnmax = vmec.mode_poloidal.len();
		let s = 1.08;

		// 手動で natural と not-a-knot それぞれの係数補間をやって、dominant mode (k=0)
		// の rmnc 補間値を比較してみる。
		let r_col: Vec<f64> = vmec.rmnc.iter().map(|row| row[0]).collect();
		let sp_nat = CubicSpline::new(&vmec.s_grid, &r_col, BoundaryCondition::Natural);
		let sp_nak = CubicSpline::new(&vmec.s_grid, &r_col, BoundaryCondition::NotAKnot);
		let v_nat = sp_nat.eval(s);
		let v_nak = sp_nak.eval(s);
		let v_grid_last = r_col[r_col.len() - 1];
		eprintln!(
			"mode 0 (rmnc) at s=1.08: natural={v_nat:.6}, not-a-knot={v_nak:.6}, at s=1.0={v_grid_last:.6}"
		);

		// (θ, φ) = (0, 0) での (R, Z) を 3 通りで比較。
		// (現在の interpolate_rz は not-a-knot を使用)
		let int = vmec.interpolate_rz(s, 0.0, 0.0);
		// 末端グリッド点での値 (s=1.0)
		let grid = vmec.index_rz(vmec.s_grid.len() - 1, 0.0, 0.0);
		eprintln!(
			"(θ=0, φ=0): at s=1.0 (R={:.4}, Z={:.4}), at s=1.08 not-a-knot (R={:.4}, Z={:.4})",
			grid.r, grid.z, int.r, int.z
		);

		// mode 0..5 の (s=1.0, s=1.08-natural, s=1.08-notaknot) を対照表示
		for k in 0..5.min(mnmax) {
			let col: Vec<f64> = vmec.rmnc.iter().map(|row| row[k]).collect();
			let a = CubicSpline::new(&vmec.s_grid, &col, BoundaryCondition::Natural);
			let b = CubicSpline::new(&vmec.s_grid, &col, BoundaryCondition::NotAKnot);
			eprintln!(
				"k={k} (m={}, n={}): rmnc at s=1.0={:.4}, s=1.08 natural={:.4}, not-a-knot={:.4}",
				vmec.mode_poloidal[k],
				vmec.mode_toroidal[k],
				col[col.len() - 1],
				a.eval(s),
				b.eval(s),
			);
		}
	}

	/// VMEC を s=1.08 で natural と not-a-knot それぞれ使って、(θ, φ) 全面を走査して
	/// R, Z の最大ズレを測る。実装が妥当なら差は数 cm 以内のはず (parastell と合わない
	/// 原因を切り分けるための診断)。
	#[test]
	fn vmec_s108_surface_drift() {
		let path = Path::new("parastell/examples/wout_vmec.nc");
		if !path.exists() {
			eprintln!("skip: {} not found", path.display());
			return;
		}
		let vmec = VmecData::load(path).expect("load vmec");
		let mnmax = vmec.mode_poloidal.len();

		// 各モードの rmnc, zmns について natural / not-a-knot 2 通りのスプラインを
		// 事前構築する (interpolate_rz は not-a-knot 固定なので、ここでは自前で計算する)。
		let mut r_nat = Vec::with_capacity(mnmax);
		let mut r_nak = Vec::with_capacity(mnmax);
		let mut z_nat = Vec::with_capacity(mnmax);
		let mut z_nak = Vec::with_capacity(mnmax);
		for k in 0..mnmax {
			let rc: Vec<f64> = vmec.rmnc.iter().map(|row| row[k]).collect();
			let zc: Vec<f64> = vmec.zmns.iter().map(|row| row[k]).collect();
			r_nat.push(CubicSpline::new(&vmec.s_grid, &rc, BoundaryCondition::Natural));
			r_nak.push(CubicSpline::new(&vmec.s_grid, &rc, BoundaryCondition::NotAKnot));
			z_nat.push(CubicSpline::new(&vmec.s_grid, &zc, BoundaryCondition::Natural));
			z_nak.push(CubicSpline::new(&vmec.s_grid, &zc, BoundaryCondition::NotAKnot));
		}
		let s = 1.08;
		let r_coef_nat: Vec<f64> = r_nat.iter().map(|sp| sp.eval(s)).collect();
		let r_coef_nak: Vec<f64> = r_nak.iter().map(|sp| sp.eval(s)).collect();
		let z_coef_nat: Vec<f64> = z_nat.iter().map(|sp| sp.eval(s)).collect();
		let z_coef_nak: Vec<f64> = z_nak.iter().map(|sp| sp.eval(s)).collect();

		let mut max_dr = 0.0f64;
		let mut max_dz = 0.0f64;
		let mut sum_sq_dr = 0.0f64;
		let mut sum_sq_dz = 0.0f64;
		let n_theta = 64;
		let n_phi = 60;
		for i in 0..n_phi {
			let phi = std::f64::consts::TAU * (i as f64) / (n_phi as f64);
			for j in 0..n_theta {
				let theta = std::f64::consts::TAU * (j as f64) / (n_theta as f64);
				let n = vmec.eval_rz(&r_coef_nat, &z_coef_nat, theta, phi);
				let k = vmec.eval_rz(&r_coef_nak, &z_coef_nak, theta, phi);
				let dr = (n.r - k.r).abs();
				let dz = (n.z - k.z).abs();
				max_dr = max_dr.max(dr);
				max_dz = max_dz.max(dz);
				sum_sq_dr += dr * dr;
				sum_sq_dz += dz * dz;
			}
		}
		let n_pts = (n_phi * n_theta) as f64;
		eprintln!(
			"s=1.08 surface drift: max(|ΔR|)={max_dr:.4}, max(|ΔZ|)={max_dz:.4}, \
			 rms(ΔR)={:.4}, rms(ΔZ)={:.4}",
			(sum_sq_dr / n_pts).sqrt(),
			(sum_sq_dz / n_pts).sqrt(),
		);
	}

	/// Natural と NotAKnot で、データ範囲内ではほぼ一致し、範囲外 (外挿) で差が出る
	/// ことを確認する。parastell との差異の起源 (境界条件) を再現する。
	#[test]
	fn natural_vs_not_a_knot_extrapolation_differs() {
		// VMEC の s_grid に似せた 201 点等間隔で、非自明な関数 y = sin(3πx) + 0.2 x³ を
		// サンプルする。scipy の CubicSpline と同様に、内挿領域ではどちらも真値に近く、
		// 外挿領域で差が出る。
		let n = 201;
		let xs: Vec<f64> = (0..n).map(|i| i as f64 / (n - 1) as f64).collect();
		let ys: Vec<f64> =
			xs.iter().map(|x| (3.0 * std::f64::consts::PI * x).sin() + 0.2 * x.powi(3)).collect();
		let natural = CubicSpline::new(&xs, &ys, BoundaryCondition::Natural);
		let not_a_knot = CubicSpline::new(&xs, &ys, BoundaryCondition::NotAKnot);

		// 内挿領域 (x=0.5) ではほぼ一致
		let y_nat_mid = natural.eval(0.5);
		let y_nak_mid = not_a_knot.eval(0.5);
		assert!(
			(y_nat_mid - y_nak_mid).abs() < 1e-6,
			"natural ({y_nat_mid}) と not-a-knot ({y_nak_mid}) が内挿で大きく違う"
		);

		// 外挿領域 (x=1.08) では差が出るはず。差が「ゼロじゃない」ことを確認。
		let y_nat_ext = natural.eval(1.08);
		let y_nak_ext = not_a_knot.eval(1.08);
		let diff = (y_nat_ext - y_nak_ext).abs();
		assert!(
			diff > 1e-3,
			"外挿で差が出ていない: natural={y_nat_ext}, not-a-knot={y_nak_ext}, diff={diff}"
		);
		eprintln!(
			"x=1.08 extrapolation: natural={y_nat_ext:.6}, not-a-knot={y_nak_ext:.6}, diff={diff:.6}"
		);
	}
}
