
# -*- coding: utf-8 -*-
"""
觸發設定點的全年追蹤（Trigger Setpoint Tracking）
════════════════════════════════════════════════════════════════════════

先前用 Pend（循環末壓）當控制面通道，但它**被手動排氣污染**——排氣會把
Pend 拉到 0.2–0.5，必須先 Hampel 濾波才能用。

改用**補氣事件的起始壓力**：那是控制器觸發瞬間的壓力，是設定點的**直接讀數**。
排氣造成的低壓補氣只是少數，用**眾數**（最密集的分箱）估計即可免疫。

判別依據（設備方證實）：
  · 循環下降 ≈ 0.03 kg/cm²/hr
  · 補氣上升 ≈ 1.8–13.6 kg/cm²/hr   → **快 60–450 倍**
兩個數量級的差距使上升事件的辨識不需要調參。

輸出 -> docs/analysis_charts_3batch/trigger_setpoint.csv
"""
import sys
import csv
import datetime as dt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from three_class_typology import partition_mean, calibrate_mean    # noqa: E402

MERGE_MIN = 15      # 相隔 < 15 分鐘的上升事件視為同一次補氣的碎片
WIN = 15            # 滑動窗（補氣事件數）
BINW = 0.05         # 眾數估計的分箱寬度
MIN_SHIFT = 0.03    # 設定點移位的最小效應量（3 個量化步階）


def load_events():
    rows = []
    with open(f'{OUT}/refill_kinetics.csv', encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            rows.append(dict(
                t=dt.datetime.strptime(r['time'], '%Y-%m-%d %H:%M'),
                P_from=float(r['P_from']), P_to=float(r['P_to']),
                amp=float(r['amp']), rate=float(r['rate'])))
    rows.sort(key=lambda x: x['t'])
    return rows


def merge_fragments(ev, gap_min=MERGE_MIN):
    """把同一次補氣被量化雜訊切碎的片段併回去，只留**第一個**片段的起始壓力。"""
    out = []
    for e in ev:
        if out and (e['t']-out[-1]['t_end']).total_seconds()/60 <= gap_min:
            out[-1]['P_to'] = e['P_to']
            out[-1]['t_end'] = e['t']
            out[-1]['nfrag'] += 1
            continue
        out.append(dict(t=e['t'], t_end=e['t'], P_from=e['P_from'],
                        P_to=e['P_to'], rate=e['rate'], nfrag=1))
    for o in out:
        o['amp'] = o['P_to']-o['P_from']
    return out


def mode_bin(v, w=BINW):
    """最密集分箱的中心＝穩健眾數。對少數離群（排氣後低壓補氣）免疫。"""
    if len(v) == 0:
        return np.nan
    lo, hi = np.floor(v.min()/w)*w, np.ceil(v.max()/w)*w+w
    edges = np.arange(lo, hi+w, w)
    c, _ = np.histogram(v, bins=edges)
    k = int(np.argmax(c))
    sel = v[(v >= edges[k]) & (v < edges[k+1])]
    return float(np.median(sel)) if len(sel) else np.nan


def main():
    ev = merge_fragments(load_events())
    T = [e['t'] for e in ev]
    Pf = np.array([e['P_from'] for e in ev])
    n = len(ev)
    print('══ 觸發設定點的全年追蹤 ══')
    print(f'   合併碎片後補氣事件 {n} 個'
          f'   {T[0].date()} → {T[-1].date()}')
    print(f'   （合併前 {len(load_events())} 個，'
          f'平均每次補氣 {len(load_events())/n:.1f} 個片段）\n')

    print('── 月度設定點（穩健眾數，對排氣免疫）──')
    print(f'   {"月":<10}{"n":>5}{"眾數":>9}{"中位":>9}{"眾數簇佔比":>12}')
    print('   '+'-'*46)
    import collections
    by = collections.defaultdict(list)
    for e in ev:
        by[(e['t'].year, e['t'].month)].append(e['P_from'])
    prev = None
    for k in sorted(by):
        v = np.array(by[k])
        m = mode_bin(v)
        frac = np.mean(np.abs(v-m) < BINW) if np.isfinite(m) else np.nan
        flag = ''
        if prev is not None and np.isfinite(m) and abs(m-prev) >= MIN_SHIFT:
            flag = f'   ← Δ={m-prev:+.3f}'
        print(f'   {k[0]}-{k[1]:02d}   {len(v):>5}{m:>9.3f}'
              f'{np.median(v):>9.3f}{frac:>12.0%}{flag}')
        if np.isfinite(m):
            prev = m

    # ── 不重疊窗的設定點軌跡 ──────────────────────────────
    # ⚠ 用**不重疊**窗而非滑動窗：重疊窗會製造假的自相關（相鄰點共用 WIN−1 個
    #   樣本），使 AR(1) 虛無校準失真；且 O(n²) 的 DP 在上千點的軌跡上跑不動。
    print(f'\n── 設定點軌跡（不重疊窗，窗寬 {WIN} 次補氣）──')
    traj, tt = [], []
    for i in range(0, n-WIN+1, WIN):
        traj.append(mode_bin(Pf[i:i+WIN]))
        tt.append(T[i+WIN//2])
    traj = np.array(traj)
    ok = np.isfinite(traj)
    traj, tt = traj[ok], [t for t, o in zip(tt, ok) if o]
    print(f'   軌跡長度 {len(traj)}   範圍 [{traj.min():.2f}, {traj.max():.2f}]')

    # ── 對照組：變點偵測（**在此通道上不適用，保留以說明為何**）──────
    rng = np.random.default_rng(31)
    m, phi, s2 = calibrate_mean(traj, rng, nsur=120)
    cps = partition_mean(traj, m*s2)
    print(f'\n   〔對照〕變點偵測：校準 β = {m:.0f}·σ̂²'
          f'（σ̂={np.sqrt(s2):.4f}, φ={phi:+.2f}）→ 候選 {len(cps)} 個')
    print('   ⚠ AR(1) 虛無在此通道上**設定錯誤**：這不是自相關的連續過程，')
    print('     而是**量化的分段常數**。AR(1) 替代序列會自行產生假階梯，')
    print('     逼使校準把 β 推高到連真階梯一併壓掉。')
    print('     （2025-11 起的子序列：0.71×12 → 0.72 → 0.92×2，肉眼可見，')
    print('      但成本下降 0.0759 vs 懲罰 0.0749，差 1% 而未達門檻。）')

    # ── 正解：眾數追蹤（無需變點偵測）─────────────────────
    print(f'\n── ★ 設定點變更（眾數追蹤，門檻 {MIN_SHIFT:.2f} ＝ 3 LSB）──')
    print('   通道 76–100% 集中在單一量化值上 → 直接追蹤眾數即可，'
          '不需變點偵測。')
    print(f'\n   {"日期":<13}{"前":>8}{"後":>8}{"Δ":>9}{"持續窗數":>10}')
    print('   '+'-'*52)
    kept, i = [], 1
    while i < len(traj):
        d = traj[i]-traj[i-1]
        if abs(d) >= MIN_SHIFT:
            # 要求新水準持續 ≥2 個窗（排除單窗跳動）
            j = i
            while j+1 < len(traj) and abs(traj[j+1]-traj[i]) < MIN_SHIFT:
                j += 1
            hold = j-i+1
            if hold >= 2:
                print(f'   {str(tt[i].date()):<13}{traj[i-1]:>8.3f}'
                      f'{traj[i]:>8.3f}{d:>+9.3f}{hold:>10}')
                kept.append((tt[i].date(), traj[i-1], traj[i], d, hold))
            i = j+1
        else:
            i += 1
    print(f'\n   共 {len(kept)} 次設定點變更')

    print('\n── 上升 vs 下降的速率不對稱（設備方指出的判別特徵）──')
    r = np.array([e['rate'] for e in ev])
    print(f'   補氣上升速率  中位 {np.median(r):.2f} kg/cm²/hr'
          f'   IQR [{np.quantile(r,.25):.2f}, {np.quantile(r,.75):.2f}]')
    print(f'   循環下降速率  約 0.03 kg/cm²/hr（見三批次分析）')
    print(f'   → 不對稱倍率 ≈ {np.median(r)/0.03:.0f}×'
          f'   **兩個數量級，故上升事件的辨識不需調參**')

    with open(f'{OUT}/trigger_setpoint.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['time', 'setpoint_mode'])
        for t, v in zip(tt, traj):
            w.writerow([t.strftime('%Y-%m-%d %H:%M'), f'{v:.3f}'])
    print(f'\n輸出 → {OUT}/trigger_setpoint.csv')


if __name__ == '__main__':
    main()
