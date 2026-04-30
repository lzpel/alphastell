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

type DownloadListProps = {
	entries: Entry[];
	onToggleHide?: (entry: Entry) => void;
	hiddenUrls?: string[];
};

export function DownloadList(props: DownloadListProps) {
	const hidden = new Set(props.hiddenUrls ?? []);
	return (
		<ul>
			{props.entries.map((e) => {
				const isGlb = e.name.toLowerCase().endsWith('.glb');
				const isHidden = hidden.has(e.url);
				return (
					<li key={e.name}>
						{isGlb && props.onToggleHide && (
							<label style={{ marginRight: 6 }}>
								<input
									type="checkbox"
									checked={isHidden}
									onChange={() => props.onToggleHide!(e)}
								/>{' '}
								hide
							</label>
						)}
						<a href={e.url} download={e.name}>
							{e.name}
						</a>{' '}
						({e.size} bytes)
					</li>
				);
			})}
		</ul>
	);
}
