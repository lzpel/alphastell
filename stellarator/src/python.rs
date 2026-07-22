//! python バインディング (issue #5 の連携経路)。maturin が feature "python" を立てて
//! cdylib をビルドしたときだけコンパイルされる。#[pymodule] の関数名が import 名になる。

use pyo3::prelude::*;

#[pyfunction]
fn hello() {
	crate::hello()
}

#[pymodule]
fn stellarator(m: &Bound<'_, PyModule>) -> PyResult<()> {
	m.add_function(wrap_pyfunction!(hello, m)?)
}
