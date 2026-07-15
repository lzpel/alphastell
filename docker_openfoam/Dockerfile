# epotFoam 焼き込み済み OpenFOAM イメージ (ghcr.io/lzpel/openfoam)
#
#   docker run --rm -v $PWD:/work -w /work ghcr.io/lzpel/openfoam epotFoam -case hartmann
#
# の形で blockMesh / checkMesh / postProcess / epotFoam 等をそのまま起動できる。
# --user は不要: ENTRYPOINT が /work の所有者 uid:gid に降格してから実行する
# (gosu パターン)。root 所有の生成物がホストに残らない。
FROM opencfd/openfoam-default:2412

# epotFoam (Tassone 2016, GPLv3) をビルドして /usr/local/bin に配置
COPY epotFoam.C createFields.H /src/epotFoam/
COPY Make /src/epotFoam/Make
RUN bash -c 'source /usr/lib/openfoam/openfoam2412/etc/bashrc && \
    cd /src/epotFoam && FOAM_USER_APPBIN=/usr/local/bin wmake' && \
    rm -rf /src

# ベースイメージのエントリポイントは作業ディレクトリをリセットするため差し替える。
# bashrc を source した後、root 起動なら**カレントディレクトリ (-w で指定した場所)**
# の所有者 uid:gid に setpriv で降格して実行する (gosu パターン) — 呼び出し側の
# --user 指定なしで、生成物がホストユーザー所有になる。
# --user で明示された場合や、cwd が root 所有 (-w なし → cwd=/ 等) はそのまま実行する。
RUN <<'EOF'
cat > /entrypoint.sh <<'SH'
#!/bin/bash
source /usr/lib/openfoam/openfoam2412/etc/bashrc >/dev/null 2>&1 || true
if [ "$(id -u)" = "0" ]; then
    uid=$(stat -c %u .)
    gid=$(stat -c %g .)
    if [ "$uid" != "0" ]; then
        export HOME=/tmp
        exec setpriv --reuid="$uid" --regid="$gid" --clear-groups "$@"
    fi
fi
if [ -z "$HOME" ] || [ "$HOME" = "/" ] || [ ! -w "$HOME" ]; then
    export HOME=/tmp
fi
exec "$@"
SH
chmod +x /entrypoint.sh
EOF
ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
