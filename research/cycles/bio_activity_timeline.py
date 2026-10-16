# -*- coding: utf-8 -*-
"""生物活性時間軸：每個循環的 CO2 轉換速率（假設無洩漏），並以排氣 CH4 獨立驗證。

2026-10-17。

════════════════════════════════════════════════════════════════════════
前提（使用者決定，2026-10-17）
  · 溶解 ≈ 0：ph_abc（pH＋壓力的 ABC，校準通過）推得真實循環的溶解中位 −0.0005 kg/cm²/hr，
    區間都貼著 0。
  · 洩漏先當作 0，**但 2026-10-01 之後的循環一律標為「可能受洩漏影響」**（10/16 設備方確認
    有洩漏、起始時間不明）。
  ⟹ 壓降速率 ≈ 生物速率。化學計量 CO2 + 4H2 → CH4 + 2H2O：氣相淨少 4 單位／轉換 1 單位
    CO2（含從液相補回的 CO2；溶解≈0 時液相存量不變）。所以
        CO2 轉換速率 ＝ CH4 生成速率 ＝ 降速 ÷ 4（壓力單位）
  ⚠ 若其實有洩漏，這裡的數字是**上限**（9/21：35 次排氣中 34 次氫氣超量流失；
    9/11 週報以 CH4 化學計量算得 8/11–8/23 只有約 38% 是生物）。下面的 CH4 驗證就是
    在量這個落差。就算絕對值偏高，只要洩漏大致穩定，**活性的變化**仍看得出來。

做法
  · 讀 Testing_data 底下所有 CSV，**依時間戳全域去重**（資料夾會重疊；rb_per_cycle 逐
    資料夾讀，`data` 與 `20260727_1min_data` 的循環被重複計入）。
  · 切段沿用 clean_and_form.seg_clean（排除洗管線的日子），補氣後跳過 3 分鐘。
  · 速率＝最小平方斜率；80% 區間以 30 分鐘區塊重抽殘差（保留自相關）。
  · 絕對量用頭空 1.00 L（descent_report.HEADSPACE_L；⚠ 四分位 0.60–2.14，很寬，
    mmol/天只能看相對變化，比值與份額不受影響）。
  · CH4 驗證：descent_report.vent_intervals（相鄰排氣錨點之間，量到的 CH4 增量 ÷ 壓降推算
    的 CH4）。若壓降全是生物，生物份額應接近 100%。

輸出 -> docs/analysis_charts_3batch/bio_activity_cycles.csv、bio_activity_vents.csv
用法（在 Jetson 或任何有 Testing_data 的機器）：python bio_activity_timeline.py
"""
import csv
import datetime as dt
import glob
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
REPO = os.path.dirname(RESEARCH)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, RESEARCH)
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from clean_and_form import seg_clean, SKIP_MIN                     # noqa: E402
from multivariate_increments import cond_of                        # noqa: E402
from core import descent_report as DR                              # noqa: E402

TD = os.path.join(RESEARCH, 'Testing_data')
OUT = os.path.join(REPO, 'docs', 'analysis_charts_3batch')
I_ORP, I_PH, I_TEMP, I_P, I_CO2, I_CH4 = 7, 9, 10, 11, 12, 13
LEAK_FROM = dt.date(2026, 10, 1)
PH_FAULT = 8.0
BLOCK_MIN = 30


def load_all():
    """全部 CSV 依時間戳去重（先讀到的保留）。回傳排序後的陣列與每筆所屬資料夾。"""
    rows = {}
    for path in sorted(glob.glob(os.path.join(TD, '**', '*.csv'), recursive=True)):
        tag = os.path.relpath(os.path.dirname(path), TD).replace(os.sep, '/')
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                q = line.strip().split(',')
                if len(q) < 14:
                    continue
                try:
                    t = dt.datetime(int(q[0]), int(q[1]), int(q[2]),
                                    int(q[3]), int(q[4]), int(float(q[5])))
                    v = (float(q[I_P]), float(q[I_PH]), float(q[I_TEMP]),
                         float(q[I_CO2]), float(q[I_CH4]))
                except (ValueError, IndexError):
                    continue
                if t not in rows:
                    rows[t] = (v, tag)
    ts = sorted(rows)
    a = np.array([rows[t][0] for t in ts], float)
    tags = [rows[t][1] for t in ts]
    return ts, a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4], tags


def rate_ci(t, y, rng, nboot=400):
    """斜率（下降為正）與 80%、95% 區間：線性擬合殘差的 30 分鐘區塊重抽。"""
    A = np.vstack([t, np.ones_like(t)]).T
    c, *_ = np.linalg.lstsq(A, y, rcond=None)
    fit = A @ c
    res = y - fit
    n = len(y)
    L = max(5, min(BLOCK_MIN, n // 4))
    nb = (n + L - 1) // L
    starts = rng.integers(0, n - L + 1, (nboot, nb))
    idx = (starts[..., None] + np.arange(L)).reshape(nboot, -1)[:, :n]
    yb = fit[None, :] + res[idx]
    tc = t - t.mean()
    sl = ((yb - yb.mean(1, keepdims=True)) * tc).sum(1) / (tc * tc).sum()
    r = -c[0]
    return r, -np.percentile(sl, [90, 10, 97.5, 2.5])


def main():
    ts, P, pH, temp, co2, ch4, tags = load_all()
    h = np.array([(x - ts[0]).total_seconds() / 3600 for x in ts])
    print('全部資料（去重後）%d 筆　%s ~ %s' % (len(ts), ts[0], ts[-1]))
    cyc, wash = seg_clean(h, P, ts)
    rng = np.random.default_rng(0)
    rows = []
    for a, b in cyc:
        d = ts[a].date()
        if d in wash:
            continue
        t = h[a:b + 1] - h[a]
        sel = t >= SKIP_MIN
        if sel.sum() < 60:
            continue
        tt, yy = t[sel] - t[sel][0], P[a:b + 1][sel]
        r, (lo80, hi80, lo95, hi95) = rate_ci(tt, yy, rng)
        ph = pH[a:b + 1][sel]
        okp = ph < PH_FAULT
        ph_slope = float(np.polyfit(tt[okp], ph[okp], 1)[0]) if okp.sum() > 30 else float('nan')
        tm = float(np.mean(temp[a:b + 1]))
        mm = lambda x: 1000 * DR.moles_from_pressure(x / 4 * 24, DR.HEADSPACE_L, tm)  # mmol/天
        rows.append(dict(
            start=ts[a].strftime('%Y-%m-%d %H:%M'), folder=tags[a],
            cond=cond_of(tags[a], d)[0], hours=round(float(tt[-1]), 2),
            p_start=round(float(yy[0]), 3), p_end=round(float(yy[-1]), 3),
            rate=round(r, 5), rate_lo80=round(lo80, 5), rate_hi80=round(hi80, 5),
            rate_lo95=round(lo95, 5), rate_hi95=round(hi95, 5),
            co2_mmol_day=round(mm(r), 3), co2_mmol_day_lo80=round(mm(lo80), 3),
            co2_mmol_day_hi80=round(mm(hi80), 3),
            ph_slope=round(ph_slope, 5), temp=round(tm, 2),
            leak_period=int(d >= LEAK_FROM)))
    print('循環 %d 個（排除洗管線日 %d 天）；其中 10/01 之後（可能受洩漏影響）%d 個'
          % (len(rows), len(wash), sum(r['leak_period'] for r in rows)))
    with open(os.path.join(OUT, 'bio_activity_cycles.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # ── CH4 獨立驗證 ──
    segs = [(a, b) for a, b in cyc if ts[a].date() not in wash]
    ch4_list = [float(x) for x in ch4]
    vi = DR.vent_intervals(ts, h, P, ch4_list, segments=segs, volume_l=DR.HEADSPACE_L,
                           temps=[float(x) for x in temp])
    print(vi['coverage_note'])
    vrows = []
    for r in vi['intervals']:
        st = r['stoichiometry'] or {}
        vrows.append(dict(start=r['ts_start'][:16], end=r['ts_end'][:16], hours=r['duration_hr'],
                          n_descents=r['n_descents'], ch4_start=r['ch4_start_pct'],
                          ch4_end=r['ch4_end_pct'], consumed=r['consumed_kgf_cm2'],
                          status=st.get('status'), bio_share=st.get('bio_share')))
    with open(os.path.join(OUT, 'bio_activity_vents.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(vrows[0]))
        w.writeheader()
        w.writerows(vrows)
    ok = [v for v in vrows if v['status'] == 'ok']
    sh = np.array([v['bio_share'] for v in ok], float)
    if len(sh):
        print('CH4 驗證：可用區間 %d 個，生物份額中位 %.0f%%（四分位 %.0f–%.0f%%）'
              % (len(sh), np.median(sh) * 100, *np.percentile(sh, [25, 75]) * 100))
    rr = np.array([r['rate'] for r in rows])
    print('循環降速中位 %.4f kg/cm²/hr → CO2 轉換中位 %.2f mmol/天（頭空 %.2f L）'
          % (np.median(rr), np.median([r['co2_mmol_day'] for r in rows]), DR.HEADSPACE_L))
    print('-> docs/analysis_charts_3batch/bio_activity_cycles.csv、bio_activity_vents.csv')


if __name__ == '__main__':
    main()
