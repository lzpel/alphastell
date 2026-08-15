# alphastell

ステラレータ液体金属ブランケットの成立性を、VMEC 平衡(`wout.nc`)から分単位で判定するオープンソースパイプライン。

プラズマ境界を入力すると、磁気面に追従する液体金属流路を生成し、次の3つのプラント判定スカラーと設計図面を返す:

1. TBR(トリチウム増殖比)<br>≥ 1.1〜1.15 で燃料サイクルが閉じるか
2. MHD 総圧損 → ポンプ動力の対核融合出力比<br>液体金属ブランケットの生死を決める数字
3. 最高壁温度 / 構造材界面温度<br>材料寿命と腐食限界

![img](figure/image.png)

きれいな 3D 可視化は副産物であって製品ではない。製品は「この磁場配位・この流路トポロジーで、ブランケットとして成立するか」への Yes/No と、TBR–圧損の Pareto フロントである。

> Status: pre-alpha. コードはまだない。設計文書([notes/](notes/))とプレプリント草稿([paper.tex](paper.tex)、現状モック結果)が先行している。

## 使い方

Requirement: cargoが入っていること

```
make al-04 # make geometry
make al-07 # コイル形状 (simsopt)
```

### simsopt (al_07 以降)

simsopt は Windows の wheel が無く、PyPI の sdist は `thirdparty/` の submodule を含まないためビルドできない。`pyproject.toml` の `[tool.uv.sources]` で git を指しているのはそのためで、ビルドには C++ コンパイラ・CMake・Boost 1.76 以上のヘッダが要る。MinGW を使う場合:

```
CC=gcc CXX=g++ CMAKE_GENERATOR="MinGW Makefiles" \
  CMAKE_ARGS="-DBOOST_ROOT=<boost のヘッダ> -DBoost_NO_BOOST_CMAKE=ON" uv sync
```

ビルド後、`libgcc_s_seh-1.dll` `libgomp-1.dll` `libstdc++-6.dll` `libwinpthread-1.dll` を `.venv/Lib/site-packages/` に置く。Python 3.8 以降は拡張モジュールと同じディレクトリしか依存 DLL を探さないため、PATH に mingw があっても足りない。

## なぜ作るか

トカマク向けブランケット設計手法は EU で確立済みだが、ステラレータの 3D にねじれた磁気面へ液体金属流路を配置する問題は未解決であり、各社・各機関の内部資料に留まっている。ジオメトリ側は [ParaStell][parastell] が均一厚シェル+中性子計算の基盤を提供しているが、その内側を流れる液体金属の MHD 圧損と TBR を連成して評価する公開ツールは存在しない。本プロジェクトは既存 OSS(OpenMC, epotFoam)を配管し、未実施の計算を最初に実行する。

## パイプライン

```
wout.nc (VMEC 平衡)
   │  フーリエ評価・解析導関数・オフセット面
   ▼
流路ジオメトリ生成(磁気面追従ダクト・マニホールド)
   │
   ├─▶ 材料色付き STEP ──▶ DAGMC / OpenMC ──▶ 中性子束・核発熱・TBR
   │      (cadrum: B-rep, boolean, sweep)
   │
   ├─▶ 相関式 MHD 圧損ネットワーク(1D ダクト網)──▶ 総Δp・ポンプ動力比   ← 高速スキャン(分単位)
   │      B(r) を各ダクト区間に写像、Miyazaki/Smolentsev 系相関式
   │
   └─▶ パラメトリック座標から直接生成する構造格子(polyMesh)
          └─▶ epotFoam (OpenFOAM) ──▶ フル MHD CFD                    ← 検証の錨(代表ダクトのみ)
```

- **高速系(相関式ネットワーク)が主力**: 設計案を1日に何十件も回すための分単位の判定機
- **フル CFD は検証専用**: Hartmann 層を解像した代表計算で相関式との一致(目標: 数%)を示す
- CAD カーネルは [cadrum][cadrum](OCCT 静的リンクの Rust ライブラリ、STEP のソリッド色=材料タグ)

## 検証方針

ツールの妥当性は既知の解析解・実験で事前に証明する:

| ケース | 内容 | 出典 |
|--------|------|------|
| Hartmann flow | 一様磁場下の平行平板流 | Hartmann 1937 |
| Shercliff flow | 矩形ダクト・非導体壁 | Shercliff 1953 |
| Hunt flow | 矩形ダクト・導体/非導体混合壁 | Hunt 1965 |

新規性の主張は「ソルバーを作った」ではなく「**検証済みツール群をステラレータ 3D 磁場に最初に適用した**」に置く。

## 関連プロジェクト

- cadrum 自作RustCADカーネル step出力
- OpenMC モンテカルロ中性子輸送 — TBR・核発熱
- OpenMC-anywhere windows版PIPでもうごくようにした自前ビルドのOpenMC
- parastell
	- ステラレータ炉構造のパラメトリックCAD
- epotFoam (OpenFOAM) | 低磁気レイノルズ数 MHD の標準実装 — 検証用フル CFD

## ドキュメント

- [notes/20260714-全体構成.md](notes/20260714-全体構成.md) — レイヤー分業とリポジトリ構成
- [notes/20260714-3カ月で作り上げる計画.md](notes/20260714-3カ月で作り上げる計画.md) — 週次マイルストーン
- [notes/20260714-CTO論評.md](notes/20260714-CTO論評.md) — 製品定義に至った戦略論評の記録

## 参考資料

- Lion, J., Anglès, J.-C., Bonauer, L., Bañón Navarro, A., Cadena Ceron, S. A., Davies, R., Drevlak, M., Foppiani, N., Geiger, J., Goodman, A., Guo, W., Guiraud, E., Hernández, F., Henneberg, S., Herrero, R., Höchter, J., Jelonnek, J., Jenko, F., Jorge, R., ... Xanthopoulos, P., & Zheng, M. (2025). Stellaris: A high-field quasi-isodynamic stellarator for a prototypical fusion power plant. Fusion Engineering and Design, 214, 114868. PDF[https://github.com/user-attachments/files/31101341/Lion2025_Stellaris_A_high-field_quasi-isodynamic_stellarator_for_a_prototypical_fusion_power_plant.pdf]
	- Proximaの設計論文
	- 3.2 Further improvements and ongoing research
		- full neutronics and structural calculations of a blanket design that is not fully homogenized and includes open ports, including thermal stress analysis and estimation of pumping requirements (完全には均質化されておらず、開いたポートを含むブランケット設計の、完全な中性子工学計算および構造計算。熱応力解析とポンプ動力要求の見積もりを含む)
		- further tritium blanket analyses, including simulating MHD effects in the PbLi, estimations of corrosion, simulation of tritium transport and a respective TBR target, water activation and safety relevant analyses(トリチウムブランケットに関するさらなる解析。これには、PbLiにおけるMHD効果のシミュレーション、腐食の推定、トリチウム輸送および対応するTBRターゲットのシミュレーション、水の活性化、ならびに安全性に関する解析が含まれる。)

- Smolentsev, S., Morley, N. B., Abdou, M. A., & Malang, S. (2015).Dual-coolant lead–lithium (DCLL) blanket status and R&D needs. Fusion Engineering and Design, 100, 44–54. [PDF](https://bpb-us-w2.wpmucdn.com/research.seas.ucla.edu/dist/d/39/files/2019/08/FED-v100-Smolentsev-Dual_Coolant_Lead_Lithium_Blanket_Status2015.pdf)
	- カジュアルな解説：PbLiを流す流路の一つDCLLのレビュー論文　図が分かりやすい
- Martelli, E., Del Nevo, A., Arena, P., Bongiovì, G., Caruso, G., Di Maio, P. A., Eboli, M., Mariano, G., Marinari, R., Moro, F., Mozzillo, R., Giannetti, F., Di Gironimo, G., Tarallo, A., Tassone, A., & Villari, R. (2017). Advancements in DEMO WCLL breeding blanket design and integration [Preprint]. EUROfusion. [PDF](https://scipub.euro-fusion.org/wp-content/uploads/eurofusion/WPBBPR17_17326_submitted.pdf)
	- カジュアルな解説：PbLiをポンプで流さず溜池にするWCLLの論文 CAD図が分かりやすい

## License

MIT

[parastell]: https://github.com/svalinn/parastell
[openmc]: https://github.com/openmc-dev/openmc
[cadrum]: https://github.com/lzpel/cadrum
