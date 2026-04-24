use crate::out::{TestServer, axum_router, print_axum_router};

#[tokio::main]
pub async fn run(port: u16) {
	print_axum_router(port);
	let api = TestServer {};
	let app = axum_router(api).layer(axum::extract::DefaultBodyLimit::disable());
	let listener = tokio::net::TcpListener::bind(format!("0.0.0.0:{port}"))
		.await
		.unwrap();
	axum::serve(listener, app)
		.with_graceful_shutdown(async { tokio::signal::ctrl_c().await.unwrap() })
		.await
		.unwrap();
}
