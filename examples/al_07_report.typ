#set page(paper: "a4", margin: 2cm, numbering: "1")
#set text(font: ("Yu Gothic", "Meiryo", "Noto Sans CJK JP"), size: 10pt, lang: "ja")
#set par(justify: true)

= VMEC 平衡を再現するモジュラーコイル (al_07)

VMEC 平衡 `wout_vmec.nc` (nfp={nfp}, R={r_major:.2f} m) の LCFS を固定し、その外側にモジュラーコイルを
simsopt の stage-2 最適化で置いた。al_06 で PbLi 殻を厚くするほど TBR が上がると分かったので、
ここではコイルをどこまで離せるか、つまり半径方向にいくら予算があるかを見る。

== 方法

磁気面を動かさずコイルだけを動かす stage-2 である。半周期に {ncoils} 本の独立コイル
(1 本あたり Fourier {order} 次) を等間隔の円環として置き、stellarator 対称と nfp 回転で
{ncoils_total} 本に増やす。目的関数は LCFS 上の規格化法線磁場

$ integral (bold(B) dot bold(n))^2 / abs(bold(B))^2 thin d A $

に、コイル長 ({length_target} m)・コイル間距離 ({cc_threshold} m)・コイル-プラズマ距離・曲率
({curvature_threshold} 1/m、曲げ半径 {bend_radius:.0f} m) の各ペナルティを足したもので、L-BFGS-B を {maxiter} 反復かけた。
コイル-プラズマ距離の要求値だけを {standoff_min}〜{standoff_max} m で振っている。

電流の絶対値はこの wout からは決まらない。正味ポロイダル電流を与える `bsubvmnc` が無く、
`rmnc` / `zmns` / `xm` / `xn` しか持たないためである。R#sub[0] = {r_major:.2f} m で
B#sub[0] = {b0} T を仮定して総電流を固定した。目的関数が B·n/|B| で電流スケールに不変なので、
コイル形状はこの仮定に依らず、下表の電流値だけが B#sub[0] に比例する。同じ理由で、virtual casing に
必要な量が無いため有限ベータ補正も入っておらず、コイルだけで LCFS を作る真空磁場に近い扱いである。

== 結果: どこまでコイルを離せるか

#table(
  columns: 6,
  align: (right, right, right, right, right, right),
  [要求距離 [m]], [実現距離 [m]], [max |B·n|/|B|], [mean |B·n|/|B|], [全コイル長 [m]], [コイル間 [m]],
{scan_rows})

要求 {standoff_min} m はほぼそのまま実現できる ({cs_first:.2f} m)。別途 1.0 m を要求しても 1.38 m までしか
近づかないので、この配位のコイルは放っておいても 1.4 m 前後に落ち着く。一方、要求を上げると
法線磁場誤差は {error_first:.1e} ({cs_first:.2f} m) から {error_last:.1e} ({cs_last:.2f} m) へ 1 桁上がり、
同時にコイル間距離が {cc_first:.2f} m から {cc_last:.2f} m へ詰まる。離した分を長いコイルで補おうとして
互いに衝突するためで、2 m 付近が実用上の壁になる。

#figure(image("al_07_error.png", width: 100%), caption: [左: 実現距離 {cs_first:.2f} m での
LCFS 上の B·n/|B| 分布。右: コイル-プラズマ距離に対する法線磁場誤差。点線は al_06 の PbLi 最大厚み。])

== 結果: コイル形状

以下は要求 {standoff_min} m のコイルである。

#table(
  columns: 4,
  align: (center, right, right, right),
  [コイル], [長さ [m]], [電流 [MA]], [最小曲げ半径 [m]],
{coil_rows})

#figure(image("al_07_coils.png", width: 92%), caption: [{ncoils_total} 本のモジュラーコイルと LCFS。
色は独立コイルの番号で、同色の {nimages} 本は対称操作による像である。断面が三角形から楕円へ
捻れる領域でコイルが強く曲がる。])

== 考察

半径方向の予算は約 1.4 m、無理をして 2 m である。al_06 の PbLi 殻は 70 cm でも TBR が
飽和していなかったから、残る 70 cm 前後に第一壁・冷却管・背面支持構造・遮蔽・真空容器・
組立公差の全部を収めなければならない。al_06 の「厚くすれば TBR が上がる」と本節の
「離すと磁気面が再現できない」は独立した 2 つの結果ではなく、1 つの半径方向予算の奪い合いである。
コイル本数を増やしてもこの壁は動かない (半周期 5 本・6 本でも max |B·n|/|B| は 1e-2 台に留まり、
全コイル長だけが 20〜30% 増えた)。al_08 以降で不均質な WCLL 構造を入れるとき、厚みの上限はここで決まる。

コイル形状は `out/al_07_coils.csv` に全 {ncoils_total} 本の Fourier 係数として出してある。
各コイルは m = 0…{order} の

$ bold(x)(t) = sum_m [ bold(c)_m cos(2 pi m t) + bold(s)_m sin(2 pi m t) ] $

で表され、点列と違って任意の分解能で滑らかに引き直せる。対称操作による像も回転行列を掛けた
だけで次数は変わらないので、全数を同じ形式で持てる。al_04 と同じ経路で STEP にすれば、
そのまま構造解析と干渉チェックに渡せる。
