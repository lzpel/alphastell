# make install + make generateで大体良い感じのフロントエンドが書けるmakefile
# tailwind css で material ui風のpaletteを導入
server-generate:
	# 無視するファイルを.gitignoreに追加
	sed -i -e '/##/q' .gitignore && printf "AGENTS.md\nCLAUDE.md\n*.config.*" >> .gitignore
	# 設定ファイルを作成
	echo "$${next_config_ts}" > ./next.config.ts
	echo "$${agents_md}" | tee ./CLAUDE.md ./AGENTS.md > /dev/null
server-run:
	npm run dev

server-deploy: server-generate
	npm run build
define agents_md
# Frontend Rules

## Component Declaration
- UI components must use `export function` or `export default function`. Never assign functions to `const`.
- Function arguments must be declared as `(props: Type)` and accessed via `props.xxx`. Destructuring in the parameter list `({ xxx }: Type)` is prohibited.

## Props Design
- Define prop types so that event handlers and values can be injected from the parent when needed.

## stateless_ui/ Directory
- Files under `stateless_ui/` define appearance only, not behavior. `useState`, `useEffect`, `useRef`, and other hooks are prohibited.
- Each file must define `export function Sandbox()` that renders all UI components defined in that file for visual review.
- Each file's `<Filename.Sandbox />` must be placed in `app/sandbox/page.tsx`.
endef
export

define next_config_ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
	output: "export",
	basePath: $(if $(REPONAME),"/$(REPONAME)",undefined),
	assetPrefix: $(if $(REPONAME),"/$(REPONAME)/",undefined),
	env: {
		NEXT_PUBLIC_PREFIX: "$(if $(REPONAME),/$(REPONAME))",
		SERVER_URL: $(if $(REPONAME),"https://d3l2x153v6axn.cloudfront.net",undefined)
	},
	images: {
		unoptimized: true,
	},
	experimental: {
		externalDir: true,
	},
}
;export default nextConfig;
endef
export
