pub mod vmec;
pub mod spline;
pub mod geometry;
use pyo3::prelude::*;


#[pyclass]
#[repr(transparent)]
struct SurfaceRZFourier(crate::vmec::SurfaceRZFourier);

#[pymethods]
impl SurfaceRZFourier {
	#[staticmethod]
	fn load(file: &Bound<'_, PyAny>) -> PyResult<Self> {
		// PyBackedBytes は python の bytes を掴んだまま &[u8] を貸す型 (Vec への再コピーが無い)。
		// Cursor<T> は T: AsRef<[u8]> で Read + Seek を満たし、所有型なので 'static も通る。
		let data: pyo3::pybacked::PyBackedBytes = file.call_method0("read")?.extract()?;
		crate::vmec::SurfaceRZFourier::load(std::io::Cursor::new(data))
			.map(Self)
			.map_err(pyo3::exceptions::PyValueError::new_err)
	}
	fn point_normal(&self, phi: f64, theta: f64, s: f64, use_surface: bool) -> [[f64; 3]; 2] {
		self.0.interpolate(phi, theta, s, match use_surface {
			true => crate::vmec::NormalKind::Surface,
			false => crate::vmec::NormalKind::Planar,
		})
	}
}

#[pymodule]
fn alphastell(m: &Bound<'_, PyModule>) -> PyResult<()> {
	hello::module(&mut m)?;
	geometry::module(&mut m)?:
	m.add_class::<SurfaceRZFourier>()?;
	Ok(())
}