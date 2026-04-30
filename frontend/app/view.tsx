'use client';

import { useEffect, useState } from 'react';
import Lambda360View from 'lambda360view';

export interface GlbViewerProps {
	/** 読み込む GLB の URL (Blob URL でも HTTP URL でも可)。null で空状態。*/
	url: string | null;
	/** ビューア領域の高さ。CSS 値 (`number` は px 扱い)。デフォルト 500px。*/
	height?: number | string;
}

/**
 * `lambda360view` の Lambda360View を薄くラップしたビュワー。
 * URL から GLB を fetch して ArrayBuffer に詰め直し、3D 表示する。
 *
 * - VMEC 由来モデルは Z-up (parastell 準拠) なので `axisUp="Z"` 固定。
 * - 編集や注釈機能は使わないので最小プロップで構成。
 */
export default function GlbViewer(props: GlbViewerProps) {
	const [model, setModel] = useState<ArrayBuffer | null>(null);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		setError(null);
		if (!props.url) {
			setModel(null);
			return;
		}
		const ctrl = new AbortController();
		fetch(props.url, { signal: ctrl.signal })
			.then((r) => r.arrayBuffer())
			.then((buf) => {
				if (!ctrl.signal.aborted) setModel(buf);
			})
			.catch((e: unknown) => {
				if (!ctrl.signal.aborted) {
					setError(e instanceof Error ? e.message : String(e));
				}
			});
		return () => ctrl.abort();
	}, [props.url]);

	const height = props.height ?? 500;

	const overlay = error ? (
		<div style={{ padding: '8px 16px', background: '#fff', color: '#c00', borderRadius: 6 }}>
			Error: {error}
		</div>
	) : !model && props.url ? (
		<div style={{ padding: '8px 16px', background: 'rgba(255,255,255,0.9)', color: '#666', borderRadius: 6 }}>
			Loading…
		</div>
	) : !props.url ? (
		<div style={{ color: '#999' }}>Select a layer to view</div>
	) : null;

	return (
		<div style={{ width: '100%', height, position: 'relative' }}>
			<Lambda360View model={model} axisUp="Z" showEdges showViewMenu nodeCenter={overlay} backgroundColor='#EEE' />
		</div>
	);
}
