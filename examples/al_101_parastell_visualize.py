import pathlib

from alphastell import Geometry


def main(
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".png").name,
	stem: str = "al_10_parastell_cad_to_dagmc_example",  # al_10 が層ごとに書く STEP の接頭辞。make al-10 の後に走らせる
	layers: list[str] = ["chamber", "first_wall", "breeder", "back_wall", "shield", "vacuum_vessel", "magnets"],
) -> None:
	out.parent.mkdir(parents=True, exist_ok=True)
	geometry = None
	for layer in layers:
		step = out.parent / f"{stem}.{layer}.step"
		with open(step, "rb") as f:
			solids = Geometry.read_step(f)
		print(f"{step.name}: {len(solids)} solids, volume {sum(solids.volume()) * 1e-6:.3f} m^3")
		geometry = solids if geometry is None else geometry.concat(solids)
	# 90° 扇形の切断面で層が露出するので、ブーリアンせず重ねるだけで断面構造が見える
	with open(out, "wb") as f:
		geometry.write_png(f)
	print(f"{out}: {len(geometry)} solids, {out.stat().st_size} bytes")


if __name__ == "__main__":
	main()
