
# -*- coding: utf-8 -*-
"""
組成槓桿：合併 4:1 與 1:1 的資料能否辨識生物速率？
════════════════════════════════════════════════════════════════════════

先前十四次嘗試全部失敗，但**都是在單一進氣組成內**用 τ 當槓桿——
τ 只改變 k_La，兩個通道仍然共線。

組成槓桿不同：
    物理項 ∝ f_CO2   （4:1 → 0.2；1:1 → 0.5，**變大 2.5 倍**）
    生物項 受 H2 限制（4:1 → 0.8；1:1 → 0.5，**變小**）
兩個通道在兩種組成下往**相反方向**縮放，這是單一組成下不存在的資訊。

模型（每個循環的早期，遠離平衡）：

    dP/dt = −k_La(c) · [ f_CO2 · P − p* ]  −  r_b(f_H2)

  k_La(c)  每個循環條件各一（泵關／1／5／10 min/hr／連續）
  p*       CO2 在液相的飽和分壓，**與氣相組成無關**（同液體、同溫度）
  r_b      生物淨移除速率

檢定方式：對 r_b 做**剖面**——固定 r_b 於格點，其餘參數重新最佳化，
看懲罰曲線有無曲率。平坦 = 不可辨識；有曲率 = 可辨識並給出區間。

**這是決定性的檢定**：若合併兩種組成仍平坦，那就真的是觀測不足；
若有曲率，先前的結論就得推翻。
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import glob
import datetime as dt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import load, segment, TD                  # noqa: E402

M, PORD = 1.5, 6

# 進氣 CO2 莫耳分率與循環條件（依資料夾與日期）
FCO2_11 = '0109-0123_H2_1CO2_1'


def weak_pairs(t, y, nw=5):
    """循環內多個緊支撐測試函數 → 多組（壓力, 速率）。"""
    T = t[-1]-t[0]
    m = T/(nw+1)
    out = []
    for c in np.linspace(t[0]+m, t[-1]-m, nw):
        u = (t-c)/m
        ins = np.abs(u) < 1
        if ins.sum() < 8:
            continue
        base = 1-u[ins]**2
        ph = base**PORD
        dph = PORD*base**(PORD-1)*(-2*u[ins])/m
        w = np.trapezoid(ph, t[ins])
        if w <= 0:
            continue
        out.append((np.trapezoid(ph*y[ins], t[ins])/w,      # P
                    np.trapezoid(dph*y[ins], t[ins])/w))    # dP/dt
    return out


def cond_of(tag, ts):
    """循環條件標籤。

    ⚠ 2026-09-11 改為委派給 multivariate_increments.cond_of。此處原本是一份
      **複製品**，而兩份已經漂移：共用那份加了期間上界與自動化資料夾的排除，
      這份沒有——同一批循環在不同腳本裡會被歸到不同條件，而且不會報錯。

      漂移的代價實測過：2026-09-11 把自動化測試資料夾移進 Testing_data 後，
      舊版會把 3 個循環（tau10 的 17%）誤併進 tau10，終點值從 −62.3 被拉到 −53.0。
    """
    from multivariate_increments import cond_of as _shared
    return _shared(tag, ts.date())[0]


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

    seen, rows = {}, []
    for path, tag in folders:
        try:
            raw = load(path)
        except Exception:
            continue
        if len(raw) < 2000:
            continue
        cyc, h, P, ts = segment(raw)
        for a, b in cyc:
            key = (ts[a].replace(second=0), round(h[b]-h[a], 1))
            if key in seen:
                continue
            seen[key] = 1
            c = cond_of(tag, ts[a])
            if c == 'other':
                continue
            f = 0.5 if c == '1:1' else 0.2
            t = h[a:b+1]-h[a]; y = P[a:b+1]
            # 只用循環前半（遠離平衡，物理項近似線性）
            half = t <= t[-1]/2
            if half.sum() < 20:
                continue
            for Pm, dPdt in weak_pairs(t[half], y[half]):
                if np.isfinite(Pm) and np.isfinite(dPdt) and Pm > 0:
                    rows.append((c, f, Pm, dPdt))
    return rows


def fit(rows, rb_fixed=None):
    """最小平方：dP/dt = −k(c)·(f·P − p*) − rb。

    固定 rb 時，對每個條件的 k 與共用的 p* 求解。
    展開：dP/dt = −k(c)·f·P + k(c)·p* − rb
    令 A(c) = k(c)、B = p*，則 −dP/dt − rb = k(c)·f·P − k(c)·p*
    對每個 c：k(c)·(f·P − p*)。p* 非線性，故對 p* 做格點搜尋。
    """
    conds = sorted({r[0] for r in rows})
    best = None
    grid = np.arange(-0.20, 1.01, 0.01) if rb_fixed is not None \
        else np.arange(-0.20, 1.01, 0.02)
    for ps in grid:
        tot, ks = 0.0, {}
        ok = True
        for c in conds:
            sub = [r for r in rows if r[0] == c]
            x = np.array([r[1]*r[2]-ps for r in sub])       # f·P − p*
            yv = np.array([-r[3] for r in sub])             # −dP/dt
            if rb_fixed is not None:
                yv = yv-rb_fixed
            den = float(x @ x)
            if den <= 0:
                ok = False; break
            k = float(x @ yv)/den
            ks[c] = k
            res = yv-k*x
            tot += float(res @ res)
        if ok and (best is None or tot < best[0]):
            best = (tot, ps, ks)
    return best


def main():
    rows = gather()
    conds = sorted({r[0] for r in rows})
    print('══ 組成槓桿：合併 4:1 與 1:1 能否辨識生物速率？ ══\n')
    print(f'   弱形式配對 {len(rows)} 組，來自 {len(conds)} 個條件')
    for c in conds:
        n = sum(1 for r in rows if r[0] == c)
        f = next(r[1] for r in rows if r[0] == c)
        print(f'      {c:<10} n = {n:>4}   f_CO2 = {f}')
    if '1:1' not in conds:
        print('\n   ✘ 找不到 1:1 條件的資料，無法做組成槓桿')
        return

    print('\n── 自由擬合（rb 一併估計）──')
    # 先在 rb 格點上找全域最小
    best = None
    for rb in np.arange(-0.02, 0.061, 0.001):
        r = fit(rows, rb_fixed=rb)
        if r and (best is None or r[0] < best[0]):
            best = (r[0], r[1], r[2], rb)
    sse0, ps0, ks0, rb0 = best
    print(f'   rb   = {rb0:+.4f} kg/cm²/hr')
    print(f'   p*   = {ps0:+.3f} kg/cm²')
    for c in conds:
        print(f'   k_La({c:<9}) = {ks0[c]:.4f} /hr')
    print(f'   SSE  = {sse0:.5f}')

    # ── 剖面：這是決定性的一步 ────────────────────────────
    print('\n── rb 的剖面（固定 rb，其餘重新最佳化）──')
    print(f'   {"rb":>8}{"SSE":>12}{"相對最小值":>12}{"k_La(1:1)":>12}'
          f'{"k_La(泵關)":>12}')
    print('   '+'-'*58)
    prof = []
    for rb in np.arange(-0.02, 0.0601, 0.005):
        r = fit(rows, rb_fixed=rb)
        if not r:
            continue
        prof.append((rb, r[0], r[2]))
        mark = '  ←' if abs(rb-rb0) < 0.0005 else ''
        print(f'   {rb:>+8.3f}{r[0]:>12.5f}{r[0]/sse0:>12.4f}'
              f'{r[2].get("1:1", np.nan):>12.4f}'
              f'{r[2].get("pump_off", np.nan):>12.4f}{mark}')

    sses = np.array([p[1] for p in prof])
    rise = (sses.max()-sses.min())/sses.min()*100
    print(f'\n   剖面在檢視範圍內的最大上升：{rise:.1f}%')
    print(f'   → {"✓ 有明顯曲率，rb 可辨識" if rise > 20 else "✘ 幾乎平坦，rb 仍不可辨識"}')

    # ── 一致性檢查：k_La 的組成相依性 ─────────────────────
    print('\n── 一致性檢查 ──')
    print('   模型假設 k_La 與組成無關（只隨循環條件變）。')
    print('   1:1 期間循環泵是關的，故 k_La(1:1) 應接近 k_La(泵關)：')
    a, b = ks0.get('1:1', np.nan), ks0.get('pump_off', np.nan)
    print(f'      k_La(1:1) = {a:.4f}   k_La(泵關) = {b:.4f}'
          f'   比值 {a/b:.2f}')
    print(f'   → {"✓ 一致" if 0.6 < a/b < 1.7 else "✘ 不一致，模型設定有問題"}')


if __name__ == '__main__':
    main()
