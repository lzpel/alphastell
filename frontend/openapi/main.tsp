import "@typespec/http";
import "@typespec/openapi";
import "@typespec/openapi3";

using Http;
using OpenAPI;

/**
 * HTTP facade over the alphastell vessel/magnet subcommands. Upload a VMEC
 * NetCDF or MAKEGRID coils file and receive a tar archive containing the
 * generated STEP + STL + CSV artifacts (one set per layer/coil group).
 */
@service(#{ title: "alphastell API" })
@info(#{ version: "0.1.0" })
@server("/", "Default server")
namespace AlphastellApi;

@error
model Error {
	message: string;
}

@doc("Tar archive containing all generated artifacts (`<name>.{step,stl,csv}` per layer or coil group).")
model OkResponse {
	@statusCode statusCode: 200;
	@header contentType: "application/x-tar";
	@body body: bytes;
}

@doc("Invalid input file or parameters.")
model BadRequestResponse {
	@statusCode statusCode: 400;
	@body body: Error;
}

@doc("Processing failure.")
model ServerErrorResponse {
	@statusCode statusCode: 500;
	@body body: Error;
}

/**
 * Equivalent to the `vessel` subcommand. Accepts a VMEC `wout_*.nc` file
 * and returns a tar archive containing 18 entries: the 6 in-vessel layers
 * (chamber, first_wall, breeder, back_wall, shield, vacuum_vessel) each as
 * `<layer>.step` + `<layer>.stl` + `<layer>.csv`.
 */
@summary("Generate in-vessel components from a VMEC NetCDF file")
@operationId("vessel")
@route("/vessel")
@post
op vessel(
	/** Reference flux surface. Parastell default 1.08 (just outside the LCFS). */
	@query wall_s?: float64 = 1.08,

	/** Unit scaling factor. VMEC is in meters; 100 converts to centimeters to match the parastell default. */
	@query scale?: float64 = 100.0,

	body: bytes,
): OkResponse | BadRequestResponse | ServerErrorResponse;

/**
 * Equivalent to the `magnet` subcommand. Accepts a MAKEGRID-format coils
 * file (e.g. `coils.example`) and returns a tar archive containing
 * `magnet_set.step` + `magnet_set.stl` + `magnet_set.csv`.
 */
@summary("Generate a magnet_set STEP from a MAKEGRID coils file")
@operationId("magnet")
@route("/magnet")
@post
op magnet(
	/** Rectangular cross-section width [m]. Default 0.4 m matches parastell. */
	@query width?: float64 = 0.4,

	/** Rectangular cross-section thickness [m]. Default 0.5 m matches parastell. */
	@query thickness?: float64 = 0.5,

	/** Toroidal extent [deg]. 360 keeps all coils; values below 360 are reserved for future use. */
	@query toroidal_extent?: float64 = 360.0,

	body: bytes,
): OkResponse | BadRequestResponse | ServerErrorResponse;
