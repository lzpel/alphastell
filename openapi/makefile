server-generate:
	cargo install --root out mandolin
	npm install
	echo "$${tspconfig}" > ./out.yaml
	npm run tsp -- compile main.tsp --config ./out.yaml
	echo "$${openapi_ts}" > ./out.ts
	npm run openapi-ts -- --file ./out.ts
	./out/bin/mandolin -i ../out/openapi.json -o ../src/openapi.rs
%:
	@echo "No rule to make target '$@'"
install:
	npm install @typespec/compiler @typespec/http @typespec/openapi3 @hey-api/openapi-ts
	npm pkg set scripts.tsp="tsp" scripts.openapi-ts="openapi-ts"

define tspconfig
emit:
  - "@typespec/openapi3"
options:
  "@typespec/openapi3":
    output-file: "{project-root}/../out/openapi.json"
endef
export

define openapi_ts
import { defineConfig } from '@hey-api/openapi-ts';
export default defineConfig({
    input: '../out/openapi.json',
    output: {
        path: '../out/client',
        clean: true,
    },
    plugins: [
        '@hey-api/typescript',
        { name: '@hey-api/sdk', throwOnError: true },
        { name: '@hey-api/client-fetch', throwOnError: true },
    ],
});
endef
export