
# -*- coding: utf-8 -*-
"""
變點的鑑識分析（Change-Point Forensics）
════════════════════════════════════════════════════════════════════════

`regime_changepoints.py` 產生了一份變點日期清單。清單本身不是結果——
審稿人會問「所以呢？」本檔回答三個問題：

  Q1  哪些變點只是**資料空窗**造成的假象？（記錄中斷 ≠ 製程事件）
  Q2  每個變點**是什麼類型**的異動？（設定點改變／傳質改變／形狀改變／訊噪改變）
  Q3  偵測器**可不可信**？（懲罰敏感度、偽陽性率、對照基準）

Q1 是誠信問題，Q2 是「結果如何被理解」，Q3 是「方法建立信任」。
"""
import os
import sys
import csv
import datetime as dt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import (load, segment, head_rate,          # noqa: E402
                                 optimal_partition, TD, FCO2,
                                 DEFAULT_FCO2)

GAP_DAYS = 3.0          # 超過此天數視為記錄中斷
ALIGN_DAYS = 3          # 跨通道對齊變點的容差


# ══════════════════════════════════════════════════════════════════
#  1. 富特徵的循環收集
# ══════════════════════════════════════════════════════════════════
def gather_rich():
    seen, rows, folders = {}, [], []
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        if not os.path.isdir(p):
            continue
        if any(f.endswith('.csv') for f in os.listdir(p)):
            folders.append((p, d))
        for s in sorted(os.listdir(p)):
            sp = os.path.join(p, s)
            if os.path.isdir(sp) and any(f.endswith('.csv')
                                         for f in os.listdir(sp)):
                folders.append((sp, f'{d}/{s}'))

    for path, tag in folders:
        try:
            raw = load(path)
        except Exception:
            continue
        if len(raw) < 2000:
            continue
        cyc, h, P, ts = segment(raw)
        f = FCO2.get(tag.split('/')[0], DEFAULT_FCO2)
        for a, b in cyc:
            key = (ts[a].replace(second=0), round(h[b]-h[a], 1))
            if key in seen:
                continue
            t = h[a:b+1]-h[a]; y = P[a:b+1]
            r, pm = head_rate(t, y)
            if not np.isfinite(r) or pm <= 0:
                continue
            seen[key] = 1
            # 形狀：正規化後的中點壓降比例（>0.5 表凸／指數狀）
            tn = t/t[-1]; amp = y[0]-y[-1]
            shape = np.interp(0.5, tn, (y[0]-y)/amp) if amp > 0 else np.nan
            # 訊噪：二階差分的穩健尺度（量化雜訊以外的抖動）
            d2 = np.diff(y, 2)
            noise = 1.4826*np.median(np.abs(d2-np.median(d2)))/np.sqrt(6)
            rows.append(dict(
                t=ts[a], folder=tag, dur=t[-1],
                P0=y[0],            # 補氣上限（控制帶頂）
                Pend=y[-1],         # 觸發下限（控制帶底）
                amp=amp,
                rate=amp/t[-1],
                kla=r/(f*pm),
                shape=shape,
                noise=noise, f=f))
    rows.sort(key=lambda x: x['t'])
    return rows


# ══════════════════════════════════════════════════════════════════
#  2. 偵測器（含空窗遮罩）
# ══════════════════════════════════════════════════════════════════
def detect(vals, times, beta_mult=3.0, logscale=True):
    v = np.asarray(vals, float)
    ok = np.isfinite(v) & ((v > 0) if logscale else True)
    y = np.log(v[ok]) if logscale else v[ok]
    idx = np.where(ok)[0]
    if len(y) < 12:
        return [], idx, y
    cps = optimal_partition(y, beta_mult*np.log(len(y)))
    return cps, idx, y


def gap_days(times, i):
    """索引 i 處的變點，其前後兩個循環相隔幾天。"""
    if i <= 0 or i >= len(times):
        return 0.0
    return (times[i]-times[i-1]).total_seconds()/86400


def main():
    rows = gather_rich()
    T = [r['t'] for r in rows]
    n = len(rows)
    print('══ 變點鑑識 ══')
    print(f'   循環 {n} 個   {T[0].date()} → {T[-1].date()}\n')

    # ─────────────────────────────────────────────────────────
    #  Q1  資料覆蓋與空窗
    # ─────────────────────────────────────────────────────────
    print('── Q1  資料覆蓋（記錄中斷 ≠ 製程事件）──')
    gaps = [( (T[i]-T[i-1]).total_seconds()/86400, i) for i in range(1, n)]
    big = [(g, i) for g, i in gaps if g > GAP_DAYS]
    span = (T[-1]-T[0]).days
    covered = span - sum(g for g, _ in big)
    print(f'   跨度 {span} 天，扣掉空窗後實際覆蓋 {covered:.0f} 天'
          f'（{covered/span*100:.0f}%）')
    print(f'   超過 {GAP_DAYS} 天的空窗 {len(big)} 段：')
    for g, i in sorted(big, reverse=True):
        print(f'      {T[i-1].date()} → {T[i].date()}   空窗 {g:5.1f} 天')

    # ─────────────────────────────────────────────────────────
    #  Q3a 懲罰敏感度
    # ─────────────────────────────────────────────────────────
    print('\n── Q3a 懲罰敏感度（哪些變點是穩健的）──')
    kla = [r['kla'] for r in rows]
    mults = [1.5, 2.0, 3.0, 4.0, 6.0, 8.0]
    persist = {}
    for m in mults:
        cps, idx, _ = detect(kla, T, m)
        print(f'   β = {m:.1f}·log n  →  {len(cps):2d} 個變點')
        for c in cps:
            persist[T[idx[c]].date()] = persist.get(T[idx[c]].date(), 0)+1
    print(f'\n   在 {len(mults)} 個懲罰設定中出現次數 ≥ {len(mults)-1} 的'
          f'（最穩健）：')
    for d, k in sorted(persist.items()):
        if k >= len(mults)-1:
            print(f'      {d}   出現 {k}/{len(mults)}')

    # ─────────────────────────────────────────────────────────
    #  Q3b 偽陽性率
    # ─────────────────────────────────────────────────────────
    print('\n── Q3b 虛無校準（β = 3·log n 下的偽陽性）──')
    v = np.array([r['kla'] for r in rows], float)
    ok = np.isfinite(v) & (v > 0)
    y = np.log(v[ok]); nn = len(y)
    beta = 3*np.log(nn)
    rng = np.random.default_rng(0)

    # 虛無 A：獨立同分布重排（破壞所有時間結構）
    cA = [len(optimal_partition(rng.permutation(y), beta)) for _ in range(200)]
    # 虛無 B：AR(1) 替代序列（保留 lag-1 自相關，仍無變點）
    z = y-y.mean()
    phi = float(np.clip(np.corrcoef(z[:-1], z[1:])[0, 1], -0.95, 0.95))
    sd = z.std()*np.sqrt(max(1-phi**2, 1e-6))
    cB = []
    for _ in range(200):
        s = np.empty(nn); s[0] = rng.normal(0, z.std())
        for i in range(1, nn):
            s[i] = phi*s[i-1]+rng.normal(0, sd)
        cB.append(len(optimal_partition(s, beta)))
    obs = len(optimal_partition(y, beta))
    print(f'   實測          {obs} 個變點')
    print(f'   虛無 A iid    {np.mean(cA):.2f} ± {np.std(cA):.2f}'
          f'   （最大 {max(cA)}）')
    print(f'   虛無 B AR(1)  {np.mean(cB):.2f} ± {np.std(cB):.2f}'
          f'   （最大 {max(cB)}，φ = {phi:+.2f}）')
    print(f'   → 實測超出 AR(1) 虛無最大值 {max(cB)} 者，'
          f'{"成立" if obs > max(cB) else "不成立"}')

    # ─────────────────────────────────────────────────────────
    #  Q2  變點類型學（多通道）
    # ─────────────────────────────────────────────────────────
    print('\n── Q2  變點類型學（每個變點是什麼改變了）──')
    chans = [('P0', '補氣上限', False), ('Pend', '觸發下限', False),
             ('dur', '循環時長', True), ('kla', 'kLa 代理', True),
             ('shape', '曲線形狀', False), ('noise', '訊號雜訊', True)]
    hits = {}
    for key, lab, lg in chans:
        cps, idx, _ = detect([r[key] for r in rows], T, 3.0, lg)
        for c in cps:
            hits.setdefault(T[idx[c]].date(), set()).add(lab)

    def classify(s):
        if {'補氣上限', '觸發下限'} & s:
            return '★ 控制設定點改變（操作介入）'
        if '訊號雜訊' in s and not ({'kLa 代理', '曲線形狀'} & s):
            return '⚠ 僅訊噪改變（疑為感測／記錄問題）'
        if {'kLa 代理', '曲線形狀'} & s:
            return '● 製程狀態改變（傳質／動力學）'
        return '· 僅時長改變'

    print(f'   {"日期":<13}{"空窗":>7}  {"類型":<28}通道')
    print('   '+'-'*74)
    kcps, kidx, _ = detect(kla, T, 3.0)
    kdates = {T[kidx[c]].date() for c in kcps}
    gapmap = {T[i].date(): g for g, i in big}
    audit = []
    for d in sorted(hits):
        s = hits[d]
        g = gapmap.get(d, 0.0)
        tagg = f'{g:5.1f}d' if g else '   —'
        cls = ('✘ 資料空窗假象' if g > GAP_DAYS else classify(s))
        star = '◆' if d in kdates else ' '
        print(f'  {star}{str(d):<13}{tagg:>7}  {cls:<28}{"/".join(sorted(s))}')
        audit.append((d, g, cls, '/'.join(sorted(s))))

    print('\n   ◆ = 同時被 kLa 代理主序列偵測到')
    ng = sum(1 for _, g, c, _ in audit if c.startswith('✘'))
    print(f'   共 {len(audit)} 個候選變點，其中 {ng} 個落在資料空窗'
          f'（{ng/len(audit)*100:.0f}%）→ **不可主張為製程事件**')

    with open(f'{OUT}/changepoint_forensics.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['date', 'gap_days', 'classification', 'channels'])
        for a in audit:
            w.writerow([a[0], f'{a[1]:.1f}', a[2], a[3]])
    print(f'\n輸出 → {OUT}/changepoint_forensics.csv')


if __name__ == '__main__':
    main()
