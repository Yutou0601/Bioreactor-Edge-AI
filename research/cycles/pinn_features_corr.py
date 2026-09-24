# -*- coding: utf-8 -*-
"""PINN 的特徵圖與關聯性分析 —— 把「為什麼撈不回來」直接畫出來。

2026-09-23。補 pinn_rb_recovery.py 只用文字說明的部分。

════════════════════════════════════════════════════════════════════════
一、特徵圖：網路內部到底學到什麼？

  r̂_b(t) 網路最後一層之前的輸出，就是它自己長出來的一組基底函數。
  畫出來會看到：那只是一組平滑的曲線，本身沒有任何生物內涵，
  生物速率是這些曲線的加權和。再看壓降被拆成「物理項」與「生物項」——
  兩項的**總和**貼著資料，但**怎麼拆**資料管不著。

二、關聯性分析：兩個項之間是什麼關係？

  物理式    dP/dt = −kLa·(P − P_eq) − r_b
  若 r_b 是常數，右邊可以原封不動改寫成
            dP/dt = −kLa·(P − [P_eq − r_b/kLa])
  **這是恆等式，不是近似。**「有生物在等速吃氣」與「平衡壓力低一點、
  完全沒有生物」在壓力軌跡上是同一條曲線，殘差為零。
  可辨識的是組合 P_eq − r̄_b/kLa，不是 r_b 本身。

  量法＝**剖面掃描**：把 r_b 的平均值強制釘在一連串指定值上，
  其餘參數（kLa、P_eq、曲線形狀）全部自由重新擬合，看
    (a) 擬合誤差會不會變差 —— 不會變差就是資料沒有意見
    (b) P_eq 怎麼補償 —— 若正好沿著 +1/kLa 的斜率走，簡併就被實測到了

⚠ 2026-09-23 修正：本檔第一版用 Adam 2500 步，擬合 RMSE 0.036，
  而雜訊下限只有 0.005 —— 那是**沒訓練完**，不是不可辨識。
  兩者外觀很像（都是「換個設定就換個答案」），但結論完全不同。
  現在一律用 Adam＋LBFGS 收到 RMSE ≈ 雜訊下限才取用，並在圖上標出下限。

輸出 -> docs/analysis_charts_3batch/pinn_profile.csv
        docs/analysis_charts_3batch/deck7_pinn_features.png
        docs/analysis_charts_3batch/deck8_pinn_corr.png
"""
import csv
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402
from matplotlib import rcParams                          # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import torch                                             # noqa: E402

from analyze_three_batches import (                      # noqa: E402
    BLUE, RED, INK, INK2, MUTED, BASELINE, OUT)
from pinn_rb_recovery import synth, train_pinn, QUANT, NOISE   # noqa: E402

rcParams.update({
    'font.size': 15, 'axes.titlesize': 19, 'axes.labelsize': 16,
    'xtick.labelsize': 14, 'ytick.labelsize': 14, 'legend.fontsize': 14,
})
FIGW = 12.0
T, NP = 6.0, 360
KLA_TRUE, PEQ_TRUE, P0 = 1.4, 0.75, 1.17
RB_TRUE = lambda tt: 0.012 * np.exp(-0.7 * tt / T * 3)
RB_MEAN_TRUE = float(RB_TRUE(np.linspace(0, T, 60)).mean())
FLOOR = float(np.sqrt(NOISE ** 2 + QUANT ** 2 / 12))    # 擬合誤差的理論下限
# 剖面掃描的位置：從 0 到「生物吃掉大半壓降」（約真值的 12 倍）
RB_GRID = (0.0, 0.005, 0.012, 0.020, 0.030, 0.045, 0.060)
RB_BIG = 0.060      # 這個值下，生物項已經吃掉全部壓降的大半


def style(ax, title=None, xlabel=None, ylabel=None):
    if title:
        ax.set_title(title, color=INK, fontweight='bold', loc='left', pad=12)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(True, linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    for s_ in ('top', 'right'):
        ax.spines[s_].set_visible(False)
    return ax


def headroom(ax, top=0.0, bottom=0.0):
    """★先留白再放字。順序反了字會掉進圖裡（這條規則修過十幾次）。"""
    lo, hi = ax.get_ylim()
    span = hi - lo
    ax.set_ylim(lo - span * bottom, hi + span * top)


def save(fig, name):
    p = os.path.join(OUT, name + '.png')
    fig.savefig(p)
    plt.close(fig)
    print('  ->', name + '.png')


def best_fit(t, obs, **kw):
    """多個隨機起點取擬合最佳者。

    剖面的定義就是「對干擾參數取極小」，故多起點取最佳是正確做法而非挑好看的。
    ★圖與表必須用同一個估計量，否則圖上會出現表裡沒有的數字（本檔犯過一次）。
    """
    cands = [train_pinn(t, obs, T, lam=0.01, seed=sd, return_models=True, **kw)
             for sd in (0, 1, 2)]
    return min(cands, key=lambda d: d['rmse'])


def hidden_features(model, n=200):
    """取出 r̂_b 網路最後一層之前的隱藏輸出 = 它自己長出來的基底函數。"""
    g = torch.linspace(0, 1, n).view(-1, 1)
    h = g
    with torch.no_grad():
        for layer in list(model.net)[:-1]:      # 去掉最後的 Linear(width, 1)
            h = layer(h)
    return g.numpy().ravel(), h.numpy()


# ═══════════════════════════════════════════════════════════════
def fig_features(t, obs):
    """特徵圖：左＝網路長出來的基底；右＝壓降被拆成哪兩項。"""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(FIGW, 5.4),
                                 gridspec_kw={'wspace': 0.30})

    lo = best_fit(t, obs)
    hi = best_fit(t, obs, rb_target=RB_BIG)    # 硬把生物項拉到吃掉大半壓降

    # ── 左：隱藏層特徵 ──
    g, H = hidden_features(lo['fR'])
    rng = np.random.default_rng(0)
    pick = rng.choice(H.shape[1], 14, replace=False)
    for j in pick:
        a1.plot(g, H[:, j], color=MUTED, lw=1.6, alpha=0.55)
    a1.plot(g, H[:, pick[0]], color=BLUE, lw=3.4)
    a1.axhline(0, color=BASELINE, lw=1.2)
    a1.set_ylim(-1.05, 1.05)
    headroom(a1, bottom=0.45)
    a1.text(0.03, 0.03,
            '每一條是網路自己長出來的一個「零件」。\n'
            '它們只是形狀不同的平滑曲線，本身不帶生物意義；\n'
            '生物速率是這些零件的加權組合。',
            transform=a1.transAxes, fontsize=14, color=INK2,
            ha='left', va='bottom')
    style(a1, 'a　網路內部學到的特徵（取 14 個）',
          '一個循環走完的進度', '特徵值')

    # ── 右：同一條壓降，兩種歸因（堆疊比例）──
    drop = float(obs[0] - obs[-1])                 # 整個循環總共掉了多少
    bars = []
    for res, lab in ((lo, '讓網路自己決定'), (hi, '硬指定生物項吃得多')):
        bio = float(res['rb'].mean()) * T          # 生物項累積貢獻
        bars.append((lab, bio / drop, res['rmse']))
    xs = [0, 1]
    bio_f = [b[1] for b in bars]
    phy_f = [1 - f for f in bio_f]
    a2.bar(xs, phy_f, width=0.55, color=BLUE, label='物理：氣體溶進水裡')
    a2.bar(xs, bio_f, width=0.55, bottom=phy_f, color=RED, label='生物：菌吃掉')
    for i, (lab, f, rm) in enumerate(bars):
        # 百分比字放在各自色塊的正中間；色塊太薄就不放，免得壓線
        if 1 - f > 0.08:
            a2.text(i, (1 - f) / 2, '%.0f%%' % ((1 - f) * 100), ha='center',
                    va='center', fontsize=18, color='white', fontweight='bold')
        if f > 0.08:
            a2.text(i, 1 - f / 2, '%.0f%%' % (f * 100), ha='center',
                    va='center', fontsize=18, color='white', fontweight='bold')
        a2.text(i, -0.085, '擬合誤差 %.5f' % rm, ha='center', va='top',
                fontsize=14.5, color=INK2)
    a2.set_xticks(xs)
    a2.set_xticklabels([b[0] for b in bars], fontsize=15)
    # 長條只佔 0~1；上方整段留給圖例與結論文字，下方留給擬合誤差標註
    a2.set_ylim(-0.30, 1.72)
    a2.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    a2.set_yticklabels(['0%', '25%', '50%', '75%', '100%'])
    a2.legend(loc='upper center', frameon=False, fontsize=14, ncol=2,
              bbox_to_anchor=(0.5, 0.84))
    gap = abs(bars[1][2] / bars[0][2] - 1) * 100
    a2.text(0.5, 0.995,
            '★ 兩欄的擬合誤差只差 %.1f%%，\n'
            '但一欄說菌幾乎沒吃，另一欄說菌吃了大半' % gap,
            transform=a2.transAxes, fontsize=14.5, color=INK,
            fontweight='bold', ha='center', va='top')
    a2.grid(True, axis='y', linewidth=0.8, alpha=0.9)
    a2.set_axisbelow(True)
    for s_ in ('top', 'right'):
        a2.spines[s_].set_visible(False)
    a2.set_title('b　同一條壓降，兩種完全不同的歸因',
                 color=INK, fontweight='bold', loc='left', pad=12)
    a2.set_ylabel('佔整個循環壓降的比例')
    save(fig, 'deck7_pinn_features')


# ═══════════════════════════════════════════════════════════════
def fig_corr(rows):
    """關聯性：左＝擬合誤差在整條剖面上是平的；右＝P_eq 一比一補償。"""
    x = np.array([r['rb_target'] for r in rows])
    rmse = np.array([r['rmse'] for r in rows])
    peq = np.array([r['peq'] for r in rows])
    kla = np.array([r['kla'] for r in rows])

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(FIGW, 5.4),
                                 gridspec_kw={'wspace': 0.32})

    # ── 左：剖面 ──
    a1.plot(x * 1000, rmse * 1000, marker='o', ms=11, lw=2.8, color=BLUE)
    a1.axhline(FLOOR * 1000, color=MUTED, lw=2.2, ls=':')
    a1.axvline(RB_MEAN_TRUE * 1000, color=RED, lw=2.6, ls='--')
    a1.set_ylim(0, max(rmse.max(), FLOOR * 1.5) * 1000)
    headroom(a1, top=0.40)
    # 兩個註解都放到曲線與下限線「下方」的空白區，並拉開 y 距離免得互壓
    a1.text(RB_MEAN_TRUE * 1000, a1.get_ylim()[1] * 0.22, ' 真正的答案',
            color=RED, fontsize=15, fontweight='bold', ha='left', va='center')
    a1.text(x.max() * 1000, FLOOR * 1000 * 0.94, '感測器雜訊決定的下限 ',
            color=MUTED, fontsize=13.5, ha='right', va='top')
    a1.text(0.5, 0.985,
            '把生物速率從「完全沒有」硬拉到「吃掉大半」，\n擬合資料的能力幾乎沒有變差',
            transform=a1.transAxes, fontsize=15.5, color=RED,
            fontweight='bold', ha='center', va='top')
    style(a1, 'a　資料對「生物吃掉多少」幾乎沒有意見',
          '硬指定的生物速率 (×10⁻³ kg/cm²/hr)', '擬合誤差 (×10⁻³ kg/cm²)')

    # ── 右：補償關係 ──
    a2.plot(x * 1000, peq, marker='o', ms=11, lw=2.8, color=BLUE,
            label='實際擬合出的平衡壓力')
    pred = peq[0] + x / kla.mean()
    a2.plot(x * 1000, pred, lw=2.6, ls='--', color=RED,
            label='紙筆推導：斜率 $+1/k_La$')
    headroom(a2, top=0.45, bottom=0.12)
    a2.legend(loc='lower left', frameon=False, fontsize=14)
    dev = float(np.abs(peq - pred).max())
    a2.text(0.5, 0.985,
            '生物項多算多少，平衡壓力就自動往上補多少\n'
            '兩條線最大差距 %.4f kg/cm²＝感測器解析度的 %.0f%%'
            % (dev, dev / QUANT * 100),
            transform=a2.transAxes, fontsize=15, color=INK,
            fontweight='bold', ha='center', va='top')
    style(a2, 'b　兩個未知數一比一互換，壓力看不出差別',
          '硬指定的生物速率 (×10⁻³ kg/cm²/hr)', '擬合出的平衡壓力 (kg/cm²)')
    save(fig, 'deck8_pinn_corr')
    return dev


def main():
    print('合成「答案已知」的資料：kLa %.2f、P_eq %.2f、r_b 平均 %.5f'
          % (KLA_TRUE, PEQ_TRUE, RB_MEAN_TRUE))
    print('擬合誤差的理論下限（雜訊 %.3f ＋ 量化 %.2f）= %.5f\n'
          % (NOISE, QUANT, FLOOR))
    t, P, obs = synth(T, NP, RB_TRUE, KLA_TRUE, PEQ_TRUE, P0)

    print('剖面掃描：把生物速率平均值釘死，其餘參數自由重擬合')
    rows = []
    for tgt in RB_GRID:
        r = best_fit(t, obs, rb_target=tgt)
        rows.append(dict(rb_target=tgt, rb_got=float(r['rb'].mean()),
                         kla=r['kla'], peq=r['peq'], rmse=r['rmse'],
                         ident=r['peq'] - float(r['rb'].mean()) / r['kla']))
        print('   指定 r_b %.4f -> 實得 %.4f　kLa %.2f　P_eq %.4f　'
              '擬合 RMSE %.5f　可辨識組合 %.4f'
              % (tgt, rows[-1]['rb_got'], r['kla'], r['peq'], r['rmse'],
                 rows[-1]['ident']))

    rmse = np.array([r['rmse'] for r in rows])
    peq = np.array([r['peq'] for r in rows])
    kla = np.array([r['kla'] for r in rows])
    x = np.array([r['rb_target'] for r in rows])
    print('\n── 判讀 ──')
    print('   擬合誤差 %.5f ~ %.5f，全距只有 %.1f%%；雜訊下限 %.5f'
          % (rmse.min(), rmse.max(), (rmse.max() / rmse.min() - 1) * 100, FLOOR))
    print('   -> %s'
          % ('生物速率從 0 到吃掉大半壓降，資料的滿意度幾乎不變 ⇒ 不可辨識'
             if rmse.max() / rmse.min() < 1.15 else
             '擬合誤差有明顯變化，資料仍有選擇力'))
    slope = np.polyfit(x, peq, 1)[0]
    pred_slope = 1 / kla.mean()
    print('   P_eq 對 r_b 的斜率 %+.4f；理論預測 +1/kLa = %+.4f（相對差 %.1f%%）'
          % (slope, pred_slope, abs(slope - pred_slope) / pred_slope * 100))
    ident = np.array([r['ident'] for r in rows])
    truth = PEQ_TRUE - RB_MEAN_TRUE / KLA_TRUE
    print('   可辨識組合 A = P_eq − r̄_b/kLa：%.4f ~ %.4f（全距 %.4f）'
          % (ident.min(), ident.max(), ident.max() - ident.min()))
    print('   真值的 A = %.3f − %.5f/%.2f = %.4f；實測均值 %.4f，差 %+.4f'
          % (PEQ_TRUE, RB_MEAN_TRUE, KLA_TRUE, truth, ident.mean(),
             ident.mean() - truth))
    print('   -> 生物項與平衡壓力一比一互換，A 始終不變（全距只有量化步階的 %.0f%%）'
          % ((ident.max() - ident.min()) / QUANT * 100))

    print('\n產圖：')
    fig_features(t, obs)
    dev = fig_corr(rows)
    print('   補償關係與理論線最大偏離 %.5f kg/cm²（量化步階的 %.0f%%）'
          % (dev, dev / QUANT * 100))

    path = os.path.join(OUT, 'pinn_profile.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print('\n剖面明細 -> %s（%d 列）' % (os.path.relpath(path, REPO), len(rows)))


if __name__ == '__main__':
    main()
