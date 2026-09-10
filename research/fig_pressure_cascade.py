
# -*- coding: utf-8 -*-
"""設備架構圖：微正壓循環控制系統。
════════════════════════════════════════════════════════════════════════

依洪博簡報「解決方法」的系統流程繪製，全英文：

  Reactant system  3 L H2 + 3 L CO2 -> 閥1/閥2 -> 1 L 混合槽（4:1）
  Culture system   閥3 -> 5 L 反應槽（液相＋頂空），循環泵頂空抽氣底部進氣
  Product system   閥4 -> 光學式 CH4/CO2 感測

⚠ 這張圖只畫**設備架構**。先前版本額外疊了壓力階梯線、Δ0.4 壓差標註、
  工作週期鋸齒波——資訊愈加愈多，架構本身反而看不出來。使用者指出後
  全部移除。壓力層級只在區名下方以一行文字帶過，不畫成圖形。

⚠ 槽體規格與壓力來自設備方簡報，未自行推算。
輸出 -> docs/paper_figures/figE_pressure_cascade.{pdf,svg,png}
"""
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import matplotlib.pyplot as plt                                    # noqa: E402
from matplotlib.patches import FancyBboxPatch, Circle              # noqa: E402

from paper_style import apply, save, W, C, FS_NOTE, FS_SMALL       # noqa: E402
from analyze_three_batches import OUT                              # noqa: E402

FIGDIR = os.path.join(os.path.dirname(OUT), 'paper_figures')
AX = 1.90                        # 主流程軸線，所有槽體對齊它


def vessel(ax, x, y, w, h, cap, sub=None, liquid=0.0):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle='round,pad=0.02,rounding_size=0.07',
        facecolor=C['fill'], edgecolor=C['main'], lw=.9, zorder=2))
    if liquid > 0:
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h*liquid,
            boxstyle='round,pad=0.02,rounding_size=0.07',
            facecolor=C['sec'], edgecolor='none', alpha=.35, zorder=3))
    cy = y+h/2
    if sub:
        ax.text(x+w/2, cy+0.15, cap, ha='center', va='center',
                fontsize=FS_NOTE, zorder=5)
        ax.text(x+w/2, cy-0.15, sub, ha='center', va='center',
                fontsize=FS_NOTE, color=C['main'], zorder=5)
    else:
        ax.text(x+w/2, cy, cap, ha='center', va='center',
                fontsize=FS_NOTE, zorder=5)


def valve(ax, x, y, n):
    """閘閥：圓圈內標 V1..V4。

    ⚠ 閥門型式（閘閥）由使用者指定，簡報上只寫「閥1~閥4」。
    若現場實際是球閥／電磁閥／針閥，這行圖例要跟著改。
    """
    ax.add_patch(Circle((x, y), .21, facecolor='white',
                        edgecolor=C['main'], lw=.9, zorder=4))
    ax.text(x, y, 'V'+str(n), ha='center', va='center',
            fontsize=FS_NOTE, zorder=5)


def flow(ax, p, q):
    ax.annotate('', xy=q, xytext=p, zorder=1,
                arrowprops=dict(arrowstyle='-|>', lw=1.0, color=C['main'],
                                shrinkA=2, shrinkB=2))


def main():
    os.makedirs(FIGDIR, exist_ok=True)
    apply()
    fig, ax = plt.subplots(figsize=(W, 2.18))

    # ── Reactant ───────────────────────────────────────────
    vessel(ax, -.30, AX+.20, .95, .80, '3L', 'H$_2$')
    vessel(ax, -.30, AX-1.04, .95, .80, '3L', 'CO$_2$')
    valve(ax, 1.50, AX+.60, 2)
    valve(ax, 1.50, AX-.64, 1)
    flow(ax, (.65, AX+.60), (1.29, AX+.60))
    flow(ax, (.65, AX-.64), (1.29, AX-.64))
    vessel(ax, 2.05, AX-.50, 1.50, 1.00, 'Premix tank', '1L,  4:1')
    flow(ax, (1.71, AX+.60), (2.05, AX+.28))
    flow(ax, (1.71, AX-.64), (2.05, AX-.30))

    # ── Culture ────────────────────────────────────────────
    valve(ax, 4.25, AX, 3)
    flow(ax, (3.55, AX), (4.04, AX))
    vessel(ax, 4.90, AX-1.05, 1.95, 1.90, '', liquid=.52)
    ax.text(5.88, AX+.72, '5L reactor', ha='center', va='center',
            fontsize=FS_NOTE, zorder=5)
    flow(ax, (4.46, AX), (4.90, AX))
    ax.add_patch(Circle((6.46, AX+.22), .23, facecolor='white',
                        edgecolor=C['accent'], lw=1.0, zorder=5))
    ax.text(6.46, AX+.22, 'PT', ha='center', va='center',
            fontsize=FS_NOTE, color=C['accent'], zorder=6)
    ax.add_patch(Circle((7.25, AX-1.58), .23, facecolor='white',
                        edgecolor=C['main'], lw=.9, zorder=4))
    ax.plot([7.13, 7.13, 7.37], [AX-1.68, AX-1.48, AX-1.58],
            lw=.9, color=C['main'], zorder=5)
    ax.text(6.95, AX-1.58, 'Pump', ha='right', va='center',
            fontsize=FS_NOTE, color=C['main'], zorder=5)
    # ⚠ 管路的**轉角不要放箭頭**。先前每一段都用 flow()，於是路徑上出現
    #   三個中途箭頭，看起來像三條斷掉的線而不是一條管路。
    #   轉角用純線條，只在終點放一個箭頭。
    ax.plot([6.85, 7.25, 7.25], [AX+.62, AX+.62, AX-1.37],
            lw=1.0, color=C['main'], solid_joinstyle='miter', zorder=1)
    ax.plot([7.25, 4.35, 4.35], [AX-1.79, AX-1.79, AX-.85],
            lw=1.0, color=C['main'], solid_joinstyle='miter', zorder=1)
    # ⚠ flow() 的 zorder=1 在槽體（zorder=2）之下，箭頭會被槽體蓋住。
    #   進入槽體的這一段要畫在上層才看得見。
    ax.annotate('', xy=(5.32, AX-.85), xytext=(4.35, AX-.85), zorder=6,
                arrowprops=dict(arrowstyle='-|>', lw=1.0,
                                color=C['main'], shrinkA=0, shrinkB=0))
    for bx in (5.55, 5.95, 6.35):
        ax.plot([bx, bx], [AX-1.02, AX-.40], ls=':', lw=.7,
                color=C['main'], zorder=4)

    # ── Product ────────────────────────────────────────────
    valve(ax, 8.55, AX+.62, 4)
    ax.plot([7.25, 8.34], [AX+.62, AX+.62], lw=1.0,
            color=C['main'], zorder=1)
    vessel(ax, 9.38, AX+.20, 2.20, .80, 'Optical analyser', 'CH$_4$')
    vessel(ax, 9.38, AX-1.04, 2.20, .80, 'Optical analyser', 'CO$_2$')
    # ⚠ 分流要正交走線，與泵迴路同一種畫法。先前兩支都從 V4 斜拉，
    #   下面那支斜穿過整個 Product 區，看起來就是變形的箭頭。
    ax.plot([8.74, 8.88], [AX+.62, AX+.62], lw=1.0, color=C['main'],
            zorder=1)
    ax.plot([8.88, 8.88], [AX+.62, AX-.64], lw=1.0, color=C['main'],
            zorder=1)
    flow(ax, (8.88, AX+.62), (9.38, AX+.62))
    flow(ax, (8.88, AX-.64), (9.38, AX-.64))

    # ── 分區 ───────────────────────────────────────────────
    for xz in (3.92, 8.06):
        ax.plot([xz, xz], [AX-2.28, AX+1.25], ls=(0, (4, 3)), lw=.8,
                color=C['main'], alpha=.55, zorder=0)
    for xm, name, lim in ((1.70, 'Reactant system', '6'),
                          (5.99, 'Culture system', '1.5'),
                          (10.30, 'Product system', '1')):
        ax.text(xm, AX-2.02, name, ha='center', va='center',
                fontsize=FS_SMALL, fontweight='bold')
        ax.text(xm, AX-2.26, f'up to {lim} kg/cm$^2$', ha='center',
                va='center', fontsize=FS_NOTE, color=C['main'])

    ax.text(5.93, AX-2.60,
            'V1-V4 = Gate valves      PT = Pressure transducer',
            ha='center', va='center', fontsize=FS_NOTE, color=C['main'])

    ax.set_xlim(-.52, 11.72)
    ax.set_ylim(AX-2.80, AX+1.32)
    ax.axis('off')
    fig.tight_layout(pad=0.12)
    save(fig, 'figE_pressure_cascade', FIGDIR)


if __name__ == '__main__':
    main()
