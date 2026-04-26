//! HTTP API: VMEC または coils ファイルをアップロードすると STEP / STL / CSV を
//! base64 入りの JSON で返す。`vessel`/`magnet` サブコマンドを HTTP 越しに叩く薄い fa
//! cade。
//!
//! 重い CAD 構築は `tokio::task::spawn_blocking` でブロッキングプールに逃がす。

use std::io::Cursor;

use crate::artifact::Artifact;
use crate::openapi::{
	self, ApiInterface, Error as ApiError, FileEntry, MagnetRequest, MagnetResponse,
	VesselRequest, VesselResponse, axum_router, print_axum_router,
};

struct AlphaStellApi {}

impl ApiInterface for AlphaStellApi {
	async fn vessel(&self, req: VesselRequest) -> VesselResponse {
		let bytes = req.body.body;
		let wall_s = req.wall_s.unwrap_or(1.08);
		let scale = req.scale.unwrap_or(100.0);

		let join = tokio::task::spawn_blocking(move || -> Result<Vec<FileEntry>, String> {
			let arts = crate::vessel::run(Cursor::new(bytes), wall_s, scale)
				.map_err(|e| e.to_string())?;
			artifacts_to_entries(&arts)
		})
		.await;

		match join {
			Ok(Ok(entries)) => VesselResponse::Status200(entries),
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

		let join = tokio::task::spawn_blocking(move || -> Result<Vec<FileEntry>, String> {
			let arts = crate::magnet::run(
				Cursor::new(bytes),
				width,
				thickness,
				toroidal_extent,
				scale,
			)
			.map_err(|e| e.to_string())?;
			artifacts_to_entries(&arts)
		})
		.await;

		match join {
			Ok(Ok(entries)) => MagnetResponse::Status200(entries),
			Ok(Err(msg)) => MagnetResponse::Status500(ApiError { message: msg }),
			Err(e) => MagnetResponse::Status500(ApiError {
				message: format!("blocking task join error: {e}"),
			}),
		}
	}
}

impl openapi::ApiInterfaceAxum for AlphaStellApi {}

/// 1 つの `Artifact` を STEP/STL/CSV の 3 entries に展開して flatten。
fn artifacts_to_entries(arts: &[Artifact]) -> Result<Vec<FileEntry>, String> {
	let mut out = Vec::with_capacity(arts.len() * 3);
	for a in arts {
		let step = a.step_bytes().map_err(|e| e.to_string())?;
		out.push(FileEntry {
			filename: format!("{}.step", a.name),
			content_type: "model/step".into(),
			data: base64_encode(&step),
		});
		let stl = a.stl_bytes().map_err(|e| e.to_string())?;
		out.push(FileEntry {
			filename: format!("{}.stl", a.name),
			content_type: "model/stl".into(),
			data: base64_encode(&stl),
		});
		let csv = a.csv_bytes();
		out.push(FileEntry {
			filename: format!("{}.csv", a.name),
			content_type: "text/csv".into(),
			data: base64_encode(&csv),
		});
	}
	Ok(out)
}

/// 標準 base64 (RFC 4648, +/= 入り)。`openapi::base64_serde::enc` と同実装。
fn base64_encode(b: &[u8]) -> String {
	const T: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
	b.chunks(3)
		.flat_map(|c| {
			let n = c.iter().fold(0u32, |a, &b| a << 8 | b as u32) << (8 * (3 - c.len()));
			[
				T[(n >> 18 & 63) as usize],
				T[(n >> 12 & 63) as usize],
				if c.len() > 1 {
					T[(n >> 6 & 63) as usize]
				} else {
					b'='
				},
				if c.len() > 2 {
					T[(n & 63) as usize]
				} else {
					b'='
				},
			]
		})
		.map(|b| b as char)
		.collect()
}

#[tokio::main]
pub async fn run(port: u16) {
	print_axum_router(port);
	let api = AlphaStellApi {};
	let app = axum_router(api).layer(axum::extract::DefaultBodyLimit::disable());
	let listener = tokio::net::TcpListener::bind(format!("0.0.0.0:{port}"))
		.await
		.unwrap();
	axum::serve(listener, app)
		.with_graceful_shutdown(async { tokio::signal::ctrl_c().await.unwrap() })
		.await
		.unwrap();
}
