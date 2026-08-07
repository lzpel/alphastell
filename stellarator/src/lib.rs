//! ステラレータ幾何カーネル。
//!
//! `vmec` が W1 (VMEC 平衡 `wout_*.nc` の読み込みと磁気面の評価)、
//! `geometry` が W2 (点群格子から cadrum で流路ソリッド)。
//! cadrum は OCCT のビルド済み静的ライブラリを取得するので、
//! C++ ツールチェインは要らない。

pub mod vmec;
pub mod spline;
pub mod geometry;

// python バインディングは python.rs に隔離。feature ゲートが必要な理由は
// コードの隔離ではなく依存の隔離: pyo3 を通常依存にすると cargo test のたびに
// pyo3 の build script が Python インタプリタを要求して落ちる (実測)。
// optional 依存 + feature が pyo3 をビルド対象から外せる唯一の Cargo 機構。
#[cfg(feature = "python")]
mod python;