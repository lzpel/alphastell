'use client';

import { useState } from 'react';
import { parseTar } from 'nanotar';
import { magnet, vessel } from '@/client/sdk.gen';
import { client } from '@/client/client.gen';
import GlbViewer from './view';

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

/** 処理中インジケータ。CSS keyframes は styled-jsx で同梱。 */
export function Spinner() {
	return (
		<>
			<span className="spinner" aria-hidden="true" />
			<style jsx>{`
				.spinner {
					display: inline-block;
					width: 12px;
					height: 12px;
					margin-right: 6px;
					border: 2px solid #ccc;
					border-top-color: #333;
					border-radius: 50%;
					animation: spin 0.8s linear infinite;
					vertical-align: middle;
				}
				@keyframes spin {
					to {
						transform: rotate(360deg);
					}
				}
			`}</style>
		</>
	);
}

type DownloadListProps = {
	entries: Entry[];
	onView?: (entry: Entry) => void;
	activeUrl?: string | null;
};

export function DownloadList(props: DownloadListProps) {
	return (
		<ul>
			{props.entries.map((e) => {
				const isGlb = e.name.toLowerCase().endsWith('.glb');
				const isActive = props.activeUrl === e.url;
				return (
					<li key={e.name}>
						<a href={e.url} download={e.name}>
							{e.name}
						</a>{' '}
						({e.size} bytes)
						{isGlb && props.onView && (
							<>
								{' '}
								<button
									type="button"
									onClick={() => props.onView!(e)}
									disabled={isActive}
								>
									{isActive ? 'viewing' : 'view'}
								</button>
							</>
						)}
					</li>
				);
			})}
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

	// 現在ビュワーに表示している GLB の Blob URL (vessel/magnet 共通)。
	const [viewUrl, setViewUrl] = useState<string | null>(null);

	async function uploadVessel(f: File) {
		setVesselEntries([]);
		setVesselUploading(true);
		setVesselStatus(`uploading ${f.name} (${f.size.toLocaleString()} bytes)…`);
		try {
			const b64 = await fileToBase64(f);
			setVesselStatus('computing on server… (10-60s)');
			const res = await vessel({ body: { body: b64 }, parseAs: 'blob' });
			setVesselStatus('parsing response…');
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
		setMagnetStatus(`uploading ${f.name} (${f.size.toLocaleString()} bytes)…`);
		try {
			const b64 = await fileToBase64(f);
			setMagnetStatus('computing on server… (5-30s)');
			const res = await magnet({ body: { body: b64 }, parseAs: 'blob' });
			setMagnetStatus('parsing response…');
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
		<main style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
			<aside
				style={{
					width: 360,
					flexShrink: 0,
					padding: '16px',
					borderRight: '1px solid #ddd',
					overflowY: 'auto',
				}}
			>
				<h1 style={{ marginTop: 0 }}>alphastell</h1>

				<section>
					<h2>vessel</h2>
					<p style={{ fontSize: 12, color: '#666', margin: '4px 0' }}>
						VMEC NetCDF (wout_*.nc) → 6 layers × {`{step,glb,csv}`}
					</p>
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
						{vesselUploading ? (
							<>
								<Spinner />
								building…
							</>
						) : (
							'build vessel'
						)}
					</button>
					<p style={{ minHeight: '1.2em' }}>
						{vesselUploading && <Spinner />}
						{vesselStatus}
					</p>
					<DownloadList entries={vesselEntries} onView={(e) => setViewUrl(e.url)} activeUrl={viewUrl} />
				</section>

				<section>
					<h2>magnet</h2>
					<p style={{ fontSize: 12, color: '#666', margin: '4px 0' }}>
						MAKEGRID coils → magnet_set.{`{step,glb,csv}`}
					</p>
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
						{magnetUploading ? (
							<>
								<Spinner />
								building…
							</>
						) : (
							'build magnet'
						)}
					</button>
					<p style={{ minHeight: '1.2em' }}>
						{magnetUploading && <Spinner />}
						{magnetStatus}
					</p>
					<DownloadList entries={magnetEntries} onView={(e) => setViewUrl(e.url)} activeUrl={viewUrl} />
				</section>
			</aside>

			<div style={{ flex: 1, minWidth: 0, height: '100%' }}>
				<GlbViewer url={viewUrl} height="100%" />
			</div>
		</main>
	);
}
