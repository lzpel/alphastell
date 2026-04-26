import "@typespec/http";
import "@typespec/openapi";
import "@typespec/openapi3";

using Http;
using OpenAPI;

/**
 * HTTP facade over the alphastell vessel/magnet subcommands. Upload a VMEC
 * NetCDF or MAKEGRID coils file and receive the generated STEP + CSV
 * artifacts as a list of base64-encoded files.
 */
@service(#{ title: "alphastell API" })
@info(#{ version: "0.1.0" })
@server("/", "Default server")
namespace AlphastellApi;

model FileEntry {
	/** Output filename, e.g. `chamber.step` or `magnet_set.csv`. */
	filename: string;

	/** MIME type hint for the payload (e.g. `model/step`, `text/csv`). */
	content_type: string;

	/** Base64-encoded file contents. */
	@encode("base64")
	data: bytes;
}

@error
model Error {
	message: string;
}

@doc("Generated in-vessel artifacts (6 STEP + 6 CSV).")
model OkResponse {
	@statusCode statusCode: 200;
	@body body: FileEntry[];
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
 * and returns 12 artifacts: 6 STEP solids (chamber, first_wall, breeder,
 * back_wall, shield, vacuum_vessel) and their corresponding CSV point
 * clouds.
 */
@summary("Generate in-vessel components from a VMEC NetCDF file")
@operationId("uploadVmec")
@route("/vessel")
@post
op uploadVmec(
	/** Reference flux surface. Parastell default 1.08 (just outside the LCFS). */
	@query wall_s?: float64 = 1.08,

	/** Unit scaling factor. VMEC is in meters; 100 converts to centimeters to match the parastell default. */
	@query scale?: float64 = 100.0,

	body: bytes,
): OkResponse | BadRequestResponse | ServerErrorResponse;

/**
 * Equivalent to the `magnet` subcommand. Accepts a MAKEGRID-format coils
 * file (e.g. `coils.example`) and returns 2 artifacts: a STEP of the swept
 * rectangular-section coils and its CSV point cloud.
 */
@summary("Generate a magnet_set STEP from a MAKEGRID coils file")
@operationId("uploadCoils")
@route("/magnet")
@post
op uploadCoils(
	/** Rectangular cross-section width [m]. Default 0.4 m matches parastell. */
	@query width?: float64 = 0.4,

	/** Rectangular cross-section thickness [m]. Default 0.5 m matches parastell. */
	@query thickness?: float64 = 0.5,

	/** Toroidal extent [deg]. 360 keeps all coils; values below 360 are reserved for future use. */
	@query toroidal_extent?: float64 = 360.0,

	body: bytes,
): OkResponse | BadRequestResponse | ServerErrorResponse;
