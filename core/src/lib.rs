//! alphastell-core — VMEC 由来のステラレータ CAD ジオメトリ中核ライブラリ。
//!
//! `cadrum` (OCCT) を用いて in-vessel build とモジュラーコイルの solid を生成し、
//! STEP / GLB / CSV として取り出す。ネイティブ CLI (`alphastell`) とブラウザ wasm
//! (`alphastell-web`) の双方から共有される。
//!
//! モジュール構成:
//! - `vmec`     : VMEC `wout_*.nc` 読み込みと (θ, φ) での (R, Z) 評価
//! - `coils`    : MAKEGRID コイルファイルのパース
//! - `vessel`   : 6 層 in-vessel build の生成 (`run`)
//! - `magnet`   : コイル sweep の生成 (`run`)
//! - `artifact` : solid + 点群をまとめ STEP/GLB/CSV を出力する共通 record
//!
//! 以下は `std::fs` / `regex` に依存するネイティブ専用で、`cli` feature でのみ有効:
//! - `bbox` / `compound` / `cut` / `validate` / `strip_netcdf`、および `Artifact::write`。

pub mod artifact;
pub mod coils;
pub mod magnet;
pub mod vessel;
pub mod vmec;

#[cfg(feature = "cli")]
pub mod bbox;
#[cfg(feature = "cli")]
pub mod compound;
#[cfg(feature = "cli")]
pub mod cut;
#[cfg(feature = "cli")]
pub mod strip_netcdf;
#[cfg(feature = "cli")]
pub mod validate;

/// 本クレート共通の Result 型。`Box<dyn Error>` なので !Send なエラー
/// (例: netcdf3 の ReadError) もそのまま保持できる。
pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
