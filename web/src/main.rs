//! alphastell-web — ブラウザ内 (wasm) でステラレータ vessel + コイルを可視化する。
//!
//! `alphastell-core` の `vessel::run` / `magnet::run` を wasm 上でそのまま実行し、
//! レイヤごとに GLB を生成。`viewer.js` (three.js) に渡してレイヤ単位の表示切替付きで描画する。
//!
//! 起動シーケンスは cadrum-wasm-example に倣う:
//! `__anchor_wasi_stub()` → `__wasm_call_ctors()` (OCCT の C++ グローバルコンストラクタ) の順。

use std::cell::RefCell;
use std::io::Cursor;

use alphastell_core::{magnet, vessel};
use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use wasm_bindgen_futures::{spawn_local, JsFuture};
use web_sys::{Document, Event, HtmlInputElement};

// OCCT の C++ グローバルコンストラクタ。headless ビルドは呼ばないので明示実行が必要。
unsafe extern "C" {
	fn __wasm_call_ctors();
}

/// vessel/magnet の単位スケール (cm)。CLI 既定 (`--scale 100`) と一致させる。
const SCALE: f64 = 100.0;
/// コイル矩形断面 [m] と toroidal 範囲 [deg]。CLI 既定と一致。
const COIL_WIDTH: f64 = 0.4;
const COIL_THICKNESS: f64 = 0.5;
const COIL_TOROIDAL_EXTENT: f64 = 360.0;

/// 同梱デモ (trunk copy-file) のファイル名。
const VMEC_ASSET: &str = "wout_vmec.nc";
const COILS_ASSET: &str = "coils.example";

thread_local! {
	/// 現在描画に使う入力バイト列。アップロードで差し替えられる。
	static STATE: RefCell<State> = RefCell::new(State::default());
}

#[derive(Default)]
struct State {
	vmec: Vec<u8>,
	coils: Vec<u8>,
}

#[wasm_bindgen(module = "/viewer.js")]
extern "C" {
	fn initViewer(canvas_id: &str);
	fn loadModel(name: &str, url: &str);
	fn setVisible(name: &str, visible: bool);
	fn clearModels();
}

// trunk は web/ を bin crate としてビルドするため、エントリは `fn main`。
// wasm-bindgen の start は 1 つだけで、ここで OCCT 初期化 + UI 起動を兼ねる
// (cadrum-wasm-example と同じ方針)。
fn main() {
	console_error_panic_hook::set_once();
	cadrum::__anchor_wasi_stub();
	unsafe { __wasm_call_ctors() };

	initViewer("view");
	build_ui().expect("build_ui");

	// 起動時に同梱デモを読み込んで描画。
	spawn_local(async {
		let vmec = fetch_bytes(VMEC_ASSET).await.expect("fetch vmec");
		let coils = fetch_bytes(COILS_ASSET).await.expect("fetch coils");
		STATE.with(|s| {
			let mut s = s.borrow_mut();
			s.vmec = vmec;
			s.coils = coils;
		});
		render();
	});
}

fn document() -> Document {
	web_sys::window().unwrap().document().unwrap()
}

/// `<input type=file>` (VMEC / coils) と「描画」ボタン、レイヤトグル用 `#layers` を `#ui` に生成。
fn build_ui() -> Result<(), JsValue> {
	let doc = document();
	let ui = doc.get_element_by_id("ui").ok_or("missing #ui")?;

	make_file_input(&doc, &ui, "VMEC (wout_*.nc):", ".nc", true)?;
	make_file_input(&doc, &ui, "Coils (coils.example):", "", false)?;

	let layers = doc.create_element("span")?;
	layers.set_id("layers");
	ui.append_child(&layers)?;
	Ok(())
}

/// ラベル付きファイル入力を生成。`is_vmec=true` なら VMEC、false なら coils を差し替える。
fn make_file_input(
	doc: &Document,
	ui: &web_sys::Element,
	label_text: &str,
	accept: &str,
	is_vmec: bool,
) -> Result<(), JsValue> {
	let label = doc.create_element("label")?;
	label.set_text_content(Some(label_text));
	let input: HtmlInputElement = doc.create_element("input")?.dyn_into()?;
	input.set_type("file");
	if !accept.is_empty() {
		input.set_accept(accept);
	}

	let on_change = Closure::<dyn FnMut(Event)>::new(move |ev: Event| {
		let target: HtmlInputElement = ev.target().unwrap().dyn_into().unwrap();
		let Some(files) = target.files() else { return };
		let Some(file) = files.get(0) else { return };
		spawn_local(async move {
			let bytes = blob_to_vec(&file).await.expect("read file");
			STATE.with(|s| {
				let mut s = s.borrow_mut();
				if is_vmec {
					s.vmec = bytes;
				} else {
					s.coils = bytes;
				}
			});
			render();
		});
	});
	input.set_onchange(Some(on_change.as_ref().unchecked_ref()));
	on_change.forget();

	label.append_child(&input)?;
	ui.append_child(&label)?;
	Ok(())
}

/// 現在の STATE から vessel + magnet を生成し、レイヤごとに GLB 化して描画する。
fn render() {
	clearModels();
	clear_checkboxes();

	let (vmec, coils) = STATE.with(|s| {
		let s = s.borrow();
		(s.vmec.clone(), s.coils.clone())
	});
	if vmec.is_empty() || coils.is_empty() {
		return;
	}

	let mut artifacts = match vessel::run(Cursor::new(vmec), SCALE) {
		Ok(a) => a,
		Err(e) => {
			web_sys::console::error_1(&format!("vessel failed: {e}").into());
			return;
		}
	};
	match magnet::run(
		Cursor::new(coils),
		COIL_WIDTH,
		COIL_THICKNESS,
		COIL_TOROIDAL_EXTENT,
		SCALE,
	) {
		Ok(a) => artifacts.extend(a),
		Err(e) => web_sys::console::error_1(&format!("magnet failed: {e}").into()),
	}

	for a in &artifacts {
		match a.glb_bytes() {
			Ok(glb) => match blob_url(&glb) {
				Ok(url) => {
					loadModel(&a.name, &url);
					if let Err(e) = add_layer_checkbox(&a.name) {
						web_sys::console::error_1(&e);
					}
				}
				Err(e) => web_sys::console::error_1(&e),
			},
			Err(e) => web_sys::console::error_1(&format!("glb {} failed: {e}", a.name).into()),
		}
	}
}

/// レイヤ表示トグル用チェックボックス (既定 ON) を `#layers` に追加。
fn add_layer_checkbox(name: &str) -> Result<(), JsValue> {
	let doc = document();
	let layers = doc.get_element_by_id("layers").ok_or("missing #layers")?;

	let label = doc.create_element("label")?;
	label.set_class_name("layer");
	let cb: HtmlInputElement = doc.create_element("input")?.dyn_into()?;
	cb.set_type("checkbox");
	cb.set_checked(true);

	let layer_name = name.to_string();
	let on_change = Closure::<dyn FnMut(Event)>::new(move |ev: Event| {
		let target: HtmlInputElement = ev.target().unwrap().dyn_into().unwrap();
		setVisible(&layer_name, target.checked());
	});
	cb.set_onchange(Some(on_change.as_ref().unchecked_ref()));
	on_change.forget();

	label.append_child(&cb)?;
	let text = doc.create_element("span")?;
	text.set_text_content(Some(name));
	label.append_child(&text)?;
	layers.append_child(&label)?;
	Ok(())
}

fn clear_checkboxes() {
	if let Some(layers) = document().get_element_by_id("layers") {
		layers.set_inner_html("");
	}
}

/// GLB バイト列を Blob にして object URL を作る。three.js GLTFLoader は
/// arraybuffer として fetch するので MIME 型は不問。
fn blob_url(bytes: &[u8]) -> Result<String, JsValue> {
	let u8arr = js_sys::Uint8Array::from(bytes);
	let parts = js_sys::Array::new();
	parts.push(&u8arr);
	let blob = web_sys::Blob::new_with_u8_array_sequence(&parts)?;
	web_sys::Url::create_object_url_with_blob(&blob)
}

/// 静的アセットを fetch して `Vec<u8>` で返す。
async fn fetch_bytes(url: &str) -> Result<Vec<u8>, JsValue> {
	let window = web_sys::window().ok_or("no window")?;
	let resp_val = JsFuture::from(window.fetch_with_str(url)).await?;
	let resp: web_sys::Response = resp_val.dyn_into()?;
	let buf = JsFuture::from(resp.array_buffer()?).await?;
	Ok(js_sys::Uint8Array::new(&buf).to_vec())
}

/// File/Blob を `Vec<u8>` で読む。
async fn blob_to_vec(file: &web_sys::File) -> Result<Vec<u8>, JsValue> {
	let buf = JsFuture::from(file.array_buffer()).await?;
	Ok(js_sys::Uint8Array::new(&buf).to_vec())
}
