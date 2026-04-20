CONDA     ?= $(HOME)/miniforge3/bin/conda
CONDA_ENV ?= parastell_env

define INFO
run-alphastell-fullcad-to-dagmc  <-  alphastell_fullcad_to_dagmc_example.py
  desc: cad_to_dagmc バックエンドで現行の全ジオメトリ機能を使い切るフルデモ (split_chamber / 2D thickness / casing / custom source)
  pipe: vmec(wout_vmec.nc)+coils.example+custom_plasma-[cadquery+casing]-step-[cad_to_dagmc]-dagmc(h5m)
  out : alphastell_full/{plasma,chamber,first_wall,breeder,back_wall,shield,vacuum_vessel,magnet_set}.step alphastell_full/{invessel_mesh_gmsh,invessel_mesh_moab,magnet_mesh_inner,magnet_mesh_outer,magnet_mesh_both,source_mesh,dagmc}.h5m

run-custom-first-wall-profile  <-  custom_first_wall_profile_example.py
  desc: Kisslinger 形式リブ座標からカスタム第一壁プロファイルを生成
  pipe: vmec(wout_vmec.nc)+kisslinger(FW profile)-[cadquery]-step-[cad_to_dagmc]-dagmc(h5m) / coils.example-[cadquery]-step-[cad_to_dagmc]-h5m
  out : first_wall.step breeder.step back_wall.step shield.step vacuum_vessel.step chamber.step magnets.step source_mesh.h5m dagmc.h5m

run-custom-source  <-  custom_source_example.py
  desc: ユーザー定義の反応率でカスタムプラズマ線源メッシュを生成
  pipe: vmec(wout_vmec.nc)-source_mesh(h5m)  (線源のみ / ジオメトリパイプライン無し)
  out : source_mesh.h5m

run-nwl-cubit  <-  nwl_cubit_example.py
  desc: Cubit ワークフローで中性子壁負荷 (NWL) を計算
  pipe: vmec(wout_vmec.nc)-[cadquery]-step-[cubit]-dagmc(h5m) / coils.example-[cadquery]-step-[cubit]-h5m -> [openmc]-nwl(png)
  out : *.step source_mesh.h5m nwl_geom.h5m surface_source.h5 nwl_mean.png nwl_std_dev.png

run-nwl-pydagmc  <-  nwl_pydagmc_example.py
  desc: PyDAGMC ワークフローで中性子壁負荷 (NWL) を計算
  pipe: vmec(wout_vmec.nc)-[pydagmc]-dagmc(h5m) / coils.example-[cadquery]-step-[cad_to_dagmc]-h5m -> [openmc]-nwl(png)
  out : source_mesh.h5m nwl_geom.h5m surface_source.h5 nwl_mean.png nwl_std_dev.png

run-parastell-cad-to-dagmc  <-  parastell_cad_to_dagmc_example.py
  desc: CAD→DAGMC 変換で滑らかなスプライン面のステラレータモデルを構築
  pipe: vmec(wout_vmec.nc)-[cadquery]-step-[cad_to_dagmc]-dagmc(h5m) / coils.example-[cadquery]-step-[cad_to_dagmc]-h5m
  out : *.step magnet_set.step magnet_mesh.h5m source_mesh.h5m dagmc.h5m

run-parastell-cubit  <-  parastell_cubit_example.py
  desc: Cubit ワークフローでステラレータモデルを構築
  pipe: vmec(wout_vmec.nc)-[cadquery]-step-[cubit]-dagmc(h5m) / coils.example-[cadquery]-step-[cubit]-h5m
  out : *.step magnet_set.step magnet_mesh.h5m source_mesh.h5m dagmc.h5m

run-parastell-pydagmc  <-  parastell_pydagmc_example.py
  desc: PyDAGMC で面化ステラレータモデルを構築 (複雑形状に強い)
  pipe: vmec(wout_vmec.nc)-[pydagmc]-dagmc(h5m) / coils.example-[cadquery]-step-[cad_to_dagmc]-h5m
  out : dagmc.h5m weight_window_mesh.h5m vacuum_vessel_tally_mesh.h5m

run-radial-distance  <-  radial_distance_example.py
  desc: プラズマ面とコイル間の放射状距離計算ユーティリティ
  pipe: vmec(wout_vmec.nc)-[cubit]-radial_distances / vmec+coils.example-[cadquery]-step-[cad_to_dagmc]-dagmc(h5m)
  out : *.step magnet_set.step source_mesh.h5m dagmc.h5m
endef
export INFO

TARGETS := $(filter run-%,$(INFO))

.PHONY: list run

list:
	@echo "Available targets (run-<name> <- <python file>):"
	@echo "$$INFO"

run-%:
	@echo "$$INFO" | awk -v t='run-$*' '$$1==t{f=1;print;next} /^run-/{f=0} f'
	@file=$$(echo "$$INFO" | awk -v t='run-$*' '$$1==t{print $$3}') && \
		cd examples && $(CONDA) run --no-capture-output -n $(CONDA_ENV) python $$file

run:
	@ok=""; ng=""; for t in $(TARGETS); do \
		if $(MAKE) --no-print-directory $$t; then \
			ok="$$ok $$t"; \
		else \
			ng="$$ng $$t"; \
		fi; \
	done; \
	echo ""; \
	echo "Summary"; \
	echo "  OK:$$ok"; \
	echo "  NG:$$ng"
