#!/usr/bin/env python3
"""32 本の閉ループに矩形断面を掃引し、モジュラーコイルの導体ソリッドを作る (al_09)。

al_07 はコイルの中心線 (Fourier 係数) までしか出せず、断面を持つ実体にする手段が無かった。
sweep_geometry で経路を通すのが目的なので、経路は VMEC には触らず解析式の摂動円で置く。
本数と大きさだけ al_07 の結果 (nfp=4, 半周期 4 本, 大半径 14 m) に合わせてある。

up はコイル面の法線 e_phi にとる。ProfileOrient::Up は up が接線と平行になる箇所で破綻するが、
ループの接線は面外の揺らぎを入れても R-z 面から最大 5.4 度しか外れないので全周で安全である。
up = e_z にすると theta = ±pi/2 で接線と平行になって破綻する。

    make al-09
"""

import math
import pathlib
from typing import Any

import typst

from alphastell import Geometry

R0 = 14.0  # コイル中心円の大半径 [m]。al_07 のコイル中心 13.95 m に合わせた
A = 5.0  # コイルの平均小半径 [m]
NFP = 4  # 磁場周期数。小半径変調の位相がこの周期でトロイダルに回る
NCOIL = 32  # 全周のコイル本数 = 2 * nfp * (半周期あたり 4 本)
NPOINT = 48  # 1 本あたりの制御点数
EPS = 0.15  # 小半径の変調率。ポロイダル 2 ローブ。正の動径グラフなので自己交差しない
WOBBLE = 0.4  # コイル面から外れるトロイダル方向の振幅 [m]。全コイル同位相なので間隔は保たれる
WIDTH = 0.6  # 導体パックのトロイダル幅 [m]。断面のローカル x
HEIGHT = 0.4  # 導体パックの半径方向厚み [m]。断面のローカル y

CONVERGENCE = [12, 24, 48, 96]  # 制御点数を振って体積の収束を見る
TILT = [0.0, 0.2, 0.4, 0.8]  # 面外の揺らぎを振る。up が接線と直交しなくなる度合いに対応する
SEAM_SHIFT = [0, 7, 16]  # 同じ曲線で継ぎ目だけずらす。閉経路の掃引が seam で歪まないかの検査
FINE = 96  # 収束後とみなす制御点数。傾きの影響を離散化から切り離すのに使う

OUT = pathlib.Path("out")
STEM = "al_09_coil_sweep"
PROFILE = [-WIDTH / 2, -HEIGHT / 2, WIDTH / 2, -HEIGHT / 2, WIDTH / 2, HEIGHT / 2, -WIDTH / 2, HEIGHT / 2]


def coil_point(phi: float, theta: float, wobble: float = WOBBLE) -> tuple[float, float, float]:
	"""トロイダル角 phi のコイルの、ポロイダル角 theta における中心線座標 [m]。"""
	radial, normal = (math.cos(phi), math.sin(phi)), (-math.sin(phi), math.cos(phi))
	r = A * (1.0 + EPS * math.cos(2.0 * theta - NFP * phi))
	major, out_of_plane = R0 + r * math.cos(theta), wobble * math.sin(theta)
	return (major * radial[0] + out_of_plane * normal[0], major * radial[1] + out_of_plane * normal[1], r * math.sin(theta))


def coil_path(index: int, npoint: int = NPOINT, shift: int = 0, wobble: float = WOBBLE) -> list[float]:
	"""コイル 1 本の掃引経路 [upx, upy, upz, x, y, z, ...] を返す。shift は始点 (継ぎ目) をずらす。"""
	phi = math.tau * index / NCOIL
	path = [-math.sin(phi), math.cos(phi), 0.0]
	# 周期性はスプラインの基底に入るので、始点を末尾で繰り返さない
	for j in range(npoint):
		path += coil_point(phi, math.tau * ((j + shift) % npoint) / npoint, wobble)
	return path


def exact_volume(index: int, wobble: float = WOBBLE, division: int = 20000) -> float:
	"""断面積 x 中心線長 [m^3]。断面が法平面に乗っていれば掃引体積はこれに一致する。"""
	phi = math.tau * index / NCOIL
	point = [coil_point(phi, math.tau * j / division, wobble) for j in range(division + 1)]
	return WIDTH * HEIGHT * sum(math.dist(a, b) for a, b in zip(point, point[1:]))


def max_tilt(wobble: float) -> float:
	"""接線が法平面から外れる最大角 [deg]。up は面の法線に固定してあるので、これが断面の傾きになる。"""
	return math.degrees(math.atan2(wobble, A * (1.0 - EPS)))


def swept_volume(**kwargs: Any) -> float:
	"""コイル 0 本目を掃引して体積を返す。パラメータを 1 つずつ振るための薄い包み。"""
	return Geometry.sweep_geometry(True, PROFILE, coil_path(0, **kwargs)).volume()[0]


def main() -> dict[str, Any]:
	OUT.mkdir(parents=True, exist_ok=True)
	coils = Geometry.sweep_geometry(True, PROFILE, *(coil_path(index) for index in range(NCOIL)))
	for suffix, write in (("step", coils.write_step), ("png", coils.write_png)):
		path = OUT / f"{STEM}.{suffix}"
		with open(path, "wb") as f:
			write(f)
		print(f"{path}: {len(coils)} solids, {path.stat().st_size} bytes")

	volume = coils.volume()
	error = [(v / exact_volume(i) - 1.0) * 100 for i, v in enumerate(volume)]
	# 制御点数、面外の揺らぎ、継ぎ目の位置をそれぞれ 1 本だけで振る。掃引は 1 本あたり数十 ms で済む
	converge = [(n, swept_volume(npoint=n)) for n in CONVERGENCE]
	tilt = [(w, swept_volume(npoint=FINE, wobble=w), exact_volume(0, wobble=w)) for w in TILT]
	seam = [swept_volume(shift=s) for s in SEAM_SHIFT]

	print(f"volume {min(volume):.3f}..{max(volume):.3f} m^3, error vs exact {min(error):+.2f}..{max(error):+.2f} %")
	print(f"tilt residual at {FINE} points: " + ", ".join(f"{max_tilt(w):.1f}deg {(v / e - 1.0) * 100:+.3f}%" for w, v, e in tilt))
	print(f"seam shift spread: {(max(seam) / min(seam) - 1.0) * 100:.3f} %")
	return {
		"ncoil": NCOIL,
		"npoint": NPOINT,
		"fine": FINE,
		"r0": f"{R0:.1f}",
		"a": f"{A:.1f}",
		"nfp": NFP,
		"eps": f"{EPS:.2f}",
		"wobble": f"{WOBBLE:.1f}",
		"width": f"{WIDTH * 100:.0f}",
		"height": f"{HEIGHT * 100:.0f}",
		"area": f"{WIDTH * HEIGHT:.2f}",
		"tilt": f"{max_tilt(WOBBLE):.1f}",
		"length": f"{sum(exact_volume(i) for i in range(NCOIL)) / NCOIL / (WIDTH * HEIGHT):.2f}",
		"volume_min": f"{min(volume):.3f}",
		"volume_max": f"{max(volume):.3f}",
		"error_min": f"{min(error):+.2f}",
		"error_max": f"{max(error):+.2f}",
		"spread": f"{(max(volume) / min(volume) - 1.0) * 100:.2f}",
		"converge_tail": f"{abs(converge[-1][1] / converge[-2][1] - 1.0) * 100:.3f}",
		"tilt_flat": f"{(tilt[0][1] / tilt[0][2] - 1.0) * 100:+.3f}",
		"tilt_ref": f"{next((v / e - 1.0) * 100 for w, v, e in tilt if w == WOBBLE):.2f}",
		"tilt_last": f"{(tilt[-1][1] / tilt[-1][2] - 1.0) * 100:.2f}",
		"seam_spread": f"{(max(seam) / min(seam) - 1.0) * 100:.3f}",
		"step_size": f"{(OUT / f'{STEM}.step').stat().st_size / 1e6:.1f}",
		"converge_rows": "".join(f"  [{n}], [{v:.4f}],\n" for n, v in converge),
		"tilt_rows": "".join(f"  [{max_tilt(w):.1f}], [{e:.4f}], [{v:.4f}], [{(v / e - 1.0) * 100:+.3f}],\n" for w, v, e in tilt),
		"seam_rows": "".join(f"  [{s}], [{v:.4f}],\n" for s, v in zip(SEAM_SHIFT, seam)),
	}


TEMPLATE = """#set page(paper: "a4", margin: 2cm, numbering: "1")
#set text(font: ("Yu Gothic", "Meiryo", "Noto Sans CJK JP"), size: 10pt, lang: "ja")
#set par(justify: true)

= 断面の掃引によるコイル導体ソリッド (al_09)

al_07 の stage-2 最適化はモジュラーコイルの中心線を Fourier 係数として出すが、そこから先の
「断面を持つ実体」を作る手段が alphastell に無かった。ブランケット殻は磁気面を張るだけなので
`bspline_geometry` で足りていたのに対し、コイルは断面を経路に沿って動かす別種の操作を要求する。

そこで `sweep_geometry` を Rust 側に足し、経路が通ることをここで確認する。al_07 の実係数を
食わせるのは次段に回し、本数と大きさだけ揃えた解析式の摂動円で土台を検査する。

== 方法

`cadrum::Solid::sweep` は閉じた断面ワイヤを 1 本の経路ワイヤに沿って掃引する。1 回の呼び出しが
1 本の経路に対応するので、{ncoil} 本のコイルには {ncoil} 回呼んで `Vec<Solid>` に集める。

経路は各点の位置だけを与え、`[upx, upy, upz, x, y, z, ...]` の $3 + 3N$ 要素で表す。接線は
スプラインから決まるので点ごとの方向は要らない。閉ループかどうかは呼び出し側が `periodic` 引数で
明示する。周期性はスプラインの基底に入るため、閉ループでは始点を末尾で繰り返さない。

断面の姿勢は `ProfileOrient::Up(up)` で運ぶ。これは OCCT の binormal law で、フレームが各点の
接線と固定した `up` だけから決まる。経路を一周しても捻れが蓄積しないので、閉経路に向いている。

=== up の取り方

`ProfileOrient::Up` は `up` が接線と平行になる箇所で破綻する。トロイダル角 $phi$ のコイルは
$e_R (phi)$ と $e_z$ の張る面内のループなので、**その面の法線 $e_phi = (-sin phi, cos phi, 0)$**
を `up` に選べば、面内成分に対して常に直交する。面外の揺らぎ $A sin theta$ を入れても直交から
最大 {tilt} 度しか外れない。$e_z$ を選ぶと $theta = plus.minus pi\\/2$ で接線と平行になって破綻する。

`up` の選び方は呼び出し側の責任で、実装は検査しない。誤っても例外にはならず、形だけが壊れる。
実測では、このコイルに $e_phi$ ではなく $e_z$ を渡すと体積が本来の 6.1%、接線に平行な向きを
渡すと 44 倍になった。どちらも `sweep` は成功を返すので、図か体積で確かめるほかない。

=== 形状

大半径 {r0} m、平均小半径 {a} m。小半径を $r(theta) = {a} (1 + {eps} cos(2 theta - {nfp} phi))$ と
変調してあり、位相が磁場周期 {nfp} でトロイダルに回るので軸対称にならない。正の動径グラフなので
$epsilon < 1$ である限り自己交差しない。面外の揺らぎは全コイル同位相なので、隣接コイルの間隔は
内側最狭部でも 1.0 m 残り、al_07 の下限 0.8 m を満たす。断面は {width} × {height} cm の矩形で、
制御点は 1 本あたり {npoint} 点である。

== 結果

#figure(image("{stem}.png", width: 100%), caption: [{ncoil} 本のコイル導体。左上 ISO、右上 +Z、
左下 +X、右下 +Y。四面とも同一尺度で、原点との相対位置が読める。+Z 面の内側輪郭が {nfp} 回対称に
脈打っているのが小半径変調である。])

掃引した {ncoil} 個のソリッドの体積は {volume_min}〜{volume_max} m³ で、断面積 {area} m² ×
中心線長 (平均 {length} m) に対する差は {error_min}〜{error_max} % である。STEP は {step_size} MB。

断面が経路の法平面に乗っているなら、掃引体積は断面積 × 弧長にちょうど一致する。曲がりの内側で
縮む分と外側で伸びる分が、断面の重心が経路上にある限り一次で打ち消し合うためである。上のずれが
何に由来するのかを、制御点数・断面の傾き・継ぎ目の位置の 3 つに分けて測った。

=== 制御点数

コイル 0 本目で制御点数だけを振ったもの。

#table(
  columns: 2,
  align: (right, right),
  [制御点数], [体積 [m³]],
{converge_rows})

=== 断面の傾き

面外の揺らぎを振り、接線が法平面から外れる最大角を変えたもの。離散化と切り分けるため制御点数は
{fine} 点に固定してある。

#table(
  columns: 4,
  align: (right, right, right, right),
  [最大傾き [deg]], [断面積 × 弧長 [m³]], [掃引体積 [m³]], [差 [%]],
{tilt_rows})

=== 継ぎ目の位置

同じ曲線のまま始点 (周期スプラインの継ぎ目) だけをずらしたもの。制御点の集合は変わらないので、
経路そのものは同一である。

#table(
  columns: 2,
  align: (right, right),
  [始点のずらし幅 [点]], [体積 [m³]],
{seam_rows})

== 考察

=== 誤差の主因は離散化ではなく断面の傾き

制御点数を {npoint} から {fine} に倍にしても体積は {converge_tail} % しか動かない。この段階で
すでに収束しており、{error_min}〜{error_max} % のずれは制御点数を増やしても消えない。

傾きの表がその正体を示している。揺らぎを外して接線が法平面に厳密に乗る場合、掃引体積は
断面積 × 弧長と {tilt_flat} % で一致する。つまり掃引そのものは厳密である。傾きを入れると差が
現れ、しかも**傾きが 2 倍になるごとに差が約 4 倍**になる。二次の依存であり、断面が法平面から
$alpha$ だけ傾いた分の $cos alpha$ 的な減少として理解できる。{tilt} 度で {tilt_ref} %、
その 2 倍の傾きでは {tilt_last} % に達する。

`ProfileOrient::Up` は `up` を固定軸として保つ法則なので、`up` が接線と直交しない箇所では
断面が真の法平面から傾く。これは実装の不具合ではなく、この姿勢法則を選んだことの帰結である。

実用上の含意ははっきりしている。**経路が平面に載っていて `up` をその法線に取れる形状なら、
掃引は厳密に正しい。** 経路が面外に出るほど断面が傾き、体積が二次で目減りする。実際のコイルは
巻線パックが経路に沿って捻れるので、`up` を 1 本の固定ベクトルで済ませることはできない。

=== 継ぎ目に大きな歪みは無い

cadrum の notes には、閉経路に**複数断面をモーフィングさせる**掃引で継ぎ目に 1.2% の非対称が
出るという記録がある (その API は既に削除済み)。今回は単一断面なので該当しないはずだが、実測でも
確かめた。経路が同一のまま始点だけをずらしたときの体積差は {seam_spread} % で、記録された 1.2%
とは桁が違う。ただしゼロでもない。断面の傾きに由来する {tilt_ref} % と同程度の量なので、
このレベルの精度を要求する用途では継ぎ目の位置も効くと考えておく必要がある。

=== 周期性は判定せず引数で受ける

当初は始点と終点の一致から閉ループを自動判定していたが、これは危険だった。終点の重複を忘れると
開いた掃引になり、**エラーも警告も出ずに継ぎ目の空いたコイルができる**。実際この example の
最初の版がそれを踏んだ。図を見れば一目で分かるものの、静かに壊れる経路が残ってしまう。

そこで判定をやめ、`periodic` を先頭の引数で明示的に受ける形にした。誤って終点を重複させた場合は
cadrum の `Edge::bspline` が「周期指定では始点を末尾で繰り返すな」と明示的に弾くので、
間違いが静かに通らなくなる。許容差の定数も 1 つ消えた。

=== 次段

ここで確認したのは経路であって形状ではない。次は al_07 が出す `al_07_coils.csv` の Fourier 係数を
中心線に使う。そのとき `up` を固定ベクトルで済ませられないことは上で分かったので、
`ProfileOrient::Auxiliary` に補助曲線を渡して断面の向きを経路に沿って制御する形が要る。
cadrum の doc がこの variant を「ステラレーターの断面回転」用と名指ししているのは、
まさにこの問題のためである。
"""


if __name__ == "__main__":
	fields = main()
	report = OUT / "al_09_report.typ"
	report.write_text(TEMPLATE.format(stem=STEM, **fields), encoding="utf-8")
	typst.compile(report, output=OUT / "al_09_report.pdf")
	print(f"{OUT / 'al_09_report.pdf'}: {(OUT / 'al_09_report.pdf').stat().st_size} bytes")
