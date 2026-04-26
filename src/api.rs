//! HTTP API: VMEC または coils ファイルをアップロードすると STEP / STL / CSV を
//! 1 本の tar (`application/x-tar`) で返す。`vessel`/`magnet` サブコマンドを HTTP 越しに
//! 叩く薄い facade。
//!
//! 重い CAD 構築は `tokio::task::spawn_blocking` でブロッキングプールに逃がす。
//! gzip 圧縮は `tower-http::CompressionLayer` 任せで、ハンドラは無圧縮 tar を返す。

use std::io::Cursor;

use crate::artifact::Artifact;
use crate::openapi::{
	self, ApiInterface, Error as ApiError, MagnetRequest, MagnetResponse, VesselRequest,
	VesselResponse, axum_router, print_axum_router,
};

struct AlphaStellApi {}

impl ApiInterface for AlphaStellApi {
	async fn vessel(&self, req: VesselRequest) -> VesselResponse {
		let bytes = req.body.body;
		let wall_s = req.wall_s.unwrap_or(1.08);
		let scale = req.scale.unwrap_or(100.0);

		let join = tokio::task::spawn_blocking(move || -> Result<Vec<u8>, String> {
			let arts = crate::vessel::run(Cursor::new(bytes), wall_s, scale)
				.map_err(|e| e.to_string())?;
			artifacts_to_tar(&arts)
		})
		.await;

		match join {
			Ok(Ok(tar)) => VesselResponse::Status200(tar),
			Ok(Err(msg)) => VesselResponse::Status500(ApiError { message: msg }),
			Err(e) => VesselResponse::Status500(ApiError {
				message: format!("blocking task join error: {e}"),
			}),
		}
	}

	async fn magnet(&self, req: MagnetRequest) -> MagnetResponse {
		let bytes = req.body.body;
		let width = req.width.unwrap_or(0.4);
		let thickness = req.thickness.unwrap_or(0.5);
		let toroidal_extent = req.toroidal_extent.unwrap_or(360.0);
		// CLI/makefile 既定 (cm 出力) と揃える。OpenAPI 側に scale が出ていないので固定。
		let scale = 100.0_f64;

		let join = tokio::task::spawn_blocking(move || -> Result<Vec<u8>, String> {
			let arts = crate::magnet::run(
				Cursor::new(bytes),
				width,
				thickness,
				toroidal_extent,
				scale,
			)
			.map_err(|e| e.to_string())?;
			artifacts_to_tar(&arts)
		})
		.await;

		match join {
			Ok(Ok(tar)) => MagnetResponse::Status200(tar),
			Ok(Err(msg)) => MagnetResponse::Status500(ApiError { message: msg }),
			Err(e) => MagnetResponse::Status500(ApiError {
				message: format!("blocking task join error: {e}"),
			}),
		}
	}
}

impl openapi::ApiInterfaceAxum for AlphaStellApi {}

/// 各 `Artifact` を `<name>.{step,stl,csv}` の 3 entries として 1 本の tar にまとめる。
fn artifacts_to_tar(arts: &[Artifact]) -> Result<Vec<u8>, String> {
	let mut buf: Vec<u8> = Vec::new();
	{
		let mut builder = tar::Builder::new(&mut buf);
		for a in arts {
			append(&mut builder, &format!("{}.step", a.name), &a.step_bytes().map_err(|e| e.to_string())?)?;
			append(&mut builder, &format!("{}.stl", a.name), &a.stl_bytes().map_err(|e| e.to_string())?)?;
			append(&mut builder, &format!("{}.csv", a.name), &a.csv_bytes())?;
		}
		builder.finish().map_err(|e| format!("tar finish: {e}"))?;
	}
	Ok(buf)
}

fn append<W: std::io::Write>(builder: &mut tar::Builder<W>, name: &str, data: &[u8]) -> Result<(), String> {
	let mut header = tar::Header::new_gnu();
	header.set_size(data.len() as u64);
	header.set_mode(0o644);
	header.set_cksum();
	builder
		.append_data(&mut header, name, data)
		.map_err(|e| format!("tar append {name}: {e}"))
}

#[tokio::main]
pub async fn run(port: u16) {
	print_axum_router(port);
	let api = AlphaStellApi {};
	let app = axum_router(api)
		.layer(axum::extract::DefaultBodyLimit::disable())
		.layer(tower_http::compression::CompressionLayer::new());
	let listener = tokio::net::TcpListener::bind(format!("0.0.0.0:{port}"))
		.await
		.unwrap();
	axum::serve(listener, app)
		.with_graceful_shutdown(async { tokio::signal::ctrl_c().await.unwrap() })
		.await
		.unwrap();
}
