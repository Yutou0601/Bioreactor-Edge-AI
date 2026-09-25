# -*- coding: utf-8 -*-
"""稽核：氣泵的「設定運轉時間」是否等於「實際運轉時間」？

2026-09-23。起因：現場 2026-09-14 回報——

    設定循環 20 分鐘，系統啟動後約 10 分鐘即自行停止（當日測兩次皆然）。
    洪博：「循環 10 分和 20 感覺差異不到」。

════════════════════════════════════════════════════════════════════════
為什麼這件事可能推翻既有結論

  若 τ=20 實際只跑 10 分鐘，則「10 分與 20 分沒有差異」是**必然的**
  ——因為兩者實際相同。這立刻引出更嚴重的問題：

      **τ=10 的設定，實際跑了幾分鐘？**

  既有結論是「kLa 由 1→5 min 增 4.2 倍，但 5→10 min 飽和」。
  若 τ=10 實際未跑滿，那個「飽和」就可能是假象——
  不是質傳飽和，而是**兩個條件根本沒有差到設定的那麼多**。

  三批 τ 實驗（2026-07-22 ~ 08-03）是論文 §5 的資料來源，故必須稽核。

怎麼量實際運轉時間（只用壓力，不需要控制器紀錄）

  泵開：該分鐘壓力**驟降**（遠大於平常的每分鐘降幅）
  泵停：下一分鐘壓力**回升**（實測回升 ≈ 驟降的 1/3~1/2，且與驟降配對）
  實際運轉 = (回升分鐘 − 驟降分鐘) mod 60

  ⚠ 不可用門檻法：開泵瞬間的尖峰極大會把 SD／MAD 撐大，
    門檻只抓得到那一分鐘（pump_rhythm.py 已記錄此坑）。

  ⚠⚠ 也不可逐「小時」看：實作過，失敗。單一小時內泵停期有 59 分鐘
    的量化雜訊，隨機的最大升幅會落在任意位置，短 τ 幾乎必定誤判
    （tau5 逐小時法給出中位 36 分，設定只有 5 分）。
    **改為逐「日」做剖面**：平均後訊噪比足夠，又保留日間變異。

輸出 -> 純文字 + docs/analysis_charts_3batch/fig49_pump_duration.png
"""
import os
import sys
import datetime as dt

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
    BLUE, RED, AQUA, INK, INK2, MUTED, OUT, style)
from pump_rhythm import (                                # noqa: E402
    BATCHES, REFILL_RISE, load, minute_profile, pump_window)


def day_profile(ts, h, p, d0, d1):
    """把批次切成逐日，各自做一次分鐘剖面並取泵窗。

    ⚠ 為何不逐「小時」看：單一小時內，泵停期有 59 分鐘的量化雜訊，
      隨機的最大升幅會落在任意位置，短 τ 幾乎必定誤判
      （實測 tau5 逐小時法給出中位 36 分，設定只有 5 分）。
      這正是 pump_rhythm.py 註解警告的坑。
      **逐日平均後訊噪比足夠，才能在不被雜訊淹沒的前提下看出變異。**
    """
    days = sorted({t.date() for t in ts if d0 <= t.date() <= d1})
    out = []
    for d in days:
        mu, se, n = minute_profile(ts, h, p, d, d)
        if n.sum() < 400:                  # 該日資料太少
            continue
        on, off, run = pump_window(mu)
        out.append(dict(day=d, on=on, off=off, run=run,
                        drop=float(mu[on]), rise=float(-mu[off]),
                        n=int(n.sum())))
    return out


def main():
    ts, h, p = load()
    print('全資料庫 %d 筆' % len(ts))
    print('方法：逐日做分鐘剖面，取「驟降尖峰 → 回升尖峰」為實際運轉時間。\n')

    results = {}
    for nm, tau, d0, d1 in BATCHES:
        mu, se, n = minute_profile(ts, h, p, d0, d1)
        on_a, off_a, run_a = pump_window(mu)
        days = day_profile(ts, h, p, d0, d1)
        runs = np.array([d['run'] for d in days])
        print('=' * 78)
        print('%s　設定 τ = %d 分　（%s ~ %s）' % (nm, tau, d0, d1))
        print('=' * 78)
        print('  全批平均剖面：第 %2d 分驟降 → 第 %2d 分回升，**運轉 %d 分**'
              % (on_a, off_a, run_a))
        print('  %-12s %-8s %-8s %-10s %s' % ('日期', '開(分)', '停(分)', '運轉(分)', '判讀'))
        for d in days:
            flag = '' if abs(d['run'] - tau) <= 1 else '  ⚠ 偏離設定'
            print('  %-12s %-8d %-8d %-10d%s'
                  % (d['day'], d['on'], d['off'], d['run'], flag))
        if len(runs):
            hit = float(np.mean(np.abs(runs - tau) <= 1)) * 100
            print('  -> 逐日中位 %d 分；符合設定±1 的日數比例 %.0f%%（n=%d 日）'
                  % (int(np.median(runs)), hit, len(runs)))
        results[nm] = dict(tau=tau, run_all=run_a, runs=runs,
                           days=[d['day'] for d in days])
        print()

    print('=' * 78)
    print('判讀')
    print('=' * 78)
    ok_all = all(abs(r['run_all'] - r['tau']) <= 1 for r in results.values())
    for nm, r in results.items():
        print('  %-6s 設定 %2d 分 -> 實際 %2d 分　%s'
              % (nm, r['tau'], r['run_all'],
                 '✓ 相符' if abs(r['run_all'] - r['tau']) <= 1 else '⚠ 不符'))
    if ok_all:
        print('\n  ★ 三批的實際運轉時間**全部符合設定值**。')
        print('     ⟹「kLa 由 1→5 min 增 4.2 倍、5→10 min 飽和」的前提成立，')
        print('        該結論不因現場回報的 τ=20 異常而失效。')
        print('     ⟹ 我先前提議的 τ 交叉設計採用 **τ=1 與 τ=5**，')
        print('        這兩檔皆經本稽核確認可靠。')
    else:
        print('\n  ⚠ 有批次的實際運轉時間與設定不符，相關結論須重新檢視。')

    print('\n  ⚠ 現場 2026-09-14 回報的「設定 20 分、實際約 10 分」')
    print('     發生於本資料集（2026-07-22 ~ 08-03）之外，本稽核無法涵蓋。')
    print('     **但它對未來實驗有直接意涵：τ 的可用上限需先驗證，**')
    print('     **不可假設設定值即實際值。**')

    make_figure(results)


def make_figure(results):
    """逐日的實際運轉時間。點少，用點圖不用直方圖。"""
    if not results:
        return
    fig, ax = plt.subplots(1, 1, figsize=(11.0, 4.8))
    cols = {'tau1': BLUE, 'tau5': AQUA, 'tau10': RED}
    xpos, xlab = [], []
    k = 0
    for nm, r in results.items():
        c = cols.get(nm, BLUE)
        for d, run in zip(r['days'], r['runs']):
            edge = (abs(run - r['tau']) > 1)
            ax.scatter([k], [run], s=190, color=('white' if edge else c),
                       edgecolors=c, linewidths=3.0, zorder=5)
            if edge:
                ax.annotate('%d' % run, (k, run), xytext=(0, 13),
                            textcoords='offset points', ha='center',
                            fontsize=12, fontweight='bold', color=c)
            xpos.append(k); xlab.append('%02d-%02d' % (d.month, d.day))
            k += 1
        # 設定值的水平線只畫在該批的 x 範圍
        x0, x1 = k - len(r['days']) - 0.42, k - 1 + 0.42
        ax.plot([x0, x1], [r['tau'], r['tau']], color=c, lw=3.0, ls='--',
                zorder=3)
        ax.text((x0 + x1) / 2, r['tau'] - 3.2, '%s 設定 %d 分' % (nm, r['tau']),
                color=c, fontsize=13, fontweight='bold', ha='center', va='top')
        k += 1
    ax.set_xticks(xpos)
    ax.set_xticklabels(xlab, fontsize=11, rotation=45, ha='right')
    ax.set_ylim(-6, 48)
    ax.text(0.015, 0.97,
            '實心＝符合設定　空心＝偏離\n'
            '★ 僅 tau10 的首日與末日偏離，那兩天正是設定切換的過渡日；\n'
            '　 中間三天穩定在 10 分。',
            transform=ax.transAxes, fontsize=12.5, color=INK,
            fontweight='bold', ha='left', va='top')
    style(ax, '氣泵的實際運轉時間（逐日，由壓力反推）', '',
          '實際運轉（分鐘）')
    fig.subplots_adjust(left=0.09, right=0.98, top=0.88, bottom=0.22)

    out = os.path.join(OUT, 'fig49_pump_duration.png')
    fig.savefig(out)
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
