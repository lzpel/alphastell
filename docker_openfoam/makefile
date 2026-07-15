# epotFoam 焼き込み OpenFOAM イメージのビルドと公開
#
#   make (build)   # ローカルビルド (タグ: ghcr.io/lzpel/openfoam)
#   make push      # ビルドして ghcr.io へ push
#                  # 認証: gh auth token | docker login ghcr.io -u lzpel --password-stdin

IMAGE = ghcr.io/lzpel/openfoam

.PHONY: build push

build:
	docker build -t $(IMAGE) .

push: build
	docker push $(IMAGE)
