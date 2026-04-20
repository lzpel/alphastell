NETCDF_DIR ?= $(HOME)/miniforge3/envs/parastell_env
HDF5_DIR   ?= $(NETCDF_DIR)
export NETCDF_DIR HDF5_DIR

VMEC_IN  := parastell/examples/wout_vmec.nc
RUST_OUT := out/plasma.step
PARA_OUT := parastell/examples/alphastell_full/plasma.step

# LD_LIBRARY_PATH は recipe 内で親 env を継承してから prepend する
RUN := LD_LIBRARY_PATH=$(NETCDF_DIR)/lib:$$LD_LIBRARY_PATH cargo run --release --

.PHONY: run generate validate

run: generate validate

generate:
	$(RUN) generate --input $(VMEC_IN) --output $(RUST_OUT)

validate:
	$(RUN) validate --union $(RUST_OUT) $(PARA_OUT)
