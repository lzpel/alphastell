use cadrum::{DVec3, Solid};
use std::fs;

fn sandbox_cad(homogenized: bool, vv_inner: bool, breeder_only: bool) -> Vec<Solid> {
	let depth = 2.0; // 断面図なので z は薄板にし、multiview の +Z パネルだけを図として読む
	let duct = 25.0; // ARIES-CS 2006 p.3 の増殖ゾーン
	let wall = 1.5; // 同 FS/He 隔壁
	let fci = 0.5; // 同 SiC insert
	let pitch = duct + wall;
	let cells = 2usize; // トロイダル 2 周期
	let span = pitch * cells as f64;

	let mut solids: Vec<Solid> = Vec::new();
	let mut x = 0.0;
	let stack = |solids: &mut Vec<Solid>, x: &mut f64, thickness: f64, color: &str| {
		solids.push(Solid::cube(DVec3::new(*x, 0.0, 0.0), DVec3::new(*x + thickness, span, depth)).color(color));
		*x += thickness;
	};

	if !breeder_only {
		stack(&mut solids, &mut x, 5.0, "#6e7176");
	}
	if homogenized {
		stack(&mut solids, &mut x, span, "#59a869");
	} else {
		let base = x;
		let (mut lipb, mut sic) = (0.0, 0.0);
		for i in 0..cells {
			let cell = base + i as f64 * pitch;
			solids.push(Solid::cube(DVec3::new(cell, 0.0, 0.0), DVec3::new(cell + wall, span, depth)).color("#8b5a2b")); // 隔壁はセルの低い側だけに置くと重なりなく敷き詰まる
			for j in 0..cells {
				let (x0, y0) = (cell + wall, j as f64 * pitch + wall);
				solids.push(Solid::cube(DVec3::new(x0, y0 - wall, 0.0), DVec3::new(x0 + duct, y0, depth)).color("#8b5a2b"));
				let duct_box = Solid::cube(DVec3::new(x0, y0, 0.0), DVec3::new(x0 + duct, y0 + duct, depth));
				let center = DVec3::new(x0 + duct / 2.0, y0 + duct / 2.0, depth / 2.0);
				let open: Vec<&cadrum::Face> = duct_box.iter_face().filter(|f| f.project(center).1.z.abs() > 0.5).collect(); // z は断面の切り口なので内張りしない
				let shell = duct_box.shell(-fci, open).expect("FCI shell");
				let core = Solid::cube(DVec3::new(x0 + fci, y0 + fci, 0.0), DVec3::new(x0 + duct - fci, y0 + duct - fci, depth));
				sic += shell.volume().abs();
				lipb += core.volume().abs();
				solids.push(shell.color("#e8d44d"));
				solids.push(core.color("#59a869"));
			}
		}
		let total = span * span * depth;
		println!("  breeder vol%: LiPb {:.1} / SiC {:.1} / FS+He {:.1}", 100.0 * lipb / total, 100.0 * sic / total, 100.0 * (total - lipb - sic) / total);
		x = base + span;
	}
	if breeder_only {
		return solids; // FCI 0.5 cm は径方向ビルド全体の倍率では線幅に潰れるので、増殖層だけの拡大図を別に出す
	}
	stack(&mut solids, &mut x, 5.0, "#c08457");
	if vv_inner {
		stack(&mut solids, &mut x, 50.0, "#4a4e69"); // ParaStell / ARIES-CS は遮蔽が VV の内側
		stack(&mut solids, &mut x, 10.0, "#b0b7bd");
	} else {
		stack(&mut solids, &mut x, 20.0, "#6a6f8c"); // ARIES-ACT2 は構造リング / VV / LT 遮蔽の順
		stack(&mut solids, &mut x, 10.0, "#b0b7bd");
		stack(&mut solids, &mut x, 32.0, "#3a3e59");
	}
	stack(&mut solids, &mut x, 50.0, "#e08a2e");
	solids
}

fn main() -> Result<(), cadrum::Error> {
	fs::create_dir_all("out").unwrap();
	let write = |name: String, solids: Vec<Solid>| -> Result<(), cadrum::Error> {
		println!("{name}");
		Solid::mesh(&solids, Default::default())?.write_multiview_png(&mut fs::File::create(&name).unwrap())
	};
	for homogenized in [true, false] {
		for vv_inner in [true, false] {
			let name = format!(
				"out/sandbox_cad.{}_{}.png",
				if homogenized { "homogenized" } else { "heterogeneous" },
				if vv_inner { "vv_inner" } else { "vv_outer" }
			);
			write(name, sandbox_cad(homogenized, vv_inner, false))?;
		}
	}
	write("out/sandbox_cad.heterogeneous_breeder.png".to_string(), sandbox_cad(false, true, true))?;
	Ok(())
}
