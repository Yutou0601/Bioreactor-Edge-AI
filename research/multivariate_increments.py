
# -*- coding: utf-8 -*-
"""
多變量增量關聯：用 pH 與 ORP 分離物理／生物通道
════════════════════════════════════════════════════════════════════════

**先前十五次嘗試的共同錯誤**：都在擬合**單一通道（壓力）的絕對軌跡**。
那需要連續時間，而本資料有 110 天空窗；而且壓力把兩個通道疊在一起，
單通道無論怎麼擬合都是共線的。

**改為：多變量增量關聯。** 兩個通道對三個訊號的作用方向不同——

              壓力      pH                    ORP
  物理 CO2 溶解  ↓    ↓（生成 H2CO3）          幾乎不動
  生物 CO2+4H2   ↓    ↑（消耗溶解碳酸）        ↑（H2 被消耗）
       →CH4

  ⇒ **ORP 只有生物會動**：物理溶解 CO2 不消耗 H2。

因為只看**每個循環內的變化量**，時間不連續完全不影響——每個循環各自
貢獻一組 (dP/dt, dpH/dt, dORP/dt)，跨空窗照樣可以匯總。

檢定：
  T1  三個訊號的增量在循環內是否相關？（若 ORP 與 P 無關，這條路不通）
  T2  以 dORP/dt 為生物代理，迴歸 dP/dt = a·dORP/dt + b → 斜率即生物貢獻
  T3  加入 dpH/dt 做二元迴歸，檢查兩個係數的符號是否符合上表
  T4  跨條件一致性：生物份額應隨進氣 H2 分率而變（4:1 的 H2 比 1:1 多）

輸出 -> docs/analysis_charts_3batch/multivariate_increments.csv
"""
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

PORD = 6
# ══ 欄位索引：由 scratchpad/columns.py 逐欄剖析實際數值後確定 ══
#   ⚠ 先前用 I_ORP=12、I_PH=13 是**錯的**——那兩欄是氣體分析儀的 CO2/CH4，
#     也就是 99.98% 為無效拖尾的通道。用它們做的分析全部無效。
#     徵兆：pH 的標準差算出 22（pH 全域只有 0–14，不可能）。
#   實際：欄7 = ORP(mV, 368–761)   欄9 = pH(6.8–7.3)
#         欄11 = 反應器壓力        欄8 = 混合槽壓力   欄10 = 溫度(恆 30.00)
I_P_REACTOR = 11
I_ORP = 7
I_PH = 9

# ⚠⚠ 符號約定：**記錄器只存絕對值，負號沒寫進檔案**（設備方 2026-08-07 告知）。
#    原始檔逐列檢查確認：三個資料夾各約 1,400 列，一個 '-' 都沒有，
#    ORP 欄存的是 567 / 588 / 563 這類正整數。
#    真實 ORP = −(記錄值)。
#    驗證：中位 −554 mV，加 Ag/AgCl 參考 +197 → **−357 mV vs SHE**，
#    正好落在文獻要求產甲烷菌的 < −300 mV（最佳 −330）區間內。
#    未套用此符號時，換算出 +751 mV，與「排氣含 31.6–43.0 % CH4」直接矛盾。
ORP_SIGN = -1.0


def load4(folder):
    """讀取四個可信訊號：時間、反應器壓力、ORP、pH。"""
    rows = []
    for fp in sorted(glob.glob(os.path.join(folder, '*.csv'))):
        for line in open(fp, encoding='utf-8', errors='replace'):
            p = line.strip().split(',')
            if len(p) < 14:
                continue
            try:
                rows.append((
                    dt.datetime(int(p[0]), int(p[1]), int(p[2]),
                                int(p[3]), int(p[4]), int(float(p[5]))),
                    float(p[I_P_REACTOR]),
                    ORP_SIGN*float(p[I_ORP]),      # 還原負號，見上方註解
                    float(p[I_PH])))
            except Exception:
                continue
    rows.sort()
    return rows


def seg(h, P, minhr=4):
    out, valley, start = [], P[0], 0
    for i in range(1, len(P)):
        if h[i]-h[i-1] > 1.0:
            if h[i-1]-h[start] > minhr:
                out.append((start, i-1))
            start, valley = i, P[i]; continue
        if P[i]-valley > 0.03:
            if h[i-1]-h[start] > minhr:
                out.append((start, i-1))
            start, valley = i, P[i]
        elif P[i] < valley:
            valley = P[i]
    if h[-1]-h[start] > minhr:
        out.append((start, len(P)-1))
    return [(a, b) for a, b in out
            if h[b]-h[a] >= minhr and P[a]-P[b] >= 0.10]


def wrate(t, y, half=1.5):
    """弱形式速率：不微分量化資料。"""
    m = min(half, (t[-1]-t[0])/5)
    u = (t-(t[0]+m))/m
    ins = np.abs(u) < 1
    if ins.sum() < 15:
        return np.nan
    base = 1-u[ins]**2
    ph = base**PORD
    dph = PORD*base**(PORD-1)*(-2*u[ins])/m
    w = np.trapezoid(ph, t[ins])
    return np.trapezoid(dph*y[ins], t[ins])/w if w > 0 else np.nan


# τ 三批的實際結束日。202607至08最新循環研究 的最後一筆是 2026-08-03。
TAU_END = dt.date(2026, 8, 4)

# ⚠ 2026-09-11 移入 Testing_data 的自動化測試資料夾。它們是**完全不同的
#   運轉條件**（每約 2 小時自動補氣、振幅 0.05、期間還氫氣耗盡），不屬於
#   τ 三批的任何一批。
AUTO_PREFIXES = ('0813_', '0817_', '0825-0831_')


def cond_of(tag, d):
    """循環的實驗條件標籤。

    ⚠ 2026-09-11 修正兩個會靜默污染結果的問題：

      1. 原本 `if d >= 2026-07-30: return 'tau10'` **沒有上界**——任何
         日期在那之後的資料都會被標成 tau10。2026-09-11 把三個自動化測試
         資料夾移進 Testing_data 之後，實測有 3 個循環（tau10 的 17%）
         就是這樣混進去的，而且不會有任何錯誤訊息。

      2. 依「日期」判定條件本身就脆弱。條件是由**資料夾**（實驗批次）決定
         的，不是由日期決定的。所以先看資料夾，日期只用來切同一個資料夾
         內的不同階段。
    """
    if tag.startswith(AUTO_PREFIXES):
        return 'auto', 0.2                      # 自動化測試，不併入任何 τ 批
    if tag.startswith('0109-0123'):
        return '1:1', 0.5
    if '0301-0416' in tag:
        return ('pump_off' if d < dt.date(2026, 4, 7) else 'pump_on5'), 0.2
    if d >= TAU_END:
        return 'other', 0.2                     # 超出 τ 三批的期間
    if d >= dt.date(2026, 7, 30):
        return 'tau10', 0.2
    if d >= dt.date(2026, 7, 27):
        return 'tau5', 0.2
    if d >= dt.date(2026, 7, 22):
        return 'tau1', 0.2
    return 'other', 0.2


def pearson(a, b):
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


def main():
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

    seen, rec = {}, []
    for path, tag in folders:
        try:
            raw = load4(path)
        except Exception:
            continue
        if len(raw) < 2000:
            continue
        ts = [r[0] for r in raw]
        P = np.array([r[1] for r in raw]); O = np.array([r[2] for r in raw])
        H = np.array([r[3] for r in raw])
        h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
        for a, b in seg(h, P):
            key = (ts[a].replace(second=0), round(h[b]-h[a], 1))
            if key in seen:
                continue
            seen[key] = 1
            c, f = cond_of(tag, ts[a].date())
            if c == 'other':
                continue
            t = h[a:b+1]-h[a]
            rP = wrate(t, P[a:b+1])
            rO = wrate(t, O[a:b+1])
            rH = wrate(t, H[a:b+1])
            if not all(np.isfinite(v) for v in (rP, rO, rH)):
                continue
            rec.append(dict(t=ts[a], cond=c, f=f, dP=rP, dORP=rO, dpH=rH))
    rec.sort(key=lambda r: r['t'])

    print('══ 多變量增量關聯 ══')
    print(f'   循環 {len(rec)} 個，各貢獻一組 (dP/dt, dORP/dt, dpH/dt)')
    print('   ⚠ 只用循環內的變化量 ⇒ **時間不連續完全不影響**\n')
    conds = sorted({r['cond'] for r in rec})
    for c in conds:
        n = sum(1 for r in rec if r['cond'] == c)
        print(f'      {c:<10} n = {n:>3}')

    dP = np.array([r['dP'] for r in rec])
    dO = np.array([r['dORP'] for r in rec])
    dH = np.array([r['dpH'] for r in rec])

    # ── T1 三訊號的增量是否相關？ ───────────────────────
    print('\n── T1  三個訊號的增量相關性 ──')
    for nm, a, b in (('dP  vs dORP', dP, dO), ('dP  vs dpH', dP, dH),
                     ('dORP vs dpH', dO, dH)):
        r, p = pearson(a, b)
        print(f'   {nm:<14} r = {r:+.3f}   p = {p:.2e}'
              f'   {"✓ 相關" if np.isfinite(p) and p < 0.05 else "✘ 不相關"}')

    # ── T2 以 ORP 為生物代理 ────────────────────────────
    print('\n── T2  dP/dt = a·dORP/dt + b（a 為生物貢獻，b 為物理）──')
    m = np.isfinite(dP) & np.isfinite(dO)
    A = np.vstack([dO[m], np.ones(m.sum())]).T
    coef, *_ = np.linalg.lstsq(A, dP[m], rcond=None)
    res = dP[m]-A@coef
    s2 = res @ res/(m.sum()-2)
    cov = s2*np.linalg.inv(A.T@A)
    for i, nm in enumerate(('a (斜率)', 'b (截距)')):
        se = np.sqrt(cov[i, i]); tt = coef[i]/se
        print(f'   {nm:<10} {coef[i]:+.5f} ± {se:.5f}'
              f'   t = {tt:+.2f}   p = {erfc(abs(tt)/sqrt(2)):.3f}')
    print(f'   R² = {1-res@res/np.sum((dP[m]-dP[m].mean())**2):.3f}')

    # ── T3 二元迴歸：符號是否符合物理？ ──────────────────
    print('\n── T3  dP/dt = a·dORP/dt + c·dpH/dt + b ──')
    print('   預期符號：dORP 與 dpH 皆代表生物活性 ⇒ 兩者係數應同號')
    m3 = m & np.isfinite(dH)
    A3 = np.vstack([dO[m3], dH[m3], np.ones(m3.sum())]).T
    c3, *_ = np.linalg.lstsq(A3, dP[m3], rcond=None)
    r3 = dP[m3]-A3@c3
    s3 = r3 @ r3/(m3.sum()-3)
    cv3 = s3*np.linalg.inv(A3.T@A3)
    for i, nm in enumerate(('a (dORP)', 'c (dpH)', 'b (截距)')):
        se = np.sqrt(cv3[i, i]); tt = c3[i]/se
        print(f'   {nm:<10} {c3[i]:+.5f} ± {se:.5f}'
              f'   t = {tt:+.2f}   p = {erfc(abs(tt)/sqrt(2)):.3f}')
    print(f'   R² = {1-r3@r3/np.sum((dP[m3]-dP[m3].mean())**2):.3f}'
          f'   （單變量 ORP 為上一節的值）')

    # ── T4 跨條件一致性 ────────────────────────────────
    print('\n── T4  各條件的 dORP/dt（生物代理）──')
    print(f'   {"條件":<10}{"n":>5}{"dORP/dt 中位":>14}{"IQR":>22}'
          f'{"dP/dt 中位":>13}')
    print('   '+'-'*66)
    for c in conds:
        s = np.array([r['cond'] == c for r in rec])
        o = dO[s]; pp = dP[s]
        q = np.quantile(o, [.25, .75])
        print(f'   {c:<10}{s.sum():>5}{np.median(o):>14.3f}'
              f'{f"[{q[0]:.2f}, {q[1]:.2f}]":>22}{np.median(pp):>13.4f}')

    with open(f'{OUT}/multivariate_increments.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['time', 'cond', 'f_CO2', 'dP_dt', 'dORP_dt', 'dpH_dt'])
        for r in rec:
            w.writerow([r['t'].strftime('%Y-%m-%d %H:%M'), r['cond'], r['f'],
                        f'{r["dP"]:.5f}', f'{r["dORP"]:.4f}',
                        f'{r["dpH"]:.5f}'])
    print(f'\n輸出 → {OUT}/multivariate_increments.csv')


if __name__ == '__main__':
    main()
