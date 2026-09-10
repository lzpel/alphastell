use core::panic;

use crate::vmec;
use pyo3::prelude::*;

#[pyclass]
#[repr(transparent)]
pub struct SurfaceFourierRZ(vmec::SurfaceFourierRZ);

#[pymethods]
impl SurfaceFourierRZ {
	/// constant-φ 断面内の 2D 法線 (parastell 互換)。φ 方向の形状変化を無視する
	#[classattr]
	const NORMAL_PLANAR: u8 = 2;
	/// 真の 3D 曲面法線 ∂p/∂φ × ∂p/∂θ
	#[classattr]
	const NORMAL_SURFACE: u8 = 3;
	#[staticmethod]
	fn load(file: &Bound<'_, PyAny>) -> PyResult<Self> {
		// PyBackedBytes は python の bytes を掴んだまま &[u8] を貸す型 (Vec への再コピーが無い)。
		// Cursor<T> は T: AsRef<[u8]> で Read + Seek を満たし、所有型なので 'static も通る。
		let data: pyo3::pybacked::PyBackedBytes = file.call_method0("read")?.extract()?;
		vmec::SurfaceFourierRZ::load(std::io::Cursor::new(data))
			.map(Self)
			.map_err(pyo3::exceptions::PyValueError::new_err)
	}
	fn point_normal(&self, phi: f64, theta: f64, s: f64, normal: u8) -> [[f64; 3]; 2] {
		self.0.interpolate(phi, theta, s, match normal {
			Self::NORMAL_SURFACE => vmec::NormalKind::Surface,
			Self::NORMAL_PLANAR => vmec::NormalKind::Planar,
			_ => panic!("invalid normal")
		})
	}
	/// 点 p に最も近い磁束面 s 上の点の [phi, theta]。初期値の盆地に収束する。
	fn nearest(&self, phi_initial: f64, theta_initial: f64, s: f64, p: [f64; 3]) -> PyResult<[f64; 2]> {
		self.0.nearest(phi_initial, theta_initial, s, p).map_err(pyo3::exceptions::PyValueError::new_err)
	}
}

pub fn module(m: &Bound<'_, PyModule>) -> PyResult<()> {
	m.add_class::<SurfaceFourierRZ>()?;
	Ok(())
}
