
# -*- coding: utf-8 -*-
"""
r_b 的診斷：它是生物速率，還是兩項互相補償的產物？
════════════════════════════════════════════════════════════════════════

`rb_per_cycle.py` 得到 r_b ≈ 0.012 且通過設定誤差虛無。但通過虛無只證明
「純指數產生不出這個值」，**不等於**這個值就是生物速率。

本檔檢查它會不會是**簡併的產物**——在 P(t) = P_eq + A·e^(−kt) − r_b·t 裡，
指數項與線性項在有限取樣下部分可互換：k 小時，e^(−kt) 本身近乎線性，
於是「大 A、小 k」與「小 A、大 r_b」可以擬合得一樣好。

  D1  r_b 與 k 的相關 —— 真生物速率**不該**系統性依賴物理速率常數
  D2  r_b 與循環時長／幅度／起始壓力的相關 —— 都不該依賴
  D3  分層：把循環依 k 分組，各組內 r_b 是否一致？
  D4  tau10 為何解出負值——逐循環檢視
  D5  以資料夾（＝時間分期）分組，看 r_b 的穩定性

**若 D1 出現強相關，主結果就要收回。**

輸出 -> docs/analysis_charts_3batch/rb_diagnostics.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv
from math import erfc, sqrt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402


def pear(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5:
        return np.nan, np.nan
    r = float(np.corrcoef(a[m], b[m])[0, 1])
    n = int(m.sum())
    if abs(r) >= 1:
        return r, 0.0
    z = 0.5*np.log((1+r)/(1-r))*sqrt(n-3)
    return r, erfc(abs(z)/sqrt(2))


def spear(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    ra = np.argsort(np.argsort(a[m])).astype(float)
    rb_ = np.argsort(np.argsort(b[m])).astype(float)
    return pear(ra, rb_)


def main():
    rows = []
    with open(f'{OUT}/rb_per_cycle.csv', encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append(dict(
                    t=r['time'], folder=r['folder'], cond=r['cond'],
                    dur=float(r['dur_hr']), rb=float(r['rb']),
                    k=float(r['k']), peq=float(r['peq']),
                    rmse=float(r['rmse']), tot=float(r['total_rate']),
                    dORP=float(r['dORP'])))
            except Exception:
                pass
    rb = np.array([r['rb'] for r in rows])
    k = np.array([r['k'] for r in rows])
    dur = np.array([r['dur'] for r in rows])
    tot = np.array([r['tot'] for r in rows])
    peq = np.array([r['peq'] for r in rows])

    print('══ r_b 的診斷 ══\n')
    print(f'   循環 {len(rows)} 個   r_b 中位 {np.median(rb):+.5f}')

    # ── D1 與 k 的糾纏（關鍵）───────────────────────────
    print('\n── D1  r_b 與擬合出的 k 的相關（簡併指紋）──')
    r1, p1 = pear(rb, k); s1, sp1 = spear(rb, k)
    print(f'   Pearson  r = {r1:+.3f}   p = {p1:.2e}')
    print(f'   Spearman ρ = {s1:+.3f}   p = {sp1:.2e}')
    deg = abs(s1) > 0.5
    print(f'   → {"✘ 強相關：r_b 與物理項糾纏，主結果須收回" if deg else "✓ 相關不強，未見明顯簡併"}')

    # ── D2 與其他外生量的相關 ───────────────────────────
    print('\n── D2  r_b 與外生量的相關（都不該依賴）──')
    print(f'   {"量":<14}{"Spearman ρ":>13}{"p":>11}   判定')
    print('   '+'-'*46)
    for nm, v in (('循環時長', dur), ('總下降速率', tot), ('擬合的 P_eq', peq)):
        s, p = spear(rb, v)
        bad = abs(s) > 0.5
        print(f'   {nm:<14}{s:>13.3f}{p:>11.2e}   '
              f'{"✘ 可疑" if bad else "✓"}')

    # ── D3 依 k 分層 ───────────────────────────────────
    print('\n── D3  依 k 分層後，r_b 是否一致？──')
    qs = np.quantile(k, np.linspace(0, 1, 6))
    print(f'   {"k 區間":<20}{"n":>5}{"k 中位":>10}{"r_b 中位":>11}'
          f'{"r_b IQR":>22}')
    print('   '+'-'*68)
    meds = []
    for i in range(5):
        m = (k >= qs[i]) & (k < qs[i+1] if i < 4 else k <= qs[i+1])
        if m.sum() < 5:
            continue
        q = np.quantile(rb[m], [.25, .75])
        meds.append(np.median(rb[m]))
        print(f'   [{qs[i]:.2f}, {qs[i+1]:.2f}){"":<7}{m.sum():>5}'
              f'{np.median(k[m]):>10.3f}{np.median(rb[m]):>11.5f}'
              f'{f"[{q[0]:+.4f}, {q[1]:+.4f}]":>22}')
    if meds:
        sp_ = (max(meds)-min(meds))/abs(np.median(meds)) if np.median(meds) else np.inf
        print(f'\n   各層中位數的相對散布 {sp_*100:.0f} %'
              f'   → {"✓ 大致一致" if sp_ < 1.0 else "✘ 分層間差異大"}')

    # ── D4 tau10 的負值 ────────────────────────────────
    print('\n── D4  tau10 為何解出負 r_b？──')
    t10 = [r for r in rows if r['cond'] == 'tau10']
    if t10:
        print(f'   {"起始":<17}{"時長":>7}{"k":>8}{"r_b":>10}'
              f'{"總速率":>10}{"RMSE":>9}')
        print('   '+'-'*62)
        for r in sorted(t10, key=lambda x: x['t']):
            print(f'   {r["t"][5:16]:<17}{r["dur"]:>7.1f}{r["k"]:>8.2f}'
                  f'{r["rb"]:>10.5f}{r["tot"]:>10.5f}{r["rmse"]:>9.5f}')
        kk = np.array([r['k'] for r in t10])
        print(f'\n   tau10 的 k 中位 {np.median(kk):.3f}'
              f'   全體 k 中位 {np.median(k):.3f}')
        print(f'   → {"k 明顯偏高，指數項吸走了下降量" if np.median(kk) > 1.5*np.median(k) else "k 與全體相當"}')

    # ── D5 依資料夾（＝時間分期）分組 ────────────────────
    print('\n── D5  依資料夾分組的 r_b ──')
    print(f'   {"資料夾":<30}{"n":>5}{"r_b 中位":>11}{"正值比例":>10}'
          f'{"k 中位":>9}')
    print('   '+'-'*66)
    out = []
    for f in sorted({r['folder'] for r in rows}):
        s = [r for r in rows if r['folder'] == f]
        if len(s) < 5:
            continue
        v = np.array([x['rb'] for x in s])
        kv = np.array([x['k'] for x in s])
        print(f'   {f[:29]:<30}{len(s):>5}{np.median(v):>11.5f}'
              f'{np.mean(v > 0)*100:>9.0f}%{np.median(kv):>9.3f}')
        out.append([f, len(s), f'{np.median(v):.5f}',
                    f'{np.mean(v>0):.3f}', f'{np.median(kv):.3f}'])

    fm = [float(o[2]) for o in out]
    print(f'\n   八組中位數：{min(fm):+.5f} ~ {max(fm):+.5f}')
    allpos = all(x > 0 for x in fm)
    print(f'   → {"✓ 全部為正，跨分期一致" if allpos else "✘ 有分期為負"}')

    print('\n══ 判定 ══')
    if deg:
        print('   ✘ r_b 與 k 強相關 ⇒ **主結果須收回**')
    elif not allpos:
        print('   ⚠ 未見簡併，但有分期解出負值 ⇒ 結果部分成立，須說明')
    else:
        print('   ✓ 未見簡併，跨分期一致 ⇒ 主結果維持')

    with open(f'{OUT}/rb_diagnostics.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['folder', 'n', 'rb_median', 'pos_frac', 'k_median'])
        w.writerows(out)
    print(f'\n輸出 → {OUT}/rb_diagnostics.csv')


if __name__ == '__main__':
    main()
