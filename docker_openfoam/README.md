# docker_openfoam — epotFoam 焼き込み済み OpenFOAM イメージ

`ghcr.io/lzpel/openfoam` のビルド元。OpenFOAM v2412 (ESI) に MHD ソルバー
epotFoam(Tassone 2016 転記、GPLv3)をビルド済みバイナリとして焼き込み、

```sh
docker run --rm --user $(id -u):$(id -g) -v $PWD:/work -w /work \
  ghcr.io/lzpel/openfoam epotFoam -case hartmann
```

の1行で任意の OpenFOAM コマンド(blockMesh / checkMesh / postProcess / epotFoam …)を
起動できるようにする。利用側(sandbox-openfoam-cadrum)から wmake・環境設定・マウント合成の
知識を消すのが目的。

## 使い方

```sh
make          # ローカルビルド
make push     # ビルドして ghcr.io へ push
              # 認証: gh auth token | docker login ghcr.io -u lzpel --password-stdin
```

匿名 pull させるには GitHub Packages 側でパッケージを public にすること。
ローカルに同名タグがあれば pull は不要(docker はローカル優先)。

## 設計判断と根拠

| 判断 | 選択 | 根拠 |
|---|---|---|
| ソルバー配布 | バイナリをイメージに焼き込み(利用側での wmake を廃止) | 利用側の makefile が `docker run … epotFoam -case <case>` の1行になる。ソルバービルドの再現性もイメージのタグで固定される |
| ソース配置 | epotFoam.C / createFields.H / Make/ を**このディレクトリにコピーして保持** | ディレクトリの完結性を優先(ユーザー方針)。原本は [sandbox-openfoam/epotFoam](../sandbox-openfoam/epotFoam/) と同一 — **ソルバーを変更したら両方を同期すること** |
| 配置先 | `FOAM_USER_APPBIN=/usr/local/bin` で wmake | PATH に元から入っており、環境変数の細工なしで `epotFoam` が見つかる |
| ENTRYPOINT | 自前スクリプトに差し替え(bashrc source → **setpriv による自動降格** → `exec "$@"`) | ベースイメージのエントリポイントは作業ディレクトリをリセットする(実測)ため `-w` が効くよう置き換え。root 起動なら**カレントディレクトリ(`-w` で指定した場所)の所有者 uid:gid** に `setpriv` で降格(gosu パターン、公式 postgres 等と同じ常套手段)— 通常のホストでは `--user` 指定なしで生成物がホストユーザー所有になる。`--user` 明示時や cwd が root 所有(`-w` なし)ならそのまま実行 |
| 実行ユーザー | `--user` 指定は不要(entrypoint の setpriv 自動降格に任せる)。sandbox-openfoam-cadrum の makefile も `--user` なし | Docker 本体に Podman `--userns=keep-id` 相当は無い(調査済み: 透過解は rootless Docker のみ)ため、イメージ側で解決する。実ワークロード(epotFoam/blockMesh 等の単一コマンド起動)では生成物がホストユーザー所有になることをフルパイプラインで検証済み。既知の注意: 本開発ホストでは降格後プロセスが fork した子の書き込みに説明不能な異常を観測(bash -c で複数コマンドを繋ぐ場合など)。単一コマンド起動では問題なし |

## ライセンス注意

epotFoam は OpenFOAM (GPLv3) の icoFoam 派生のため **GPLv3**(リポジトリ全体の MIT と異なる)。
