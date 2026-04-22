//! alphastell library surface. The binary (src/main.rs) also uses these modules,
//! but exposing them here lets `examples/` access `VmecData` etc. directly.

pub mod vmec;

/// 本クレート共通の Result 型 (main.rs と共通)。
pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
