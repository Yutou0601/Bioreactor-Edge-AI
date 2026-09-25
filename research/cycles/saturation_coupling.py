# -*- coding: utf-8 -*-
"""飽和程度、產甲烷、ORP、pH 的關聯集合。

2026-09-23。起因：使用者觀察到「頂空壓力趨於飽和時產甲烷速率下降，
且 ORP 與 pH 也有關聯」，要求找出其關聯之集合。

════════════════════════════════════════════════════════════════════════
兩個層級，觀測單位不同，不可混用

  **循環層級**（n 約 250）：壓力、ORP、pH 皆逐分鐘可得
      → 可做多變數關聯，樣本足夠
  **排氣層級**（n = 35）：加入 CH4/CO2，但氣體僅排氣當下可信
      → 樣本少，只能做少數幾個檢定，且必須報 MDE

「飽和程度」怎麼量

  循環內壓力趨近 P_eq 時，**壓降速率**會趨緩。故以
      飽和指標 = 1 − (該段末端壓降速率 / 該段初期壓降速率)
  越接近 1 表示越飽和（速率掉得越多）。
  另併報「段內壓降速率」本身與「壓力水準」。

⚠ 三個必須控制的混淆（本專案已被咬過）

  1. **時間漂移**：C2ST 曾以 AUC 0.867 區分兩時期，但安慰劑對照亦達 0.767
     → 任何相關都要看扣掉時間後還剩多少（**偏相關**）。
  2. **pH 量化**：步階 0.01、週期內全距僅約 5 階
     → 一律用 robust_change（最小平方斜率 × 時長），不可用端點差。
  3. **小樣本**：n=35 時 Spearman 的 MDE 約 0.46
     → p > 0.05 **不等於**沒有關係，必須併報 MDE。

輸出 -> 純文字 + docs/analysis_charts_3batch/fig48_coupling.png
"""
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (                      # noqa: E402
    BLUE, RED, INK, INK2, MUTED, OUT, style)
from ph_orp_discriminator import (                       # noqa: E402
    descents, robust_change, PH_FAULT)
from orp_calibration import find_vents, load_with_gas    # noqa: E402
from carbonate_degassing_test import (                   # noqa: E402
    spearman, perm_p, mde_spearman)

LABELS = ['壓力水準', '壓降速率', '飽和程度', 'ORP 水準',
          'ORP 變化', 'pH 變化', '循環時長']


def seg_features(hh, p, orp, ph, s, e):
    """單一下降段的特徵。"""
    t = hh[s:e + 1]
    y = p[s:e + 1]
    dur = float(t[-1] - t[0])
    if dur < 1.0 or len(t) < 60:
        return None
    # 初期／末端的壓降速率（各取前後三分之一，用最小平方斜率）
    n3 = len(t) // 3
    sl_early = -np.polyfit(t[:n3] - t[0], y[:n3], 1)[0]
    sl_late = -np.polyfit(t[-n3:] - t[-n3], y[-n3:], 1)[0]
    if sl_early <= 0:
        return None
    sat = 1.0 - sl_late / sl_early          # 越接近 1 越飽和
    return dict(
        p_level=float(np.mean(y)),
        rate=float((y[0] - y[-1]) / dur),
        sat=float(sat),
        orp_level=float(np.nanmean(orp[s:e + 1])),
        orp_chg=robust_change(orp, hh, s, e),
        ph_chg=robust_change(ph, hh, s, e),
        dur=dur,
        t_mid=float((t[0] + t[-1]) / 2),
    )


def partial_spearman(x, y, z):
    """控制 z 之後 x 與 y 的偏相關（在等級上做線性殘差化）。"""
    def rank(v):
        return np.argsort(np.argsort(v)).astype(float)
    rx, ry, rz = rank(x), rank(y), rank(z)
    def resid(a):
        A = np.column_stack([np.ones_like(rz), rz])
        b, *_ = np.linalg.lstsq(A, a, rcond=None)
        return a - A @ b
    return float(np.corrcoef(resid(rx), resid(ry))[0, 1])


def main():
    ts, hh, p, orp, ph, co2, ch4 = load_with_gas()
    ph = np.where((ph <= 0) | (ph >= PH_FAULT), np.nan, ph)
    segs = descents(hh, p)
    print('全資料庫 %d 筆，切出下降段 %d 個' % (len(ts), len(segs)))

    feats = [f for f in (seg_features(hh, p, orp, ph, s, e) for s, e in segs)
             if f is not None]
    print('特徵齊全者 %d 個\n' % len(feats))

    M = np.array([[f['p_level'], f['rate'], f['sat'], f['orp_level'],
                   f['orp_chg'], f['ph_chg'], f['dur']] for f in feats])
    tmid = np.array([f['t_mid'] for f in feats])
    ok = np.all(np.isfinite(M), axis=1)
    M, tmid = M[ok], tmid[ok]
    print('剔除含缺值者後 n = %d' % len(M))

    print('\n' + '=' * 72)
    print('一、循環層級的關聯矩陣（Spearman，n = %d）' % len(M))
    print('=' * 72)
    k = len(LABELS)
    R = np.zeros((k, k))
    for i in range(k):
        for j in range(k):
            R[i, j] = 1.0 if i == j else spearman(M[:, i], M[:, j])
    hdr = '            ' + ''.join('%-11s' % s[:5] for s in LABELS)
    print(hdr)
    for i in range(k):
        print('%-12s' % LABELS[i] + ''.join('%+-11.3f' % R[i, j]
                                            for j in range(k)))

    print('\n' + '=' * 72)
    print('二、扣掉時間漂移後還剩多少（偏相關，控制段落的時間中點）')
    print('=' * 72)
    print('  ⚠ 本專案曾因未控制時間漂移而誤判（C2ST 安慰劑達 AUC 0.767）。\n')
    print('  %-26s %10s %10s %8s' % ('配對', '原始 ρ', '偏相關', '衰減'))
    pairs = [(2, 1, '飽和程度 vs 壓降速率'),
             (2, 4, '飽和程度 vs ORP 變化'),
             (2, 5, '飽和程度 vs pH 變化'),
             (4, 5, 'ORP 變化 vs pH 變化'),
             (1, 4, '壓降速率 vs ORP 變化'),
             (1, 5, '壓降速率 vs pH 變化'),
             (3, 4, 'ORP 水準 vs ORP 變化')]
    res = []
    for a, b, name in pairs:
        r0 = spearman(M[:, a], M[:, b])
        rp = partial_spearman(M[:, a], M[:, b], tmid)
        drop = (1 - abs(rp) / abs(r0)) * 100 if abs(r0) > 1e-9 else np.nan
        res.append((name, r0, rp, drop))
        print('  %-26s %+10.3f %+10.3f %7.0f%%' % (name, r0, rp, drop))
    mde = mde_spearman(len(M))
    print('\n  本層級的 MDE（n=%d）≈ %.3f —— 小於此值者不可解讀' % (len(M), mde))

    print('\n' + '=' * 72)
    print('三、排氣層級：飽和程度與產甲烷（n = 35，⚠ 檢定力有限）')
    print('=' * 72)
    ev = find_vents(ts, hh, p, co2, ch4)
    rows = []
    for j, i in enumerate(ev):
        if j == 0:
            continue
        gap = hh[i] - hh[ev[j - 1]]
        if gap <= 0:
            continue
        # 該次排氣前一段時間的平均壓降速率（代表「是否已趨飽和」）
        w0 = max(0, i - 240)                 # 前 4 小時
        if i - w0 < 60:
            continue
        t_w = hh[w0:i]
        y_w = p[w0:i]
        rate_before = -float(np.polyfit(t_w - t_w[0], y_w, 1)[0])
        rows.append(dict(ch4=ch4[i], gap=gap,
                         ch4_rate=ch4[i] / gap,     # 每小時累積的甲烷 %
                         rate_before=rate_before,
                         p_before=float(p[i - 1])))
    print('  可用排氣事件 %d 個' % len(rows))
    r_b = np.array([d['rate_before'] for d in rows])
    c_r = np.array([d['ch4_rate'] for d in rows])
    c_a = np.array([d['ch4'] for d in rows])
    mde35 = mde_spearman(len(rows))
    for x, y, nm, pred in ((r_b, c_r, '排氣前壓降速率 vs 甲烷累積速率', '正'),
                           (r_b, c_a, '排氣前壓降速率 vs 甲烷濃度', '正')):
        rho, pv = perm_p(x, y)
        tag = ('符合' if (rho > 0 and pv < 0.05) else
               ('無定論（|ρ| < MDE）' if abs(rho) < mde35 else '不符'))
        print('  %-34s ρ = %+.3f  p = %.4f  -> %s' % (nm, rho, pv, tag))
    print('\n  使用者的觀察預測：越飽和（壓降越慢）產甲烷越慢 ⟹ **正相關**')
    print('  MDE（n=%d）≈ %.3f' % (len(rows), mde35))

    make_figure(M, tmid, res, rows, mde)
    return M, res


def make_figure(M, tmid, res, rows, mde):
    fig = plt.figure(figsize=(15.0, 4.8))
    gs = fig.add_gridspec(1, 3, wspace=0.42, width_ratios=[1.15, 1, 1])

    # a 相關矩陣熱圖
    ax = fig.add_subplot(gs[0, 0])
    k = len(LABELS)
    R = np.zeros((k, k))
    for i in range(k):
        for j in range(k):
            R[i, j] = 1.0 if i == j else spearman(M[:, i], M[:, j])
    im = ax.imshow(R, cmap='RdBu_r', vmin=-1, vmax=1)
    ax.set_xticks(range(k)); ax.set_yticks(range(k))
    ax.set_xticklabels(LABELS, rotation=45, ha='right', fontsize=9)
    ax.set_yticklabels(LABELS, fontsize=9)
    for i in range(k):
        for j in range(k):
            if i != j and abs(R[i, j]) > mde:
                ax.text(j, i, '%+.2f' % R[i, j], ha='center', va='center',
                        fontsize=8, color='white' if abs(R[i, j]) > 0.5 else INK)
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.ax.tick_params(labelsize=9)
    ax.set_title('a　循環層級的關聯（n=%d）\n只標出超過 MDE %.2f 者' % (len(M), mde),
                 color=INK, fontweight='bold', loc='left', fontsize=12, pad=10)

    # b 原始 vs 偏相關
    ax = fig.add_subplot(gs[0, 1])
    names = [r[0].replace(' vs ', '\nvs ') for r in res]
    r0 = [r[1] for r in res]
    rp = [r[2] for r in res]
    yy = np.arange(len(res))
    ax.barh(yy - 0.2, r0, height=0.38, color=MUTED, label='原始')
    ax.barh(yy + 0.2, rp, height=0.38, color=BLUE, label='扣掉時間漂移')
    ax.axvline(0, color=INK, lw=1.2)
    for s_ in (mde, -mde):
        ax.axvline(s_, color=RED, lw=1.8, ls=':')
    ax.set_yticks(yy); ax.set_yticklabels(names, fontsize=8.5)
    ax.invert_yaxis()
    ax.legend(loc='lower right', frameon=False, fontsize=9)
    ax.set_xlabel('Spearman ρ', fontsize=11)
    ax.set_title('b　扣掉時間後還剩多少\n紅點線＝MDE', color=INK,
                 fontweight='bold', loc='left', fontsize=12, pad=10)
    ax.grid(True, axis='x', lw=0.8, alpha=0.9); ax.set_axisbelow(True)
    for s_ in ('top', 'right'):
        ax.spines[s_].set_visible(False)

    # c 排氣層級：飽和 vs 產甲烷
    ax = fig.add_subplot(gs[0, 2])
    rb = np.array([d['rate_before'] for d in rows])
    cr = np.array([d['ch4_rate'] for d in rows])
    ax.scatter(rb, cr, s=70, color=BLUE, edgecolors='white', zorder=4)
    rho = spearman(rb, cr)
    _lo, hi = ax.get_ylim()
    ax.set_ylim(_lo, hi * 1.38)
    ax.text(0.03, 0.97,
            '使用者觀察預測：正相關\n實測 ρ = %+.3f（n=%d，MDE %.2f）'
            % (rho, len(rows), mde_spearman(len(rows))),
            transform=ax.transAxes, fontsize=10.5, color=INK,
            fontweight='bold', ha='left', va='top')
    style(ax, 'c　越飽和，產甲烷越慢嗎', '排氣前的壓降速率 (kgf/cm²/hr)',
          '甲烷累積速率 (%/hr)')

    out = os.path.join(OUT, 'fig48_coupling.png')
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
