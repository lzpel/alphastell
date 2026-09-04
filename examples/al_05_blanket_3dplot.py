import math
import pathlib

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Line3DCollection

from alphastell import SurfaceFourierRZ


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".md").name,
	s_first_wall: float = 1.0,
	s_back: float = 1.08,  # alphastell の wall_s。s>1 はスプライン外挿になる
	div_phi: int = 160,  # 背景に敷く第一壁の格子
	div_theta: int = 48,
	div_path: int = 300,  # 流路 1 本あたりの点数
	# 名前, (トロイダル巻き数, ポロイダル巻き数), 本数。この 2 数だけが流路の向きを決める。
	directions: list[tuple[str, tuple[int, int], int]] = [
		("poloidal", (0, 1), 16),  # W2 v0: 曲がり最小・B にほぼ直交
		("toroidal", (1, 0), 14),  # QTS 相当: B とほぼ平行
		("helical", (1, 1), 14),  # 中間。iota に合わせれば field-aligned になる
	],
) -> None:
	with open(wout, "rb") as f:
		surface = SurfaceFourierRZ.load(f)
	s_channel = (s_first_wall + s_back) / 2  # 流路中心が乗る面

	# --- 背景: 第一壁とブランケット厚み ---------------------------------------
	phi_grid, theta_grid = np.meshgrid(
		np.linspace(0, math.tau, div_phi, endpoint=False),
		np.linspace(0, math.tau, div_theta, endpoint=False),
		indexing="ij",
	)
	wall, _ = surface_points(surface, phi_grid, theta_grid, s_first_wall)
	# φ=0 と φ=2π、θ=0 と θ=2π は同一点なので先頭を末尾に足して継ぎ目を閉じる
	wall = np.concatenate([wall, wall[:1]], axis=0)
	wall = np.concatenate([wall, wall[:, :1]], axis=1)

	# φ=0 での第一壁と背面の輪郭。この 2 本の間隙がブランケットで、流路はその中を通る。
	theta_line = np.linspace(0, math.tau, 200)
	sections = [surface_points(surface, np.zeros_like(theta_line), theta_line, s)[0] for s in (s_first_wall, s_back)]

	# 磁力線の矢印は外周側 (θ=0) に数本だけ立てる。全点に生やすと面が見えなくなる。
	arrow_phi = np.linspace(0, math.tau, 10, endpoint=False)
	arrow_at, arrow_normal = surface_points(surface, arrow_phi, np.zeros_like(arrow_phi), s_first_wall)
	arrow_dir = field_direction(arrow_at, arrow_normal)

	norm = plt.Normalize(0.0, 1.0)
	cmap = plt.get_cmap("coolwarm")  # 青=磁場平行で有利、赤=直交で不利
	out.parent.mkdir(parents=True, exist_ok=True)
	summary = []

	for name, (n_phi, n_theta), count in directions:
		# 巻き数が 0 でない側に沿って流路を並べる。ポロイダル流路なら φ 方向に等間隔。
		start = np.linspace(0, math.tau, count, endpoint=False)
		phi0, theta0 = (start, np.zeros(count)) if n_phi == 0 else (np.zeros(count), start)

		t = np.linspace(0, 1, div_path)
		traced = [surface_points(surface, p + math.tau * n_phi * t, q + math.tau * n_theta * t, s_channel) for p, q in zip(phi0, theta0)]
		channels = [points for points, _ in traced]
		perp = [perp_fraction(points, normals) for points, normals in traced]
		mean_perp2 = float(np.mean([np.mean(p**2) for p in perp]))

		fig = plt.figure(figsize=(11, 6))
		ax = fig.add_subplot(projection="3d")
		ax.plot_surface(
			wall[..., 0], wall[..., 1], wall[..., 2],
			color="#b8bec7", alpha=0.22, rstride=2, cstride=2,
			linewidth=0, antialiased=False, shade=True,
		)
		for section, style in zip(sections, ("-", "--")):
			ax.plot(section[:, 0], section[:, 1], section[:, 2], style, color="#2b2b2b", linewidth=1.0)
		ax.quiver(
			arrow_at[:, 0], arrow_at[:, 1], arrow_at[:, 2],
			arrow_dir[:, 0], arrow_dir[:, 1], arrow_dir[:, 2],
			length=2.0, color="#3d3d3d", linewidth=0.8, arrow_length_ratio=0.3,
		)

		for channel, value in zip(channels, perp):
			segments = np.stack([channel[:-1], channel[1:]], axis=1)
			collection = Line3DCollection(segments, cmap=cmap, norm=norm, linewidth=2.6)
			collection.set_array(0.5 * (value[:-1] + value[1:]))
			ax.add_collection3d(collection)
		# 入口を点で置く。流路が閉ループに見えるのを避けるための目印で、実際の給排水系は W2 の外。
		inlets = np.array([c[0] for c in channels])
		ax.scatter(inlets[:, 0], inlets[:, 1], inlets[:, 2], s=18, color="#111111", depthshade=False)

		# トーラスは扁平なので軸ごとの実寸比を保たないと形が嘘になる
		ax.set_box_aspect((np.ptp(wall[..., 0]), np.ptp(wall[..., 1]), np.ptp(wall[..., 2])), zoom=1.15)
		ax.set(xlabel="x [m]", ylabel="y [m]", zlabel="z [m]")
		ax.zaxis.set_major_locator(matplotlib.ticker.MaxNLocator(3))
		ax.view_init(elev=38, azim=-55)
		ax.grid(False)
		for pane in (ax.xaxis, ax.yaxis, ax.zaxis):
			pane.pane.set_alpha(0.0)
		# 図中の文字は ASCII に寄せる。matplotlib 既定の DejaVu Sans は日本語グリフを持たない。
		ax.set_title(
			f"blanket channels: {name} (n_phi={n_phi}, n_theta={n_theta}), {count} ducts\n"
			f"s={s_first_wall}-{s_back} shell, mean sin^2 = {mean_perp2:.2f}  (MHD dp proxy, higher is worse)"
		)
		fig.colorbar(
			plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax,
			orientation="horizontal", shrink=0.4, aspect=40, pad=0.06,
			label="sin angle(duct tangent, field line):  0 = along B, 1 = across B",
		)
		out_png = out.with_suffix(f".{name}.png")
		fig.savefig(out_png, dpi=150, bbox_inches="tight")
		plt.close(fig)
		summary.append((name, (n_phi, n_theta), count, mean_perp2, out_png))
		print(f"{out_png}: {count} 本 x {div_path} 点, mean sin^2 = {mean_perp2:.3f}")

	worst = max(row[3] for row in summary)

	# --- Markdown レポート。PDF 化は make al-05 が md2pdf.py (tectonic) で行う ------------
	# 相対パスは .md 自身からの解決なので、PNG と同じ out/ に置けばファイル名だけで貼れる。
	rows = "".join(f"| {name} | ({n_phi}, {n_theta}) | {count} | {value:.2f} | {value / worst:.2f} |\n" for name, (n_phi, n_theta), count, value, _ in summary)
	figures = "".join(
		f"![{name}: 巻き数 ({n_phi}, {n_theta})、{count} 本。平均 $\\sin^2$ = {value:.2f}]({png.name})\n\n"
		for name, (n_phi, n_theta), count, value, png in summary
	)
	report = f"""# ブランケット流路方向の比較 (al_05)

VMEC 平衡 `wout_vmec.nc` (nfp=4, R≈11 m) の磁気面 s={s_first_wall}〜{s_back} をブランケット殻とし、
その中を通る流路の向きを変えて MHD 圧損の代用指標を比べた。

## 方法

流路の向きを (φ, θ) 平面の巻き数 (n_phi, n_theta) ひとつで表す。φ を 1 周する間に θ が
何周するかであり、(0, 1) が純ポロイダル、(1, 0) が純トロイダルになる。各流路上で接線と
磁力線の成す角を取り、その $\\sin^2$ の平均を指標とした。MHD 圧損は流れに直交する磁場成分の
2 乗で効くので、この値が大きいほど不利である。

磁力線は e_φ を磁気面の接平面に射影して代用した。B が磁気面に接する事実は満たすが、
iota が python 側に出ていないためポロイダル成分は入っていない。

## 結果

| 方向 | (n_phi, n_theta) | 本数 | 平均 $\\sin^2$ | poloidal 比 |
|:--|:-:|--:|--:|--:|
{rows}
ポロイダル流路は全長にわたり磁力線と直交し、指標は 1.00 で頭打ちになる。一方トロイダル流路は
0 にならない。ステラレータでは φ を進むと断面形状そのものが捻れるため、θ 一定のダクトは
磁力線と平行にならないからである。

## 図

{figures}"""
	out.write_text(report, encoding="utf-8")
	print(f"\n{out}: {out.stat().st_size} bytes")


def unit(vectors: np.ndarray) -> np.ndarray:
	return vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)


def surface_points(surface: SurfaceFourierRZ, phi: np.ndarray, theta: np.ndarray, s: float) -> tuple[np.ndarray, np.ndarray]:
	"""同じ shape の (φ, θ) 配列を点と法線にする。末尾に xyz の軸が増える。"""
	points = np.empty(np.shape(phi) + (3,))
	normals = np.empty_like(points)
	for index in np.ndindex(np.shape(phi)):
		points[index], normals[index] = surface.point_normal(float(phi[index]), float(theta[index]), s, True)
	return points, normals


def field_direction(points: np.ndarray, normals: np.ndarray) -> np.ndarray:
	"""磁力線方向の代用。B は磁気面に接するので e_phi を接平面に落とす。iota は未使用。"""
	e_phi = np.stack([-points[..., 1], points[..., 0], np.zeros(points.shape[:-1])], axis=-1)
	normal = unit(normals)
	return unit(e_phi - (e_phi * normal).sum(axis=-1, keepdims=True) * normal)


def perp_fraction(points: np.ndarray, normals: np.ndarray) -> np.ndarray:
	"""流路接線と磁力線の成す角の sin。0 で磁場平行、1 で直交。"""
	tangent = unit(np.gradient(points, axis=0))
	field = field_direction(points, normals)
	return np.linalg.norm(tangent - (tangent * field).sum(axis=-1, keepdims=True) * field, axis=-1)


if __name__ == "__main__":
	main()
