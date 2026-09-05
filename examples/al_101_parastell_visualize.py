import math
import pathlib

from alphastell import Geometry


def main(
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".md").name,
	# 層名 (stem の末尾) → 色。Release previous_steps の parastell 全構造プレビューと同じ割り当て
	colors: dict[str, str] = {
		"chamber": "#9ec9de",  # 真空
		"first_wall": "#6e7176",  # タングステン
		"breeder": "#59a869",  # 増殖材
		"back_wall": "#c08457",  # EUROFER
		"shield": "#4a4e69",  # 炭化タングステン
		"vacuum_vessel": "#b0b7bd",  # SS316
		"magnets": "#e08a2e",  # コイル
	},
	rotate_z: float = math.pi,  # 扇形 (第 1 象限) を回して、切断面が 4 面図のカメラに向くようにする [rad]
) -> None:
	rows, figures, combined = [], [], None
	for step in sorted(out.parent.glob("*parastell*.step")):
		color = colors.get(step.stem.rsplit(".", 1)[-1], "gray")
		with open(step, "rb") as f:
			geometry = Geometry.read_step(f).color(color).rotate(rad_z=rotate_z)
		png = step.with_suffix(".png")
		with open(png, "wb") as f:
			geometry.write_png(f)
		rows.append(f"| {step.name} | {color} | {len(geometry)} | {sum(geometry.volume()) * 1e-6:.3f} | {png.stat().st_size} |")
		figures.append(f"![{png.name}]({png.name})")
		combined = geometry if combined is None else combined.concat(geometry)
	# 全層を重ねた 1 枚。扇形の切断面で層が露出するので、色で層が読める
	with open(out.with_suffix(".png"), "wb") as f:
		combined.write_png(f)
	fields = {"rows": "\n".join(rows), "figures": "\n\n".join(figures), "combined_png": out.with_suffix(".png").name}
	out.write_text(TEMPLATE.format(**fields), encoding="utf-8")
	print(f"{out}: {len(rows)} step files, {out.stat().st_size} bytes")


TEMPLATE = """# ParaStell 形状の 4 面図 (al_101)

al_10 が層ごとに書いた STEP を alphastell の `Geometry.read_step` で読み、層ごとに色を付けて cadrum の 4 面図に描く。
90° 扇形の切断面で層が露出するので、重ねた 1 枚でも断面構造が色で読める。
体積は cadrum が STEP から測った値で、al_10 が cadquery で測った値との突き合わせになる。

![全層を重ねた 4 面図]({combined_png})

| STEP | 色 | ソリッド数 | 体積 [m³/扇形] | png [bytes] |
|:--|:--|--:|--:|--:|
{rows}

{figures}
"""

if __name__ == "__main__":
	main()
