'use client';

import { NetCDFReader } from 'netcdfjs';

/**
 * VMEC `wout_*.nc` から `vessel::run` が必要とする 4 変数 (`xm`, `xn`,
 * `rmnc`, `zmns`) だけを抜き出して、最小構成の NetCDF3 Classic ファイルを
 * Blob として返す。
 *
 * 元のファイルは ~8MB あるが浮動小数バイナリで gzip がほぼ効かない。本当に
 * 計算で使う変数だけ残せば 600KB 級まで縮み、Lambda 同期 invoke の 6MB
 * 制限を余裕で下回れる。サーバ側 (`crate::vmec::VmecData::load`) は
 * 同じ NetCDF パーサで読めるので変更不要。
 *
 * 結果は **完全に lossless**: 4 変数のバイト列は元ファイルと同一なので、
 * vessel の出力 STEP / GLB はバイト一致する。
 */
export async function slimVmec(file: File): Promise<Blob> {
	const buf = await file.arrayBuffer();
	const reader = new NetCDFReader(new Uint8Array(buf));

	// netcdfjs の getDataVariable は型 `(string|number|number[])[]` を返す
	// (異種配列の総和型)。VMEC の 4 変数は数値の 1D / 2D なので number[] と
	// 見なして Float64Array に正規化。
	const toF64 = (v: unknown) => new Float64Array(v as ArrayLike<number>);
	const xm = toF64(reader.getDataVariable('xm'));
	const xn = toF64(reader.getDataVariable('xn'));
	const rmnc = toF64(reader.getDataVariable('rmnc'));
	const zmns = toF64(reader.getDataVariable('zmns'));
	const mnmax = xm.length;
	const ns = rmnc.length / mnmax;

	if (zmns.length !== ns * mnmax || xn.length !== mnmax) {
		throw new Error(
			`vmec slim: shape mismatch (ns=${ns} mnmax=${mnmax}, ` +
			`xm=${xm.length} xn=${xn.length} rmnc=${rmnc.length} zmns=${zmns.length})`,
		);
	}

	return new Blob([encodeVmecSlim(ns, mnmax, xm, xn, rmnc, zmns)]);
}

// ============================================================
// NetCDF3 Classic encoder (4 fixed f64 variables, no global attrs)
// ============================================================
//
// File layout (big-endian, 4-byte aligned):
//   magic "CDF\x01" + numrecs(=0)
//   dim_list:   tag=NC_DIMENSION(10) + count(2) + 2 dims
//   gatt_list:  NC_ABSENT (8 zero bytes)
//   var_list:   tag=NC_VARIABLE(11) + count(4) + 4 vars
//   var data:   xm | xn | rmnc | zmns  (each 8-byte aligned natively)
//
// 各 var の `begin` (32-bit absolute file offset) はヘッダ末尾より後ろの
// データ領域を指す。f64 (NC_DOUBLE) の vsize はバイト数を 4 で繰り上げ。

const NC_DIMENSION = 10;
const NC_VARIABLE = 11;
const NC_DOUBLE = 6;

/** 4-byte 整列の合計ヘッダサイズを変数 / 次元名から事前計算する。 */
function computeHeaderSize(): number {
	// magic(4) + numrecs(4) = 8
	// dim_list: tag(4) + count(4) = 8
	// 2 dims, name="radius"(6→8) + len(4) = 16, name="mn_mode"(7→8) + len(4) = 16
	// gatt_list: NC_ABSENT(8)
	// var_list: tag(4) + count(4) = 8
	// 4 vars: xm/xn (1 dim each) と rmnc/zmns (2 dims each)
	//   xm/xn each:  nameLen(4)+name(2→4)=8 + numDims(4)+dimIds(4)=8 + vatt(8) + type(4)+vsize(4)+begin(4) = 36
	//   rmnc/zmns:   nameLen(4)+name(4→4)=8 + numDims(4)+dimIds(8)=12 + vatt(8) + type(4)+vsize(4)+begin(4) = 40
	return 8 + 8 + 16 + 16 + 8 + 8 + 36 + 36 + 40 + 40;
}

function encodeVmecSlim(
	ns: number,
	mnmax: number,
	xm: Float64Array,
	xn: Float64Array,
	rmnc: Float64Array,
	zmns: Float64Array,
): ArrayBuffer {
	const headerSize = computeHeaderSize();
	const xmBegin = headerSize;
	const xnBegin = xmBegin + xm.byteLength;
	const rmncBegin = xnBegin + xn.byteLength;
	const zmnsBegin = rmncBegin + rmnc.byteLength;
	const total = zmnsBegin + zmns.byteLength;

	const out = new ArrayBuffer(total);
	const view = new DataView(out);
	let p = 0;
	const u32 = (v: number) => {
		view.setUint32(p, v, false);
		p += 4;
	};
	const enc = new TextEncoder();
	const writeName = (s: string) => {
		const bytes = enc.encode(s);
		u32(bytes.length);
		new Uint8Array(out, p).set(bytes);
		p += bytes.length;
		const pad = (4 - (bytes.length % 4)) % 4;
		p += pad;
	};
	const writeF64BE = (arr: Float64Array, beginOffset: number) => {
		const dv = new DataView(out, beginOffset, arr.byteLength);
		for (let i = 0; i < arr.length; i++) dv.setFloat64(i * 8, arr[i], false);
	};

	// magic "CDF\x01"
	new Uint8Array(out, 0, 4).set([0x43, 0x44, 0x46, 0x01]);
	p = 4;
	u32(0); // numrecs

	// dim_list
	u32(NC_DIMENSION);
	u32(2);
	writeName('radius');
	u32(ns);
	writeName('mn_mode');
	u32(mnmax);

	// gatt_list = NC_ABSENT
	u32(0);
	u32(0);

	// var_list
	u32(NC_VARIABLE);
	u32(4);

	// var "xm" (1D over mn_mode = dim 1)
	const writeVar = (
		name: string,
		dimIds: number[],
		vsize: number,
		begin: number,
	) => {
		writeName(name);
		u32(dimIds.length);
		for (const d of dimIds) u32(d);
		u32(0); // vatt_list NC_ABSENT
		u32(0);
		u32(NC_DOUBLE);
		u32(vsize);
		u32(begin);
	};
	const pad4 = (n: number) => n + ((4 - (n % 4)) % 4);
	writeVar('xm', [1], pad4(xm.byteLength), xmBegin);
	writeVar('xn', [1], pad4(xn.byteLength), xnBegin);
	writeVar('rmnc', [0, 1], pad4(rmnc.byteLength), rmncBegin);
	writeVar('zmns', [0, 1], pad4(zmns.byteLength), zmnsBegin);

	if (p !== headerSize) {
		throw new Error(`vmec slim: header size mismatch (wrote ${p}, expected ${headerSize})`);
	}

	// data region (big-endian f64)
	writeF64BE(xm, xmBegin);
	writeF64BE(xn, xnBegin);
	writeF64BE(rmnc, rmncBegin);
	writeF64BE(zmns, zmnsBegin);

	return out;
}
