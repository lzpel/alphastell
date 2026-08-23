use cadrum::{self, DVec3};
use pyo3::prelude::*;

#[derive(Debug)]
pub struct Error(pub cadrum::Error);

impl From<cadrum::Error> for Error {
	fn from(e: cadrum::Error) -> Self {
		Error(e)
	}
}

impl std::fmt::Display for Error {
	fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
		write!(f, "{}", self.0)
	}
}

impl std::error::Error for Error {}

impl From<Error> for PyErr {
	fn from(e: Error) -> PyErr {
		pyo3::exceptions::PyValueError::new_err(e.to_string())
	}
}

#[pyclass(unsendable)]
#[repr(transparent)]
pub struct Geometry(Vec<cadrum::Solid>);

impl Geometry {
	fn expression(&self) -> cadrum::Boolean<cadrum::Solid> {
		self.0.iter().fold(cadrum::Boolean::default(), |a, s| a + s)
	}
	fn write_bytes(file: &Bound<'_, PyAny>, data: &[u8]) -> PyResult<()> {
		file.call_method1("write", (pyo3::types::PyBytes::new(file.py(), data),))?;
		Ok(())
	}
	/// 入力の形が不正なときの Error。cadrum の InvalidEdge に載せると PyValueError になる。
	fn invalid(message: String) -> Error {
		Error(cadrum::Error::InvalidEdge(message))
	}
	fn points_to_dvec3(points: Vec<f64>) -> (usize, usize, Vec<cadrum::DVec3>) {
		// 最初の2要素は n, m のサイズ 残りは n*m*3のフラットな座標配列
		let n = points[0] as usize;
		let m = points[1] as usize;
		let dvec3_points: Vec<cadrum::DVec3> = points[2..]
			.chunks(3)
			.map(|chunk| cadrum::DVec3::new(chunk[0], chunk[1], chunk[2]))
			.collect();
		(n, m, dvec3_points)
	}
}

#[pymethods]
impl Geometry {
	#[staticmethod]
	fn loft_geometry(points: Vec<f64>) -> Result<Geometry, Error> {
		let (u, v, point) = Self::points_to_dvec3(points);
		let sections: std::result::Result<Vec<Vec<cadrum::Edge>>, cadrum::Error> = (0..u).map(|i| cadrum::Edge::polygon((0..v).map(|j| &point[i * v + j]))).collect();
		Ok(Geometry(vec![cadrum::Solid::loft(&sections?, true)?]))
	}
	#[staticmethod]
	fn bspline_geometry(points: Vec<f64>) -> Result<Geometry, Error> {
		let (u, v, point) = Self::points_to_dvec3(points);
		Ok(Geometry(vec![cadrum::Solid::bspline(u, v, true, |i,j| point[i*v+j])?]))
	}
	/// 断面を経路に沿って掃引する。profile は原点まわりの平面断面 [x0, y0, x1, y1, ...]、
	/// paths は [x, y, z, aux_x, aux_y, aux_z, ...] の 6N 要素で、aux はガイド曲線の制御点そのもの。
	/// 断面のローカル +X が経路点から対応するガイド点の向きを追う。
	/// 全要素 0 の 6 要素を挟むと、そこで経路が切れて別のソリッドになる。
	/// periodic なら経路とガイドを周期スプラインとして閉じるので、始点を末尾で繰り返さない。
	/// ガイドは経路の接線と平行にならない向き (コイルなら巻線面の法線側) に置く。
	#[staticmethod]
	#[pyo3(signature = (periodic, profile, *paths))]
	fn sweep_geometry(periodic: bool, profile: Vec<f64>, paths: Vec<f64>) -> Result<Geometry, Error> {
		if profile.len() < 6 || profile.len() % 2 != 0 {
			return Err(Self::invalid(format!("profile needs >=3 xy points as an even count, got {}", profile.len())));
		}
		if paths.len() % 6 != 0 {
			return Err(Self::invalid(format!("paths needs 6 values per point, got {}", paths.len())));
		}
		// 断面は XY 平面に置く。align_z が局所 +Z を接線へ向けるので、この向きなら経路と直交する
		let section: Vec<DVec3> = profile.chunks_exact(2).map(|c| DVec3::new(c[0], c[1], 0.0)).collect();
		let path: Vec<[DVec3; 2]> = paths.chunks_exact(6).map(|v| [DVec3::from_slice(v), DVec3::from_slice(&v[3..])]).collect();
		let sweeper = |single: &[[DVec3; 2]]| -> Result<cadrum::Solid, Error> {
			if single.len() < 3 {
				return Err(Self::invalid(format!("path needs >=3 points, got {}", single.len())));
			}
			let end = match periodic {
				true => cadrum::BSplineEnd::Periodic,
				false => cadrum::BSplineEnd::NotAKnot,
			};
			let spine = cadrum::Edge::bspline(single.iter().map(|v| &v[0]), end)?;
			let guide = cadrum::Edge::bspline(single.iter().map(|v| &v[1]), end)?;
			// 断面は経路の始点へ、その接線を法線として置く。sweep は断面を動かさずそのまま掃く
			let wire: Vec<cadrum::Edge> = cadrum::Edge::polygon(&section)?.into_iter().map(|e| e.align_z(spine.start_tangent(), single[0][1] - single[0][0]).translate(single[0][0])).collect();
			cadrum::Solid::sweep(&wire, &[spine], cadrum::ProfileOrient::Auxiliary(&[guide])).map_err(Error)
		};
		path.split(|v| v[0].length() + v[1].length() < 1e-9)
			.filter(|single| !single.is_empty())
			.map(sweeper)
			.collect::<Result<Vec<cadrum::Solid>, Error>>()
			.map(Geometry)
	}
	fn boolean_union(&self, other: &Geometry) -> Result<Geometry, Error> {
		Ok(Geometry((self.expression() + other.expression()).build_vec()?))
	}
	fn boolean_subtract(&self, other: &Geometry) -> Result<Geometry, Error> {
		Ok(Geometry((self.expression() - other.expression()).build_vec()?))
	}
	fn boolean_intersect(&self, other: &Geometry) -> Result<Geometry, Error> {
		Ok(Geometry((self.expression() * other.expression()).build_vec()?))
	}
	fn __len__(&self) -> usize {
		self.0.len()
	}
	/// ソリッドごとの体積。掃引や押し出しの結果を解析値と突き合わせる用。
	fn volume(&self) -> Vec<f64> {
		self.0.iter().map(|s| s.volume().abs()).collect()
	}
	/// SurfaceFourierRZ::load が file-like から read() するのと対称に、file-like へ write() する。
	fn write_step(&self, file: &Bound<'_, PyAny>) -> PyResult<()> {
		let mut data = Vec::new();
		cadrum::Solid::write_step(&self.0, &mut data).map_err(Error)?;
		Self::write_bytes(file, &data)
	}
	/// 4 面図の PNG。write_step と同じく file-like へ write() する。
	fn write_png(&self, file: &Bound<'_, PyAny>) -> PyResult<()> {
		let mut data = Vec::new();
		cadrum::Solid::mesh(&self.0, Default::default()).map_err(Error)?.write_multiview_png(&mut data).map_err(Error)?;
		Self::write_bytes(file, &data)
	}
}

pub fn module(m: &Bound<'_, PyModule>) -> PyResult<()> {
	m.add_class::<Geometry>()?;
	Ok(())
}
