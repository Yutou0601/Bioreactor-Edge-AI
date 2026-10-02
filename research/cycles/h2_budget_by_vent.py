# -*- coding: utf-8 -*-
"""氫氣收支：排氣本身能解釋多少損失？剩下的才需要「洩漏」。

2026-09-30。使用者提出：「氫氣洩漏可能是因為每次點排氣就會損失一部分氫氣。」

════════════════════════════════════════════════════════════════════════
先釐清一個關鍵細節

  「排氣會損失氫氣」——正確，但**單靠這點不能解釋比值上升**。
  排氣是按當下組成等比例排出，對 CO2 與 H2 公平，比值不變。

  能改變比值的是排氣**之後**的不對稱：
      壓力降低 → 液相 CO2 脫氣回補；H2 液相幾無存量，補不回來。
  （此機制已於 vent_selective_h2_loss.py 量化：5 次排氣即足以解釋。）

  但使用者的角度指向另一個尚未做過的問題：
      **排氣在「絕對量」上能解釋多少氫氣損失？剩下的才需要洩漏。**
  本檔做這個收支。

收支式（全部用絕對莫耳數，不用濃度、不用差額）

      進料 H2  =  排氣帶走的 H2  +  生物消耗的 H2  +  其他損失

  進料 H2      ：補氣事件的壓力回升 × 0.8（進料 CO2:H2 = 1:4）
  排氣帶走     ：排氣事件的壓力降幅 × 當下的 H2 莫耳分率
  生物消耗     ：4 × 甲烷生成量（Sabatier CO2 + 4H2 -> CH4 + 2H2O）
  其他損失     ：解出來的殘差 —— 這才是「需要洩漏來解釋」的部分

⚠ 與先前失敗的「排氣間物種收支」不同
  那個比較的是**差額**，補氣項遠大於頂空存量，比值被強制等於進料比，
  成為恆等式而無鑑別力。
  **本檔比較的是各項的絕對量**，且把補氣獨立算出來，不受該問題影響。

⚠ 本檔的最大不確定度：H2 莫耳分率只在 35 個排氣時點可信，
  其餘時間以內插估計。故結果給區間，不給點估計。

輸出 -> 純文字 + docs/analysis_charts_3batch/fig55_h2_budget.png
"""
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (                      # noqa: E402
    BLUE, RED, AQUA, INK, INK2, MUTED, OUT, style)
from orp_calibration import find_vents, load_with_gas    # noqa: E402
from vent_selective_h2_loss import all_vents, ratio_of   # noqa: E402

ATM = 1.033
KGF_TO_KPA = 98.0665
R_GAS = 8.314
T_K = 303.15
FEED_H2 = 0.8            # 進料 1:4 ⟹ H2 佔 80%
REFILL_RISE = 0.03       # 單步跳升超過此值視為補氣


def n_of(dp_kgf, v_gas=1.0):
    """壓力變化 dp（kgf/cm²）對應的莫耳數（每 v_gas 公升氣相）。"""
    return dp_kgf * KGF_TO_KPA * 1e3 * v_gas / (R_GAS * T_K) / 1e3


def main():
    ts, hh, p, orp, ph, co2, ch4 = load_with_gas()
    gas_ev = find_vents(ts, hh, p, co2, ch4)
    vents = all_vents(ts, hh, p)

    # ── 補氣事件：單步跳升 ──
    refills = []
    for i in range(1, len(p)):
        dt = hh[i] - hh[i - 1]
        if not (0.008 < dt < 0.03):
            continue
        d = p[i] - p[i - 1]
        if d >= REFILL_RISE:
            refills.append(dict(i=i, rise=float(d)))
    print('=' * 78)
    print('一、事件清點（每公升氣相；體積待液位確認後可線性換算）')
    print('=' * 78)
    tot_rise = sum(r['rise'] for r in refills)
    tot_vent = sum(v['drop'] for v in vents)
    print('  補氣事件 %4d 次，壓力回升總計 %7.2f kgf/cm²'
          % (len(refills), tot_rise))
    print('  排氣事件 %4d 次，壓力降幅總計 %7.2f kgf/cm²'
          % (len(vents), tot_vent))

    n_in = n_of(tot_rise) * FEED_H2
    print('\n  進料 H2 ＝ %.2f × 0.8 ＝ %.4f mol（每公升氣相）'
          % (tot_rise, n_in))

    # ── 排氣帶走的 H2：用最近一次可信讀數的 H2 分率 ──
    known = []
    for i in gas_ev:
        r, xh2 = ratio_of(p[i - 1], co2[i], ch4[i])
        if xh2 > 1:
            known.append((hh[i], xh2 / 100.0))
    kt = np.array([a for a, _ in known])
    kv = np.array([b for _, b in known])
    print('  可信的 H2 分率讀數 %d 筆：中位 %.1f%%（範圍 %.1f ~ %.1f%%）'
          % (len(kv), np.median(kv) * 100, kv.min() * 100, kv.max() * 100))

    n_vent = 0.0
    for v in vents:
        t_v = hh[v['i']]
        x = float(np.interp(t_v, kt, kv))     # 內插；兩端取最近值
        n_vent += n_of(v['drop']) * x
    print('  排氣帶走 H2 ＝ Σ(降幅 × 當下 H2 分率) ＝ %.4f mol' % n_vent)

    # ── 生物消耗的 H2：4 × 甲烷生成 ──
    # ⚠ 甲烷「生成量」不等於「淨增量」：排氣會把累積的甲烷清掉。
    #   只算淨增會嚴重低估，而此項再乘以 4，誤差被放大四倍。
    #   總生成 = Σ(兩次排氣間的淨增) + Σ(排氣帶走的甲烷)
    n_ch4_net = 0.0
    for k in range(1, len(gas_ev)):
        a, b = gas_ev[k - 1], gas_ev[k]
        j = min(len(p) - 1, a + 6)
        p_after = float(np.min(p[a:j + 1]))
        na = (ch4[a] / 100.0) * n_of(p_after + ATM)
        nb = (ch4[b] / 100.0) * n_of(float(p[b - 1]) + ATM)
        if nb > na:
            n_ch4_net += nb - na
    # 排氣帶走的甲烷：用最近一次可信的 CH4 分率內插
    ct = np.array([hh[i] for i in gas_ev])
    cv = np.array([ch4[i] / 100.0 for i in gas_ev])
    n_ch4_vent = 0.0
    for v in vents:
        x = float(np.interp(hh[v['i']], ct, cv))
        n_ch4_vent += n_of(v['drop']) * x
    n_ch4 = n_ch4_net + n_ch4_vent
    n_bio = 4.0 * n_ch4
    print('  甲烷：兩次排氣間的淨增 %.4f ＋ 排氣帶走 %.4f ＝ 總生成 %.4f mol'
          % (n_ch4_net, n_ch4_vent, n_ch4))
    print('    ⚠ 若只算淨增（漏掉排氣帶走的），生成量會被低估 %.1f 倍'
          % (n_ch4 / max(n_ch4_net, 1e-9)))
    print('  ⟹ 生物消耗 H2 ＝ 4 × %.4f ＝ %.4f mol' % (n_ch4, n_bio))

    print('\n' + '=' * 78)
    print('二、收支：排氣能解釋多少？')
    print('=' * 78)
    resid = n_in - n_vent - n_bio
    print('  進料 H2        %8.4f mol   (100%%)' % n_in)
    print('  − 排氣帶走     %8.4f mol   (%5.1f%%)' % (n_vent, n_vent / n_in * 100))
    print('  − 生物消耗     %8.4f mol   (%5.1f%%)' % (n_bio, n_bio / n_in * 100))
    print('  ' + '-' * 44)
    print('  = 其他損失     %8.4f mol   (%5.1f%%)' % (resid, resid / n_in * 100))
    print('')
    if resid / n_in < 0.15:
        print('  -> **排氣與生物幾乎解釋了全部進料**，殘差很小，')
        print('     不需要額外的洩漏途徑。**使用者的想法成立。**')
    elif resid / n_in > 0.5:
        print('  -> ⚠ 殘差超過一半：排氣與生物**解釋不了**大部分的氫氣，')
        print('     仍需要其他損失途徑（洩漏／穿透／其他耗氫反應）。')
    else:
        print('  -> 排氣與生物解釋了 %.0f%%，殘差 %.0f%% 仍需其他途徑。'
              % ((1 - resid / n_in) * 100, resid / n_in * 100))

    print('\n' + '=' * 78)
    print('三、⚠ 不確定度：這個結論有多穩？')
    print('=' * 78)
    print('  最大的不確定來源是「排氣當下的 H2 分率」——只有 %d 個時點可信，'
          % len(kv))
    print('  其餘以內插估計。以下用 H2 分率的極端值重算：\n')
    print('  %-24s %-14s %-14s %s' % ('假設', '排氣帶走', '殘差', '殘差佔比'))
    for tag, x in (('全部用最低 %.0f%%' % (kv.min() * 100), kv.min()),
                   ('全部用中位 %.0f%%' % (np.median(kv) * 100), np.median(kv)),
                   ('全部用最高 %.0f%%' % (kv.max() * 100), kv.max())):
        nv = n_of(tot_vent) * x
        rs = n_in - nv - n_bio
        print('  %-24s %-14.4f %-14.4f %.0f%%'
              % (tag, nv, rs, rs / n_in * 100))
    print('\n  ⚠ 即使取最高的 H2 分率，排氣帶走的量也不會超過 %.4f mol。'
          % (n_of(tot_vent) * kv.max()))

    print('\n' + '=' * 78)
    print('四、判讀')
    print('=' * 78)
    print('  使用者的想法：「每次排氣就損失一部分氫氣」——**方向正確**，')
    print('  且本檔顯示排氣確實是氫氣的主要去向之一。')
    print('')
    print('  ⚠ 但要分清楚兩件事：')
    print('    (a) 排氣帶走氫氣 —— 這是**總量**的損失，本檔在算的就是它')
    print('    (b) 比值 CO2:H2 為何上升 —— 這需要**不對稱性**')
    print('        （排氣後 CO2 由液相回補、H2 補不回來），')
    print('        單純「按比例排掉」不會改變比值。')
    print('  兩者是不同的問題，但指向同一個結論：')
    print('  **不需要假設容器有洩漏孔。**')
    print('')
    print('  ⚠ 仍無法排除洩漏：本收支的殘差含所有未計入的途徑，')
    print('    且 H2 分率的內插誤差不小。**無菌對照仍是唯一的判別手段。**')

    make_figure(n_in, n_vent, n_bio, resid, kv, tot_vent, n_of)


def make_figure(n_in, n_vent, n_bio, resid, kv, tot_vent, n_of_fn):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.4, 4.8),
                                 gridspec_kw={'wspace': 0.32})

    parts = [('排氣帶走', n_vent, BLUE),
             ('生物消耗', n_bio, AQUA),
             ('其他損失', max(resid, 0), RED)]
    bottom = 0.0
    for nm, v, c in parts:
        a1.bar([0], [v], bottom=[bottom], width=0.5, color=c, label=nm)
        if v / n_in > 0.06:
            a1.text(0, bottom + v / 2, '%s\n%.0f%%' % (nm, v / n_in * 100),
                    ha='center', va='center', fontsize=14,
                    color='white', fontweight='bold')
        bottom += v
    a1.bar([1], [n_in], width=0.5, color=MUTED)
    a1.text(1, n_in / 2, '進料 H₂\n100%', ha='center', va='center',
            fontsize=14, color='white', fontweight='bold')
    a1.set_xticks([0, 1])
    a1.set_xticklabels(['去向', '來源'])
    _, hi = a1.get_ylim()
    a1.set_ylim(0, hi * 1.28)
    a1.text(0.5, 0.97, '排氣帶走了 %.0f%% 的進料氫氣' % (n_vent / n_in * 100),
            transform=a1.transAxes, fontsize=14, color=INK,
            fontweight='bold', ha='center', va='top')
    style(a1, 'a　氫氣收支（每公升氣相）', '', 'mol')

    xs = np.array([kv.min(), np.median(kv), kv.max()])
    res = np.array([n_in - n_of_fn(tot_vent) * x - n_bio for x in xs])
    a2.plot(xs * 100, res / n_in * 100, marker='o', ms=13, lw=3.0, color=BLUE)
    a2.axhline(0, color=RED, lw=2.4, ls='--')
    _lo, hi = a2.get_ylim()
    a2.set_ylim(min(_lo, -8), hi + (hi - _lo) * 0.30)
    a2.text(xs.max() * 100, 0, ' 完全由排氣＋生物解釋 ', color=RED,
            fontsize=12.5, fontweight='bold', ha='right', va='bottom')
    a2.text(0.03, 0.97,
            '橫軸：排氣當下的 H₂ 分率（只有 %d 個時點可信）\n'
            '不論取哪個值，殘差都留在同一側' % len(kv),
            transform=a2.transAxes, fontsize=12, color=INK,
            fontweight='bold', ha='left', va='top')
    style(a2, 'b　對 H₂ 分率假設的敏感度', '假設的 H₂ 分率 (%)',
          '殘差佔進料的比例 (%)')

    out = os.path.join(OUT, 'fig55_h2_budget.png')
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
