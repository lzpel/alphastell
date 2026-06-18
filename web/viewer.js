// three.js による GLB 描画グルー。alphastell-web (wasm) から
// `#[wasm_bindgen(module = "/viewer.js")]` の named export として呼ばれる。
// importmap は index.html で定義 ("three" / "three/addons/")。

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

let scene, camera, renderer, controls;
const models = new Map();
const loader = new GLTFLoader();

export function initViewer(canvasId) {
	const canvas = document.getElementById(canvasId);

	// VMEC は Z-up。
	THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

	renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
	renderer.setPixelRatio(window.devicePixelRatio);

	scene = new THREE.Scene();
	scene.background = new THREE.Color(0x111111);

	camera = new THREE.PerspectiveCamera(45, 1, 1, 200000);
	camera.up.set(0, 0, 1);
	camera.position.set(3500, 3500, 2500);

	controls = new OrbitControls(camera, renderer.domElement);
	controls.enableDamping = true;

	scene.add(new THREE.AmbientLight(0xffffff, 0.7));
	const key = new THREE.DirectionalLight(0xffffff, 1.0);
	key.position.set(1, 1, 1);
	scene.add(key);
	const fill = new THREE.DirectionalLight(0xffffff, 0.4);
	fill.position.set(-1, -1, -0.5);
	scene.add(fill);

	const resize = () => {
		const w = canvas.clientWidth || window.innerWidth;
		const h = canvas.clientHeight || window.innerHeight;
		renderer.setSize(w, h, false);
		camera.aspect = w / h;
		camera.updateProjectionMatrix();
	};
	window.addEventListener("resize", resize);
	resize();

	const animate = () => {
		requestAnimationFrame(animate);
		controls.update();
		renderer.render(scene, camera);
	};
	animate();
}

export function loadModel(name, url) {
	loader.load(
		url,
		(gltf) => {
			const group = gltf.scene;
			group.name = name;
			const prev = models.get(name);
			if (prev) scene.remove(prev);
			models.set(name, group);
			scene.add(group);
			URL.revokeObjectURL(url);
		},
		undefined,
		(err) => console.error("GLTF load failed:", name, err),
	);
}

export function setVisible(name, visible) {
	const g = models.get(name);
	if (g) g.visible = visible;
}

export function clearModels() {
	for (const g of models.values()) scene.remove(g);
	models.clear();
}
