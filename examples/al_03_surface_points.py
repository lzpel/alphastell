#!/usr/bin/env python3
"""VMEC の LCFS (s=1) を (φ, θ) 格子で走査し、3D 点と法線を CSV と PNG に出す。

rust 側 SurfaceRZFourier の python 経路 (load → point_normal) の疎通確認を兼ねる。
CSV は x,y,z,nx,ny,nz の 6 列。行の並びは φ 外側・θ 内側のループ順なので、
DIV_THETA 行ずつ切り出せば constant-φ の断面 1 枚になる。

リポジトリルートで:

    make al-03
"""

import csv
import math
import pathlib

import matplotlib
import numpy as np

matplotlib.use("Agg")  # 画面の無い環境でも PNG を書けるようにする
import matplotlib.pyplot as plt

from stellarator import SurfaceRZFourier

# cwd に依存しないよう、wout はこのファイルからの相対で引く。
WOUT = pathlib.Path(__file__).resolve().parent.parent / "stellarator" / "wout_vmec.nc"
OUT_CSV = pathlib.Path("results/al_03_surface_points.csv")
OUT_PNG = pathlib.Path("results/al_03_surface_points.png")

S = 1.0  # LCFS (プラズマ最外縁)。s>1 はスプライン外挿になる
DIV_PHI = 240  # トロイダル分割。nfp=4 なので 1 周期あたり 60 点
DIV_THETA = 64  # ポロイダル分割
# 真の 3D 曲面法線。False にすると constant-φ 断面内の 2D 法線 (parastell 互換)
USE_SURFACE = True

# rust 側 load は file-like を受けるので、開いて渡す。
with open(WOUT, "rb") as f:
    surface = SurfaceRZFourier.load(f)

points = np.empty((DIV_PHI, DIV_THETA, 3))
normals = np.empty((DIV_PHI, DIV_THETA, 3))
for i in range(DIV_PHI):
    phi = math.tau * i / DIV_PHI
    for j in range(DIV_THETA):
        theta = math.tau * j / DIV_THETA
        points[i, j], normals[i, j] = surface.point_normal(phi, theta, S, USE_SURFACE)

OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
with open(OUT_CSV, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["x", "y", "z", "nx", "ny", "nz"])
    writer.writerows(np.concatenate([points, normals], axis=2).reshape(-1, 6))
print(f"{OUT_CSV}: {DIV_PHI * DIV_THETA} 点 (s={S}, {DIV_PHI} x {DIV_THETA})")

# --- 3D 可視化 -----------------------------------------------------------
# φ=0 と φ=2π、θ=0 と θ=2π は同一点なので、先頭を末尾に足して継ぎ目を閉じる。
# これをしないとトーラスに 1 本スリットが入って見える。
closed = np.concatenate([points, points[:1]], axis=0)
closed = np.concatenate([closed, closed[:, :1]], axis=1)
x, y, z = closed[..., 0], closed[..., 1], closed[..., 2]

# 面の色は大半径 R = √(x²+y²)。内側 (小 R) と外側 (大 R) の別が一目で分かり、
# ヘリカルな R の振れがそのまま縞になる。Z で塗ると形状の焼き直しで情報が増えない。
r_major = np.hypot(x, y)
norm = plt.Normalize(r_major.min(), r_major.max())
# 単一色相の light→dark ランプ。レインボー系は大小の順序が読めないので使わない。
# 両端の白つぶれ/黒つぶれを避けて中央 75% だけ切り出す。切り出した側を colorbar にも
# 渡すので、凡例の色帯と面の色が厳密に一致する。
cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
    "blues_mid", plt.get_cmap("Blues")(np.linspace(0.15, 0.90, 256))
)

# このトーラスは扁平 (x,y が ±15 m に対し z は ±2.5 m) なので、
# 正方形のキャンバスだと上下が大きく余る。横長にして無駄な余白を減らす。
fig = plt.figure(figsize=(11, 6))
ax = fig.add_subplot(projection="3d")
ax.plot_surface(
    x, y, z,
    facecolors=cmap(norm(r_major)),
    rstride=1, cstride=1, linewidth=0, antialiased=False, shade=True,
)

# 法線は間引いて矢印で重ねる。全点に生やすと面が見えなくなる。
# なお図中の文字は ASCII に寄せてある。matplotlib 既定の DejaVu Sans は日本語グリフを
# 持たず、和文を入れると豆腐 (□) になるため。
step_phi, step_theta = 12, 8
p = points[::step_phi, ::step_theta].reshape(-1, 3)
n = normals[::step_phi, ::step_theta].reshape(-1, 3)
ax.quiver(
    p[:, 0], p[:, 1], p[:, 2], n[:, 0], n[:, 1], n[:, 2],
    length=1.5, color="#c1440e", linewidth=0.7, label="outward normal n",
)

# トーラスは扁平なので、軸ごとの実寸比を保たないと形が嘘になる。
ax.set_box_aspect((np.ptp(x), np.ptp(y), np.ptp(z)))
ax.set(xlabel="x [m]", ylabel="y [m]", zlabel="z [m]")
# z は x,y の 1/6 の高さしかないので、既定の目盛り本数だと数字が重なって潰れる。
ax.zaxis.set_major_locator(matplotlib.ticker.MaxNLocator(3))
ax.view_init(elev=38, azim=-55)
ax.grid(False)
for pane in (ax.xaxis, ax.yaxis, ax.zaxis):
    pane.pane.set_alpha(0.0)  # 背景の箱は情報を持たないので消す
ax.legend(loc="upper left", frameon=False)
# 縦置きにすると 3D 軸の z 目盛りと重なって両方読めなくなるので、下に横置きする。
fig.colorbar(
    plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax,
    orientation="horizontal", shrink=0.4, aspect=40, pad=0.0,
    label="major radius R = sqrt(x^2 + y^2) [m]",
)
ax.set_title(f"VMEC LCFS (s={S}) with outward normals - {DIV_PHI} x {DIV_THETA} grid")
fig.savefig(OUT_PNG, dpi=150, bbox_inches="tight")
print(f"{OUT_PNG}")
