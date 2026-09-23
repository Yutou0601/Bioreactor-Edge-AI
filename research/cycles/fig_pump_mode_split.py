# -*- coding: utf-8 -*-
"""pump_mode_split.py 的圖（2026-09-17）。三張：

  fig33  脈衝長什麼樣：tau10 一個循環的原始壓力＋泵窗，放大兩小時看分鐘怎麼標
  fig34  主結果：包絡速率隨 τ 翻倍、r_off 不動；每小時壓降的預算拆分
  fig35  三個檢查：r_off 不隨壓力變／安靜期內平坦／回升與驟降配對

輸出 -> docs/analysis_charts_3batch/fig33~35
"""
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                      # noqa: E402
from matplotlib.patches import Patch                 # noqa: E402
from matplotlib.lines import Line2D                  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))            # research/
sys.path.insert(0, HERE)
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (                  # noqa: E402
    BLUE, YELLOW, AQUA, RED, INK, INK2, MUTED, BASELINE, GRID, OUT, style)
import pump_mode_split as M                          # noqa: E402

COL = {'tau1': BLUE, 'tau5': YELLOW, 'tau10': AQUA}
MK = {'tau1': 'o', 'tau5': 's', 'tau10': '^'}
NAME = {'tau1': 'τ=1 分/時', 'tau5': 'τ=5 分/時', 'tau10': 'τ=10 分/時'}
RB, RB_LO, RB_HI = M.RB_PAPER
UNIT = 'kg/cm²/hr'


def rb_band(ax, label=None):
    """論文 r_b 的參考帶。label 給座標時把說明放在圖區右外緣，避開資料點。"""
    ax.axhspan(RB_LO, RB_HI, color=RED, alpha=0.10, lw=0)
    ax.axhline(RB, color=RED, lw=1, ls='--', alpha=0.8)
    if label is not None:
        ax.text(label, RB, '論文 r_b\n0.0125\n[0.0112,\n 0.0139]', ha='left',
                va='center', fontsize=8, color=RED, linespacing=1.35)


# ═══════════════════════════════════════════════════════════════
def fig33(B):
    """tau10 一個循環：原始壓力＋泵窗；放大兩小時看分鐘標籤。"""
    t2, h2, p2 = B['t2'], B['h2'], B['p2']
    gap = B['gap']
    # 挑一個中位長度的循環（第 5 個：6.0 hr，1.17→0.91）
    ci = 5
    c = B['reg'][ci - 1]
    on_c, rows = B['rows_by_cyc'][ci]
    s, e = c['s'], c['e']
    t = (h2[s:e + 1] - h2[s])
    y = p2[s:e + 1]
    tt = t2[s:e + 1]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7.4),
                                   gridspec_kw={'height_ratios': [1, 1.15], 'hspace': 0.42})

    # ── (a) 整個循環 ──
    lab_t = np.array([(x.minute - on_c) % 60 for x in tt])
    on_mask = lab_t < gap
    # 泵開窗口著色
    j = 0
    while j < len(t):
        if on_mask[j]:
            k = j
            while k + 1 < len(t) and on_mask[k + 1]:
                k += 1
            ax1.axvspan(t[j] - 1 / 120, t[k] + 1 / 120, color=AQUA, alpha=0.18, lw=0)
            j = k + 1
        else:
            j += 1
    ax1.plot(t, y, color=INK, lw=1.2)
    # 包絡線（直線擬合）
    sl, r2 = M.lin_r2(t, y)
    a = y.mean() + sl * t.mean()
    ax1.plot(t, a - sl * t, color=MUTED, lw=1, ls='--')
    xa = t[-1] * 0.72
    ax1.annotate('包絡線（直線擬合 R² = %.2f）\n論文擬合的是這條' % r2,
                 xy=(xa, a - sl * xa), xytext=(t[-1] * 0.40, y.min() + 0.028),
                 ha='left', va='bottom', fontsize=8.5, color=INK2,
                 arrowprops=dict(arrowstyle='-', color=BASELINE, lw=0.8))
    ax1.text(t[on_mask][0] + 0.02, y.max() - 0.005, '綠帶 = 泵運轉（每小時 %d 分）' % gap,
             ha='left', va='top', fontsize=8.5, color=INK2)
    style(ax1, 'a　τ=10 批第 %d 個循環：壓力不是平滑下降，是每小時一階' % ci,
          '循環開始後的小時', '壓力 (kg/cm²)')
    ax1.set_xlim(-0.05, t[-1] + 0.05)

    # ── (b) 放大兩小時 ──
    # 取循環中段完整的兩個小時
    hk = sorted({x.strftime('%m-%d %H') for x in tt})
    mid = hk[len(hk) // 2 - 1: len(hk) // 2 + 1]
    sel = np.array([x.strftime('%m-%d %H') in mid for x in tt])
    idx = np.flatnonzero(sel)
    tz, yz, tzt = t[idx], y[idx], [tt[i] for i in idx]
    labs = []
    for x in tzt:
        k = (x.minute - on_c) % 60
        labs.append('spike' if k == 0 else 'on' if k < gap else 'rebound' if k == gap
                    else 'edge' if (k <= gap + M.GUARD or k >= 60 - M.GUARD) else 'off')
    band = {'spike': (RED, 0.22), 'on': (AQUA, 0.18), 'rebound': (YELLOW, 0.35),
            'edge': (MUTED, 0.18), 'off': (None, 0)}
    # 每分鐘的壓降 p[j-1]-p[j] 歸在第 j 分，所以帶子畫在 (t_{j-1}, t_j]
    for j in range(1, len(tz)):
        col, al = band[labs[j]]
        if col:
            ax2.axvspan(tz[j - 1], tz[j], color=col, alpha=al, lw=0)
    ax2.plot(tz, yz, color=INK, lw=1.1, marker='.', ms=4)
    # 安靜期的斜率示意
    # ⚠ 必須對「連續的安靜段」擬合。安靜期是從泵停跨到下一次泵開，會跨過整點，
    #   若按時鐘小時分組，同一組會含被泵窗切開的前後兩段，擬合線橫跨泵事件，
    #   斜率會灌成 0.04 以上（真值 ~0.009）。
    runs, cur = [], []
    for j in range(len(tz)):
        contig = j == 0 or (tz[j] - tz[j - 1]) < 1.6 / 60
        if labs[j] == 'off' and (contig or not cur):
            cur.append(j)
        else:
            if len(cur) >= 15:
                runs.append(cur)
            cur = [j] if labs[j] == 'off' else []
    if len(cur) >= 15:
        runs.append(cur)
    for r in runs:
        r = np.array(r)
        sl_q, _ = M.lin_r2(tz[r], yz[r])
        aq = yz[r].mean() + sl_q * tz[r].mean()
        ax2.plot(tz[r], aq - sl_q * tz[r], color=BLUE, lw=1.6, zorder=5)
        ax2.annotate('安靜期 %d 分：斜率 %.4f' % (len(r), sl_q),
                     xy=(tz[r].mean(), aq - sl_q * tz[r].mean()),
                     xytext=(tz[r].mean(), yz.max() - 0.004),
                     ha='center', va='top', fontsize=8.5, color=BLUE,
                     arrowprops=dict(arrowstyle='-', color=BLUE, lw=0.7, alpha=0.5))
    style(ax2, 'b　放大兩小時：每一分鐘怎麼標', '循環開始後的小時', '壓力 (kg/cm²)')
    ax2.set_xlim(tz[0] - 0.02, tz[-1] + 0.02)
    yr = yz.max() - yz.min()
    ax2.set_ylim(yz.min() - 0.12 * yr, yz.max() + 0.62 * yr)
    handles = [Patch(color=RED, alpha=0.4, label='驟降尖峰（泵開第 1 分）'),
               Patch(color=AQUA, alpha=0.35, label='泵開（其餘 %d 分）' % (gap - 1)),
               Patch(color=YELLOW, alpha=0.5, label='回升（泵停那一分）'),
               Patch(color=MUTED, alpha=0.3, label='保護帶（頭尾各 %d 分，不算）' % M.GUARD),
               Line2D([], [], color=BLUE, lw=1.6, label='安靜期擬合 → r_off')]
    ax2.legend(handles=handles, loc='upper right', fontsize=8.5, frameon=False, ncol=2)

    fig.savefig(os.path.join(OUT, 'fig33_pump_pulse_anatomy.png'))
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════
def fig34(BS):
    """主結果：包絡速率 vs r_off 隨 τ；每小時壓降預算。"""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.9),
                                   gridspec_kw={'width_ratios': [1.15, 1], 'wspace': 0.3})
    xs = {'tau1': 0, 'tau5': 1, 'tau10': 2}
    rng = np.random.default_rng(0)
    med_env, med_off = [], []
    for nm, B in BS.items():
        pc = B['per_cyc']
        env = np.array([c['drop'] / c['dur'] for c in pc])
        off = np.array([c['r_off'] for c in pc])
        x = xs[nm]
        jit = rng.uniform(-0.06, 0.06, len(pc))
        ax1.scatter(x - 0.18 + jit, env, s=22, color=MUTED, alpha=0.7, lw=0, zorder=3)
        ax1.scatter(x + 0.18 + jit, off, s=26, color=COL[nm], marker=MK[nm],
                    alpha=0.85, lw=0, zorder=3)
        ax1.hlines(np.median(env), x - 0.30, x - 0.06, color=INK, lw=2, zorder=4)
        ax1.hlines(np.median(off), x + 0.06, x + 0.30, color=INK, lw=2, zorder=4)
        med_env.append(np.median(env))
        med_off.append(np.median(off))
        # 中位數的字放在該欄橫線的外側，不要壓在點雲上
        ax1.text(x - 0.33, np.median(env), '%.4f' % np.median(env),
                 ha='right', va='center', fontsize=8.5, color=INK2)
        ax1.text(x + 0.33, np.median(off), '%.4f' % np.median(off),
                 ha='left', va='center', fontsize=8.5, color=INK2)
    ax1.plot([xs[k] - 0.18 for k in xs], med_env, color=MUTED, lw=1, ls=':', zorder=2)
    ax1.plot([xs[k] + 0.18 for k in xs], med_off, color=INK2, lw=1, ls=':', zorder=2)
    rb_band(ax1, label=2.62)
    ax1.set_xticks([0, 1, 2])
    ax1.set_xticklabels([NAME[k] for k in xs])
    ax1.set_xlim(-0.58, 3.20)
    ax1.set_ylim(-0.002, 0.060)
    ax1.text(-0.52, 0.0575, '左欄　包絡速率（每循環整段平均）', ha='left', va='top',
             fontsize=8.5, color=MUTED)
    ax1.text(-0.52, 0.0525, '右欄　r_off（泵停安靜期）', ha='left', va='top',
             fontsize=8.5, color=INK2)
    ax1.annotate('τ 1→10：×%.1f' % (med_env[2] / med_env[0]),
                 xy=(2 - 0.26, med_env[2]), xytext=(2.30, 0.0465), ha='left',
                 fontsize=9, color=INK, arrowprops=dict(arrowstyle='-', color=BASELINE))
    ax1.annotate('r_off：×%.1f' % (med_off[2] / med_off[0]),
                 xy=(2 + 0.26, med_off[2]), xytext=(2.40, 0.0020), ha='left',
                 fontsize=9, color=INK, arrowprops=dict(arrowstyle='-', color=BASELINE))
    style(ax1, 'a　泵停期速率 r_off 不隨 τ 變（每點＝一個循環，橫線＝中位）',
          None, '速率 (%s)' % UNIT)

    # ── (b) 每小時壓降預算 ──
    keys = [('泵開（驟降＋運轉）', ('spike', 'on'), AQUA),
            ('回升', ('rebound',), YELLOW),
            ('保護帶', ('edge',), MUTED),
            ('安靜期', ('off',), BLUE)]
    for nm, B in BS.items():
        pc = B['per_cyc']
        hours = sum(c['dur'] for c in pc)
        x = xs[nm]
        pos, neg = 0.0, 0.0
        for lab, parts, col in keys:
            v = sum(c['tot'][k] for c in pc for k in parts) / hours
            if v >= 0:
                ax2.bar(x, v, bottom=pos, width=0.55, color=col, alpha=0.85, lw=0)
                yc = pos + v / 2
                pos += v
            else:
                ax2.bar(x, v, bottom=neg, width=0.55, color=col, alpha=0.85, lw=0)
                yc = neg + v / 2
                neg += v
            if abs(v) > 0.0040:
                ax2.text(x, yc, '%+.4f' % v, ha='center', va='center', fontsize=8,
                         color=INK)
        net = sum(c['drop'] for c in pc) / hours
        # 淨值的刻度畫在長條之外（長條寬 0.55），否則會壓到薄段的數字標籤
        ax2.hlines(net, x + 0.30, x + 0.42, color=INK, lw=2, zorder=5)
        ax2.text(x + 0.44, net, '淨 %.4f' % net, ha='left', va='center', fontsize=8.5,
                 color=INK)
    ax2.axhline(0, color=BASELINE, lw=1)
    ax2.set_xticks([0, 1, 2])
    ax2.set_xticklabels([NAME[k] for k in xs])
    ax2.set_xlim(-0.5, 3.05)
    ax2.legend(handles=[Patch(color=c, alpha=0.85, label=l) for l, _, c in keys],
               loc='upper left', fontsize=8.5, frameon=False)
    style(ax2, 'b　每小時壓降的預算：τ 加的全在泵開那幾分鐘', None,
          '每小時壓降 (kg/cm²)')

    fig.savefig(os.path.join(OUT, 'fig34_roff_vs_tau.png'))
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════
def fig35(BS):
    """三個檢查。"""
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14, 4.4),
                                        gridspec_kw={'wspace': 0.32})

    # ── (a) r_off vs 壓力（每小時）──
    Pd, Yd = [], []
    for nm, B in BS.items():
        H = B['hours']
        P = np.array([x['P'] for x in H])
        y = np.array([x['r_off'] for x in H])
        ax1.scatter(P, y, s=18, color=COL[nm], marker=MK[nm], alpha=0.65, lw=0,
                    label=NAME[nm])
        a, b, _ = M.ols(P, y)
        xx = np.array([P.min(), P.max()])
        ax1.plot(xx, a + b * xx, color=COL[nm], lw=1.4)
        Pd += list(P - P.mean())
        Yd += list(y - y.mean())
    _, b, seb = M.ols(Pd, Yd)
    pv = M.perm_slope_p(Pd, Yd)
    rb_band(ax1)
    ax1.text(0.02, 0.98,
             '合併斜率 %+.4f ± %.4f（p = %.2f）\n一個循環掉 0.25 → r_off 只變 %+.0f%%\n'
             '⚠ 縱軸呈橫列：一小時的安靜期只掉 0~3 個 0.01 量化階'
             % (b, seb, pv, -0.25 * b / RB * 100), transform=ax1.transAxes,
             ha='left', va='top', fontsize=8.5, color=INK2)
    ax1.legend(loc='lower right', fontsize=8.5, frameon=False)
    style(ax1, 'a　r_off 不隨壓力變（每點＝一個完整小時）', '該小時平均壓力 (kg/cm²)',
          'r_off (%s)' % UNIT)
    ax1.set_ylim(-0.036, 0.056)

    # ── (b) 安靜期內三段 ──
    w = 0.26
    for i, (nm, B) in enumerate(BS.items()):
        q = [x for x in B['quiet'] if x[3] == 'off']
        kq = np.array([x[0] for x in q], float)
        dq = np.array([x[1] for x in q], float)
        nq = int(kq.max()) + 1
        edges = [0, nq // 3, 2 * nq // 3, nq]
        for j in range(3):
            sel = (kq >= edges[j]) & (kq < edges[j + 1])
            m = dq[sel].mean() * 60
            se = dq[sel].std(ddof=1) / np.sqrt(sel.sum()) * 60
            ax2.bar(j + (i - 1) * w, m, width=w * 0.9, color=COL[nm], alpha=0.85, lw=0,
                    label=NAME[nm] if j == 0 else None)
            ax2.errorbar(j + (i - 1) * w, m, yerr=se, color=INK, lw=0.9, capsize=2)
    rb_band(ax2)
    ax2.set_xticks([0, 1, 2])
    ax2.set_xticklabels(['安靜期前 1/3', '中 1/3', '後 1/3'])
    ax2.legend(loc='upper left', fontsize=8.5, frameon=False, ncol=3,
               columnspacing=1.2, handletextpad=0.5)
    ax2.text(0.98, 0.86,
             '逐分鐘斜率檢定 p = 0.82 / 0.51 / 0.63（去掉頭尾保護帶後）\n'
             '⚠ τ=5/10 前 1/3 偏低，但誤差棒重疊、檢定力不足；\n'
             '　 只能說「未偵測到趨勢」，不能說「已證實平坦」',
             transform=ax2.transAxes, ha='right', va='top', fontsize=8.5, color=INK2)
    ax2.set_ylim(-0.007, 0.040)
    style(ax2, 'b　安靜期內未偵測到加速或減速', None, '該段平均速率 (%s)' % UNIT)

    # ── (c) 驟降 vs 回升 ──
    # ⚠ 兩軸都是 0.01 的整數倍，直接散點會整片疊在同幾個格點上，看不出密度。
    #   改成計數氣泡：面積 ∝ 落在該格點的小時數，三批各給微小水平位移。
    txt = []
    for i, (nm, B) in enumerate(BS.items()):
        H = B['hours']
        sp = np.array([x['spike'] for x in H])
        rb_ = -np.array([x['rebound'] for x in H])
        pair = np.round(np.vstack([sp, rb_]).T, 4)
        uniq, cnt = np.unique(pair, axis=0, return_counts=True)
        ax3.scatter(uniq[:, 0] + (i - 1) * 0.0011, uniq[:, 1], s=10 + 9 * cnt,
                    color=COL[nm], marker=MK[nm], alpha=0.6, lw=0,
                    label='%s（n=%d）' % (NAME[nm], len(H)))
        txt.append('%s：|回升|/驟降 %.2f，相關 %+.2f'
                   % (NAME[nm], rb_.mean() / sp.mean(), np.corrcoef(sp, rb_)[0, 1]))
    lim = 0.05
    ax3.plot([0, lim], [0, lim], color=BASELINE, lw=1, ls='--')
    ax3.plot([0, lim], [0, lim / 2], color=BASELINE, lw=1, ls=':')
    ax3.text(lim * 0.76, lim * 0.70, '1:1（全可逆）', ha='left', va='top', fontsize=8,
             color=MUTED)
    ax3.text(lim * 0.99, lim * 0.495, '1:2', ha='right', va='top', fontsize=8, color=MUTED)
    ax3.text(0.02, 0.97, '\n'.join(txt) + '\n氣泡面積 ∝ 落在該格點的小時數',
             transform=ax3.transAxes, ha='left', va='top', fontsize=8.5, color=INK2)
    ax3.set_xlim(-0.005, lim)
    ax3.set_ylim(-0.026, lim)
    ax3.legend(loc='lower right', fontsize=8.5, frameon=False)
    style(ax3, 'c　驟降越大回升越大：尖峰有三到五成是可逆的', '泵開第一分鐘的驟降 (kg/cm²)',
          '泵停那一分鐘的回升 (kg/cm²)')

    fig.savefig(os.path.join(OUT, 'fig35_roff_checks.png'))
    plt.close(fig)


def main():
    ts, h, p = M.load()
    BS = {nm: M.analyse_batch(ts, h, p, nm, tau, d0, d1) for nm, tau, d0, d1 in M.BATCHES}
    fig33(BS['tau10'])
    fig34(BS)
    fig35(BS)
    for f in ('fig33_pump_pulse_anatomy', 'fig34_roff_vs_tau', 'fig35_roff_checks'):
        print('->', os.path.relpath(os.path.join(OUT, f + '.png'), os.path.dirname(os.path.dirname(HERE))))


if __name__ == '__main__':
    main()
