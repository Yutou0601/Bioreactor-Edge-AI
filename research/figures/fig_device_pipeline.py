
# -*- coding: utf-8 -*-
"""
新圖組（三）：微正壓循環裝置 ＝ 內生激發的來源，與探勘管線
════════════════════════════════════════════════════════════════════════

改版的核心敘事：**裝置不是背景，是 r_b 能被量出來的前提**。
閾值觸發補氣使反應器每天自發產生約 2.2 次弛豫實驗，351 段軌跡
**全部來自正常生產**，未施加任何外部擾動。

  (a) 裝置與觸發迴路 —— 控制器狀態**不被記錄**，只有壓力（量化 0.01）
  (b) 實測壓力軌跡 —— 每一段下降就是一次弛豫實驗
  (c) 探勘管線 —— Alg.1 → Alg.2 → 擬合 → Alg.3 → Alg.4

⚠ 繪圖既有教訓（先前踩過）：
  · FancyBboxPatch 的 pad 是**往外加**的，框會比算出來的大
  · 6.6 pt 下字寬實測約 0.059 in/char，不是 0.049
  ⇒ 本檔一律用 Rectangle ＋ 由字數反推寬度，並留固定邊距。

輸出 -> docs/paper_figures/
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import glob

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import matplotlib.pyplot as plt                                    # noqa: E402
from matplotlib.patches import Rectangle, FancyArrow              # noqa: E402
import matplotlib.gridspec as gridspec                            # noqa: E402

from paper_style import apply, save, W, C, U, FS_NOTE, FS_SMALL    # noqa: E402
from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import TD                                 # noqa: E402
from multivariate_increments import load4                          # noqa: E402

FIGDIR = os.path.join(os.path.dirname(OUT), 'paper_figures')


def box(ax, cx, cy, lines, fs=FS_SMALL, pad_pt=4.2, fc='white',
        ec=None, lw=.7, ls='-', left=None):
    """置中文字方塊：**先畫字、量實際 bbox、再依量測畫框**。

    ⚠ 不要用字數估寬度。先前 fig1 用估的（0.049 in/char）結果實際是
      0.059，字被裁掉；本檔初版改用 axes 比例估，又因為「各 axes 不是
      滿版寬，axes 比例 ≠ 圖比例」而全部包不住。量測是唯一可靠的做法。
    """
    fig = ax.figure
    t = ax.text(cx, cy, '\n'.join(lines), ha='center', va='center',
                fontsize=fs, zorder=4, linespacing=1.35)
    fig.canvas.draw()
    bb = t.get_window_extent(renderer=fig.canvas.get_renderer())
    p = pad_pt*fig.dpi/72.0                       # points → pixels
    # ⚠⚠ 這裡原本用 transAxes.inverted()，回傳的是 **axes 比例 0–1**；
    #   但文字是放在**資料座標**，而本面板的座標範圍是 [-0.06, 1.06]。
    #   兩者差一個平移與縮放，所以框一直被畫在跟文字不同的位置——
    #   我先前所有的「間距計算」全都建立在錯的座標上，才會改一輪撞一輪。
    #   必須用 transData。
    inv = ax.transData.inverted()
    (x0, y0), (x1, y1) = inv.transform(
        ((bb.x0-p, bb.y0-p), (bb.x1+p, bb.y1+p)))
    # ⚠ `left=` 指定**左緣**而非中心。框寬是量測出來的，事先不知道，
    #   所以用猜的 cx 一定對不準——右欄的框就這樣一再壓到反應器本體。
    #   量到寬度後把文字移到 left+w/2 再重量一次，左緣就精準對齊。
    if left is not None:
        t.set_x(left+(x1-x0)/2)
        fig.canvas.draw()
        bb = t.get_window_extent(renderer=fig.canvas.get_renderer())
        (x0, y0), (x1, y1) = inv.transform(
            ((bb.x0-p, bb.y0-p), (bb.x1+p, bb.y1+p)))
    ax.add_patch(Rectangle((x0, y0), x1-x0, y1-y0, facecolor=fc,
                           edgecolor=(ec or C['main']), lw=lw, ls=ls,
                           zorder=3))
    BOXES.append((id(ax), lines[0][:18], x0, y0, x1, y1))
    return x1-x0, y1-y0


BOXES = []          # (axes_id, label, x0, y0, x1, y1)，供 check_overlaps()


def check_overlaps(tol=0.004):
    """列出所有相交或幾乎相接的方塊。

    ⚠ 先前靠目視縮圖判斷有沒有相碰，改了四五輪都還在碰。方塊的座標
      本來就在程式裡，直接兩兩比對是確定性的，不必用眼睛猜。
    """
    bad = []
    for i in range(len(BOXES)):
        for j in range(i+1, len(BOXES)):
            a, b = BOXES[i], BOXES[j]
            if a[0] != b[0]:          # 不同面板不可比
                continue
            ox = min(a[4], b[4])-max(a[2], b[2])
            oy = min(a[5], b[5])-max(a[3], b[3])
            if ox > -tol and oy > -tol:
                bad.append((a[1], b[1], ox, oy))
    if bad:
        print('   ✘ 方塊相碰／過近：')
        for n1, n2, ox, oy in bad:
            print(f'      {n1:<20} × {n2:<20} '
                  f'重疊 x={ox:+.3f}  y={oy:+.3f}')
    else:
        print(f'   ✓ {len(BOXES)} 個方塊兩兩皆不相交（間距 > {tol}）')
    return not bad


def arrow(ax, x0, y0, x1, y1, ls='-', color=None, lw=.8):
    """⚠ zorder 必須高於方塊（方塊是 3）。原本設 2，箭頭尖端被方塊蓋住，
    畫出來只剩一條豎線，看起來像沒有箭頭。"""
    ax.annotate('', xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle='-|>,head_width=.16,head_length=.34',
                                lw=lw, ls=ls, color=(color or C['ink']),
                                shrinkA=0, shrinkB=0), zorder=6)


def load_window():
    """取一段實測壓力，涵蓋數個完整循環。"""
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        subs = [p]+[os.path.join(p, s) for s in
                    (os.listdir(p) if os.path.isdir(p) else [])]
        for sp in subs:
            if not os.path.isdir(sp) or not glob.glob(f'{sp}/*.csv'):
                continue
            try:
                raw = load4(sp)
            except Exception:
                continue
            if len(raw) < 4000:
                continue
            ts = [r[0] for r in raw]
            P = np.array([r[1] for r in raw])
            h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
            # ⚠ 初版只要求「壓力全距 > 0.15」，取到的視窗裡只有 **1 次**
            #   補氣，鋸齒完全看不出來，圖說「每一段下降就是一次實驗」
            #   反而沒被畫面支持。改成**要求視窗內至少 3 次觸發**。
            # numpy 2.x 移除了 ndarray.ptp() 方法，改用 np.ptp()
            for t0 in range(0, max(int(h[-1])-96, 1), 12):
                m = (h >= t0) & (h <= t0+96)
                if m.sum() < 1500:
                    continue
                if int((np.diff(P[m]) > 0.03).sum()) >= 3 \
                        and np.ptp(P[m]) > 0.15:
                    return h[m]-h[m][0], P[m]
    return None, None


def main():
    os.makedirs(FIGDIR, exist_ok=True)
    print('══ 新圖組（三）══\n')
    apply()
    # 高度由 3.45 收到 2.80 in：這是四張圖裡最佔版面的一張，而 10 頁是硬上限。
    # 面板 (b) 已移除（與 figF 的架構圖重複），畫布隨之收高。
    # ⚠ 寬度改為 3.33"（ACM 單欄）而非 W=4.80"：一條時間序列用跨欄
    #   6.89" 排是浪費，而畫布寬度必須等於實際排版寬度，字級才正確。
    fig = plt.figure(figsize=(3.33, 1.25))
    # (a) 的方塊是量測後才畫的，欄位太窄就一定會互相擠。把寬度從 0.90
    # 加到 1.18、(b) 縮到 0.82——同樣的文字在較寬的 axes 裡佔的比例更小。
    # (a) 的座標現在由內容自動撐開（見下方 set_xlim/set_ylim），
    # 不再需要靠欄寬硬擠，所以把寬度還給 (b)。
    # wspace 由 .20 加到 .34：(b) 的左緣（y 軸標籤）原本快貼到 (a) 的
    # 「P < threshold」框。加大欄間距等於把 (b) 的左側往右收，右緣不動。
    # 面板 (a) 已移除（與 Fig. 1 重複），改為兩列一欄。
    gs = gridspec.GridSpec(1, 1, figure=fig)

    # ⚠ 面板 (a) 與 Fig. 1 重複，整段停用（保留供日後參考）。
    # # ── (a) 裝置與觸發迴路 ──────────────────────────────
    # ax = fig.add_subplot(gs[0, 0]); ax.axis('off')
    # # ⚠ 座標放寬到 [-0.06, 1.06]：方塊是**量測後**才畫的，尺寸事先不知道，
    # #   若把範圍鎖在 [0,1]，貼邊的框會被裁掉。留邊界比事後調位置可靠。
    # ax.set_xlim(-0.06, 1.06); ax.set_ylim(-0.06, 1.06)
    # ax.set_title('(a)  Reactor and trigger loop', loc='left')

    # # ⚠ 位置一律以「量測後的實際框寬」為準重排。初版的座標是照舊版
    # #   （尺寸估錯而偏小的）方塊排的，改成量測式之後右側兩框就壓到本體。
    # # 反應器本體 —— 收窄到 x∈[.16,.44]，把右半留給感測與控制器
    # # 本體 x∈[.12,.46]；液相 .20–.45、氣相 .45–.64，兩個標籤各自置中於
    # # 自己那一段（liquid → .325、headspace → .545）。
    # # 本體 x∈[.10,.44]、y∈[.20,.70]（拉高以吃滿垂直空間）；
    # # 液相 .20–.47、氣相 .47–.70，兩個標籤各自置中於自己那一段。
    # # ⚠ facecolor 原為 'white' 且 zorder=3，把 zorder=2 的液相填色整個蓋掉，
    # #   所以底色一直看不見。外框改成不填色，讓填色透出來。
    # # ⚠ 進氣閥框的實測高度是 **0.346**（面板矮、y 範圍 1.12，兩行 6.2pt 就
    # #   佔掉三分之一）。本體頂端原本在 .70，上方根本塞不下它——放低會撞、
    # #   放高會被面板上緣切掉。解法是把本體整個下移騰出空間。
    # # 本體下移並略為放寬，看起來接近正方形；上方騰出的空間讓
    # # 「gas inlet → headspace」那支箭頭有明顯長度。
    # # 寬度要留得住 'headspace'（本體內最長的字），高度取相近值讓它接近正方形。
    # RX0, RX1 = .08, .54
    # RY0, RY1, LY = .02, .50, .28        # 本體下緣／上緣／液面
    # ax.add_patch(Rectangle((RX0, RY0), RX1-RX0, RY1-RY0, facecolor='none',
    #                        edgecolor=C['main'], lw=1.0, zorder=3))
    # # ⚠ 外框原為 facecolor='white' 且 zorder=3，把 zorder=2 的液相填色蓋掉，
    # #   底色一直看不見；改成不填色讓它透出來。
    # ax.add_patch(Rectangle((RX0, RY0), RX1-RX0, LY-RY0, facecolor=C['fill'],
    #                        edgecolor='none', alpha=.95, zorder=2))
    # BOXES.append((id(ax), 'reactor body', RX0, RY0, RX1, RY1))
    # ax.text((RX0+RX1)/2, (RY0+LY)/2, 'liquid', ha='center', va='center',
    #         fontsize=FS_NOTE, zorder=4)
    # ax.text((RX0+RX1)/2, (LY+RY1)/2, 'headspace', ha='center', va='center',
    #         fontsize=FS_NOTE, zorder=4)

    # # 循環迴路（走本體左外側）
    # ax.plot([RX0, RX0-.075, RX0-.075, RX0], [RY0+.06, RY0+.06, RY1-.06, RY1-.06],
    #         color=C['sec'], lw=.9, zorder=2)
    # arrow(ax, RX0-.075, RY1-.10, RX0-.075, RY0+.12, color=C['sec'])
    # ax.text(RX0-.115, (RY0+RY1)/2, 'recirculation', fontsize=FS_NOTE,
    #         ha='center', va='center', rotation=90, color=C['sec'])

    # # ⚠ 圖高由 3.45 收到 2.80 in 之後，方塊在 axes 比例下變高，先前的固定
    # #   座標又互相壓到。標籤縮短、右欄兩個方塊拉開到 .78 / .22。
    # # ⚠ 試過在 (a) 加一句「no excitation is imposed」：放右上被壓力方塊蓋住，
    # #   移到左下又壓到 state not logged。**這個面板沒有真正的空白**——
    # #   看起來像空白的地方是面板標題的行距。硬塞文字只會製造重疊，
    # #   該句已在圖說與 §3 出現，這裡不重複。
    # # 進氣閥
    # # 單行版寬到衝出左邊界並壓到壓力方塊，改回兩行。
    # # 進氣閥的中心由**本體上緣 ＋ 半個框高 ＋ 間距**推出，不用猜。
    # hg_guess = .35
    # CY_G = RY1+hg_guess/2+.17   # 間距加大，箭頭才看得出來
    # _, hg = box(ax, (RX0+RX1)/2, CY_G, ['gas inlet', '$H_2$:$CO_2$ = 4:1'],
    #             fs=FS_NOTE)
    # arrow(ax, (RX0+RX1)/2, CY_G-hg/2-.006, (RX0+RX1)/2, RY1+.005)

    # # 壓力感測——右欄置於 x=.77。⚠ 標籤寫 'pressure sensor' 會把框撐寬撐高，
    # # 直接壓到下方的控制器框；量測式方塊的尺寸完全由文字決定，控制文字長度
    # # 比事後挪座標有效。
    # # ⚠ CY_P 必須落在**氣相區** .47–.70 之內。先前設 .74 高過反應器頂端，
    # #   箭頭起點根本沒碰到本體，看起來變成從進氣閥拉出來的。
    # # 右欄一律以**左緣 X_R** 對齊；本體右緣是 .44，留 .10 的空隙。
    # CY_P, X_R = (LY+RY1)/2, RX1+.10   # 與 headspace 同高；右欄離本體 .10
    # wp, hp = box(ax, 0, CY_P, ['pressure', '0.01 step'],
    #              fs=FS_NOTE, ec=C['accent'], left=X_R)
    # arrow(ax, RX1+.005, CY_P, X_R-.008, CY_P)

    # # 控制器：讀壓力、決定補氣，但**狀態不被記錄**
    # # 只畫「壓力→控制器」一條虛線；「控制器→閥」若要畫成路徑會穿過
    # # 本體或循環迴路，改用文字帶過，避免交叉。
    # # 行要短——'refill when P < threshold' 那行讓框寬到壓住本體與鄰欄軸標籤。
    # # ⚠ 兩框相撞、箭頭甚至反向，是因為我用猜的間距（.13）而實際框高更大。
    # #   兩個框同字級、同兩行 ⇒ 高度相同，所以中心距 = hp + gap 就一定不撞。
    # GAP = .17          # 加大，讓 pressure->controller 箭頭明顯
    # cy_ctl = CY_P-hp-GAP
    # wc, hh = box(ax, 0, cy_ctl, ['controller', 'P < threshold'],
    #              fs=FS_NOTE, ec=C['sec'], ls=(0, (2.4, 1.6)), left=X_R)
    # xc = X_R+wc/2
    # arrow(ax, X_R+wp/2, CY_P-hp/2-.004, X_R+wp/2, cy_ctl+hh/2+.004,
    #       ls=(0, (2.4, 1.6)), color=C['sec'])
    # ax.text(xc, cy_ctl-hh/2-.030, 'state not logged', ha='center',
    #         va='top', fontsize=FS_NOTE, color=C['sec'])

    # # ⚠ 控制器框的下緣算出來在 y≈−0.13，超出原本寫死的 ylim −0.06 而被切掉。
    # #   方塊的實際範圍都已記在 BOXES 裡，直接用它撐開座標，不要再猜界線。
    # mine = [b for b in BOXES if b[0] == id(ax)]
    # y_lo = min(b[3] for b in mine)-.11        # 留給「state not logged」
    # y_hi = max(b[5] for b in mine)+.03
    # x_lo = min(b[2] for b in mine)-.10        # 留給旋轉的 recirculation 標籤
    # x_hi = max(b[4] for b in mine)+.03
    # ax.set_xlim(x_lo, x_hi); ax.set_ylim(y_lo, y_hi)

    # # ── (b) 實測軌跡 ────────────────────────────────────
    ax = fig.add_subplot(gs[0, 0])
    t, P = load_window()
    if t is not None:
        ax.plot(t, P, '-', lw=.55, color=C['main'])
        d = np.diff(P)
        for i in np.where(d > 0.03)[0]:
            ax.axvline(t[i], color=C['accent'], lw=.5, alpha=.55)
    ax.set_xlabel('Time  (hr)')
    ax.set_ylabel(f'Pressure  ({U["p"]})')
    ax.set_title('(a)  Each descent is one experiment', loc='left')
    # 說明文字改寫在圖說裡（紅線＝閾值觸發補氣，約 2.2 次/日，共 351 次）——
    # 放在圖內會壓到軌跡，且 10 頁硬上限下版面要省。

    # ⚠ 面板 (b)「Mining pipeline」已移除：figF 的架構圖涵蓋同一條
    #   管線且更完整，兩張並存會把讀者的注意力分成兩處。

    check_overlaps()
    save(fig, 'figD_device_pipeline', FIGDIR)


if __name__ == '__main__':
    main()
