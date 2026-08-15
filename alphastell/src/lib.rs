mod hello;
mod surface_rz_fourier;
pub mod vmec;
pub mod spline;
pub mod geometry;
use pyo3::prelude::*;

#[pymodule]
fn alphastell(m: &Bound<'_, PyModule>) -> PyResult<()> {
	hello::module(m)?;
	geometry::module(m)?;
	surface_rz_fourier::module(m)?;
	Ok(())
}
