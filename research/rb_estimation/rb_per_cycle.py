
# -*- coding: utf-8 -*-
"""
逐循環的生物速率估計 ＋ 設定誤差虛無檢定
════════════════════════════════════════════════════════════════════════

**為什麼這次的做法不同**：先前十五次都在「用多個條件的斜率／截距去解共用
參數」，自由度永遠不夠。形式檢定（`clean_and_form.py`）證實 78.1 % 的循環
需要線性＋指數兩項，所以改為**直接擬合軌跡**，每個循環各自吐一個 r_b：

    P(t) = P_eq + A·exp(−k·t) − r_b·t          A = P0 − P_eq

  指數項負責曲率（物理：CO2 趨近飽和）
  線性項負責定速率下降（生物：CO2 + 4H2 → CH4）

  ⇒ 不需跨條件共用參數，351 個循環給 351 個獨立估計。

**但估計出來不算數，要先過三關**：

  V1  雜訊地板：以量化步階（0.01）模擬純雜訊，看能「回收」出多少假 r_b
  V2  **設定誤差虛無**：以**純指數（r_b ≡ 0）**為真相產生資料，
      經同一管線看回收出多少 r_b。這是先前推翻 r_b = 0.011 的那個檢定。
  V3  ORP 佐證：若 r_b 是真的生物速率，應與獨立通道 ΔORP 相關

輸出 -> docs/analysis_charts_3batch/rb_per_cycle.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv
import glob
import datetime as dt
from math import erfc, sqrt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import TD                                 # noqa: E402
from multivariate_increments import load4, cond_of                 # noqa: E402
from clean_and_form import seg_clean, SKIP_MIN                     # noqa: E402

QUANT = 0.01
KGRID = np.arange(0.01, 1.501, 0.01)
NSIM = 400


def fit_LE(t, y):
    """P = A·exp(−k t) + (−r_b)·t + P_eq，格點搜 k，其餘線性解。"""
    best = None
    for k in KGRID:
        A = np.vstack([np.exp(-k*t), t, np.ones_like(t)]).T
        c, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y-A@c
        s = float(r @ r)
        if best is None or s < best[0]:
            best = (s, c, k)
    s, c, k = best
    return dict(rb=-c[1], k=k, amp=c[0], peq=c[2], sse=s,
                rmse=np.sqrt(s/len(t)))


def fit_E(t, y):
    """純指數（r_b ≡ 0）——虛無資料的產生器。"""
    best = None
    for k in KGRID:
        A = np.vstack([np.exp(-k*t), np.ones_like(t)]).T
        c, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y-A@c
        s = float(r @ r)
        if best is None or s < best[0]:
            best = (s, c, k)
    s, c, k = best
    return dict(k=k, amp=c[0], peq=c[1], resid_sd=np.sqrt(s/max(len(t)-2, 1)))


def gather():
    folders = []
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        if not os.path.isdir(p):
            continue
        if glob.glob(os.path.join(p, '*.csv')):
            folders.append((p, d))
        for s in sorted(os.listdir(p)):
            sp = os.path.join(p, s)
            if os.path.isdir(sp) and glob.glob(os.path.join(sp, '*.csv')):
                folders.append((sp, f'{d}/{s}'))
    out = []
    for path, tag in folders:
        try:
            raw = load4(path)
        except Exception:
            continue
        if len(raw) < 500:
            continue
        ts = [r[0] for r in raw]
        P = np.array([r[1] for r in raw]); O = np.array([r[2] for r in raw])
        h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
        cyc, wash = seg_clean(h, P, ts)
        for a, b in cyc:
            if ts[a].date() in wash:
                continue
            t = h[a:b+1]-h[a]
            sel = t >= SKIP_MIN
            if sel.sum() < 20:
                continue
            t2 = t[sel]-t[sel][0]
            out.append(dict(tag=tag, t0=ts[a], t=t2, P=P[a:b+1][sel],
                            O=O[a:b+1][sel],
                            cond=cond_of(tag, ts[a].date())[0]))
    return out


def main():
    cyc = gather()
    print('══ 逐循環的生物速率估計 ══\n')
    print(f'   循環 {len(cyc)} 個')

    rng = np.random.default_rng(31337)

    # ── 逐循環擬合 ──────────────────────────────────────
    for c in cyc:
        c['LE'] = fit_LE(c['t'], c['P'])
        c['E'] = fit_E(c['t'], c['P'])
        c['dORP'] = c['O'][-1]-c['O'][0]
        c['dur'] = c['t'][-1]
        c['tot'] = (c['P'][0]-c['P'][-1])/c['dur']

    rb = np.array([c['LE']['rb'] for c in cyc])
    print(f'\n── r_b 的分布（351 個獨立估計）──')
    q = np.quantile(rb, [.05, .25, .5, .75, .95])
    print(f'   5% {q[0]:+.5f}   25% {q[1]:+.5f}   中位 {q[2]:+.5f}'
          f'   75% {q[3]:+.5f}   95% {q[4]:+.5f}')
    print(f'   平均 {rb.mean():+.5f} ± {rb.std(ddof=1)/np.sqrt(len(rb)):.5f}'
          f'   （SE）')
    print(f'   r_b > 0 的比例：{np.mean(rb > 0)*100:.1f} %')

    # ── V1 雜訊地板 ─────────────────────────────────────
    print('\n── V1  雜訊地板（純量化雜訊，無任何趨勢）──')
    fake = []
    for _ in range(NSIM):
        c = cyc[rng.integers(len(cyc))]
        y = np.round(np.full(len(c['t']), c['P'][0])/QUANT)*QUANT \
            + rng.normal(0, QUANT/2, len(c['t']))
        fake.append(fit_LE(c['t'], np.round(y/QUANT)*QUANT)['rb'])
    fake = np.array(fake)
    print(f'   雜訊回收的 |r_b| 中位 {np.median(np.abs(fake)):.5f}'
          f'   95 百分位 {np.quantile(np.abs(fake), .95):.5f}')
    print(f'   實測 |r_b| 中位 {np.median(np.abs(rb)):.5f}'
          f'   → {"✓ 遠高於雜訊地板" if np.median(np.abs(rb)) > 3*np.quantile(np.abs(fake), .95) else "✘ 與雜訊地板同量級"}')

    # ── V2 設定誤差虛無（關鍵）──────────────────────────
    print('\n── V2  設定誤差虛無：以純指數（r_b ≡ 0）為真相 ──')
    print('   （這正是先前推翻 r_b = 0.011 的檢定）')
    # ⚠ 初版把「虛無**單次抽樣**」拿去比「實測**中位數**」——那是拿單一觀測
    #   的分布比 351 個樣本的聚合統計量，尺度根本不同，必然過不了。
    #   正確做法：模擬「整組 351 個循環」，取其中位數與正值比例，
    #   重複多次得到**聚合統計量在虛無下的分布**，再與實測比。
    def sim_null_set():
        v = []
        for c in cyc:
            e = c['E']
            y = e['peq']+e['amp']*np.exp(-e['k']*c['t'])
            y = y+rng.normal(0, max(e['resid_sd'], QUANT/2), len(c['t']))
            v.append(fit_LE(c['t'], np.round(y/QUANT)*QUANT)['rb'])
        v = np.array(v)
        return np.median(v), float(np.mean(v > 0))

    NSET = 60
    med_null, pos_null = [], []
    for _ in range(NSET):
        m_, p_ = sim_null_set()
        med_null.append(m_); pos_null.append(p_)
    med_null = np.array(med_null); pos_null = np.array(pos_null)

    obs_med = float(np.median(rb)); obs_pos = float(np.mean(rb > 0))
    print(f'   虛無下「整組中位數」：{med_null.mean():+.5f} ± '
          f'{med_null.std(ddof=1):.5f}'
          f'   [{np.quantile(med_null,.025):+.5f},'
          f' {np.quantile(med_null,.975):+.5f}]')
    print(f'   實測中位數：          {obs_med:+.5f}')
    z_med = (obs_med-med_null.mean())/max(med_null.std(ddof=1), 1e-12)
    p_med = (np.sum(med_null >= obs_med)+1)/(NSET+1)
    print(f'   → z = {z_med:+.1f}   置換 p = {p_med:.4f}')

    print(f'\n   虛無下「r_b > 0 的比例」：{pos_null.mean()*100:.1f} % ± '
          f'{pos_null.std(ddof=1)*100:.1f} %')
    print(f'   實測比例：                {obs_pos*100:.1f} %')
    p_pos = (np.sum(pos_null >= obs_pos)+1)/(NSET+1)
    z_pos = (obs_pos-pos_null.mean())/max(pos_null.std(ddof=1), 1e-12)
    print(f'   → z = {z_pos:+.1f}   置換 p = {p_pos:.4f}')

    v2 = (p_med < 0.05) and (p_pos < 0.05)
    print(f'   → {"✓ 通過：純指數虛無無法產生實測的中位數與正值比例" if v2 else "✘ 未通過"}')

    # ── 條件相依性 ──────────────────────────────────────
    print('\n── r_b 的條件相依性 ──')
    print(f'   {"條件":<10}{"n":>5}{"r_b 中位":>11}{"總速率中位":>12}'
          f'{"生物份額":>10}{"ΔORP 中位":>11}')
    print('   '+'-'*60)
    conds = sorted({c['cond'] for c in cyc})
    for cd in conds:
        s = [c for c in cyc if c['cond'] == cd]
        if len(s) < 3:
            continue
        r = np.median([c['LE']['rb'] for c in s])
        tt = np.median([c['tot'] for c in s])
        do = np.median([c['dORP'] for c in s])
        print(f'   {cd:<10}{len(s):>5}{r:>11.5f}{tt:>12.5f}'
              f'{r/tt*100 if tt else np.nan:>9.1f}%{do:>11.1f}')

    # ── V3 ORP 佐證 ────────────────────────────────────
    print('\n── V3  r_b 與獨立通道 ΔORP 的相關 ──')
    do = np.array([c['dORP'] for c in cyc])
    m = np.isfinite(rb) & np.isfinite(do)
    r = float(np.corrcoef(rb[m], do[m])[0, 1])
    n = int(m.sum())
    z = 0.5*np.log((1+r)/(1-r))*sqrt(n-3)
    p = erfc(abs(z)/sqrt(2))
    print(f'   Pearson r = {r:+.3f}   n = {n}   p = {p:.2e}'
          f'   {"✓ 相關" if p < 0.05 else "✘ 不相關"}')
    print('   （生物活動消耗 H2 ⇒ r_b 越大，ORP 變化應越明顯）')

    print('\n══ 判定 ══')
    if v2:
        print('   ✓ V2 通過——這是先前所有估計都倒下的地方。')
    else:
        print('   ✘ **V2 未通過**：純指數虛無也能產生同量級的 r_b。')
        print('     ⇒ 這個 r_b **不可宣稱為生物速率**，與先前十五次同樣的結局。')

    with open(f'{OUT}/rb_per_cycle.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['time', 'folder', 'cond', 'dur_hr', 'rb', 'k', 'peq',
                    'rmse', 'total_rate', 'dORP'])
        for c in cyc:
            w.writerow([c['t0'].strftime('%Y-%m-%d %H:%M'), c['tag'],
                        c['cond'], f'{c["dur"]:.2f}', f'{c["LE"]["rb"]:.6f}',
                        f'{c["LE"]["k"]:.3f}', f'{c["LE"]["peq"]:.4f}',
                        f'{c["LE"]["rmse"]:.5f}', f'{c["tot"]:.5f}',
                        f'{c["dORP"]:.1f}'])
    print(f'\n輸出 → {OUT}/rb_per_cycle.csv')


if __name__ == '__main__':
    main()
