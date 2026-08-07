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
pub struct CubicSpline {
	/// x 軸上のサンプル点 (昇順)
	xs: Vec<f64>,
	/// 各区間の 3 次多項式係数 (y = a + b·dx + c·dx² + d·dx³)
	a: Vec<f64>,
	b: Vec<f64>,
	c: Vec<f64>,
	d: Vec<f64>,
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

impl CubicSpline {
	/// (xs, ys) のデータと境界条件からスプラインを構築する。
	///
	/// 手順:
	/// 1. 各区間の幅 h[i] を計算
	/// 2. 2 階微分 M[i] を解く三重対角連立方程式を立てる (境界条件で第 1・最終行が変化)
	/// 3. Thomas algorithm で前進消去 → 後退代入
	/// 4. NotAKnot の場合は M[0] と M[n-1] を境界条件式から復元
	/// 5. 解いた M[i] と h[i], y[i] から各区間の 3 次多項式係数 a, b, c, d を作る
	pub fn new(xs: &[f64], ys: &[f64], bc: BoundaryCondition) -> Self {
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
	pub fn eval(&self, x: f64) -> f64 {
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
#[cfg(test)]
mod tests {
	use super::*;
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
}