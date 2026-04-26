














































// This file was automatically generated from OpenAPI specification by mandolin https://github.com/lzpel/mandolin

/* Cargo.toml to build this server

[features]
mandolin_client = ["dep:reqwest"]

[dependencies]
serde= { version="*", features = ["derive"] }
serde_json= "*"
axum = { version = "*", features = ["multipart"] }
tokio = { version = "*", features = ["rt", "rt-multi-thread", "macros", "signal"] }
reqwest = { version = "*", features = ["json"], optional = true }
# optional
uuid = { version = "*", features = ["serde"] }
chrono = { version = "*", features = ["serde"] }
*/

use std::collections::HashMap;
use serde;
use std::future::Future;

/// API Interface Trait
/// Define server logic by implementing methods corresponding to each operation
pub trait ApiInterface{

	// POST /magnet
	fn upload_coils(&self, _req: UploadCoilsRequest) -> impl Future<Output = UploadCoilsResponse> + Send{async{Default::default()}}

	// POST /vessel
	fn upload_vmec(&self, _req: UploadVmecRequest) -> impl Future<Output = UploadVmecResponse> + Send{async{Default::default()}}
}


/// Auth Context: Struct to hold authentication information
#[derive(Default,Clone,Debug,serde::Serialize,serde::Deserialize)]
pub struct AuthContext{
    pub subject: String,   // User identifier (e.g., "auth0|123", "google-oauth2|456")
    pub subject_id: u128,  // UUID compatible numeric ID
    pub scopes: Vec<String>, // Scopes (e.g., "read:foo", "write:bar")
}



// Request type for upload_coils
#[derive(Debug)]
pub struct UploadCoilsRequest{
	pub width:Option<f64>,
	pub thickness:Option<f64>,
	pub toroidal_extent:Option<f64>,
	pub body: MagnetUpload,
}
// Response type for upload_coils
#[derive(Debug)]
pub enum UploadCoilsResponse{
	Status200(FileList),
	Status400(Error),
	Status500(Error),
	Error(String),
}
impl Default for UploadCoilsResponse{
	fn default() -> Self{
		Self::Status200(Default::default())
	}
}
impl axum::response::IntoResponse for UploadCoilsResponse{
	fn into_response(self) -> axum::response::Response{
		match self{
			Self::Status200(v)=> axum::response::Response::builder().status(http::StatusCode::from_u16(200).unwrap()).header(http::header::CONTENT_TYPE, "application/json").body(axum::body::Body::from(serde_json::to_vec_pretty(&v).expect("error serialize response json"))).unwrap(),
			Self::Status400(v)=> axum::response::Response::builder().status(http::StatusCode::from_u16(400).unwrap()).header(http::header::CONTENT_TYPE, "application/json").body(axum::body::Body::from(serde_json::to_vec_pretty(&v).expect("error serialize response json"))).unwrap(),
			Self::Status500(v)=> axum::response::Response::builder().status(http::StatusCode::from_u16(500).unwrap()).header(http::header::CONTENT_TYPE, "application/json").body(axum::body::Body::from(serde_json::to_vec_pretty(&v).expect("error serialize response json"))).unwrap(),
			Self::Error(msg) => axum::response::Response::builder().status(500).header(http::header::CONTENT_TYPE, "text/plain").body(axum::body::Body::from(msg)).unwrap(),
		}
	}
}

// Request type for upload_vmec
#[derive(Debug)]
pub struct UploadVmecRequest{
	pub wall_s:Option<f64>,
	pub scale:Option<f64>,
	pub body: VesselUpload,
}
// Response type for upload_vmec
#[derive(Debug)]
pub enum UploadVmecResponse{
	Status200(FileList),
	Status400(Error),
	Status500(Error),
	Error(String),
}
impl Default for UploadVmecResponse{
	fn default() -> Self{
		Self::Status200(Default::default())
	}
}
impl axum::response::IntoResponse for UploadVmecResponse{
	fn into_response(self) -> axum::response::Response{
		match self{
			Self::Status200(v)=> axum::response::Response::builder().status(http::StatusCode::from_u16(200).unwrap()).header(http::header::CONTENT_TYPE, "application/json").body(axum::body::Body::from(serde_json::to_vec_pretty(&v).expect("error serialize response json"))).unwrap(),
			Self::Status400(v)=> axum::response::Response::builder().status(http::StatusCode::from_u16(400).unwrap()).header(http::header::CONTENT_TYPE, "application/json").body(axum::body::Body::from(serde_json::to_vec_pretty(&v).expect("error serialize response json"))).unwrap(),
			Self::Status500(v)=> axum::response::Response::builder().status(http::StatusCode::from_u16(500).unwrap()).header(http::header::CONTENT_TYPE, "application/json").body(axum::body::Body::from(serde_json::to_vec_pretty(&v).expect("error serialize response json"))).unwrap(),
			Self::Error(msg) => axum::response::Response::builder().status(500).header(http::header::CONTENT_TYPE, "text/plain").body(axum::body::Body::from(msg)).unwrap(),
		}
	}
}












#[derive(Default,Clone,Debug,serde::Serialize,serde::Deserialize)]
pub struct Error{
	pub r#message:String,
}

#[derive(Default,Clone,Debug,serde::Serialize,serde::Deserialize)]
pub struct FileEntry{
	pub r#content_type:String,
	pub r#data:String,
	pub r#filename:String,
}

pub type FileList=Vec<FileEntry>;

#[derive(Default,Clone,Debug,serde::Serialize,serde::Deserialize)]
pub struct MagnetUpload{
	pub r#file:Vec<u8>,
}

#[derive(Default,Clone,Debug,serde::Serialize,serde::Deserialize)]
pub struct VesselUpload{
	pub r#file:Vec<u8>,
}




// following part is only for client

#[cfg(feature = "mandolin_client")]
pub trait ApiClient {
    fn get_client(&self) -> &reqwest::Client;
    fn get_base_url(&self) -> &str;
}

#[cfg(feature = "mandolin_client")]
impl<T: ApiClient + Sync> ApiInterface for T {

    // POST /magnet
    fn upload_coils(&self, req: UploadCoilsRequest) -> impl Future<Output = UploadCoilsResponse> + Send {
        let url = format!("{}{}", self.get_base_url(), "/magnet"
        );
        let client = self.get_client().clone();
        async move {
            let r = match client.post(&url)
                .query(&req.r#width.as_ref().map(|v| [("width", v.to_string())]))
                .query(&req.r#thickness.as_ref().map(|v| [("thickness", v.to_string())]))
                .query(&req.r#toroidal_extent.as_ref().map(|v| [("toroidal_extent", v.to_string())]))
                .body(req.body)
                .send().await {
                Ok(r) => r,
                Err(e) => return UploadCoilsResponse::Error(e.to_string()),
            };
            match r.status().as_u16() {
                200 =>
                    match r.json().await { Ok(v) => UploadCoilsResponse::Status200(v), Err(e) => UploadCoilsResponse::Error(e.to_string()) },
                400 =>
                    match r.json().await { Ok(v) => UploadCoilsResponse::Status400(v), Err(e) => UploadCoilsResponse::Error(e.to_string()) },
                500 =>
                    match r.json().await { Ok(v) => UploadCoilsResponse::Status500(v), Err(e) => UploadCoilsResponse::Error(e.to_string()) },
                code => UploadCoilsResponse::Error(format!("unexpected status: {code}")),
            }
        }
    }

    // POST /vessel
    fn upload_vmec(&self, req: UploadVmecRequest) -> impl Future<Output = UploadVmecResponse> + Send {
        let url = format!("{}{}", self.get_base_url(), "/vessel"
        );
        let client = self.get_client().clone();
        async move {
            let r = match client.post(&url)
                .query(&req.r#wall_s.as_ref().map(|v| [("wall_s", v.to_string())]))
                .query(&req.r#scale.as_ref().map(|v| [("scale", v.to_string())]))
                .body(req.body)
                .send().await {
                Ok(r) => r,
                Err(e) => return UploadVmecResponse::Error(e.to_string()),
            };
            match r.status().as_u16() {
                200 =>
                    match r.json().await { Ok(v) => UploadVmecResponse::Status200(v), Err(e) => UploadVmecResponse::Error(e.to_string()) },
                400 =>
                    match r.json().await { Ok(v) => UploadVmecResponse::Status400(v), Err(e) => UploadVmecResponse::Error(e.to_string()) },
                500 =>
                    match r.json().await { Ok(v) => UploadVmecResponse::Status500(v), Err(e) => UploadVmecResponse::Error(e.to_string()) },
                code => UploadVmecResponse::Error(format!("unexpected status: {code}")),
            }
        }
    }
}

// following part is only for server

use axum;
use axum::http;
use axum::extract::FromRequest;

/// Axum-specific API interface trait
/// Implement this trait alongside ApiInterface to use axum_router.
/// Override methods here for axum-specific behavior (streaming, custom headers, etc.)
pub trait ApiInterfaceAxum: ApiInterface + Sync{
	/// Authentication process: Generate AuthContext from request
	fn authorize(&self, _req: http::Request<()>) -> impl Future<Output = Result<AuthContext, String>> + Send{async { Ok(Default::default()) } }

	// POST /magnet
	fn upload_coils(&self, _raw: http::Request<()>, req: UploadCoilsRequest) -> impl Future<Output = axum::response::Response> + Send{
		let fut = <Self as ApiInterface>::upload_coils(self, req);
		async move{ axum::response::IntoResponse::into_response(fut.await) }
	}

	// POST /vessel
	fn upload_vmec(&self, _raw: http::Request<()>, req: UploadVmecRequest) -> impl Future<Output = axum::response::Response> + Send{
		let fut = <Self as ApiInterface>::upload_vmec(self, req);
		async move{ axum::response::IntoResponse::into_response(fut.await) }
	}
}

/// Helper function to generate text responses
fn text_response(code: http::StatusCode, body: String)->axum::response::Response{
	axum::response::Response::builder()
		.status(code)
		.header(http::header::CONTENT_TYPE, "text/plain")
		.body(axum::body::Body::from(body))
		.unwrap()
}

/// Returns axum::Router with root handlers for all operations registered
pub fn axum_router_operations<S: ApiInterfaceAxum + Sync + Send + 'static>(instance :std::sync::Arc<S>)->axum::Router{
	let router = axum::Router::new();

	let i = instance.clone();
	let router = router.route("/magnet", axum::routing::post(|
			path: axum::extract::Path<HashMap<String,String>>,
			query: axum::extract::Query<HashMap<String,String>>,
			header: http::HeaderMap,
			request: http::Request<axum::body::Body>,
		| async move{
			let (parts, body) = request.into_parts();
			let ret=<S as ApiInterfaceAxum>::upload_coils(i.as_ref(), http::Request::from_parts(parts.clone(), ()), UploadCoilsRequest{
			r#width:{let v=query.get("width").and_then(|v| v.parse().ok());v},
			r#thickness:{let v=query.get("thickness").and_then(|v| v.parse().ok());v},
			r#toroidal_extent:{let v=query.get("toroidal_extent").and_then(|v| v.parse().ok());v},
			body:{
	let r=http::Request::from_parts(parts.clone(), body);
	let v=match axum::extract::Multipart::from_request(r, &()).await{Ok(v)=>v,Err(e)=>return text_response(http::StatusCode::BAD_REQUEST, e.body_text())};
	match async |mut x: axum::extract::Multipart| -> std::result::Result<PathsMagnetPostRequestBodyContentMultipartFormDataSchema,String>{
	let mut o:PathsMagnetPostRequestBodyContentMultipartFormDataSchema=Default::default();
	while let Some(field) = x.next_field().await.map_err(|e| e.body_text())? {
		match field.name().unwrap_or_default() {
			other => return Err(format!("unknown field {other} in multipart-formdata"))
		}
	}
	Ok(o)
}(v).await {
	Ok(v)=>v,
	Err(e)=>return text_response(http::StatusCode::BAD_REQUEST,e)
}
},
		}).await;
		ret
	}));

	let i = instance.clone();
	let router = router.route("/vessel", axum::routing::post(|
			path: axum::extract::Path<HashMap<String,String>>,
			query: axum::extract::Query<HashMap<String,String>>,
			header: http::HeaderMap,
			request: http::Request<axum::body::Body>,
		| async move{
			let (parts, body) = request.into_parts();
			let ret=<S as ApiInterfaceAxum>::upload_vmec(i.as_ref(), http::Request::from_parts(parts.clone(), ()), UploadVmecRequest{
			r#wall_s:{let v=query.get("wall_s").and_then(|v| v.parse().ok());v},
			r#scale:{let v=query.get("scale").and_then(|v| v.parse().ok());v},
			body:{
	let r=http::Request::from_parts(parts.clone(), body);
	let v=match axum::extract::Multipart::from_request(r, &()).await{Ok(v)=>v,Err(e)=>return text_response(http::StatusCode::BAD_REQUEST, e.body_text())};
	match async |mut x: axum::extract::Multipart| -> std::result::Result<PathsVesselPostRequestBodyContentMultipartFormDataSchema,String>{
	let mut o:PathsVesselPostRequestBodyContentMultipartFormDataSchema=Default::default();
	while let Some(field) = x.next_field().await.map_err(|e| e.body_text())? {
		match field.name().unwrap_or_default() {
			other => return Err(format!("unknown field {other} in multipart-formdata"))
		}
	}
	Ok(o)
}(v).await {
	Ok(v)=>v,
	Err(e)=>return text_response(http::StatusCode::BAD_REQUEST,e)
}
},
		}).await;
		ret
	}));
	let router = router.route("/openapi.json", axum::routing::get(|| async move{
			r###"{"components":{"schemas":{"Error":{"properties":{"message":{"type":"string"}},"required":["message"],"type":"object"},"FileEntry":{"properties":{"content_type":{"description":"MIME type hint for the payload (e.g. `model/step`, `text/csv`).","type":"string"},"data":{"description":"Base64-encoded file contents.","format":"base64","type":"string"},"filename":{"description":"Output filename, e.g. `chamber.step` or `magnet_set.csv`.","type":"string"}},"required":["filename","content_type","data"],"type":"object"},"FileList":{"items":{"$ref":"#/components/schemas/FileEntry"},"type":"array"},"MagnetUpload":{"properties":{"file":{"description":"MAKEGRID-format coils file (text).","format":"binary","type":"string"}},"required":["file"],"type":"object"},"VesselUpload":{"properties":{"file":{"description":"VMEC NetCDF-3 64-bit offset file (wout_*.nc).","format":"binary","type":"string"}},"required":["file"],"type":"object"}}},"info":{"description":"HTTP facade over the alphastell vessel/magnet subcommands. Upload a VMEC\nNetCDF or MAKEGRID coils file and receive the generated STEP + CSV\nartifacts as a list of base64-encoded files.","title":"alphastell API","version":"0.1.0"},"openapi":"3.0.0","paths":{"/magnet":{"post":{"description":"Equivalent to the `magnet` subcommand. Accepts a MAKEGRID-format coils\nfile (e.g. `coils.example`) and returns 2 artifacts: a STEP of the swept\nrectangular-section coils and its CSV point cloud.","operationId":"uploadCoils","parameters":[{"description":"Rectangular cross-section width [m]. Default 0.4 m matches parastell.","explode":false,"in":"query","name":"width","schema":{"default":0.4,"format":"double","type":"number"},"style":"form"},{"description":"Rectangular cross-section thickness [m]. Default 0.5 m matches parastell.","explode":false,"in":"query","name":"thickness","schema":{"default":0.5,"format":"double","type":"number"},"style":"form"},{"description":"Toroidal extent [deg]. 360 keeps all coils; values below 360 are reserved for future use.","explode":false,"in":"query","name":"toroidal_extent","schema":{"default":360,"format":"double","type":"number"},"style":"form"}],"requestBody":{"content":{"multipart/form-data":{"schema":{"$ref":"#/components/schemas/MagnetUpload"}}},"required":true},"responses":{"200":{"content":{"application/json":{"schema":{"$ref":"#/components/schemas/FileList"}}},"description":"Generated in-vessel artifacts (6 STEP + 6 CSV)."},"400":{"content":{"application/json":{"schema":{"$ref":"#/components/schemas/Error"}}},"description":"Invalid input file or parameters."},"500":{"content":{"application/json":{"schema":{"$ref":"#/components/schemas/Error"}}},"description":"Processing failure."}},"summary":"Generate a magnet_set STEP from a MAKEGRID coils file"}},"/vessel":{"post":{"description":"Equivalent to the `vessel` subcommand. Accepts a VMEC `wout_*.nc` file\nand returns 12 artifacts: 6 STEP solids (chamber, first_wall, breeder,\nback_wall, shield, vacuum_vessel) and their corresponding CSV point\nclouds.","operationId":"uploadVmec","parameters":[{"description":"Reference flux surface. Parastell default 1.08 (just outside the LCFS).","explode":false,"in":"query","name":"wall_s","schema":{"default":1.08,"format":"double","type":"number"},"style":"form"},{"description":"Unit scaling factor. VMEC is in meters; 100 converts to centimeters to match the parastell default.","explode":false,"in":"query","name":"scale","schema":{"default":100,"format":"double","type":"number"},"style":"form"}],"requestBody":{"content":{"multipart/form-data":{"schema":{"$ref":"#/components/schemas/VesselUpload"}}},"required":true},"responses":{"200":{"content":{"application/json":{"schema":{"$ref":"#/components/schemas/FileList"}}},"description":"Generated in-vessel artifacts (6 STEP + 6 CSV)."},"400":{"content":{"application/json":{"schema":{"$ref":"#/components/schemas/Error"}}},"description":"Invalid input file or parameters."},"500":{"content":{"application/json":{"schema":{"$ref":"#/components/schemas/Error"}}},"description":"Processing failure."}},"summary":"Generate in-vessel components from a VMEC NetCDF file"}}},"servers":[{"description":"Default server","url":"/","variables":{}}]}"###
		}))
		.route("/ui", axum::routing::get(|| async move{
			axum::response::Html(r###"
			<html lang="en">
			<head>
			  <meta charset="utf-8" />
			  <meta name="viewport" content="width=device-width, initial-scale=1" />
			  <meta name="description" content="SwaggerUI" />
			  <title>SwaggerUI</title>
			  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui.css" />
			</head>
			<body>
			<div id="swagger-ui"></div>
			<script src="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui-bundle.js" crossorigin></script>
			<script>
			  window.onload = () => {
				window.ui = SwaggerUIBundle({
				  url: location.href.replace("/ui","/openapi.json"),
				  dom_id: '#swagger-ui',
				});
			  };
			</script>
			</body>
			</html>
			"###)
		}));
	return router;
}

/// Mount the router to the server's URL prefix with nest_service
pub fn axum_router<S: ApiInterfaceAxum + Sync + Send + 'static>(instance: S)->axum::Router{
	let instance_arc=std::sync::Arc::new(instance);
	let mut router = axum::Router::new();
	router = router.merge(axum_router_operations(instance_arc.clone()));
	router
}

/// Display the server URL list to standard output
pub fn print_axum_router(port:u16){
	println!("http://localhost:{}/ui", port);
}

/// Test server implementation (all methods return default values)
pub struct TestServer{}
impl ApiInterface for TestServer{
	// Implement required methods here

	// POST /magnet
	// async fn upload_coils(&self, _req: UploadCoilsRequest) -> UploadCoilsResponse{Default::default()}

	// POST /vessel
	// async fn upload_vmec(&self, _req: UploadVmecRequest) -> UploadVmecResponse{Default::default()}
}
impl ApiInterfaceAxum for TestServer{
	// Override for axum-specific behavior (e.g. custom auth, streaming, custom headers)
	// async fn authorize(&self, _req: http::Request<()>) -> Result<AuthContext, String>{ Ok(Default::default()) }

	// POST /magnet
	// async fn upload_coils(&self, _raw: http::Request<()>, req: UploadCoilsRequest) -> axum::response::Response{ axum::response::IntoResponse::into_response(<Self as ApiInterface>::upload_coils(self, req).await) }

	// POST /vessel
	// async fn upload_vmec(&self, _raw: http::Request<()>, req: UploadVmecRequest) -> axum::response::Response{ axum::response::IntoResponse::into_response(<Self as ApiInterface>::upload_vmec(self, req).await) }
}

/// Estimates the origin URL (scheme://host) from an HTTP request
/// Priority: Forwarded > X-Forwarded-* > Host
pub fn origin_from_request<B>(req: &http::Request<B>) -> Option<String> {
	fn first_csv(s: &str) -> &str {
		s.split(',').next().unwrap_or(s).trim()
	}
	fn unquote(s: &str) -> &str {
		let s = s.trim();
		if s.starts_with('"') && s.ends_with('"') && s.len() >= 2 {
			&s[1..s.len() - 1]
		} else {
			s
		}
	}
	fn guess_scheme(host: &str) -> &'static str {
		let hostname = host
			.trim_start_matches('[')
			.split(']')
			.next()
			.unwrap_or(host)
			.split(':')
			.next()
			.unwrap_or(host);
		match hostname {
			"localhost" | "127.0.0.1" | "::1" => "http",
			_ => "https",
		}
	}
	fn mk_origin(proto: Option<String>, host: String) -> String {
		let proto = proto.unwrap_or_else(|| guess_scheme(&host).to_string());
		format!("{proto}://{host}")
	}

	let headers = req.headers();

	// 0) Check URI authority (for absolute URIs)
	if let Some(auth) = req.uri().authority() {
		let host = auth.as_str().to_string();
		return Some(mk_origin(None, host));
	}

	// 1) Forwarded (RFC 7239)
	if let Some(raw) = headers
		.get(http::header::FORWARDED)
		.and_then(|v| v.to_str().ok())
	{
		let first = first_csv(raw);
		let mut proto: Option<String> = None;
		let mut host: Option<String> = None;

		for part in first.split(';') {
			let mut it = part.trim().splitn(2, '=');
			let k = it.next().unwrap_or("").trim().to_ascii_lowercase();
			let v = unquote(it.next().unwrap_or(""));

			match k.as_str() {
				"proto" if !v.is_empty() => proto = Some(v.to_ascii_lowercase()),
				"host" if !v.is_empty() => host = Some(v.to_string()),
				_ => {}
			}
		}

		if let Some(host) = host {
			return Some(mk_origin(proto, host));
		}
	}

	// 2) X-Forwarded-*
	if let Some(mut host) = headers
		.get("x-forwarded-host")
		.and_then(|v| v.to_str().ok())
		.map(first_csv)
		.filter(|s| !s.is_empty())
		.map(str::to_string)
	{
		if !host.contains(':') {
			if let Some(port) = headers
				.get("x-forwarded-port")
				.and_then(|v| v.to_str().ok())
				.map(str::trim)
				.filter(|s| !s.is_empty())
			{
				host = format!("{host}:{port}");
			}
		}

		let proto = headers
			.get("x-forwarded-proto")
			.and_then(|v| v.to_str().ok())
			.map(first_csv)
			.map(|s| s.to_ascii_lowercase())
			.filter(|s| !s.is_empty());

		return Some(mk_origin(proto, host));
	}

	// 3) Fallback to Host header
	let host = headers
		.get(http::header::HOST)
		.and_then(|h| h.to_str().ok())
		.map(str::trim)
		.filter(|s| !s.is_empty())?
		.to_string();

	Some(format!("{}://{}", guess_scheme(&host), host))
}
mod base64_serde {
	use serde::{Deserialize,Deserializer,Serializer};
	fn enc(b: &[u8]) -> String {
		const T: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
		b.chunks(3).flat_map(|c| {
			let n = c.iter().fold(0u32, |a,&b| a<<8|b as u32) << (8*(3-c.len()));
			[T[(n>>18&63)as usize], T[(n>>12&63)as usize],
			 if c.len()>1 {T[(n>>6&63)as usize]} else {b'='},
			 if c.len()>2 {T[(n&63)as usize]}    else {b'='}]
		}).map(|b| b as char).collect()
	}
	fn dec(s: &str) -> Result<Vec<u8>, String> {
		const T: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
		let v: Result<Vec<u8>,_> = s.bytes().filter(|&b| b!=b'=')
			.map(|b| T.iter().position(|&c|c==b).map(|i|i as u8).ok_or(format!("invalid base64 char: {b}")))
			.collect();
		Ok(v?.chunks(4).flat_map(|c| {
			let n = c.iter().fold(0u32, |a,&b| a<<6|b as u32) << (4-c.len())*6;
			(0..c.len()-1).map(move |i| (n>>(16-8*i)) as u8)
		}).collect())
	}
	pub fn serialize<S:Serializer>(b: &Vec<u8>, s: S) -> Result<S::Ok,S::Error> {
		s.serialize_str(&enc(b))
	}
	pub fn deserialize<'de,D:Deserializer<'de>>(d: D) -> Result<Vec<u8>,D::Error> {
		dec(&String::deserialize(d)?).map_err(serde::de::Error::custom)
	}
	pub mod opt {
		use serde::{Deserialize,Deserializer,Serializer};
		pub fn serialize<S:Serializer>(b: &Option<Vec<u8>>, s: S) -> Result<S::Ok,S::Error> {
			match b { Some(b) => s.serialize_some(&super::enc(b)), None => s.serialize_none() }
		}
		pub fn deserialize<'de,D:Deserializer<'de>>(d: D) -> Result<Option<Vec<u8>>,D::Error> {
			Option::<String>::deserialize(d)?.map(|s| super::dec(&s).map_err(serde::de::Error::custom)).transpose()
		}
	}
}

#[tokio::main]
async fn main() {
	let port:u16 = std::env::var("PORT").unwrap_or("8080".to_string()).parse().expect("PORT should be integer");
	print_axum_router(port);
	let api = TestServer{};
	let app = axum_router(api).layer(axum::extract::DefaultBodyLimit::disable());
	let listener = tokio::net::TcpListener::bind(format!("0.0.0.0:{port}")).await.unwrap();
	axum::serve(listener, app)
		.with_graceful_shutdown(async { tokio::signal::ctrl_c().await.unwrap() })
		.await
		.unwrap();
}