mod hello;
mod surface_fourier_rz;
pub mod vmec;
pub mod spline;
pub mod geometry;
use pyo3::prelude::*;

#[pymodule]
fn alphastell(m: &Bound<'_, PyModule>) -> PyResult<()> {
	hello::module(m)?;
	geometry::module(m)?;
	surface_fourier_rz::module(m)?;
	Ok(())
}
