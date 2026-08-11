use cadrum;

/// このモジュールのエラー。cadrum の失敗理由をそのまま運ぶ。
/// PyErr への変換だけ feature ゲートするのは、cargo test (pyo3 無し) でもここを通すため。
#[derive(Debug)]
pub struct Error(pub cadrum::Error);

impl From<cadrum::Error> for Error {
	fn from(e: cadrum::Error) -> Self {
		Error(e)
	}
}

impl std::fmt::Display for Error {
	fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
		write!(f, "{}", self.0)
	}
}

impl std::error::Error for Error {}

fn points_to_dvec3(points: Vec<f64>) -> (usize, usize, Vec<cadrum::DVec3>) {
	// 最初の2要素は n, m のサイズ 残りは n*m*3のフラットな座標配列
	let n = points[0] as usize;
	let m = points[1] as usize;
	let dvec3_points: Vec<cadrum::DVec3> = points[2..]
		.chunks(3)
		.map(|chunk| cadrum::DVec3::new(chunk[0], chunk[1], chunk[2]))
		.collect();
	(n, m, dvec3_points)
}
pub fn loft_geometry(points: Vec<f64>) -> std::result::Result<cadrum::Solid, Error> {
	let (u, v, point) = points_to_dvec3(points);
	let sections: std::result::Result<Vec<Vec<cadrum::Edge>>, cadrum::Error> = (0..u).map(|i| cadrum::Edge::polygon((0..v).map(|j| &point[i * v + j]))).collect();
	Ok(cadrum::Solid::loft(&sections?, true)?)
}
pub fn bspline_geometry(points: Vec<f64>) -> std::result::Result<cadrum::Solid, Error> {
	let (u, v, point) = points_to_dvec3(points);
	Ok(cadrum::Solid::bspline(u, v, true, |i,j| point[i*v+j])?)
}
/// STEP (AP214) をバイト列で返す。cadrum の writer は std::io::Write を取るので、
/// 呼び出し側 (python 束縛) に渡すため一旦 Vec<u8> に溜める。
pub fn write_step(solid: &cadrum::Solid) -> std::result::Result<Vec<u8>, Error> {
	let mut buffer = Vec::new();
	cadrum::Solid::write_step([solid], &mut buffer)?;
	Ok(buffer)
}