use cadrum;
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
	/// 入力の形が不正なときの Error。cadrum の Validation に載せると PyValueError になる。
	fn invalid(message: String) -> Error {
		Error(cadrum::Error::Validation(message))
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
	/// 各 path は [x, y, z, ax, ay, az, ...] の 6N 要素。
	#[staticmethod]
	fn sweep_geometry(periodic: bool, profile: Vec<f64>, paths: Vec<Vec<f64>>) -> Result<Geometry, Error> {
		if profile.len() < 2*3 || profile.len() % 2 != 0 {
			return Err(Self::invalid(format!("profile needs >=3 xy points as an even count, got {}", profile.len())));
		}
		// 断面は XY 平面に置く。align_z が局所 +Z を接線へ向けるので、この向きなら経路と直交する
		let section: Vec<cadrum::DVec3> = profile.chunks_exact(2).map(|c| cadrum::DVec3::new(c[0], c[1], 0.0)).collect();
		// sectionsと対になるpathの点群、最初の1点は上方向ベクトルで点群ではないことに注意
		let paths: Vec<[Vec<cadrum::DVec3>; 2]>=paths
			.iter()
			.map(|path| -> Result<_, Error> {
				if path.len() < 6*3 || path.len() % 6 != 0 {
					return Err(Self::invalid(format!("path needs up + >=3 xyz points as 3+3N values, got {}", path.len())));
				}
				let point_iter=path.chunks_exact(3).map(|c| cadrum::DVec3::new(c[0], c[1], c[2]));
				Ok([
					point_iter.clone().step_by(2).collect(), 
					point_iter.clone().skip(1).step_by(2).collect()
				])
			}).collect::<Result<_, Error>>()?;
		paths
			.iter()
			.map(|path| -> Result<cadrum::Solid, Error> {
				let spine_points = &path[0];
				let guide_points = &path[1];
				let up = guide_points[0]-spine_points[0];
				let bspline_end=if periodic { cadrum::BSplineEnd::Periodic } else { cadrum::BSplineEnd::NotAKnot };
				let spine_bspline = cadrum::Edge::bspline(spine_points, bspline_end).map_err(Error)?;
				let guide_bspline = cadrum::Edge::bspline(guide_points, bspline_end).map_err(Error)?;
				let edges: Vec<cadrum::Edge> = cadrum::Edge::polygon(&section).map_err(Error)?.into_iter().map(|e| e.align_z(spine_bspline.start_tangent(), up).translate(spine_bspline.start_point())).collect();
				cadrum::Solid::sweep(&edges, &[spine_bspline], cadrum::ProfileOrient::Auxiliary(&[guide_bspline])).map_err(Error)
			})
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
