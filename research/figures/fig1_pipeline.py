
# -*- coding: utf-8 -*-
"""
Fig. 1 — 系統與探勘管線（Springer LNCS 規範）
════════════════════════════════════════════════════════════════════════

LNCS 規範對應：
  · 文寬 122 mm = 4.80 in（單欄）
  · **黑白印刷可讀**：不以顏色承載資訊，改用填色深淺、框線粗細、線型
  · 線寬 ≥ 0.5 pt
  · 字型內嵌（pdf.fonttype = 42 / TrueType）
  · 向量 PDF；圖說由 LaTeX 端加，圖內不含 "Fig. 1" 字樣

圖要傳達的核心：**反應器側只有一條壓力訊號，控制器層的訊號沒有被記錄**——
那是本文新穎性的來源（Iturbe et al. 需要控制器層變數，本裝置沒有）。

輸出 -> docs/paper_figures/fig1_pipeline.pdf / .png
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                                    # noqa: E402
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch     # noqa: E402

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(os.path.dirname(HERE), 'docs', 'paper_figures')
os.makedirs(FIG, exist_ok=True)

from paper_style import apply, W, U, PNG_DPI                                # noqa: E402
apply()                    # 字型／Type 42／存檔設定與其餘四張圖同源
H = 3.00                   # 122 mm 文寬；加高 0.20 in 以拉開左欄的垂直間距
# 註：本圖為示意圖，方塊內文字用 5.2–7.4 pt，較其餘圖的 6.8–7.5 pt 略小。
#     這是刻意的——流程圖的資訊密度高於一般座標圖；但字型與輸出設定完全一致。
# ═══ 版面預算（先算再配座標，不憑感覺）═══════════════════════════
# 字寬實測（DejaVu Sans，由算圖後量測反推，非估計）：
#   正常體 **0.059 in/字元 @6.6 pt**（先前估 0.049 太小，導致 Alg. 4 被切掉）
#   ⇒ 每 pt 約 0.0089 in/字元；粗體再多約 8%
# 行高：fontsize/72 in
#
# 左欄 0.285×4.80 = 1.37 in  ← 由 0.300 縮窄，把空間讓給面板間距
#   "recirculating reactor" 21 字元粗體 @6.5 pt = 1.16 in  → 餘 0.21 in ✓
#   "setpoint / valve / pump" 23 字元 @5.2 pt = 1.01 in（框寬 1.23 in）✓
# 間距 0.133×4.80 = 0.64 in  ← 由 0.108 拉寬 23%
#   "pressure" 8 字元粗體 @5.8 pt = 0.40 in → 左右各餘 0.12 in ✓
# 右欄 0.522×4.80 = 2.51 in，扣左內縮 0.018×4.80=0.086 → 可用 2.42 in
#   "Alg. 4  Calibrated change-point detection" 41 字元：
#     @6.6 pt = 41×0.059 = 2.42 in → **零餘裕，會被切掉**
#     @6.2 pt = 41×0.055 = 2.26 in → 餘 0.16 in ✓  ← 採用
#
# 左欄垂直（面板 0.380–0.960，即 1.74 in）由上而下：
#   標題 2 行 0.235 + 專利 0.079 + 容器 0.53 + P 框 0.144 + 規格 0.076
#   + 控制器框 0.21 + not logged 0.086 = 1.36 in，餘 0.38 in 分配為間隙
# ═══════════════════════════════════════════════════════════════
# 黑白安全的灰階（無彩色資訊）
INK = '#000000'
G = {'box': '#ffffff', 'soft': '#f0f0f0', 'mid': '#d9d9d9',
     'dark': '#9e9e9e', 'star': '#e2e2e2'}
FS, FST = 6.6, 7.0         # 內文 / 標題


def box(ax, x, y, w, h, label, fc=G['box'], lw=0.7, ls='-',
        fs=FS, weight='normal', pad=0.005, va='center', ha='center'):
    # ⚠ FancyBboxPatch 的 pad 是**往外加**的：框的實際尺寸為 (w+2·pad, h+2·pad)。
    #   先前用 pad=0.02 造成每個框都比指定值大 0.04，是版面互相碰撞的根因。
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle=f'round,pad={pad},rounding_size=0.015',
        linewidth=lw, edgecolor=INK, facecolor=fc, linestyle=ls, zorder=2))
    ax.text(x+w/2 if ha == 'center' else x+0.018, y+h/2, label,
            ha=ha, va=va, fontsize=fs, color=INK, zorder=3,
            fontweight=weight, linespacing=1.35)


def arrow(ax, p, q, lw=0.8, ls='-', style='-|>', ms=6):
    ax.add_patch(FancyArrowPatch(
        p, q, arrowstyle=style, mutation_scale=ms, linewidth=lw,
        linestyle=ls, color=INK, shrinkA=0, shrinkB=0, zorder=4))


def main():
    fig, ax = plt.subplots(figsize=(W, H))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis('off')

    PT, PB = 0.960, 0.380            # 兩個面板共用的上下緣

    # ══ 左：反應器 ═══════════════════════════════════════
    LX, LW = 0.012, 0.285
    ax.add_patch(FancyBboxPatch(
        (LX, PB), LW, PT-PB,
        boxstyle='round,pad=0.005,rounding_size=0.018',
        linewidth=0.9, edgecolor=INK, facecolor=G['soft'], zorder=1))
    CX = LX+LW/2

    # 標題（2 行）與專利號：先前兩者僅隔 0.002 而重疊，現拉開至 0.026
    ax.text(CX, 0.901, 'Micro-pressurized\nrecirculating reactor',
            ha='center', va='center', fontsize=6.5, fontweight='bold',
            linespacing=1.25)
    ax.text(CX, 0.836, 'patent TW I923176', ha='center', va='center',
            fontsize=5.6, style='italic', color='#444444')

    # 容器：頂空 + 液相
    vx, vw = LX+0.016, 0.138
    ax.add_patch(FancyBboxPatch((vx, 0.728), vw, 0.078,
                                boxstyle='square,pad=0', linewidth=0.7,
                                edgecolor=INK, facecolor=G['box'], zorder=2))
    ax.text(vx+vw/2, 0.767, 'headspace', ha='center', va='center', fontsize=6.0)
    ax.add_patch(FancyBboxPatch((vx, 0.628), vw, 0.100,
                                boxstyle='square,pad=0', linewidth=0.7,
                                edgecolor=INK, facecolor=G['mid'], zorder=2))
    ax.text(vx+vw/2, 0.678, 'liquid', ha='center', va='center', fontsize=6.0)

    # 循環泵（雙向）
    arrow(ax, (vx+vw+0.012, 0.674), (vx+vw+0.012, 0.770), lw=0.7, ms=5)
    arrow(ax, (vx+vw+0.026, 0.770), (vx+vw+0.026, 0.674), lw=0.7, ms=5)
    ax.text(vx+vw+0.034, 0.722, 'pump\n' r'$\tau$ ' + U['duty'],
            ha='left', va='center', fontsize=5.5, linespacing=1.25)

    # 壓力感測器
    # ⚠ 取樣規格（1 min⁻¹、0.01 kg cm⁻²）**刻意不畫在圖裡**：
    #   圖說已載明，畫進來只會把下半部擠成四行密集文字——規格文字距虛線框
    #   僅 0.015 in、"not logged" 距框底僅 0.036 in，視覺上黏成一團。
    #   移除後下半部只剩三個元素，間距可拉開至 0.06–0.09 in。
    PW, PAD = 0.052, 0.005          # PAD 與 box() 的預設 pad 一致
    PY, PH = 0.540, 0.048
    box(ax, vx, PY, PW, PH, 'P', lw=1.0, weight='bold', fs=7.4, pad=PAD)
    # liquid 底（0.628）→ P 框頂（含 pad）：先前只隔 0.016，箭頭幾乎看不見
    arrow(ax, (vx+PW/2, 0.628), (vx+PW/2, PY+PH+PAD+0.003), lw=0.7, ms=5)
    # ⚠ 起點必須是**含 pad 的框緣** vx+PW+PAD；用 vx+PW 會讓線頭落在框內側
    ax.plot([vx+PW+PAD, LX+LW], [PY+PH/2, PY+PH/2], color=INK, lw=1.1,
            zorder=4)

    # 未被記錄的控制器層
    #   P 框底（含 pad）0.535 → 虛線框頂（含 pad）0.515：間隙 0.06 in
    #   虛線框底（含 pad）0.435 → "not logged" 頂 0.416：間隙 0.057 in
    #   "not logged" 底 0.394 → 面板底 0.380：間隙 0.042 in
    box(ax, LX+0.014, 0.440, LW-0.028, 0.070,
        'controller signals\nsetpoint / valve / pump',
        ls=(0, (2.2, 1.6)), fc=G['box'], lw=0.7, fs=5.4)
    ax.text(CX, 0.405, r'$\times$  not logged', ha='center',
            va='center', fontsize=6.2, fontweight='bold')

    # ══ 右：管線 ═════════════════════════════════════════
    px, pw = 0.448, 0.522
    ax.add_patch(FancyBboxPatch(
        (px-0.018, PB), pw+0.036, PT-PB,
        boxstyle='round,pad=0.005,rounding_size=0.018',
        linewidth=0.9, edgecolor=INK, facecolor=G['box'], zorder=1))
    ax.text(px+pw/2, 0.931, 'Edge-side mining pipeline',
            ha='center', va='center', fontsize=FST, fontweight='bold')
    ax.text(px+pw/2, 0.893,
            r'single-pass,  O(1) state,  $\leq$ 60 MB', ha='center',
            va='center', fontsize=5.6, style='italic', color='#444444')

    stages = [
        ('Alg. 1  Streaming cycle segmentation', False),
        ('Alg. 2  Weak-form rate estimation', False),
        ('Alg. 3  Control–response partitioning', True),
        ('Alg. 4  Calibrated change-point detection', False),
        ('Alg. 5  Event typology + gap masking', False),
    ]
    # 5 個框 + 4 個間隙恰好填滿 0.855 → 0.401，底部留 0.021 邊距
    y0, hh, gap = 0.785, 0.070, 0.026
    for i, (lab, star) in enumerate(stages):
        y = y0-i*(hh+gap)
        # Alg. 3 以「加粗外框 + 灰底 + 粗體字」三重標示即可。
        # 先前另在左緣畫一條 lw=2.6 的粗線，讀起來像一塊來歷不明的黑色長方形，已移除。
        box(ax, px, y, pw, hh, lab, fc=(G['star'] if star else G['box']),
            lw=(1.6 if star else 0.7), ha='left', fs=6.2,
            weight=('bold' if star else 'normal'))
        if i:
            arrow(ax, (px+0.028, y+hh+gap-0.004), (px+0.028, y+hh+0.004),
                  lw=0.7, ms=5)

    # ══ 面板之間 ═════════════════════════════════════════
    # 間隙 0.297→0.430 共 0.133（0.64 in）。"pressure" 8 字元粗體 @5.8 pt
    # = 0.40 in = 0.083，置中後左右各餘 0.025，遠離兩側圓角邊框。
    ay = PY+PH/2
    arrow(ax, (LX+LW, ay), (px-0.020, ay), lw=1.1, ms=7)
    # 註：左半的水平線由 P 框緣（vx+PW+PAD）畫到 LX+LW，與此箭頭同高，
    #     兩段接續成一條「P → 管線」的連續路徑。
    ax.text((LX+LW+px-0.020)/2, ay+0.018, 'pressure\nonly', ha='center',
            va='bottom', fontsize=5.8, fontweight='bold', linespacing=1.3)

    # ══ 下：產出 ══════════════════════════════════════════
    outs = ['Setpoint history\n8 changes',
            'Manual interventions\n18 vents',
            'Mass-transfer state\n5 duty cycles']
    ow, oy, oh = 0.298, 0.100, 0.115
    for i, o in enumerate(outs):
        x = 0.022+i*(ow+0.031)
        box(ax, x, oy, ow, oh, o, fc=G['soft'], lw=0.7, fs=FS)
        arrow(ax, (px+0.028, 0.374), (x+ow/2, oy+oh+0.010), lw=0.7, ms=5,
              ls=('-' if i == 1 else (0, (3, 2))))

    for ext in ('pdf', 'png'):
        fig.savefig(os.path.join(FIG, f'fig1_pipeline.{ext}'),
                    dpi=(PNG_DPI if ext == 'png' else None))
    plt.close(fig)
    print('══ Fig. 1（LNCS 規範）══')
    print(f'   ✓ fig1_pipeline.pdf / .png   →  {FIG}')
    print(f'   寬 {W} in = 122 mm（LNCS 單欄文寬）')
    print('   ✓ 黑白可讀（不以顏色承載資訊）  ✓ 線寬 ≥ 0.5 pt  ✓ 字型內嵌 Type 42')


if __name__ == '__main__':
    main()
