//! ステラレータ幾何カーネル。
//!
//! W1 の範囲は VMEC 平衡 (`wout_*.nc`) の読み込みと磁気面の評価まで。
//! CAD カーネル (cadrum) への依存はここには入れない — 流路生成は W2 で
//! 別モジュールとして足す。現状の依存は netCDF-3 リーダのみで、
//! C ツールチェインも HDF5 も要らない。

pub mod vmec;
pub mod spline;

/// クレート共通のエラー型。
///
/// `netcdf3::ReadError` は内部に `Rc` を持つため `!Send`。そのまま
/// `Box<dyn Error>` に載せられないので、各所で文字列化してから載せている。
pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

// python バインディングは python.rs に隔離。feature ゲートが必要な理由は
// コードの隔離ではなく依存の隔離: pyo3 を通常依存にすると cargo test のたびに
// pyo3 の build script が Python インタプリタを要求して落ちる (実測)。
// optional 依存 + feature が pyo3 をビルド対象から外せる唯一の Cargo 機構。
#[cfg(feature = "python")]
mod python;

pub fn hello(){
	println!("Hello, stellarator!");
}