
# -*- coding: utf-8 -*-
"""
排氣鋸齒：為什麼要排氣？（Vent Sawtooth）
════════════════════════════════════════════════════════════════════════

事件清單不是規律。本檔檢驗一個**機制性假說**，它把先前所有片段串起來：

  CH₄ 是產物、幾乎不溶於水 → 在頂空累積
  → CO₂ 莫耳分率被稀釋 → 吸收驅動力下降
  → **傳質表現隨「距上次排氣的時間」單調衰退**
  → 操作員排氣 → CH₄ 清除 → **重置**

若成立，資料應呈現**鋸齒**：kLa 代理在兩次排氣間衰退，每次排氣後跳回。
這同時回答三件事：為什麼要排氣、什麼時候該排、以及排氣事件為何值得挖出來。

檢驗設計：
  T1  事件研究：以 18 次排氣為原點，對齊前後各 5 個循環
  T2  迴歸：kLa 代理 對「距上次排氣的時數」（含條件固定效果）
  T3  安慰劑：以隨機時點當假排氣，重跑 T1

輸出 -> docs/analysis_charts_3batch/vent_sawtooth.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys
import csv
from math import erfc, sqrt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from changepoint_forensics import gather_rich                      # noqa: E402
from three_class_typology import hampel, HAMPEL_T, RETURN_N        # noqa: E402

W = 5               # 事件研究的前後窗（循環數）
NPLACEBO = 2000


def find_vents(rows):
    """與 three_class_typology 相同的判準：控制面孤立深跌且立刻回復。"""
    v = np.array([r['Pend'] for r in rows], float)
    idx, _, med = hampel(v)
    n = len(v)
    out = []
    for i in idx:
        if v[i] >= med[i]:
            continue                       # 只要往下的（排氣）
        back = all(abs(v[j]-med[j]) <= HAMPEL_T
                   for j in range(i+1, min(n, i+1+RETURN_N)))
        if back:
            out.append(i)
    return out


def welch(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 2 or len(b) < 2:
        return np.nan, np.nan
    va, vb = a.var(ddof=1)/len(a), b.var(ddof=1)/len(b)
    t = (a.mean()-b.mean())/sqrt(va+vb)
    return t, erfc(abs(t)/sqrt(2))


def main():
    rows = gather_rich()
    n = len(rows)
    T = [r['t'] for r in rows]
    kla = np.array([r['kla'] for r in rows], float)
    vents = find_vents(rows)
    print('══ 排氣鋸齒：為什麼要排氣？ ══')
    print(f'   循環 {n} 個   排氣事件 {len(vents)} 次\n')

    # ── T1 事件研究 ──────────────────────────────────────
    print(f'── T1  事件研究（以排氣為原點，前後各 {W} 個循環）──')
    prof = {k: [] for k in range(-W, W+1)}
    for i in vents:
        for k in range(-W, W+1):
            j = i+k
            if 0 <= j < n and np.isfinite(kla[j]) and kla[j] > 0:
                # 以該次事件鄰域的中位標準化，消除跨期水準差異
                nb = [kla[m] for m in range(max(0, i-W), min(n, i+W+1))
                      if np.isfinite(kla[m]) and kla[m] > 0]
                if len(nb) >= 4:
                    prof[k].append(kla[j]/np.median(nb))
    print(f'   {"相對位置":<10}{"n":>5}{"標準化 kLa":>13}{"SE":>9}')
    print('   '+'-'*38)
    means = {}
    for k in range(-W, W+1):
        v = np.array(prof[k])
        if len(v) < 3:
            continue
        means[k] = v.mean()
        mark = '  ← 排氣' if k == 0 else ''
        print(f'   {k:>+4}      {len(v):>5}{v.mean():>13.4f}'
              f'{v.std(ddof=1)/np.sqrt(len(v)):>9.4f}{mark}')

    pre = np.concatenate([prof[k] for k in range(-W, 0) if len(prof[k]) >= 3])
    post = np.concatenate([prof[k] for k in range(1, W+1) if len(prof[k]) >= 3])
    t, p = welch(post, pre)
    print(f'\n   排氣前 {W} 個循環  平均 {pre.mean():.4f}  n={len(pre)}')
    print(f'   排氣後 {W} 個循環  平均 {post.mean():.4f}  n={len(post)}')
    print(f'   Welch t = {t:+.2f}   p = {p:.3f}'
          f'   → {"✓ 排氣後顯著較高" if (p < 0.05 and t > 0) else "✘ 無鋸齒證據"}')

    # ── T2 距上次排氣的時數 ───────────────────────────────
    print('\n── T2  kLa 代理 對「距上次排氣的時數」──')
    last = None
    since, y = [], []
    for i in range(n):
        if i in vents:
            last = T[i]; continue
        if last is None or not np.isfinite(kla[i]) or kla[i] <= 0:
            continue
        dh = (T[i]-last).total_seconds()/3600
        if 0 < dh <= 24*21:                     # 三週內
            since.append(dh); y.append(np.log(kla[i]))
    since, y = np.array(since), np.array(y)
    if len(since) >= 10:
        A = np.vstack([since, np.ones_like(since)]).T
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        resid = y-A@coef
        s2 = resid @ resid/(len(y)-2)
        se = np.sqrt(s2*np.linalg.inv(A.T@A)[0, 0])
        tt = coef[0]/se
        pp = erfc(abs(tt)/sqrt(2))
        r = np.corrcoef(since, y)[0, 1]
        print(f'   n = {len(since)}   斜率 = {coef[0]:+.3e} /hr'
              f'   t = {tt:+.2f}   p = {pp:.3f}   r = {r:+.3f}')
        print(f'   → 每過 100 小時，kLa 代理變 {np.exp(coef[0]*100):.3f}×')
        print(f'   → {"✓ 支持衰退" if (pp < 0.05 and coef[0] < 0) else "✘ 不支持衰退"}')
    else:
        print('   樣本不足')

    # ── T3 安慰劑 ────────────────────────────────────────
    print(f'\n── T3  安慰劑檢定（{NPLACEBO} 次隨機假排氣）──')
    rng = np.random.default_rng(53)
    obs = post.mean()-pre.mean()
    null = np.empty(NPLACEBO)
    cand = [i for i in range(W, n-W) if i not in vents]
    for b in range(NPLACEBO):
        fake = rng.choice(cand, size=len(vents), replace=False)
        pr, po = [], []
        for i in fake:
            nb = [kla[m] for m in range(i-W, i+W+1)
                  if np.isfinite(kla[m]) and kla[m] > 0]
            if len(nb) < 4:
                continue
            md = np.median(nb)
            for k in range(-W, 0):
                if np.isfinite(kla[i+k]) and kla[i+k] > 0:
                    pr.append(kla[i+k]/md)
            for k in range(1, W+1):
                if np.isfinite(kla[i+k]) and kla[i+k] > 0:
                    po.append(kla[i+k]/md)
        null[b] = (np.mean(po)-np.mean(pr)) if pr and po else np.nan
    null = null[np.isfinite(null)]
    pv = (np.sum(np.abs(null) >= abs(obs))+1)/(len(null)+1)
    print(f'   實測 前後差 = {obs:+.4f}')
    print(f'   安慰劑 {null.mean():+.4f} ± {null.std():.4f}'
          f'   置換 p = {pv:.4f}')
    print(f'   → {"✓ 超出安慰劑分布" if pv < 0.05 else "✘ 落在安慰劑分布內"}')

    print('\n── 結論 ──')
    ok1 = (p < 0.05 and t > 0)
    ok3 = pv < 0.05
    if ok1 and ok3:
        print('   ✓ 鋸齒規律成立：排氣後傳質表現回升，且非隨機。')
    else:
        print('   ✘ **鋸齒假說不成立**。排氣前後的傳質表現沒有系統性差異。')
        print('     不可宣稱「排氣是為了恢復傳質」。需另尋操作動機。')

    with open(f'{OUT}/vent_sawtooth.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['rel_pos', 'n', 'norm_kla'])
        for k in sorted(means):
            w.writerow([k, len(prof[k]), f'{means[k]:.4f}'])
    print(f'\n輸出 → {OUT}/vent_sawtooth.csv')


if __name__ == '__main__':
    main()
