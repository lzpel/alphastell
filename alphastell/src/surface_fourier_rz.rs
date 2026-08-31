use crate::vmec;
use pyo3::prelude::*;

#[pyclass]
#[repr(transparent)]
pub struct SurfaceFourierRZ(vmec::SurfaceFourierRZ);

#[pymethods]
impl SurfaceFourierRZ {
	#[staticmethod]
	fn load(file: &Bound<'_, PyAny>) -> PyResult<Self> {
		// PyBackedBytes は python の bytes を掴んだまま &[u8] を貸す型 (Vec への再コピーが無い)。
		// Cursor<T> は T: AsRef<[u8]> で Read + Seek を満たし、所有型なので 'static も通る。
		let data: pyo3::pybacked::PyBackedBytes = file.call_method0("read")?.extract()?;
		vmec::SurfaceFourierRZ::load(std::io::Cursor::new(data))
			.map(Self)
			.map_err(pyo3::exceptions::PyValueError::new_err)
	}
	fn point_normal(&self, phi: f64, theta: f64, s: f64, use_surface: bool) -> [[f64; 3]; 2] {
		self.0.interpolate(phi, theta, s, match use_surface {
			true => vmec::NormalKind::Surface,
			false => vmec::NormalKind::Planar,
		})
	}
	/// (x, y, z) を磁束座標 [phi, theta, s] に逆算する。収束しなければ ValueError。
	fn inverse(&self, point: [f64; 3]) -> PyResult<[f64; 3]> {
		self.0.inverse(point).map_err(pyo3::exceptions::PyValueError::new_err)
	}
}

pub fn module(m: &Bound<'_, PyModule>) -> PyResult<()> {
	m.add_class::<SurfaceFourierRZ>()?;
	Ok(())
}
