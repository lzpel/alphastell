'use client';

export type Entry = { name: string; url: string; size: number };

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

type SourceRowProps = {
	inputRef: React.Ref<HTMLInputElement>;
	accept?: string;
	onFileChange: (f: File | null) => void;
	presetUrl: string;
	presetName: string;
	onUsePreset: () => void;
};

/**
 * 入力ソース選択行: `[file input]  or  [Use preset]`。
 * ファイル input とプリセットは排他 — どちらを選んでも最終的に同じ
 * `vesselFile` / `magnetFile` state にロードされるが、見た目として「またはどちら」
 * を `or` の文字 + 横並びで示す。
 */
export function SourceRow(props: SourceRowProps) {
	return (
		<div
			style={{
				display: 'flex',
				alignItems: 'center',
				gap: 8,
				flexWrap: 'wrap',
				margin: '4px 0',
			}}
		>
			<input
				ref={props.inputRef}
				type="file"
				accept={props.accept}
				onChange={(e) => props.onFileChange(e.target.files?.[0] ?? null)}
				style={{ flex: '1 1 auto', minWidth: 0, maxWidth: 200 }}
			/>
			<span style={{ color: '#999', fontSize: 12 }}>or</span>
			<button type="button" onClick={props.onUsePreset}>
				Use preset
			</button>
			<a
				href={props.presetUrl}
				download={props.presetName}
				style={{ fontSize: 11, color: '#888' }}
				title="download the preset file"
			>
				({props.presetName})
			</a>
		</div>
	);
}

type DownloadListProps = {
	entries: Entry[];
	onToggleHide?: (entry: Entry) => void;
	hiddenUrls?: string[];
};

/** size をヒトに優しい単位で表示。 */
function formatSize(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * tar 展開後のエントリ一覧。`hide` 列は .glb 行のみチェックボックス、それ以外は空。
 * 列幅を固定して checkbox 有無で行幅が変わらないようにする (table が一番素直)。
 */
export function DownloadList(props: DownloadListProps) {
	if (props.entries.length === 0) return null;
	const hidden = new Set(props.hiddenUrls ?? []);
	return (
		<table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13, marginTop: 8 }}>
			<colgroup>
				<col style={{ width: 28 }} />
				<col />
				<col style={{ width: 64 }} />
			</colgroup>
			<tbody>
				{props.entries.map((e) => {
					const isGlb = e.name.toLowerCase().endsWith('.glb');
					const isHidden = hidden.has(e.url);
					return (
						<tr key={e.name}>
							<td style={{ textAlign: 'center', padding: '2px 0' }}>
								{isGlb && props.onToggleHide && (
									<input
										type="checkbox"
										checked={isHidden}
										onChange={() => props.onToggleHide!(e)}
										title={isHidden ? 'show in viewer' : 'hide from viewer'}
									/>
								)}
							</td>
							<td style={{ padding: '2px 4px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
								<a href={e.url} download={e.name}>
									{e.name}
								</a>
							</td>
							<td style={{ textAlign: 'right', padding: '2px 0', color: '#666' }}>
								{formatSize(e.size)}
							</td>
						</tr>
					);
				})}
			</tbody>
		</table>
	);
}
