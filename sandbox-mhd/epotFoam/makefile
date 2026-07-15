# epotFoam のビルドと OpenFOAM 起動設定をこのディレクトリで自己完結させる。
#
#   make -C sandbox-mhd/epotFoam           # (デフォルト=foam) docker run プレフィックスを出力。
#                                          #   バイナリ未ビルドなら先にビルドする
#   make -C sandbox-mhd/epotFoam epotFoam  # バイナリ ./epotFoam のみビルド
#   make -C sandbox-mhd/epotFoam clean     # バイナリと中間物を削除
#
# 親 makefile からの使い方 (FOAM/ENV 変数は不要):
#   $$($(MAKE) -s --no-print-directory -C epotFoam) blockMesh -case hartmann
#
# プレフィックスは親ディレクトリを /work にマウントし、コンテナ内の環境設定
# (bashrc・PATH) は openfoam.sh に集約。引用符を含まない1行なのでシェルの
# コマンド置換でそのまま展開できる。

# デフォルトターゲット。バイナリが前提条件なのでビルド済みならスキップされる
.PHONY: foam
foam: epotFoam
	@echo docker run --rm --user $$(id -u):$$(id -g) \
	  -e HOME=/work -e USER=openfoam \
	  -v $(abspath $(CURDIR)/..):/work -w /work \
	  opencfd/openfoam-default:2412 /work/epotFoam/openfoam.sh

# --user でホスト UID のまま実行 (root 所有ファイルを残さない)。
# FOAM_USER_APPBIN=/work により Make/files の EXE がこのディレクトリ直下を指す。
# ビルド出力は 1>&2: foam のコマンド置換 (stdout) を汚さないため
epotFoam: epotFoam.C createFields.H Make/files Make/options
	docker run --rm --user $$(id -u):$$(id -g) \
	  -e HOME=/work -e USER=openfoam \
	  -v $(CURDIR):/work -w /work opencfd/openfoam-default:2412 /bin/bash -c \
	  'source /usr/lib/openfoam/openfoam2412/etc/bashrc >/dev/null 2>&1 || true; \
	   export FOAM_USER_APPBIN=/work; set -e; cd /work; wmake' 1>&2

.PHONY: clean
clean:
	rm -rf epotFoam Make/linux*
