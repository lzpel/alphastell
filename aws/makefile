generate:
	npm install

# cdk.out を repo 外に出す (repoRoot 内だと Docker image asset の context 取得時に
# 再帰自己参照を起こすため)。`$(TEMP)` が使えない MSYS 環境向けに固定パスにフォールバック。
CDK_OUTPUT := $(or $(TEMP),/tmp)/alphastell-cdk-out

deploy: generate check-docker
	npm run cdk -- deploy --require-approval never --progress events --verbose --output $(CDK_OUTPUT)

audit:
	npm audit fix --force
	npm audit fix

check-docker:
	@docker ps > /dev/null 2>&1 || (echo "Error: Docker is not running. Is the Docker daemon really running?"; exit 1)

bootstrap: check-docker
	npm run cdk -- bootstrap
