//! python バインディング (issue #5 の連携経路)。maturin が feature "python" を立てて
//! cdylib をビルドしたときだけコンパイルされる。#[pymodule] の関数名が import 名になる。

use pyo3::prelude::*;

#[pyfunction]
fn hello() {
	println!("Hello, stellarator!");
}

#[pyfunction]
fn hello_numpy(sum: f64) -> f64 {
	println!("Hello, sum is {}!", sum);
	sum
}

/// rust の型を python に渡す最小例。#[pyclass] を付けた構造体は python 側の
/// オブジェクトとして扱われ、#[pymethods] のメソッドがそのまま呼べる。
#[pyclass]
struct Hello {
	name: String,
}

#[pymethods]
impl Hello {
	fn say_hello(&self) {
		println!("Hello, {}!", self.name);
	}
}

/// pyo3 の引数は既定で位置引数兼キーワード引数なので hello_constructor(name="...") で呼べる。
#[pyfunction]
fn hello_constructor(name: String) -> Hello {
	Hello { name }
}

#[pyclass(unsendable)]
#[repr(transparent)]
struct Geometry(cadrum::Solid);

#[pymethods]
impl Geometry {
	/// SurfaceRZFourier::load が file-like から read() するのと対称に、file-like へ write() する。
	fn write_step(&self, file: &Bound<'_, PyAny>) -> PyResult<()> {
		let data = crate::geometry::write_step(&self.0)?;
		file.call_method1("write", (pyo3::types::PyBytes::new(file.py(), &data),))?;
		Ok(())
	}
}

#[pyfunction]
fn loft_geometry(points: Vec<f64>) -> Result<Geometry, crate::geometry::Error> {
	Ok(Geometry(crate::geometry::loft_geometry(points)?))
}

#[pyfunction]
fn bspline_geometry(points: Vec<f64>) -> Result<Geometry, crate::geometry::Error> {
	Ok(Geometry(crate::geometry::bspline_geometry(points)?))
}

/// pyo3 も cadrum も他クレートなので impl From<cadrum::Error> for PyErr は孤児則で書けない。
/// 自前の Error を挟むことで #[pyfunction] が Result<_, Error> のまま返せる。
#[cfg(feature = "python")]
impl From<crate::geometry::Error> for pyo3::PyErr {
	fn from(e: crate::geometry::Error) -> pyo3::PyErr {
		pyo3::exceptions::PyValueError::new_err(e.to_string())
	}
}

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
fn stellarator(m: &Bound<'_, PyModule>) -> PyResult<()> {
	m.add_function(wrap_pyfunction!(hello, m)?)?;
	m.add_function(wrap_pyfunction!(hello_numpy, m)?)?;
	m.add_function(wrap_pyfunction!(hello_constructor, m)?)?;
	m.add_class::<Hello>()?;
	m.add_function(wrap_pyfunction!(loft_geometry, m)?)?;
	m.add_function(wrap_pyfunction!(bspline_geometry, m)?)?;
	m.add_class::<Geometry>()?;
	m.add_class::<SurfaceRZFourier>()?;
	Ok(())
}
