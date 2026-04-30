'use client';

import { useState } from 'react';
import { parseTar } from 'nanotar';
import { magnet, vessel } from '@/client/sdk.gen';
import { client } from '@/client/client.gen';

// rebab で /api → cargo run -- server に proxy される前提。
// 直接 :8080 を叩く場合は NEXT_PUBLIC_API_BASE で上書き。
client.setConfig({ baseUrl: process.env.NEXT_PUBLIC_API_BASE ?? '/api' });

type Entry = { name: string; url: string; size: number };

async function fileToBase64(file: File): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onerror = () => reject(reader.error);
		reader.onload = () => {
			const result = reader.result as string;
			const idx = result.indexOf(',');
			resolve(result.slice(idx + 1));
		};
		reader.readAsDataURL(file);
	});
}

function tarToEntries(buf: ArrayBuffer): Entry[] {
	return parseTar(buf)
		.filter((e) => e.data && e.data.byteLength > 0)
		.map((e) => ({
			name: e.name,
			url: URL.createObjectURL(new Blob([new Uint8Array(e.data!)])),
			size: e.size,
		}));
}

type DownloadListProps = {
	entries: Entry[];
};

export function DownloadList(props: DownloadListProps) {
	return (
		<ul>
			{props.entries.map((e) => (
				<li key={e.name}>
					<a href={e.url} download={e.name}>
						{e.name}
					</a>{' '}
					({e.size} bytes)
				</li>
			))}
		</ul>
	);
}

export default function Home() {
	const [vesselFile, setVesselFile] = useState<File | null>(null);
	const [vesselUploading, setVesselUploading] = useState(false);
	const [vesselEntries, setVesselEntries] = useState<Entry[]>([]);
	const [vesselStatus, setVesselStatus] = useState<string>('');

	const [magnetFile, setMagnetFile] = useState<File | null>(null);
	const [magnetUploading, setMagnetUploading] = useState(false);
	const [magnetEntries, setMagnetEntries] = useState<Entry[]>([]);
	const [magnetStatus, setMagnetStatus] = useState<string>('');

	async function uploadVessel(f: File) {
		setVesselEntries([]);
		setVesselUploading(true);
		setVesselStatus(`uploading ${f.name} (${f.size.toLocaleString()} bytes)...`);
		try {
			const b64 = await fileToBase64(f);
			const res = await vessel({ body: { body: b64 }, parseAs: 'blob' });
			const blob = res.data as Blob;
			const buf = await blob.arrayBuffer();
			const entries = tarToEntries(buf);
			setVesselEntries(entries);
			setVesselStatus(`done: ${entries.length} files`);
		} catch (err) {
			setVesselStatus(`error: ${err instanceof Error ? err.message : String(err)}`);
		} finally {
			setVesselUploading(false);
		}
	}

	async function uploadMagnet(f: File) {
		setMagnetEntries([]);
		setMagnetUploading(true);
		setMagnetStatus(`uploading ${f.name} (${f.size.toLocaleString()} bytes)...`);
		try {
			const b64 = await fileToBase64(f);
			const res = await magnet({ body: { body: b64 }, parseAs: 'blob' });
			const blob = res.data as Blob;
			const buf = await blob.arrayBuffer();
			const entries = tarToEntries(buf);
			setMagnetEntries(entries);
			setMagnetStatus(`done: ${entries.length} files`);
		} catch (err) {
			setMagnetStatus(`error: ${err instanceof Error ? err.message : String(err)}`);
		} finally {
			setMagnetUploading(false);
		}
	}

	return (
		<main>
			<h1>alphastell</h1>

			<section>
				<h2>vessel — VMEC NetCDF (wout_*.nc) → 6 layers × {`{step,stl,csv}`}</h2>
				<input
					type="file"
					accept=".nc"
					onChange={(e) => setVesselFile(e.target.files?.[0] ?? null)}
				/>
				<br />
				<button
					type="button"
					disabled={!vesselFile || vesselUploading}
					onClick={() => vesselFile && uploadVessel(vesselFile)}
				>
					{vesselUploading ? 'uploading…' : 'upload'}
				</button>
				<p>{vesselStatus}</p>
				<DownloadList entries={vesselEntries} />
			</section>

			<section>
				<h2>magnet — MAKEGRID coils → magnet_set.{`{step,stl,csv}`}</h2>
				<input
					type="file"
					onChange={(e) => setMagnetFile(e.target.files?.[0] ?? null)}
				/>
				<br />
				<button
					type="button"
					disabled={!magnetFile || magnetUploading}
					onClick={() => magnetFile && uploadMagnet(magnetFile)}
				>
					{magnetUploading ? 'uploading…' : 'upload'}
				</button>
				<p>{magnetStatus}</p>
				<DownloadList entries={magnetEntries} />
			</section>
		</main>
	);
}
