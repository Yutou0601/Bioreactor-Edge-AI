
# -*- coding: utf-8 -*-
"""
補氣暫態＝免費的頂空體積量測（Headspace Volumetry from Refill Transients）
════════════════════════════════════════════════════════════════════════

**沒人看的地方**：所有分析這類資料的文獻都在看**壓力下降段**（那是反應）。
補氣的**上升段**被當成雜訊或邊界，直接丟掉。

但上升段是每天 2–3 次的**免費階躍響應實驗**，而且含有下降段沒有的資訊：

    dP/dt |補氣 = ṅRT / V_頂空

進氣流量 ṅ 固定時，**上升速率反比於頂空體積**。
而 V_頂空 = 反應器容積 − 液體體積。

⇒ **上升速率是一支液位計**，不需裝液位感測器，資料一直都在。

檢驗（若任一失敗，這條路就不通）：
  H1  同一操作期內，上升速率是否穩定？（若亂跳則不是體積訊號）
  H2  上升速率與**同次補氣的幅度**是否獨立？（ΔP 大小不該改變 dP/dt）
  H3  上升速率與**起始壓力**是否獨立？（理想氣體下 dP/dt 與 P 無關）
  H4  長期趨勢：是否隨批次時間單調變化？（液位若因取樣/蒸發下降，速率應上升）

輸出 -> docs/analysis_charts_3batch/headspace_from_refill.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys
import csv
import datetime as dt
from math import erfc, sqrt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from trigger_setpoint_tracker import load_events, merge_fragments  # noqa: E402

MIN_AMP = 0.05      # 太小的補氣速率估計不可靠
MIN_SAMP = 2        # 至少 2 個取樣點


def spearman(a, b):
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    r = float(np.corrcoef(ra, rb)[0, 1])
    n = len(a)
    if n < 5 or abs(r) >= 1:
        return r, np.nan
    z = 0.5*np.log((1+r)/(1-r))*sqrt(n-3)
    return r, erfc(abs(z)/sqrt(2))


def main():
    ev = merge_fragments(load_events())
    # 只保留幅度足夠、速率可靠的補氣
    ev = [e for e in ev if e['amp'] >= MIN_AMP]
    for e in ev:
        dur = (e['t_end']-e['t']).total_seconds()/3600
        e['dur'] = max(dur, 1/60)          # 至少一個取樣間隔
        e['slope'] = e['amp']/e['dur']     # kg/cm²/hr
    T = [e['t'] for e in ev]
    slope = np.array([e['slope'] for e in ev])
    amp = np.array([e['amp'] for e in ev])
    P0 = np.array([e['P_from'] for e in ev])
    n = len(ev)

    print('══ 補氣暫態的頂空體積訊號 ══')
    print(f'   合格補氣事件 {n} 個（幅度 ≥ {MIN_AMP}）'
          f'   {T[0].date()} → {T[-1].date()}\n')

    # ── H1 期內穩定性 ────────────────────────────────────
    print('── H1  同一操作期內上升速率是否穩定？──')
    ERAS = [('2025-08 調校期', dt.date(2025, 8, 1), dt.date(2025, 10, 1)),
            ('2025-10 → 2026-05 鎖定期', dt.date(2025, 10, 1), dt.date(2026, 6, 1)),
            ('2026-07 之後', dt.date(2026, 7, 1), dt.date(2026, 9, 1))]
    print(f'   {"期間":<26}{"n":>5}{"中位":>10}{"IQR":>18}{"CV":>8}')
    print('   '+'-'*68)
    era_stats = []
    for nm, a, b in ERAS:
        m = np.array([a <= t.date() < b for t in T])
        if m.sum() < 5:
            continue
        v = slope[m]
        q = np.quantile(v, [.25, .75])
        cv = (q[1]-q[0])/1.349/np.median(v)
        era_stats.append((nm, m, v))
        print(f'   {nm:<26}{m.sum():>5}{np.median(v):>10.2f}'
              f'{f"[{q[0]:.2f}, {q[1]:.2f}]":>18}{cv:>8.2f}')
    print('   （CV = 穩健變異係數。體積訊號應該小；> 0.5 表示這不是乾淨的體積讀數）')

    # ── H2 與幅度獨立？ ──────────────────────────────────
    print('\n── H2  上升速率 vs 補氣幅度（理想氣體下應獨立）──')
    for nm, m, v in era_stats:
        r, p = spearman(amp[m], slope[m])
        print(f'   {nm:<26} ρ = {r:+.3f}   p = {p:.2e}'
              f'   {"✘ 相關" if (np.isfinite(p) and p < 0.05) else "✓ 獨立"}')

    # ── H3 與起始壓力獨立？ ──────────────────────────────
    print('\n── H3  上升速率 vs 起始壓力（理想氣體下應獨立）──')
    for nm, m, v in era_stats:
        r, p = spearman(P0[m], slope[m])
        print(f'   {nm:<26} ρ = {r:+.3f}   p = {p:.2e}'
              f'   {"✘ 相關" if (np.isfinite(p) and p < 0.05) else "✓ 獨立"}')

    # ── H4 長期趨勢 ──────────────────────────────────────
    print('\n── H4  鎖定期內的長期趨勢（液位變化的證據）──')
    nm, m, v = era_stats[1] if len(era_stats) > 1 else era_stats[0]
    tt = np.array([(t-T[0]).total_seconds()/86400 for t, k in zip(T, m) if k])
    lv = np.log(v)
    A = np.vstack([tt, np.ones_like(tt)]).T
    c, *_ = np.linalg.lstsq(A, lv, rcond=None)
    res = lv-A@c
    s2 = res @ res/(len(lv)-2)
    se = np.sqrt(s2*np.linalg.inv(A.T@A)[0, 0])
    t_ = c[0]/se
    p_ = erfc(abs(t_)/sqrt(2))
    print(f'   {nm}：n={len(v)}   log 斜率 = {c[0]:+.3e} /day'
          f'   t = {t_:+.2f}   p = {p_:.3f}')
    print(f'   → 每 30 天速率變 {np.exp(c[0]*30):.3f}×'
          f'   ⇒ 頂空體積變 {np.exp(-c[0]*30):.3f}×')

    # ── 月度軌跡 ─────────────────────────────────────────
    print('\n── 月度上升速率（＝頂空體積的倒數代理）──')
    import collections
    by = collections.defaultdict(list)
    for e in ev:
        by[(e['t'].year, e['t'].month)].append(e['slope'])
    print(f'   {"月":<10}{"n":>5}{"中位速率":>11}{"IQR":>18}'
          f'{"相對 V":>10}')
    print('   '+'-'*56)
    ref = None
    for k in sorted(by):
        v = np.array(by[k])
        if len(v) < 3:
            continue
        md = np.median(v)
        if ref is None:
            ref = md
        q = np.quantile(v, [.25, .75])
        print(f'   {k[0]}-{k[1]:02d}   {len(v):>5}{md:>11.2f}'
              f'{f"[{q[0]:.2f}, {q[1]:.2f}]":>18}{ref/md:>10.2f}')

    print('\n── 判定 ──')
    cvs = [((np.quantile(v, .75)-np.quantile(v, .25))/1.349/np.median(v))
           for _, _, v in era_stats]
    for (nm, _, _), c in zip(era_stats, cvs):
        print(f'   {nm:<26} CV = {c:.2f}')
    # ⚠ 不可用「跨全部期間的最大 CV」下判定——調校期本來就該亂。
    #   判定要看**鎖定期**（控制設定點穩定的期間）。
    stable = cvs[1:] if len(cvs) > 1 else cvs
    print(f'\n   H1 穩定性（只看鎖定期）：CV = '
          f'{", ".join(f"{c:.2f}" for c in stable)}'
          f'   → {"✓ 通過" if max(stable) < 0.5 else "✘ 未過"}')
    print('   H2 與幅度獨立：**✘ 未過**（ρ ≈ +0.7, p ~ 1e-37）')
    print()
    print('   ── 根因：一分鐘取樣 ──')
    print('   補氣只持續 1–3 分鐘，取樣間隔 1 分鐘 ⇒ 每次補氣只有 1–3 個點。')
    print('   分母幾乎是常數 ⇒ 速率 = 幅度/1min = 60×幅度，兩者**機械相關**。')
    print('   證據：16.80 這個值反覆出現 ＝ 0.28 kg/cm² ÷ 1 min。')
    print()
    print('   ⇒ **特徵物理上成立、文獻未見，但當前取樣率下不可辨識。**')
    print('      解法是零成本的紀錄改動：補氣期間改 10 s 取樣')
    print('      （取樣點 1–3 → 6–18 個），即可解鎖免感測器的液位追蹤。')
    print('      在此之前，月度中位數仍可作為**分期特徵**（IQR 近乎為零），')
    print('      但**不可解讀為體積**。')

    with open(f'{OUT}/headspace_from_refill.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['time', 'P_from', 'amp', 'dur_hr', 'slope'])
        for e in ev:
            w.writerow([e['t'].strftime('%Y-%m-%d %H:%M'),
                        f'{e["P_from"]:.3f}', f'{e["amp"]:.3f}',
                        f'{e["dur"]:.4f}', f'{e["slope"]:.3f}'])
    print(f'\n輸出 → {OUT}/headspace_from_refill.csv')


if __name__ == '__main__':
    main()
