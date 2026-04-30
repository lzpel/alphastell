'use client';

import { useRef, useState } from 'react';
import { parseTar } from 'nanotar';
import { magnet, vessel } from '@/client/sdk.gen';
import { client } from '@/client/client.gen';
import GlbViewer from './view';
import { DownloadList, Entry, SourceRow, Spinner } from './components';
import { slimVmec } from './vmec';

// rebab で /api → cargo run -- server に proxy される前提。
// 直接 :8080 を叩く場合は NEXT_PUBLIC_API_BASE で上書き。
client.setConfig({ baseUrl: process.env.NEXT_PUBLIC_API_BASE ?? '/api' });


function tarToEntries(buf: ArrayBuffer): Entry[] {
	return parseTar(buf)
		.filter((e) => e.data && e.data.byteLength > 0)
		.map((e) => ({
			name: e.name,
			url: URL.createObjectURL(new Blob([new Uint8Array(e.data!)])),
			size: e.size,
		}));
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

	// 非表示の GLB の Blob URL 群 (vessel/magnet 共通)。デフォルト空 = 全て表示。
	// チェックボックスを入れた層だけビュワーから除外する。
	const [hiddenUrls, setHiddenUrls] = useState<string[]>([]);
	const toggleHide = (e: Entry) => {
		setHiddenUrls((prev) =>
			prev.includes(e.url) ? prev.filter((u) => u !== e.url) : [...prev, e.url],
		);
	};

	// 全 .glb エントリから非表示分を引いた URL リストをビュワーに渡す。
	const visibleUrls = [...vesselEntries, ...magnetEntries]
		.filter((e) => e.name.toLowerCase().endsWith('.glb') && !hiddenUrls.includes(e.url))
		.map((e) => e.url);

	// プリセットファイル (frontend/public/) を fetch して `<input type="file">` に
	// 流し込む。input の `files` は通常 read-only だが、DataTransfer 経由で
	// プログラム的にセットできる (Chrome/Firefox/Safari いずれもサポート)。
	const vesselInputRef = useRef<HTMLInputElement>(null);
	const magnetInputRef = useRef<HTMLInputElement>(null);
	async function usePreset(url: string, filename: string, target: 'vessel' | 'magnet') {
		const res = await fetch(url);
		const blob = await res.blob();
		const file = new File([blob], filename, {
			type: blob.type || 'application/octet-stream',
		});
		const inputRef = target === 'vessel' ? vesselInputRef : magnetInputRef;
		if (inputRef.current) {
			const dt = new DataTransfer();
			dt.items.add(file);
			inputRef.current.files = dt.files;
		}
		if (target === 'vessel') setVesselFile(file);
		else setMagnetFile(file);
	}

	async function uploadVessel(f: File) {
		setVesselEntries([]);
		setVesselUploading(true);
		setVesselStatus(`extracting needed variables from ${f.name}…`);
		try {
			// 8MB 級の wout_*.nc は浮動小数バイナリで gzip がほぼ効かない (slim 後の
			// 追加 gzip は 4% 程度)。slim だけで Lambda 6MB 上限を 1/12 まで切るので
			// gzip は省く (CPU 100ms とトレードオフが合わない)。
			const slim = await slimVmec(f);
			setVesselStatus(`uploading ${slim.size.toLocaleString()} bytes (slim)…`);
			const res = await vessel({
				body: slim,
				parseAs: 'blob',
			});
			setVesselStatus('computing on server… (10-60s)');
			const blob = res.data as Blob;
			const buf = await blob.arrayBuffer();
			setVesselStatus('parsing response…');
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
			const res = await magnet({
				body: f,
				parseAs: 'blob',
			});
			setMagnetStatus('computing on server… (5-30s)');
			const blob = res.data as Blob;
			const buf = await blob.arrayBuffer();
			setMagnetStatus('parsing response…');
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
					<SourceRow
						inputRef={vesselInputRef}
						accept=".nc"
						onFileChange={setVesselFile}
						presetUrl="/wout_vmec.nc"
						presetName="wout_vmec.nc"
						onUsePreset={() => usePreset('/wout_vmec.nc', 'wout_vmec.nc', 'vessel')}
					/>
					<button
						type="button"
						disabled={!vesselFile || vesselUploading}
						onClick={() => vesselFile && uploadVessel(vesselFile)}
						style={{ marginTop: 4 }}
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
					<p style={{ minHeight: '1.2em', fontSize: 12 }}>
						{vesselUploading && <Spinner />}
						{vesselStatus}
					</p>
					<DownloadList entries={vesselEntries} onToggleHide={toggleHide} hiddenUrls={hiddenUrls} />
				</section>

				<section>
					<h2>magnet</h2>
					<p style={{ fontSize: 12, color: '#666', margin: '4px 0' }}>
						MAKEGRID coils → magnet_set.{`{step,glb,csv}`}
					</p>
					<SourceRow
						inputRef={magnetInputRef}
						onFileChange={setMagnetFile}
						presetUrl="/coils.example"
						presetName="coils.example"
						onUsePreset={() => usePreset('/coils.example', 'coils.example', 'magnet')}
					/>
					<button
						type="button"
						disabled={!magnetFile || magnetUploading}
						onClick={() => magnetFile && uploadMagnet(magnetFile)}
						style={{ marginTop: 4 }}
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
					<p style={{ minHeight: '1.2em', fontSize: 12 }}>
						{magnetUploading && <Spinner />}
						{magnetStatus}
					</p>
					<DownloadList entries={magnetEntries} onToggleHide={toggleHide} hiddenUrls={hiddenUrls} />
				</section>
			</aside>

			<div style={{ flex: 1, minWidth: 0, height: '100%' }}>
				<GlbViewer urls={visibleUrls} height="100%" />
			</div>
		</main>
	);
}
