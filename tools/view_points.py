"""指定ディレクトリ下の *.csv をすべて 3D 散布で重ね表示する viewer。

Usage:
	uv run tools/view_points.py ./out
	uv run tools/view_points.py ./out --view 135,30,
	uv run tools/view_points.py ./out --output out/view.png
	VIEW=135,30, OUTPUT=out/view.png uv run tools/view_points.py ./out

各 CSV は (x, y, z) の点群として読み込まれ、ファイルごとに別色で scatter される。
header 有無は先頭行が数値パースできるかで自動判定し、常に末尾 3 列を x,y,z として扱う。
"""
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401


def load_xyz(path: Path) -> np.ndarray:
	with path.open() as f:
		first = next(csv.reader(f))
	try:
		[float(v) for v in first]
		has_header = False
	except ValueError:
		has_header = True
	df = pd.read_csv(path, header=0 if has_header else None)
	return df.iloc[:, -3:].to_numpy(dtype=float)


def parse_view(spec: str) -> dict[str, float]:
	"""`"azim,elev,roll"` 形式をパースして view_init kwargs を返す。

	- カンマ区切りで最大 3 項目: azim, elev, roll の順。
	- 各スロットは省略可 (空文字) で、その軸は matplotlib 既定値を使う。
	- 例: `"135,30,"` → azim=135, elev=30 (roll は既定)。
	"""
	parts = [p.strip() for p in spec.split(",")]
	keys = ["azim", "elev", "roll"]
	out: dict[str, float] = {}
	for key, raw in zip(keys, parts):
		if raw:
			out[key] = float(raw)
	return out


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("directory", type=Path, help="*.csv を含むディレクトリ")
	ap.add_argument(
		"--view", "-v",
		default=os.environ.get("VIEW"),
		help='初期視点 "azim,elev,roll" (空スロット省略可、例: "135,30,")。'
		'未指定なら環境変数 VIEW を使用。',
	)
	ap.add_argument(
		"--output", "-o",
		type=Path,
		default=(Path(os.environ["OUTPUT"]) if os.environ.get("OUTPUT") else None),
		help='指定すればヘッドレスで PNG 等に保存 (plt.show は呼ばない)。'
		'未指定なら環境変数 OUTPUT を使用。',
	)
	ap.add_argument("--point-size", type=float, default=1.0)
	args = ap.parse_args()

	paths = sorted(args.directory.glob("*.csv"))
	if not paths:
		raise SystemExit(f"no *.csv under {args.directory}")

	if args.output is not None:
		matplotlib.use("Agg", force=True)

	fig = plt.figure(figsize=(10, 8))
	ax = fig.add_subplot(111, projection="3d")
	cmap = plt.get_cmap("tab10")

	all_pts = []
	for i, p in enumerate(paths):
		xyz = load_xyz(p)
		print(f"  {p.name}: {len(xyz)} points")
		ax.scatter(
			xyz[:, 0], xyz[:, 1], xyz[:, 2],
			s=args.point_size, color=cmap(i % 10), label=p.name,
		)
		all_pts.append(xyz)

	merged = np.concatenate(all_pts, axis=0)
	mn, mx = merged.min(axis=0), merged.max(axis=0)
	span = float((mx - mn).max())
	mid = (mx + mn) / 2
	ax.set_xlim(mid[0] - span / 2, mid[0] + span / 2)
	ax.set_ylim(mid[1] - span / 2, mid[1] + span / 2)
	ax.set_zlim(mid[2] - span / 2, mid[2] + span / 2)
	ax.set_xlabel("X")
	ax.set_ylabel("Y")
	ax.set_zlabel("Z")
	ax.legend(loc="upper right", fontsize="small")

	if args.view:
		ax.view_init(**parse_view(args.view))

	if args.output is not None:
		args.output.parent.mkdir(parents=True, exist_ok=True)
		plt.savefig(args.output, dpi=120)
		print(f"wrote {args.output}")
	else:
		plt.show()


if __name__ == "__main__":
	main()
