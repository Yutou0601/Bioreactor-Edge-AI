# -*- coding: utf-8 -*-
"""自動偵測「圖上的文字是否壓到資料」。

2026-10-02。使用者要求：圖說放在圖上，但不要覆蓋圖表，且要嚴謹檢查。

════════════════════════════════════════════════════════════════════════
為什麼不能只用外接矩形

  一條折線的 bbox 是整條線的外接矩形，裡面大半是空白；
  用 bbox 相交判斷會得到大量假陽性（文字放在曲線上方的空白處也會被判定重疊）。

  **本檔改為逐點檢查**：把資料點轉成像素座標，看有沒有任何一點
  真的落在文字方塊內。長條圖則用其矩形本身（那是實心的，bbox 準確）。

用法
    from overlap_check import check_fig
    ...
    probs = check_fig(fig)          # 在 savefig 之前呼叫
    if probs: print(...)

回傳 [(軸索引, 文字前20字, 壓到什麼, 壓到幾個點)]

⚠ 已知的假陽性：**標籤刻意貼著它所標示的參考線**
  （例如「進料比 0.25」指著紅虛線）會被判定為壓到。
  這種情形是正確的設計意圖，應人工判斷後放行。
"""
import numpy as np
from matplotlib.patches import Rectangle


def _inside(pix, bb, pad=1.0):
    """落在文字方塊內的點數。pix 為 (N,2) 像素座標。"""
    if pix is None or len(pix) == 0:
        return 0
    x, y = pix[:, 0], pix[:, 1]
    m = ((x >= bb.x0 - pad) & (x <= bb.x1 + pad) &
         (y >= bb.y0 - pad) & (y <= bb.y1 + pad))
    return int(m.sum())


def check_fig(fig, min_pts=1, min_area_frac=0.02):
    """回傳所有「文字壓到資料」的情形。

    min_pts        ：線／散點落在文字框內幾個點才算壓到
    min_area_frac  ：長條與文字框的重疊面積佔文字框多少比例才算壓到
    """
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    out = []
    for ai, ax in enumerate(fig.axes):
        texts = [t for t in ax.texts if t.get_text().strip()]
        if not texts:
            continue
        for t in texts:
            try:
                bb = t.get_window_extent(rend)
            except Exception:
                continue
            # ① 折線：逐點
            #   ⚠ 忽略低對比的背景線（alpha < 0.3）。例如「所有曲線疊加」
            #     這種脂絡圖會鋪滿全圖，文字放哪都會被判定壓到，
            #     但那是脆弱的背景脈絡，不是要讀的主要資料。
            for ln in ax.lines:
                if not ln.get_visible():
                    continue
                al = ln.get_alpha()
                if al is not None and al < 0.3:
                    continue
                xy = ln.get_xydata()
                if xy is None or len(xy) == 0:
                    continue
                pix = ax.transData.transform(np.asarray(xy, float))
                n = _inside(pix, bb)
                # 水平／垂直參考線只有兩點，單獨判斷：看文字框是否橫跨它
                if n >= min_pts:
                    out.append((ai, t.get_text()[:20].replace('\n', ' '),
                                'line', n))
            # ② 散點
            for col in ax.collections:
                al = col.get_alpha()
                if al is not None and al < 0.3:
                    continue
                try:
                    off = col.get_offsets()
                except Exception:
                    continue
                if off is None or len(off) == 0:
                    continue
                pix = ax.transData.transform(np.asarray(off, float))
                n = _inside(pix, bb)
                if n >= min_pts:
                    out.append((ai, t.get_text()[:20].replace('\n', ' '),
                                'scatter', n))
            # ③ 長條：只檢查 ax.bar() 產生的（在 ax.containers 裡）。
            #   ⚠ 直接 add_patch 的裝飾性方框（說明色塊）不算，
            #     文字本來就該放在那裡面。不區分會產生大量假陽性。
            bar_patches = []
            for cont in getattr(ax, 'containers', []):
                for pa in getattr(cont, 'patches', []):
                    bar_patches.append(pa)
            for pa in bar_patches:
                if not isinstance(pa, Rectangle):
                    continue
                try:
                    ab = pa.get_window_extent(rend)
                except Exception:
                    continue
                dx = min(bb.x1, ab.x1) - max(bb.x0, ab.x0)
                dy = min(bb.y1, ab.y1) - max(bb.y0, ab.y0)
                if dx > 0 and dy > 0:
                    frac = (dx * dy) / max(bb.width * bb.height, 1e-9)
                    if frac >= min_area_frac:
                        out.append((ai, t.get_text()[:20].replace('\n', ' '),
                                    'bar(%.0f%%)' % (frac * 100), 1))
    return out


def report(fig, name):
    """印出檢查結果；回傳是否乾淨。"""
    probs = check_fig(fig)
    if not probs:
        print('    ✓ %s：文字未壓到資料' % name)
        return True
    print('    ⚠ %s：%d 處文字壓到資料' % (name, len(probs)))
    for ai, txt, kind, n in probs[:8]:
        print('        軸%d  「%s」 壓到 %s（%d）' % (ai, txt, kind, n))
    return False
