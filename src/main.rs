use anyhow::{Context, Result};
use cadrum::{DVec3, Solid};
use clap::Parser;
use std::f64::consts::TAU;
use std::path::PathBuf;

const M_TORO: usize = 240;
const N_POLO: usize = 64;

#[derive(Parser, Debug)]
#[command(about = "VMEC wout_*.nc から任意 s の磁束面を全周 B-spline STEP に出力")]
struct Args {
	#[arg(long)]
	input: PathBuf,
	#[arg(long)]
	output: PathBuf,
	#[arg(long, default_value_t = 1.0)]
	s: f64,
}

struct VmecData {
	s_grid: Vec<f64>,
	rmnc: Vec<Vec<f64>>, // rmnc[ns][mnmax]
	zmns: Vec<Vec<f64>>,
	xm: Vec<f64>,
	xn: Vec<f64>,
}

fn load_vmec(path: &std::path::Path) -> Result<VmecData> {
	let file = netcdf::open(path).with_context(|| format!("open {}", path.display()))?;
	let rmnc_var = file.variable("rmnc").context("missing rmnc")?;
	let zmns_var = file.variable("zmns").context("missing zmns")?;
	let xm_var = file.variable("xm").context("missing xm")?;
	let xn_var = file.variable("xn").context("missing xn")?;

	let shape = rmnc_var.dimensions().iter().map(|d| d.len()).collect::<Vec<_>>();
	let ns = shape[0];
	let mnmax = shape[1];

	let rmnc_flat = rmnc_var.get_values::<f64, _>(..)?;
	let zmns_flat = zmns_var.get_values::<f64, _>(..)?;
	let xm = xm_var.get_values::<f64, _>(..)?;
	let xn = xn_var.get_values::<f64, _>(..)?;

	let rmnc: Vec<Vec<f64>> = (0..ns)
		.map(|i| rmnc_flat[i * mnmax..(i + 1) * mnmax].to_vec())
		.collect();
	let zmns: Vec<Vec<f64>> = (0..ns)
		.map(|i| zmns_flat[i * mnmax..(i + 1) * mnmax].to_vec())
		.collect();

	// VMEC の s グリッドは一様 s = i / (ns - 1)
	let s_grid: Vec<f64> = (0..ns).map(|i| i as f64 / (ns - 1) as f64).collect();

	Ok(VmecData { s_grid, rmnc, zmns, xm, xn })
}

/// Natural cubic spline の区間ごと 3 次多項式係数 [a, b, c, d]
/// y(x) = a + b*(x-xi) + c*(x-xi)^2 + d*(x-xi)^3 over [xi, xi+1]
struct NaturalSpline {
	xs: Vec<f64>,
	a: Vec<f64>,
	b: Vec<f64>,
	c: Vec<f64>,
	d: Vec<f64>,
}

impl NaturalSpline {
	fn new(xs: &[f64], ys: &[f64]) -> Self {
		let n = xs.len();
		assert_eq!(ys.len(), n);
		assert!(n >= 2);
		let h: Vec<f64> = (0..n - 1).map(|i| xs[i + 1] - xs[i]).collect();

		// 2 次微分 M_i を求める (M_0 = M_{n-1} = 0)
		let mut m = vec![0.0; n];
		if n >= 3 {
			// Thomas algorithm: 内部 n-2 本の方程式
			let mut diag = vec![0.0; n - 2];
			let mut upper = vec![0.0; n - 2];
			let mut rhs = vec![0.0; n - 2];
			for i in 0..n - 2 {
				diag[i] = 2.0 * (h[i] + h[i + 1]);
				if i < n - 3 {
					upper[i] = h[i + 1];
				}
				rhs[i] = 6.0 * ((ys[i + 2] - ys[i + 1]) / h[i + 1] - (ys[i + 1] - ys[i]) / h[i]);
			}
			// forward sweep
			for i in 1..n - 2 {
				let w = h[i] / diag[i - 1];
				diag[i] -= w * upper[i - 1];
				rhs[i] -= w * rhs[i - 1];
			}
			// back substitution
			let mut m_inner = vec![0.0; n - 2];
			m_inner[n - 3] = rhs[n - 3] / diag[n - 3];
			for i in (0..n - 3).rev() {
				m_inner[i] = (rhs[i] - upper[i] * m_inner[i + 1]) / diag[i];
			}
			for i in 0..n - 2 {
				m[i + 1] = m_inner[i];
			}
		}

		// 各区間の 3 次多項式係数
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

		NaturalSpline { xs: xs.to_vec(), a, b, c, d }
	}

	fn eval(&self, x: f64) -> f64 {
		// 区間特定 (二分探索)。範囲外は端の多項式で外挿。
		let n = self.xs.len();
		let idx = if x <= self.xs[0] {
			0
		} else if x >= self.xs[n - 1] {
			n - 2
		} else {
			match self
				.xs
				.binary_search_by(|v| v.partial_cmp(&x).unwrap())
			{
				Ok(i) => i.min(n - 2),
				Err(i) => i - 1,
			}
		};
		let dx = x - self.xs[idx];
		self.a[idx] + self.b[idx] * dx + self.c[idx] * dx.powi(2) + self.d[idx] * dx.powi(3)
	}
}

/// 全 mnmax mode について s で内挿して (rmnc_at_s, zmns_at_s) を返す
fn interp_coeffs_at_s(vmec: &VmecData, s: f64) -> (Vec<f64>, Vec<f64>) {
	let mnmax = vmec.xm.len();
	let mut r_at_s = Vec::with_capacity(mnmax);
	let mut z_at_s = Vec::with_capacity(mnmax);
	for k in 0..mnmax {
		let r_col: Vec<f64> = vmec.rmnc.iter().map(|row| row[k]).collect();
		let z_col: Vec<f64> = vmec.zmns.iter().map(|row| row[k]).collect();
		let sr = NaturalSpline::new(&vmec.s_grid, &r_col);
		let sz = NaturalSpline::new(&vmec.s_grid, &z_col);
		r_at_s.push(sr.eval(s));
		z_at_s.push(sz.eval(s));
	}
	(r_at_s, z_at_s)
}

fn eval_rz(r_coeff: &[f64], z_coeff: &[f64], xm: &[f64], xn: &[f64], theta: f64, phi: f64) -> (f64, f64) {
	let mut r = 0.0;
	let mut z = 0.0;
	for k in 0..xm.len() {
		let angle = xm[k] * theta - xn[k] * phi;
		r += r_coeff[k] * angle.cos();
		z += z_coeff[k] * angle.sin();
	}
	(r, z)
}

fn main() -> Result<()> {
	let args = Args::parse();
	println!("Loading VMEC: {}", args.input.display());
	let vmec = load_vmec(&args.input)?;
	println!(
		"  ns = {}, mnmax = {}, s_max in grid = {}",
		vmec.s_grid.len(),
		vmec.xm.len(),
		vmec.s_grid.last().unwrap()
	);
	println!("Interpolating Fourier coefficients at s = {}", args.s);
	let (r_at_s, z_at_s) = interp_coeffs_at_s(&vmec, args.s);

	println!("Building {} x {} grid over full torus...", M_TORO, N_POLO);
	let grid: [[DVec3; N_POLO]; M_TORO] = std::array::from_fn(|i| {
		let phi = TAU * (i as f64) / (M_TORO as f64);
		let (sinp, cosp) = phi.sin_cos();
		std::array::from_fn(|j| {
			let theta = TAU * (j as f64) / (N_POLO as f64);
			let (r, z) = eval_rz(&r_at_s, &z_at_s, &vmec.xm, &vmec.xn, theta, phi);
			// parastell は m 単位で入出力。VMEC の rmnc/zmns 単位のまま cadrum に渡す。
			DVec3::new(r * cosp, r * sinp, z)
		})
	});

	println!("Constructing B-spline solid via cadrum...");
	let solid = Solid::bspline(grid, true)
		.map_err(|e| anyhow::anyhow!("cadrum bspline failed: {:?}", e))?;

	if let Some(parent) = args.output.parent() {
		if !parent.as_os_str().is_empty() {
			std::fs::create_dir_all(parent)
				.with_context(|| format!("create_dir_all {}", parent.display()))?;
		}
	}
	println!("Writing STEP: {}", args.output.display());
	let mut f = std::fs::File::create(&args.output)
		.with_context(|| format!("create {}", args.output.display()))?;
	cadrum::write_step(&[solid.color("cyan")], &mut f)
		.map_err(|e| anyhow::anyhow!("write_step failed: {:?}", e))?;

	println!("Done.");
	Ok(())
}
