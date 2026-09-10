# -*- coding: utf-8 -*-
"""
子問題分解 × 集合歸屬辨識（Set-Membership Identification, SMI）
════════════════════════════════════════════════════════════════════════

為什麼不用點估計
────────────────
本專案已重複七次觀察到同一失效：在結構上不可辨識的模型上，
點估計 + 自助區間會給出**假的精確**（窄 CI 但模型診斷失敗）。
集合歸屬辨識不回傳點，而回傳**可行集**：在某些方向有界、某些方向無界，
這正是不可辨識性的誠實表述。

子問題分解（每個對不同干擾免疫）
────────────────────────────────
  SP1  泵開／關的速率差      -> 對 P_eq、r_b 免疫（相減時消去）
  SP2  固定壓力下的批次漂移  -> 對 P_eq、r_b 的絕對水平免疫
  SP3  分箱內的雙時鐘係數    -> 對**任何 P 的函數形式**免疫

合併方式
────────
每個循環條件 i 量得 (k_i, c_i)：rate = k_i (P - P0) + c_i。
模型要求   c_i = k_i (P0 - P_eq) + r_b。
故每個條件在 (P_eq, r_b) 平面上定義一條**帶狀可行區**

    | c_i - k_i (P0 - P_eq) - r_b |  <=  tol_i

tol_i 取自該條件的自助不確定度。可行集 = 所有帶的交集。
逐一加入條件，觀察可行集如何收縮——這回答的是**設計問題**：
要幾個循環設定才能把 r_b 框住。

輸出 -> docs/analysis_charts_3batch/set_membership.csv + fig32
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
from paths import testing_data          # Testing_data 的位置解析
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv
import glob
import datetime as dt
import itertools

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT, RED, AQUA, BLUE, INK, INK2, MUTED, style  # noqa: E402
from analyze_new_methods import collect                  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OLD = os.path.join(testing_data(), '0301-0416_無循環與有循環_5mins')
SPLIT = dt.datetime(2026, 4, 7, 9)
P0 = 1.00
M, PORD, NT = 1.5, 6, 20
NB = 800


def weak_pts(t, y):
    out = []
    for tc in np.linspace(t[0]+M, t[-1]-M, NT):
        u = (t-tc)/M
        ins = np.abs(u) < 1
        if ins.sum() < 20:
            continue
        base = 1-u[ins]**2
        ph = base**PORD
        dph = PORD*base**(PORD-1)*(-2*u[ins])/M
        w = np.trapezoid(ph, t[ins])
        if w > 0:
            out.append((np.trapezoid(ph*y[ins], t[ins])/w,
                        np.trapezoid(dph*y[ins], t[ins])/w))
    return out


def conditions():
    d = {}
    for name, cs in collect().items():
        tag = {'1.1 (1min)': 'tau=1min', '2.1 (5min)': 'tau=5min',
               '3.1 (10min)': 'tau=10min'}.get(name, name)
        lst = []
        for ci, c in enumerate(cs):
            t = (c.ts-c.ts.iloc[0]).dt.total_seconds().values/3600
            y = c.p_reactor.values.astype(float)
            if t[-1] < 2*M+0.5 or (y[0]-y[-1]) < 0.10:
                continue
            for p, r in weak_pts(t, y):
                lst.append((p, r, ci))
        d[tag] = lst
    raw = []
    for fp in sorted(glob.glob(os.path.join(OLD, '*.csv'))):
        for line in open(fp, encoding='utf-8', errors='replace'):
            p = line.strip().split(',')
            if len(p) < 14:
                continue
            try:
                raw.append((dt.datetime(int(p[0]), int(p[1]), int(p[2]),
                                        int(p[3]), int(p[4]), int(float(p[5]))),
                            float(p[11])))
            except Exception:
                continue
    raw.sort()
    ts = [r[0] for r in raw]; P = np.array([r[1] for r in raw])
    h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
    cyc, valley, start = [], P[0], 0
    for i in range(1, len(P)):
        if h[i]-h[i-1] > 0.5:
            if h[i-1]-h[start] > 3:
                cyc.append((start, i-1))
            start, valley = i, P[i]; continue
        if P[i]-valley > 0.03:
            if h[i-1]-h[start] > 3:
                cyc.append((start, i-1))
            start, valley = i, P[i]
        elif P[i] < valley:
            valley = P[i]
    for tag, sel in (('泵關', lambda t: t < SPLIT), ('泵開5min', lambda t: t >= SPLIT)):
        lst = []
        for ci, (a, b) in enumerate(cyc):
            if h[b]-h[a] < 4 or P[a]-P[b] < 0.10 or not sel(ts[a]):
                continue
            for p, r in weak_pts(h[a:b+1]-h[a], P[a:b+1]):
                lst.append((p, r, ci))
        d[tag] = lst
    return d


def fit(pts):
    p = np.array([x[0] for x in pts]); r = np.array([x[1] for x in pts])
    A = np.column_stack([p-P0, np.ones(len(p))])
    b, *_ = np.linalg.lstsq(A, r, rcond=None)
    return b[0], b[1]


def band(pts, rng):
    """回傳 (k, c, tol_k, tol_c)：以叢集自助取 95% 半寬。"""
    k0, c0 = fit(pts)
    ids = np.array([x[2] for x in pts]); uc = np.unique(ids)
    K, C = [], []
    for _ in range(NB):
        pick = rng.choice(uc, len(uc), replace=True)
        m = np.concatenate([np.where(ids == c)[0] for c in pick])
        if len(m) < 20:
            continue
        k, c = fit([pts[i] for i in m])
        K.append(k); C.append(c)
    K, C = np.array(K), np.array(C)
    return (k0, c0,
            (np.percentile(K, 97.5)-np.percentile(K, 2.5))/2,
            (np.percentile(C, 97.5)-np.percentile(C, 2.5))/2)


def main():
    rng = np.random.default_rng(29)
    cond = conditions()
    order = [o for o in ['泵關', 'tau=1min', 'tau=10min', '泵開5min', 'tau=5min']
             if o in cond and len(cond[o]) > 30]
    print('══ 子問題：各條件的 (k, c) 與不確定度 ══')
    print(f"{'條件':<12}{'循環':>5}{'k':>9}{'±':>8}{'c':>10}{'±':>9}")
    print('-' * 54)
    B = {}
    for o in order:
        k, c, tk, tc = band(cond[o], rng)
        B[o] = (k, c, tk, tc)
        ncy = len({x[2] for x in cond[o]})
        print(f'{o:<12}{ncy:>5}{k:>9.4f}{tk:>8.4f}{c:>10.5f}{tc:>9.5f}')

    # ── 合併：在 (P_eq, r_b) 平面上求交集 ──────────────────────
    PE = np.linspace(-0.5, 1.05, 620)
    RB = np.linspace(-0.02, 0.06, 640)
    G_pe, G_rb = np.meshgrid(PE, RB, indexing='ij')

    def feas(o):
        k, c, tk, tc = B[o]
        # 對 k 的不確定度以最壞情況併入容差
        pred = k*(P0-G_pe) + G_rb
        tol = tc + tk*np.abs(P0-G_pe)
        return np.abs(c - pred) <= tol

    print('\n══ 合併：逐一加入條件，觀察可行集收縮 ══')
    print(f"{'加入後條件數':>12}{'r_b 下界':>12}{'r_b 上界':>12}"
          f"{'寬度':>10}{'P_eq 範圍':>20}")
    print('-' * 68)
    acc = np.ones_like(G_pe, bool)
    rows = []
    for n, o in enumerate(order, 1):
        acc &= feas(o)
        if not acc.any():
            print(f'{n:>12}   可行集為空 —— 模型被拒絕（加入「{o}」後）')
            rows.append(dict(n=n, added=o, rb_lo='', rb_hi='',
                             width='EMPTY', peq_lo='', peq_hi=''))
            break
        rb_v = G_rb[acc]; pe_v = G_pe[acc]
        rows.append(dict(n=n, added=o, rb_lo=f'{rb_v.min():.5f}',
                         rb_hi=f'{rb_v.max():.5f}',
                         width=f'{rb_v.max()-rb_v.min():.5f}',
                         peq_lo=f'{pe_v.min():.3f}', peq_hi=f'{pe_v.max():.3f}'))
        print(f'{n:>12}{rb_v.min():>12.5f}{rb_v.max():>12.5f}'
              f'{rb_v.max()-rb_v.min():>10.5f}'
              f'{f"[{pe_v.min():.2f}, {pe_v.max():.2f}]":>20}   +{o}')

    if acc.any():
        rb_v = G_rb[acc]
        print(f'\n   ★ 最終可行區間  r_b ∈ [{rb_v.min():.5f}, {rb_v.max():.5f}]')
        print(f'      {"包含 0 -> r_b 未被框住" if rb_v.min() <= 0 <= rb_v.max() else "★★ 不含 0 -> r_b 被框在正值"}')
        print(f'      可行集面積佔網格 {acc.mean()*100:.2f}%')

    # ── 設計問題：任兩／任三條件的組合能框多緊 ─────────────────
    print('\n══ 設計問題：不同條件組合對 r_b 的框定寬度 ══')
    best = []
    for m in (2, 3, 4):
        for comb in itertools.combinations(order, m):
            a = np.ones_like(G_pe, bool)
            for o in comb:
                a &= feas(o)
            if not a.any():
                best.append((np.inf, comb, 'EMPTY'))
                continue
            v = G_rb[a]
            best.append((v.max()-v.min(), comb, f'[{v.min():.4f}, {v.max():.4f}]'))
    best.sort(key=lambda x: x[0])
    print(f"{'寬度':>10}   組合")
    for w, comb, iv in best[:8]:
        print(f'{w if np.isfinite(w) else float("nan"):>10.5f}   '
              f'{" + ".join(comb):<44} {iv}')

    with open(f'{OUT}/set_membership.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        wtr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wtr.writeheader(); wtr.writerows(rows)

    figure(B, order, PE, RB, G_pe, G_rb, feas)
    print(f'\n輸出 → {OUT}/set_membership.csv')


def figure(B, order, PE, RB, G_pe, G_rb, feas):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6))
    ax = axes[0]
    cols = [BLUE, AQUA, RED, '#8A6FBF', '#D08A00']
    acc = np.ones_like(G_pe, bool)
    for i, o in enumerate(order):
        acc &= feas(o)
        if acc.any():
            ax.contour(PE, RB, acc.T.astype(float), levels=[0.5],
                       colors=[cols[i % len(cols)]], linewidths=1.6)
    ax.axhline(0, color=INK2, lw=1, ls=':')
    style(ax, '可行集隨條件加入而收縮', 'P_eq (kg/cm²)', 'r_b (kg/cm²/hr)')

    ax = axes[1]
    for i, o in enumerate(order):
        k, c, tk, tc = B[o]
        ax.errorbar([k], [c], xerr=[tk], yerr=[tc], fmt='o', ms=7,
                    color=cols[i % len(cols)], capsize=4, label=o)
    ax.axhline(0, color=INK2, lw=1, ls=':')
    style(ax, '各條件的 (k, c)：模型要求共線', 'k_La (1/hr)',
          'c = P0 處的速率')
    ax.legend(frameon=False, fontsize=9)
    fig.suptitle('圖32  子問題分解與集合歸屬辨識', fontweight='bold',
                 x=0.05, ha='left', y=0.99)
    fig.savefig(f'{OUT}/fig32_set_membership.png', bbox_inches='tight')
    plt.close(fig)
    print('  圖 32 完成')


if __name__ == '__main__':
    main()
