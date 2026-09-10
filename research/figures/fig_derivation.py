
# -*- coding: utf-8 -*-
"""化學計量對帳的逐步推導圖：頭空體積為什麼會消掉，以及上限 0.25 從哪來。

三格：
  (a) 兩個狀態的莫耳盤點——起點與終點的頭空
  (b) 推導鏈，把 V/(RT) 標成同一個顏色，讓它在分子分母同時出現而相消
  (c) 化學計量上限，以及「起點分率若設錯就會衝破上限」的敏感度檢核

⚠ 壓力一律用**絕對壓**。錶壓轉絕對壓要加 1.033 kg/cm²；
  雖然只有壓力差進入最終比值、偏移會自動抵消，但分子的 f·P 是
  **分率乘壓力**、不是差，所以那裡非用絕對壓不可。這一點畫在圖上。
"""
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['mathtext.fontset'] = 'dejavusans'

B, R, G, O = '#1F6FB5', '#C0392B', '#666666', '#E8912B'
V = '#2E7D32'                     # V/(RT) 這個因子的專用色


def box(ax, x, y, w, h, fc, ec, lw=1.1):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle='round,pad=0.02,rounding_size=0.03',
                                facecolor=fc, edgecolor=ec, lw=lw,
                                zorder=2))


def main():
    # 兩頁呈現：第一頁講公式怎麼來，第二頁講怎麼反推。內容不重複。
    f1 = plt.figure(figsize=(14.2, 5.8))
    ga = f1.add_axes([0.030, 0.05, 0.42, 0.80])
    gb = f1.add_axes([0.530, 0.05, 0.44, 0.80])
    f2 = plt.figure(figsize=(14.2, 5.8))
    gc = f2.add_axes([0.030, 0.05, 0.42, 0.80])
    gd = f2.add_axes([0.530, 0.05, 0.44, 0.80])
    for a in (ga, gb, gc, gd):
        a.set_xlim(0, 1); a.set_ylim(0, 1); a.axis('off')

    # ── (a) 兩個狀態的盤點 ──
    ga.set_title('(a) 頭空的兩個狀態', fontweight='bold', fontsize=13)
    for i, (yy, lab, f, P, col) in enumerate(
            [(0.60, '起點（進氣後）', '9.50%', '2.212', B),
             (0.16, '終點（排氣前）', '31.64%', '2.118', R)]):
        box(ga, 0.06, yy, 0.88, 0.30, '#EAF2FA' if i == 0 else '#FDECEA',
            col)
        ga.text(0.50, yy + 0.235, lab, ha='center', fontsize=11.5,
                fontweight='bold', color=col)
        ga.text(0.50, yy + 0.145,
                r'$n = P\,V/(RT)$', ha='center', fontsize=13, color=V)
        ga.text(0.50, yy + 0.055,
                'P = %s kg/cm²(abs)   CH4 = %s' % (P, f),
                ha='center', fontsize=10.5, color=G)
    ga.add_patch(FancyArrowPatch((0.50, 0.585), (0.50, 0.475),
                                 arrowstyle='-|>', mutation_scale=14,
                                 lw=1.4, color=G))
    ga.text(0.54, 0.53, '114.5 hr、6 次補氣', fontsize=10, color=G,
            va='center')
    ga.text(0.50, 0.055,
            '必須用絕對壓：分子是分率×壓力，不是壓力差',
            ha='center', fontsize=10, color=R, fontweight='bold')

    # ── (b) 推導鏈 ──
    gb.set_title('(b) 頭空體積為什麼會消掉', fontweight='bold', fontsize=13)
    steps = [
        (0.790, 'CH4 生成量', r'$(f_2P_2-f_1P_1)\cdot V/(RT)$', 14),
        (0.575, '氣體消耗量', r'$(\dot{P}\cdot T_{tot})\cdot V/(RT)$', 14),
        (0.360, '相除', r'$\dfrac{(f_2P_2-f_1P_1)\;\cdot\;V/(RT)}'
                        r'{(\dot{P}\,T_{tot})\;\cdot\;V/(RT)}$', 12),
        (0.115, '結果', r'$\dfrac{f_2P_2-f_1P_1}{\dot{P}\,T_{tot}}$', 13),
    ]
    for yy, lab, eq, fs in steps:
        box(gb, 0.04, yy, 0.92, 0.14, 'white', G, .9)
        gb.text(0.10, yy + 0.070, lab, fontsize=10.5, color=G,
                va='center', fontweight='bold')
        gb.text(0.60, yy + 0.070, eq, fontsize=fs, color='black',
                ha='center', va='center')
    # 箭頭放在框與框之間的空隙（間距 0.055，扣掉 pad 後仍有餘裕）
    for y0 in (0.770, 0.555):
        gb.add_patch(FancyArrowPatch((0.50, y0 - 0.003), (0.50, y0 - 0.048),
                                     arrowstyle='-|>', mutation_scale=11,
                                     lw=1.2, color=G))
    gb.text(0.50, 0.307, '兩個 V/(RT) 相消', ha='center', fontsize=11.5,
            color=V, fontweight='bold')
    gb.text(0.50, 0.012, '★ 不需要知道頭空體積，也不需要知道溫度',
            ha='center', fontsize=11.5, color=V, fontweight='bold')

    # ── (c) 上限與敏感度 ──
    gc.set_title('(c) 上限 0.25 從哪裡來', fontweight='bold', fontsize=13)
    gc.text(0.50, 0.90, r'$\mathrm{CO_2 + 4H_2 \rightarrow CH_4 + 2H_2O}$',
            ha='center', fontsize=13.5, fontweight='bold')
    box(gc, 0.05, 0.60, 0.90, 0.21, '#EAF2FA', B)
    gc.text(0.50, 0.745, '5 個氣體分子進，1 個出', ha='center',
            fontsize=11.5, color=B, fontweight='bold')
    gc.text(0.50, 0.655, '淨少 4 個 → 每 4 個消耗產 1 個 CH4',
            ha='center', fontsize=10.5, color=G)
    gc.text(0.50, 0.505, 'CH4 ÷ 消耗  最多  1/4  =  0.25', ha='center',
            fontsize=14.5, color=R, fontweight='bold')
    gc.text(0.50, 0.425, '此上限由化學決定，不是擬合出來的',
            ha='center', fontsize=10, color=G)
    box(gc, 0.05, 0.10, 0.90, 0.27, '#FFF8E1', O)
    gc.text(0.50, 0.315, '敏感度檢核', ha='center', fontsize=11,
            fontweight='bold', color=O)
    gc.text(0.50, 0.225, '批次 1 實測 0.2172 < 0.25  通過', ha='center',
            fontsize=11, color=B)
    gc.text(0.50, 0.145, '若起點 CH4 誤設為 0% → 0.3164 > 0.25  不可能',
            ha='center', fontsize=10.5, color=R)


    # ── (d) 從比值反推 r_b ──
    gd.set_title('(d) 我們怎麼從比值反推出 r_b', fontweight='bold',
                 fontsize=13)
    gd.text(0.50, 0.955, '只有生物那一份會產甲烷，每 4 個消耗產 1 個',
            ha='center', fontsize=10.5, color=G)
    box(gd, 0.03, 0.795, 0.94, 0.115, '#EAF2FA', B, .9)
    gd.text(0.50, 0.8525,
            'CH4 ÷ 消耗  =  (1/4) × (生物 ÷ 消耗)  =  0.25 × s',
            ha='center', va='center', fontsize=14,
            color='black')

    chain = [
        (0.590, '① 測到的比值', '0.2172', B),
        (0.415, '② 除以 0.25 → 生物份額 s', '0.869', R),
        (0.240, '③ × 總下降速率 0.0185', '0.0161', R),
    ]
    for yy, lab, val, col in chain:
        box(gd, 0.03, yy, 0.94, 0.115, 'white', G, .9)
        gd.text(0.07, yy + 0.057, lab, fontsize=11.5, va='center',
                color=G if col is B else col, fontweight='bold')
        gd.text(0.90, yy + 0.057, val, fontsize=14, va='center',
                ha='right', color=col, fontweight='bold')
    gd.text(0.50, 0.130,
            'r_b = 0.0161 kg/cm²/hr（批次 1）', ha='center',
            fontsize=13, color=R, fontweight='bold')
    gd.text(0.50, 0.040,
            's 是生物佔總下降的比例；此處未涉頭空體積與溫度',
            ha='center', fontsize=10, color=G)

    D = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                     'docs', 'paper_figures')
    f1.suptitle('化學計量對帳（一）：公式怎麼來的', fontsize=15,
                fontweight='bold', y=0.985)
    f1.savefig(os.path.join(D, 'figW1_formula.png'), dpi=180,
               bbox_inches='tight')
    f2.suptitle('化學計量對帳（二）：怎麼從比值反推出速率', fontsize=15,
                fontweight='bold', y=0.985)
    f2.savefig(os.path.join(D, 'figW2_inference.png'), dpi=180,
               bbox_inches='tight')
    plt.close(f1); plt.close(f2)
    print('→ figW1_formula.png / figW2_inference.png')


if __name__ == '__main__':
    main()
