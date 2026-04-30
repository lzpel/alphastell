'use client';

import { useEffect, useRef, useState } from 'react';
import Lambda360View from 'lambda360view';

export interface GlbViewerProps {
	/** 読み込む GLB の URL 配列 (Blob URL でも HTTP URL でも可)。空配列で空状態。*/
	urls: string[];
	/** ビューア領域の高さ。CSS 値 (`number` は px 扱い)。デフォルト 500px。*/
	height?: number | string;
}

/**
 * `lambda360view` の Lambda360View を薄くラップしたビュワー。
 * 与えられた URL 群から GLB を fetch して ArrayBuffer 配列にし、3D に同時表示する。
 *
 * - VMEC 由来モデルは Z-up (parastell 準拠) なので `axisUp="Z"` 固定。
 * - 一度 fetch した URL は内部 Map にキャッシュ。チェック on/off の度に再 fetch しない。
 * - 編集や注釈機能は使わないので最小プロップで構成。
 */
export default function GlbViewer(props: GlbViewerProps) {
	const cacheRef = useRef<Map<string, ArrayBuffer>>(new Map());
	const [models, setModels] = useState<ArrayBuffer[]>([]);
	const [error, setError] = useState<string | null>(null);
	const [loading, setLoading] = useState(false);

	useEffect(() => {
		setError(null);
		const ctrl = new AbortController();
		const cache = cacheRef.current;

		const missing = props.urls.filter((u) => !cache.has(u));
		if (missing.length === 0) {
			setLoading(false);
			setModels(props.urls.map((u) => cache.get(u)!));
			return;
		}

		setLoading(true);
		Promise.all(
			missing.map((u) =>
				fetch(u, { signal: ctrl.signal })
					.then((r) => r.arrayBuffer())
					.then((b) => [u, b] as const),
			),
		)
			.then((entries) => {
				if (ctrl.signal.aborted) return;
				for (const [u, b] of entries) cache.set(u, b);
				setModels(props.urls.map((u) => cache.get(u)!));
			})
			.catch((e: unknown) => {
				if (ctrl.signal.aborted) return;
				setError(e instanceof Error ? e.message : String(e));
			})
			.finally(() => {
				if (!ctrl.signal.aborted) setLoading(false);
			});

		return () => ctrl.abort();
	}, [props.urls]);

	const height = props.height ?? 500;

	const overlay = error ? (
		<div style={{ padding: '8px 16px', background: '#fff', color: '#c00', borderRadius: 6 }}>
			Error: {error}
		</div>
	) : loading ? (
		<div style={{ padding: '8px 16px', background: 'rgba(255,255,255,0.9)', color: '#666', borderRadius: 6 }}>
			Loading…
		</div>
	) : props.urls.length === 0 ? (
		<div style={{ color: '#999' }}>Check layers to view</div>
	) : null;

	return (
		<div style={{ width: '100%', height, position: 'relative' }}>
			<Lambda360View model={models} axisUp="Z" showEdges showViewMenu nodeCenter={overlay} backgroundColor='#EEE' />
		</div>
	);
}
