NETCDF_DIR ?= $(HOME)/miniforge3/envs/parastell_env
HDF5_DIR   ?= $(NETCDF_DIR)
export NETCDF_DIR HDF5_DIR

VMEC_IN  := parastell/examples/wout_vmec.nc
PARA_DIR := parastell/examples/alphastell_full
OUT_DIR  := out

# plasma (chamber, s=1.0, thickness=0)
PLASMA_OUT  := $(OUT_DIR)/plasma.step
PLASMA_REF  := $(PARA_DIR)/plasma.step

# first_wall (s=wall_s=1.08, thickness=5 cm)
FW_OUT      := $(OUT_DIR)/first_wall.step
FW_REF      := $(PARA_DIR)/first_wall.step
WALL_S      := 1.08
FW_THICK    := 5.0

# LD_LIBRARY_PATH は recipe 内で親 env を継承してから prepend する
RUN := LD_LIBRARY_PATH=$(NETCDF_DIR)/lib:$$LD_LIBRARY_PATH cargo run --release --

.PHONY: run generate validate first-wall first-wall-generate first-wall-validate

run: generate validate

generate:
	$(RUN) generate --input $(VMEC_IN) --output $(PLASMA_OUT)

validate:
	$(RUN) validate --union $(PLASMA_OUT) $(PLASMA_REF)

first-wall: first-wall-generate first-wall-validate

first-wall-generate:
	$(RUN) generate --input $(VMEC_IN) --output $(FW_OUT) --s $(WALL_S) --thickness $(FW_THICK)

first-wall-validate:
	# first_wall は s=1.08 外挿 + 法線定義差 (parastell=2D poloidal / cadrum=3D surface) で
	# 約 3% 程度のズレが仕様上出るため tolerance を 5% に緩める
	$(RUN) validate --tol 0.05 $(FW_OUT) $(FW_REF)
