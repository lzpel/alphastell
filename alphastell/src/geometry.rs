use cadrum;
use pyo3::prelude::*;

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

#[pyclass(unsendable)]
#[repr(transparent)]
struct Geometry(cadrum::Solid);

#[pymethods]
impl Geometry {
	#[staticmethod]
	fn loft_geometry(points: Vec<f64>) -> Result<Geometry, crate::geometry::Error> {
		let (u, v, point) = points_to_dvec3(points);
		let sections: std::result::Result<Vec<Vec<cadrum::Edge>>, cadrum::Error> = (0..u).map(|i| cadrum::Edge::polygon((0..v).map(|j| &point[i * v + j]))).collect();
		Ok(cadrum::Solid::loft(&sections?, true)?)
	}
	#[staticmethod]
	fn bspline_geometry(points: Vec<f64>) -> Result<Geometry, crate::geometry::Error> {
		let (u, v, point) = points_to_dvec3(points);
		Ok(cadrum::Solid::bspline(u, v, true, |i,j| point[i*v+j])?)
	}
	/// SurfaceRZFourier::load が file-like から read() するのと対称に、file-like へ write() する。
	fn write_step(&self, file: &Bound<'_, PyAny>) -> PyResult<()> {
		let mut data = Vec::new();
		cadrum::Solid::write_step([&self.0], &mut data).map_err(crate::geometry::Error)?;
		file.call_method1("write", (pyo3::types::PyBytes::new(file.py(), &data),))?;
		Ok(())
	}
	/// 4 面図の PNG。write_step と同じく file-like へ write() する。
	fn write_png(&self, file: &Bound<'_, PyAny>) -> PyResult<()> {
		let mut data = Vec::new();
		self.0.write_multiview_png(&mut data).map_err(crate::geometry::Error)?;
		file.call_method1("write", (pyo3::types::PyBytes::new(file.py(), &data),))?;
		Ok(())
	}
}

pub fn module(m: &Bound<'_, PyModule>) -> PyResult<()>{
	m.add_class::<Geometry>()?;
}