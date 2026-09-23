# -*- coding: utf-8 -*-
"""能不能量出「準確的 CO2 消耗速率」與「確切的生物活性」？三個檢定，全部是否定的。

2026-09-21。起點是使用者的要求：對資料繼續做實驗，反推準確的 CO2 消耗速率。
結論是資料撐不起來，但過程中量到一個對論文有威脅的東西（檢定三）。

════════════════════════════════════════════════════════════════════════
檢定一　氣體感測器讀的是頂空莫耳分率嗎？—— 不是（分鐘尺度）

  若是真的頂空莫耳分率，補氣（加入不含 CH4 的氣體）必定稀釋 CH4：
      Δln x_CH4 = −Δln P
  實測（自動化批 214 次補氣）斜率 = +0.008 ± 0.225
      距「真頂空」的 −1 有 4.5σ；距「完全無反應」的 0 只有 0.0σ。
  循環內（99 段）斜率中位 −0.551，IQR [−1.09, −0.23]。
  → 分鐘尺度無反應、小時尺度部分反應 = 感測器以數十分鐘時間常數滯後追蹤。
  → 不可用來做分壓層級的物種平衡。

檢定二　兩次排氣之間做物種質量平衡 —— 沒有鑑別力

  全archive 去重後有 35 次排氣事件帶頂空組成（2025-08 ~ 2026-08）。
  原本的構想：CO2 收支 = 期初 + 補氣帶入 − 生物消耗 − 物理溶解 = 期末，
  解出物理溶解；再用 H2 溶解度只有 CO2 的 1/44 當否證檢定。

  ⚠ 失敗原因（結構性，不是資料量）：補氣項遠大於頂空存量（如 14.39 vs 0.4），
    於是 R_CO2 → 0.2·補氣、R_H2 → 0.8·補氣，比值被**強制**拉到進料比 4:1，
    與反應機制無關。看起來「完美符合產甲烷化學計量」其實是恆等式。
    要有鑑別力必須「頂空存量變化 ≳ 補氣量」，即單一循環內的兩點組成，
    而組成只在排氣瞬間有效，排氣又終結循環 → 資料結構上取不到。

檢定三　CO2 耗盡的天然實驗 —— 虛無，且有檢定力  ★對論文有威脅

  自動化批 2026-08-11~08-31：頂空 CO2 由 4.2% 單調降到 0.0%（08-23 後），
  CH4 升到 08-26 達頂後轉為下降（= 產甲烷停止）。碳源沒了，產甲烷必須停。

      CO2 尚存（~08-22）  59 個循環  速率中位 0.0347 kg/cm²/hr
      CO2 歸零（08-25~）  31 個循環  速率中位 0.0367
      差 +0.0020（方向相反）  置換 p = 0.21

  MDE：若真實生物貢獻 = 0.0080 → 檢定力 87%；= 0.0125（論文 r_b）→ 100%。
  → 不是「檢定力不足」的虛無。若壓降的 0.0125 真的是生物的，此檢定必定看得到。

  ⚠ 反對解釋（未排除）：CO2 讀數趨近 0 也可能是「CO2 一進來就被吃掉」的
    傳輸受限穩態，而非碳源不存在。但 08-26 後 p_CH4 由 0.9211 掉到 0.6697
    （無產氣的預測是 p_CH4 維持定值），顯示該時段確實沒有淨產甲烷，
    而壓降速率在該時段仍是 0.0367。

  ⚠ 未解釋的收支缺口：該批連續以 0.037 kg/cm²/hr 吸走氣體卻不產甲烷，
    115 小時共 4.14 kg/cm²（與補氣量相符）。純洩漏需 1.7%/hr，與既有
    洩漏率 ≤0.001 矛盾。此缺口未明 → 檢定三的解讀仍有不確定性。

════════════════════════════════════════════════════════════════════════
⚠ 兩個我自己踩過的坑（都已修正，留著提醒）

  1. 消耗量**不可**用「所有負差加總」：±0.01 的量化抖動一小時累出 0.11，
     而實測速率只有 0.03。第一版算出「補氣 13.07、下降 39.38」，反推期末
     壓力是負的。正解：以補氣為界切段，下降 = 段首 − 段尾。
  2. 「無產氣」的 CH4 預測**不是**逐次補氣的稀釋連乘，那漏掉了下降期的濃縮
     （完整循環裡兩者剛好抵銷）。正解：無產氣 ⟺ p_CH4 = x_CH4·P_abs 維持定值。

輸出 -> docs/analysis_charts_3batch/co2_exhaustion_test.csv
"""
import csv
import datetime as dt
import glob
import os
import sys

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))

OUT = os.path.join(REPO, 'docs', 'analysis_charts_3batch')
AUTO = '0825-0831_氫氣不夠暫停進氣__自動化測試'
ATM = 1.033          # kgf/cm²，換算絕對壓力
RISE = 0.03          # 補氣判定（單步跳升）
GAPH = 0.05          # 相鄰兩筆超過此小時數視為資料缺口
CUT_A = dt.date(2026, 8, 22)    # CO2 尚存的最後一天
CUT_B = dt.date(2026, 8, 25)    # CO2 歸零後的第一天（跳過 08-23/24 過渡）
RB_PAPER = 0.0125


def load(folder):
    from core.cycle_store import read_series_full
    d = os.path.join(REPO, 'research', 'Testing_data', folder)
    got = read_series_full(sorted(glob.glob(os.path.join(d, '**', '*.csv'), recursive=True)))
    if got is None:
        raise SystemExit('讀不到：%s' % d)
    ts, hh, p, temp, co2, ch4 = got
    f = lambda v: np.array([x if x is not None else 0.0 for x in v], float)
    return ts, np.asarray(hh, float), np.asarray(p, float), f(co2), f(ch4)


def descents(hh, p, min_pts=30, min_drop=0.05, min_hr=1.0):
    """以補氣為界切下降段。⚠ 下降量一律 段首−段尾，不可加總負差。"""
    segs, start, valley = [], 0, p[0]
    for i in range(1, len(p)):
        if hh[i] - hh[i - 1] > GAPH or p[i] - valley > RISE:
            if i - 1 > start:
                segs.append((start, i - 1))
            start, valley = i, p[i]
        elif p[i] < valley:
            valley = p[i]
    segs.append((start, len(p) - 1))
    return [(s, e) for s, e in segs
            if e - s >= min_pts and p[s] - p[e] >= min_drop and hh[e] - hh[s] >= min_hr]


def ols(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    X = np.vstack([np.ones(len(x)), x]).T
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ b
    s2 = float(r @ r) / max(1, len(x) - 2)
    cov = s2 * np.linalg.inv(X.T @ X)
    return float(b[1]), float(np.sqrt(cov[1, 1]))


def perm_median_p(a, b, n_iter=20000, seed=0):
    rng = np.random.default_rng(seed)
    obs = abs(np.median(b) - np.median(a))
    pool = np.concatenate([a, b])
    n = len(a)
    hit = sum(abs(np.median(q[n:]) - np.median(q[:n])) >= obs
              for q in (rng.permutation(pool) for _ in range(n_iter)))
    return hit / n_iter


def power_at(a, b, delta, nrep=1500, seed=1):
    """把 b 整體下移 delta，估 5% 水準下偵測得到的機率。"""
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(nrep):
        aa = rng.choice(a, len(a), replace=True)
        bb = rng.choice(b, len(b), replace=True) - delta
        o = abs(np.median(bb) - np.median(aa))
        pl = np.concatenate([aa, bb])
        k = sum(abs(np.median(q[len(aa):]) - np.median(q[:len(aa)])) >= o
                for q in (rng.permutation(pl) for _ in range(199)))
        if (k + 1) / 200 < 0.05:
            hits += 1
    return hits / nrep


def test1_dilution(ts, hh, p, c, m):
    """補氣時 CH4 有沒有被稀釋 —— 判斷讀數是不是頂空莫耳分率。"""
    print('═' * 72)
    print('檢定一　補氣稀釋反應（真頂空 → 斜率 −1；無反應 → 0）')
    dx, dP = [], []
    for i in range(1, len(ts)):
        if (p[i] - p[i - 1] > RISE and hh[i] - hh[i - 1] < GAPH
                and m[i] > 5 and m[i - 1] > 5):
            dx.append(np.log(m[i] / m[i - 1]))
            dP.append(np.log((p[i] + ATM) / (p[i - 1] + ATM)))
    b, se = ols(dP, dx)
    print('   補氣瞬間　n=%d　斜率 %+.3f ± %.3f　距 −1 為 %.1fσ，距 0 為 %.1fσ'
          % (len(dx), b, se, abs(b + 1) / se, abs(b) / se))
    sl = []
    for s, e in descents(hh, p, min_pts=30, min_drop=0.05, min_hr=0.0):
        if m[s] <= 5:
            continue
        X = np.log(p[s:e + 1] + ATM)
        if X.std() < 1e-6:
            continue
        sl.append(np.polyfit(X, np.log(np.clip(m[s:e + 1], 0.1, None)), 1)[0])
    sl = np.array(sl)
    print('   循環內　　n=%d　斜率中位 %+.3f　IQR [%+.3f, %+.3f]'
          % (len(sl), np.median(sl), *np.percentile(sl, [25, 75])))
    print('   → 分鐘尺度無反應、小時尺度部分反應 = 滯後追蹤，不可做分壓平衡')
    return b, se


def test3_exhaustion(ts, hh, p, c, m):
    """CO2 耗盡前後的壓降速率。"""
    print('\n' + '═' * 72)
    print('檢定三　CO2 耗盡天然實驗')
    segs = descents(hh, p)
    A, B, rows = [], [], []
    for s, e in segs:
        r = (p[s] - p[e]) / (hh[e] - hh[s])
        d = ts[s].date()
        grp = 'CO2尚存' if d <= CUT_A else ('CO2歸零' if d >= CUT_B else '過渡')
        rows.append(dict(start=ts[s].strftime('%Y-%m-%d %H:%M'), group=grp,
                         hours=round(hh[e] - hh[s], 2), drop=round(p[s] - p[e], 3),
                         rate=round(r, 5), co2=round(float(np.median(c[s:e + 1])), 2),
                         ch4=round(float(np.median(m[s:e + 1])), 2)))
        if grp == 'CO2尚存':
            A.append(r)
        elif grp == 'CO2歸零':
            B.append(r)
    A, B = np.array(A), np.array(B)
    print('   CO2 尚存（~%s）n=%3d　速率中位 %.4f（SD %.4f）' % (CUT_A, len(A), np.median(A), A.std(ddof=1)))
    print('   CO2 歸零（%s~）n=%3d　速率中位 %.4f（SD %.4f）' % (CUT_B, len(B), np.median(B), B.std(ddof=1)))
    print('   差 %+.4f　置換 p = %.4f' % (np.median(B) - np.median(A), perm_median_p(A, B)))
    print('\n   MDE（虛無若無檢定力就不是證據）：')
    for d in (0.004, 0.006, 0.008, 0.010, RB_PAPER):
        tag = '  ← 論文 r_b' if abs(d - RB_PAPER) < 1e-9 else ''
        print('      生物貢獻 %.4f（佔總降 %2.0f%%）→ 檢定力 %3.0f%%%s'
              % (d, d / np.median(A) * 100, power_at(A, B, d) * 100, tag))
    return rows


def ch4_inventory(ts, hh, p, m, d0, d1, label):
    """p_CH4 = x·P_abs。無產氣 ⟺ p_CH4 定值（補氣稀釋與下降濃縮恰好抵銷）。"""
    i0 = min(range(len(ts)), key=lambda k: abs((ts[k] - d0).total_seconds()))
    i1 = min(range(len(ts)), key=lambda k: abs((ts[k] - d1).total_seconds()))
    q0 = m[i0] / 100 * (p[i0] + ATM)
    q1 = m[i1] / 100 * (p[i1] + ATM)
    hrs = hh[i1] - hh[i0]
    print('   %-16s p_CH4 %.4f → %.4f　Δ %+.4f　淨產甲烷 %+.5f kg/cm²/hr'
          % (label, q0, q1, q1 - q0, (q1 - q0) / hrs))
    return q1 - q0, hrs


def main():
    ts, hh, p, c, m = load(AUTO)
    print('自動化批 %d 筆　%s ~ %s\n' % (len(ts), ts[0].date(), ts[-1].date()))
    test1_dilution(ts, hh, p, c, m)
    print('\n' + '═' * 72)
    print('CH4 存量（判斷產甲烷有沒有停）')
    ch4_inventory(ts, hh, p, m, dt.datetime(2026, 8, 11, 12), dt.datetime(2026, 8, 23, 12), '產氣期')
    ch4_inventory(ts, hh, p, m, dt.datetime(2026, 8, 26, 12), dt.datetime(2026, 8, 31, 6), 'CO2 歸零後')
    print('   → 歸零後 p_CH4 下降 = 沒有淨產甲烷，且存在未解釋的 CH4 消失途徑')
    rows = test3_exhaustion(ts, hh, p, c, m)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'co2_exhaustion_test.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print('\n逐循環明細 -> %s（%d 列）' % (os.path.relpath(path, REPO), len(rows)))


if __name__ == '__main__':
    main()
