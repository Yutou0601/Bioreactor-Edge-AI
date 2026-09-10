
# -*- coding: utf-8 -*-
"""階梯式分壓示意圖——供 Fig.1(b) 半寬使用的版本。

為什麼要另做一份：原圖畫在 122 mm 全寬、字級 FS_NOTE=6.2 pt。放到
Fig.1(b) 的 82 mm 寬時，字會縮成 4.2 pt，完全讀不了。把畫布縮小、
字級不動可以讓字恢復可讀，但方框是硬座標、不會跟著長，於是
Premix tank、Optical analyser、Pump、各閥都會溢出。

這份的作法：**版面語彙完全沿用原圖**（同樣的圓角方框、圓圈閥、
正交走線、三區虛線與壓力層級），只把方框加寬、間距拉開，讓放大後
的文字裝得下。y 座標與配色一律不動。

⚠ 原圖 fig_pressure_cascade.py 保持不變，仍供全寬場合使用。
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, FancyBboxPatch

KX = 1.234   # x 軸單位較密，圓要補這個倍率才和原圖同形

from fig_pressure_cascade import AX, FIGDIR, flow
from paper_style import C, FS_NOTE, FS_SMALL, apply, save

WN = 3.23                        # 82 mm ≒ 3.23 in


def vessel(ax, x, y, w, h, cap, sub=None, liquid=0.0):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle='round,pad=0.02,rounding_size=0.07',
        facecolor=C['fill'], edgecolor=C['main'], lw=.9, zorder=2))
    if liquid > 0:
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h * liquid,
            boxstyle='round,pad=0.02,rounding_size=0.07',
            facecolor=C['sec'], edgecolor='none', alpha=.35, zorder=3))
    cy = y + h / 2
    if sub:
        ax.text(x + w / 2, cy + 0.17, cap, ha='center', va='center',
                fontsize=FS_NOTE, zorder=5)
        ax.text(x + w / 2, cy - 0.17, sub, ha='center', va='center',
                fontsize=FS_NOTE, color=C['main'], zorder=5)
    else:
        ax.text(x + w / 2, cy, cap, ha='center', va='center',
                fontsize=FS_NOTE, zorder=5)


def valve(ax, x, y, n):
    ax.add_patch(Ellipse((x, y), 2*.30*KX, 2*.30, facecolor='white',
                         edgecolor=C['main'], lw=.9, zorder=4))
    ax.text(x, y, 'V' + str(n), ha='center', va='center',
            fontsize=FS_NOTE, zorder=5)


def main():
    apply()
    fig, ax = plt.subplots(figsize=(WN, 2.18 * WN / 4.80))

    # ── Reactant ───────────────────────────────────────────
    vessel(ax, -.30, AX + .20, 1.20, .80, '3L', 'H$_2$')
    vessel(ax, -.30, AX - 1.04, 1.20, .80, '3L', 'CO$_2$')
    valve(ax, 1.85, AX + .60, 2)
    valve(ax, 1.85, AX - .64, 1)
    flow(ax, (.90, AX + .60), (1.51, AX + .60))
    flow(ax, (.90, AX - .64), (1.51, AX - .64))
    vessel(ax, 2.50, AX - .50, 2.60, 1.00, 'Premix tank', '1L,  4:1')
    flow(ax, (2.15, AX + .60), (2.50, AX + .28))
    flow(ax, (2.15, AX - .64), (2.50, AX - .30))

    # ── Culture ────────────────────────────────────────────
    valve(ax, 5.80, AX, 3)
    flow(ax, (5.10, AX), (5.42, AX))
    vessel(ax, 6.50, AX - 1.05, 2.75, 1.90, '', liquid=.52)
    ax.text(7.88, AX + .72, '5L reactor', ha='center', va='center',
            fontsize=FS_NOTE, zorder=5)
    flow(ax, (6.20, AX), (6.50, AX))
    ax.add_patch(Ellipse((7.95, AX + .22), 2*.26*KX, 2*.26,
                         facecolor='white', edgecolor=C['accent'],
                         lw=1.0, zorder=5))
    ax.text(7.95, AX + .22, 'PT', ha='center', va='center',
            fontsize=FS_NOTE, color=C['accent'], zorder=6)
    ax.add_patch(Ellipse((8.90, AX - 1.58), 2*.26*KX, 2*.26,
                         facecolor='white', edgecolor=C['main'],
                         lw=.9, zorder=4))
    ax.plot([8.74, 8.74, 9.06], [AX - 1.69, AX - 1.47, AX - 1.58],
            lw=.9, color=C['main'], zorder=5)
    ax.text(8.40, AX - 1.58, 'Pump', ha='right', va='center',
            fontsize=FS_NOTE, color=C['main'], zorder=5)
    # 轉角用純線條，只在終點放箭頭（沿用原圖的處理）
    ax.plot([9.25, 8.90, 8.90], [AX + .62, AX + .62, AX - 1.32],
            lw=1.0, color=C['main'], solid_joinstyle='miter', zorder=1)
    ax.plot([8.90, 5.92, 5.92], [AX - 1.84, AX - 1.84, AX - .85],
            lw=1.0, color=C['main'], solid_joinstyle='miter', zorder=1)
    ax.annotate('', xy=(6.95, AX - .85), xytext=(5.92, AX - .85),
                zorder=6,
                arrowprops=dict(arrowstyle='-|>', lw=1.0,
                                color=C['main'], shrinkA=0, shrinkB=0))
    for bx in (7.35, 7.85, 8.35):
        ax.plot([bx, bx], [AX - 1.02, AX - .40], ls=':', lw=.7,
                color=C['main'], zorder=4)

    # ── Product ────────────────────────────────────────────
    valve(ax, 10.55, AX + .62, 4)
    ax.plot([9.25, 10.18], [AX + .62, AX + .62], lw=1.0,
            color=C['main'], zorder=1)
    vessel(ax, 11.60, AX + .20, 3.85, .80, 'Optical analyser', 'CH$_4$')
    vessel(ax, 11.60, AX - 1.04, 3.85, .80, 'Optical analyser', 'CO$_2$')
    ax.plot([10.92, 11.10], [AX + .62, AX + .62], lw=1.0,
            color=C['main'], zorder=1)
    ax.plot([11.10, 11.10], [AX + .62, AX - .64], lw=1.0,
            color=C['main'], zorder=1)
    flow(ax, (11.10, AX + .62), (11.60, AX + .62))
    flow(ax, (11.10, AX - .64), (11.60, AX - .64))

    # ── 分區 ───────────────────────────────────────────────
    for xz in (5.32, 9.95):
        ax.plot([xz, xz], [AX - 2.33, AX + 1.25], ls=(0, (4, 3)), lw=.8,
                color=C['main'], alpha=.55, zorder=0)
    for xm, name, lim in ((2.30, 'Reactant system', '6'),
                          (7.60, 'Culture system', '1.5'),
                          (13.30, 'Product system', '1')):
        ax.text(xm, AX - 2.06, name, ha='center', va='center',
                fontsize=FS_SMALL, fontweight='bold')
        ax.text(xm, AX - 2.31, f'up to {lim} kg/cm$^2$', ha='center',
                va='center', fontsize=FS_NOTE, color=C['main'])
    ax.text(7.75, AX - 2.66,
            'V1-V4 = Gate valves      PT = Pressure transducer',
            ha='center', va='center', fontsize=FS_NOTE, color=C['main'])

    ax.set_xlim(-.55, 15.65)
    ax.set_ylim(AX - 2.86, AX + 1.32)
    ax.axis('off')
    fig.tight_layout(pad=0.12)
    save(fig, 'figE_cascade_narrow', FIGDIR)


if __name__ == '__main__':
    main()
