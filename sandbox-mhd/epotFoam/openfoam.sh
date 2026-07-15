#!/bin/bash
# コンテナ内で OpenFOAM 環境を整えて任意のコマンドを実行するランチャ。
# makefile の foam ターゲットが出力する docker run プレフィックスから呼ばれる。
source /usr/lib/openfoam/openfoam2412/etc/bashrc >/dev/null 2>&1 || true
export PATH=/work/epotFoam:$PATH
cd /work
exec "$@"
