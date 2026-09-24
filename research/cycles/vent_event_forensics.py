# -*- coding: utf-8 -*-
"""排氣事件鑑識：那 35 次到底是「排氣」還是「沖洗感測器」？

2026-09-23。起因：使用者提出替代假說——氫氣超量流失（全案最強發現）
可能是假象，真正發生的是**操作人員在沖洗感測器**（多次短時間進氣排氣）。

════════════════════════════════════════════════════════════════════════
為什麼這個假說必須認真查

  主結論「34/35 次殘餘 CO2:H2 高於進料比」依賴一個前提：
  **那 35 次讀數代表頂空的真實組成。**

  若其中有一部分是沖洗管路時讀到的「進氣本身」或「管路殘氣」，
  該前提就破了，而整個氫氣流失的結論會跟著倒。

  ⚠ 注意方向：沖洗若只是「等比例排掉混合氣」，並不會改變組成比例。
    會改變比例的是：(a) 讀到的其實是進氣或管路殘氣，而非頂空；
    (b) 沖洗用的氣體不是 1:4。故本檔要找的是**組成異常**的結構，
    不只是「有沒有短排氣」。

沖洗假說的可檢驗後果（若為真，應同時看到）

  1. 事件在時間上**聚集**：幾分鐘～幾十分鐘內連續多次，而非隨機散布
  2. 每次的**壓力降幅小**（沖洗不需要洩掉整個頂空）
  3. CH4 躍升的**持續時間短**
  4. 聚集事件與孤立事件的 **CO2:H2 比值應有系統性差異**
  5. 排除聚集事件後，主結論**應該消失或顯著減弱**

  第 5 點是決定性的：若排除後結論仍在，沖洗假說就無法解釋主結果。

輸出 -> 純文字 + docs/analysis_charts_3batch/fig45_vent_forensics.png
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
    BLUE, RED, INK, INK2, MUTED, OUT, style)
from orp_calibration import find_vents, load_with_gas    # noqa: E402

ATM = 1.033
FEED_RATIO = 0.25
P_H2O_KPA = 4.24
KGF_TO_KPA = 98.0665


def ratio_of(p_prev, x_co2, x_ch4):
    """由乾基組成算 CO2:H2，與 feed_ratio_drift.py 一致。"""
    P_abs = p_prev + ATM
    f_h2o = P_H2O_KPA / (P_abs * KGF_TO_KPA) * 100
    x_h2 = 100 - x_co2 - x_ch4 - f_h2o
    if x_h2 <= 1:
        return None, x_h2
    return x_co2 / x_h2, x_h2


def main():
    ts, hh, p, orp, ph, co2, ch4 = load_with_gas()
    ev = find_vents(ts, hh, p, co2, ch4)
    print('全資料庫 %d 筆；偵測到排氣事件 %d 次' % (len(ts), len(ev)))
    print('時間範圍 %s ~ %s\n' % (ts[ev[0]].date(), ts[ev[-1]].date()))

    # ── 逐事件的特徵 ──────────────────────────────────────
    rec = []
    for k, i in enumerate(ev):
        r, xh2 = ratio_of(p[i - 1], co2[i], ch4[i])
        # 壓力降幅：事件前後各取數點
        lo = max(0, i - 3)
        hi_ = min(len(p) - 1, i + 6)
        p_before = float(np.max(p[lo:i + 1]))
        p_after = float(np.min(p[i:hi_ + 1]))
        drop = p_before - p_after
        # CH4 躍升持續幾筆（每筆一分鐘）
        dur = 0
        j = i
        while j < len(ch4) and ch4[j] > 10:
            dur += 1
            j += 1
        # 與前一次事件的間隔（小時）
        gap_prev = (hh[i] - hh[ev[k - 1]]) if k > 0 else np.nan
        gap_next = (hh[ev[k + 1]] - hh[i]) if k < len(ev) - 1 else np.nan
        rec.append(dict(i=i, t=ts[i], ratio=r, xh2=xh2, co2=co2[i], ch4=ch4[i],
                        drop=drop, dur=dur, gap_prev=gap_prev, gap_next=gap_next,
                        p_before=p_before))

    print('%-17s %6s %6s %6s %7s %6s %5s %8s'
          % ('時刻', 'CO2%', 'CH4%', 'H2%', 'CO2:H2', '壓降', '分鐘', '距前次hr'))
    for d in rec:
        print('%-17s %6.1f %6.1f %6.1f %7s %6.3f %5d %8s'
              % (d['t'].strftime('%Y-%m-%d %H:%M'), d['co2'], d['ch4'], d['xh2'],
                 ('%.3f' % d['ratio']) if d['ratio'] else '  --',
                 d['drop'], d['dur'],
                 ('%.1f' % d['gap_prev']) if np.isfinite(d['gap_prev']) else '   --'))

    valid = [d for d in rec if d['ratio'] is not None]
    print('\n可用於比值檢定者 %d 筆' % len(valid))

    # ── 檢驗 1：時間上是否聚集 ───────────────────────────
    print('\n' + '=' * 68)
    print('檢驗 1：事件在時間上是否聚集（沖洗應為連續多次）')
    print('=' * 68)
    gaps = np.array([d['gap_prev'] for d in rec if np.isfinite(d['gap_prev'])])
    print('  相鄰事件間隔（小時）：中位 %.1f　最小 %.2f　最大 %.1f'
          % (np.median(gaps), gaps.min(), gaps.max()))
    for thr in (0.5, 1.0, 3.0, 6.0, 24.0):
        n = int((gaps < thr).sum())
        print('    間隔 < %5.1f hr 者：%2d / %d (%.0f%%)'
              % (thr, n, len(gaps), n / len(gaps) * 100))
    # 若為隨機散布（Poisson），間隔應近似指數分布
    lam = 1.0 / gaps.mean()
    exp_frac = 1 - np.exp(-lam * 1.0)
    obs_frac = (gaps < 1.0).sum() / len(gaps)
    print('  若事件隨機散布（Poisson），間隔<1hr 的比例應為 %.1f%%；實測 %.1f%%'
          % (exp_frac * 100, obs_frac * 100))
    clustered = obs_frac > exp_frac * 2
    print('  -> %s' % ('有聚集跡象，沖洗假說得到支持'
                       if clustered else '未見明顯聚集'))

    # ── 檢驗 2：壓力降幅 ──────────────────────────────────
    print('\n' + '=' * 68)
    print('檢驗 2：壓力降幅（沖洗不需洩掉整個頂空，降幅應小）')
    print('=' * 68)
    drops = np.array([d['drop'] for d in rec])
    print('  降幅（kgf/cm²）：中位 %.3f　IQR [%.3f, %.3f]　範圍 [%.3f, %.3f]'
          % (np.median(drops), *np.percentile(drops, [25, 75]),
             drops.min(), drops.max()))
    print('  量化步階為 0.01，故降幅 <0.03 者僅約 3 階，難與雜訊區分')
    small = int((drops < 0.05).sum())
    print('  降幅 < 0.05 者 %d / %d (%.0f%%)'
          % (small, len(drops), small / len(drops) * 100))

    # ── 檢驗 3：分層比較比值 ─────────────────────────────
    print('\n' + '=' * 68)
    print('檢驗 3：孤立事件 vs 聚集事件，比值是否不同')
    print('=' * 68)
    iso = [d for d in valid if not (np.isfinite(d['gap_prev'])
                                    and d['gap_prev'] < 3.0)]
    clu = [d for d in valid if np.isfinite(d['gap_prev'])
           and d['gap_prev'] < 3.0]
    for name, grp in (('孤立（距前次 ≥3hr 或為首筆）', iso),
                      ('聚集（距前次 <3hr）', clu)):
        if not grp:
            print('  %-26s 無樣本' % name)
            continue
        rs = np.array([d['ratio'] for d in grp])
        above = int((rs > FEED_RATIO).sum())
        print('  %-26s n=%2d　中位 %.3f（進料比的 %.2f 倍）　高於進料比 %d/%d'
              % (name, len(grp), np.median(rs), np.median(rs) / FEED_RATIO,
                 above, len(grp)))

    # ── 檢驗 4：只用孤立事件重做主檢定（決定性）───────────
    print('\n' + '=' * 68)
    print('檢驗 4（決定性）：排除所有可能的沖洗事件後，主結論是否還在')
    print('=' * 68)
    rng = np.random.default_rng(0)
    for name, grp in (('全部事件（原主檢定）', valid),
                      ('僅孤立事件（距前次 ≥3hr）', iso),
                      ('僅大降幅事件（降幅 ≥0.05）',
                       [d for d in valid if d['drop'] >= 0.05]),
                      ('孤立且大降幅（最嚴格）',
                       [d for d in iso if d['drop'] >= 0.05])):
        if len(grp) < 5:
            print('  %-26s n=%d，樣本過少不檢定' % (name, len(grp)))
            continue
        rs = np.array([d['ratio'] for d in grp])
        lg = np.log(rs / FEED_RATIO)
        above = int((rs > FEED_RATIO).sum())
        # 符號置換檢定：虛無為「高於/低於等機率」
        obs = float(np.mean(lg))
        null = np.array([np.mean(lg * rng.choice([-1, 1], len(lg)))
                         for _ in range(20000)])
        pv = float((np.abs(null) >= abs(obs)).mean())
        print('  %-26s n=%2d　中位 %.3f（%.2f 倍）　%d/%d 高於　p=%s'
              % (name, len(grp), np.median(rs), np.median(rs) / FEED_RATIO,
                 above, len(grp),
                 ('%.4f' % pv) if pv > 0 else '<0.0001'))

    print('\n  -> 若最嚴格的子集仍顯著，沖洗假說無法解釋主結果。')

    # ── 檢驗 5：沖洗的方向性（邏輯檢驗，不需資料）─────────
    print('\n' + '=' * 68)
    print('檢驗 5：沖洗**會把比值推向哪一邊**？')
    print('=' * 68)
    print('  沖洗用的氣體就是進氣，組成為 1:4，即比值 0.25。')
    print('  反覆以進氣沖洗頂空，會使讀到的比值**趨近 0.25**，而非遠離。')
    print('  實測中位為 0.699 = 進料比的 2.79 倍，是**遠離**的方向。')
    print('  -> 沖洗無法製造這個偏離；若真有沖洗污染，')
    print('     則真實偏離**比實測更大**，而非更小。')

    # ── 檢驗 6（更嚴重的威脅）：H2 靠差額推算 ─────────────
    print('\n' + '=' * 68)
    print('檢驗 6：H2 係由差額推算，CH4 若被高估則比值被機械性推高')
    print('=' * 68)
    rs = np.array([d['ratio'] for d in valid])
    c4 = np.array([d['ch4'] for d in valid])
    print('  比值與 CH4 讀數的相關（取對數）：%+.3f'
          % float(np.corrcoef(np.log(rs), c4)[0, 1]))
    print('  此相關是**定義上必然**的（H2 = 100 − CO2 − CH4 − H2O），')
    print('  故不能作為 CH4 有偏的證據，但也無法排除。\n')
    print('  最嚴格的穩健性檢驗：**把 CH4 完全當成零**')
    print('  （等於假設 CH4 讀數全是拖尾、真實甲烷為零——物理上不可能，')
    print('   但這給出 H2 的絕對上限，因而給出比值的絕對下限）\n')
    worst = []
    for d in valid:
        P_abs = d['p_before'] + ATM
        f_h2o = P_H2O_KPA / (P_abs * KGF_TO_KPA) * 100
        h2_max = 100 - d['co2'] - f_h2o          # CH4 當成 0
        worst.append(d['co2'] / h2_max)
    worst = np.array(worst)
    above_w = int((worst > FEED_RATIO).sum())
    lgw = np.log(worst / FEED_RATIO)
    obs_w = float(np.mean(lgw))
    null_w = np.array([np.mean(lgw * rng.choice([-1, 1], len(lgw)))
                       for _ in range(20000)])
    pv_w = float((np.abs(null_w) >= abs(obs_w)).mean())
    print('  比值下限：中位 %.3f（進料比的 %.2f 倍）' % (np.median(worst),
                                                np.median(worst) / FEED_RATIO))
    print('  仍高於進料比者：**%d / %d**　符號置換 p=%s'
          % (above_w, len(worst), ('%.4f' % pv_w) if pv_w > 0 else '<0.0001'))
    print('  -> %s' % (
        '即使在物理上不可能的最壞情況下，結論仍成立'
        if above_w > len(worst) * 0.8 else
        '⚠ 最壞情況下結論削弱，主結果對 CH4 讀數的品質敏感'))

    make_figure(rec, valid, iso, clu, worst)


def make_figure(rec, valid, iso, clu, worst):
    fig, axes = plt.subplots(1, 3, figsize=(14.8, 4.6),
                             gridspec_kw={'wspace': 0.32})

    ax = axes[0]
    gaps = np.array([d['gap_prev'] for d in rec if np.isfinite(d['gap_prev'])])
    ax.hist(np.log10(np.maximum(gaps, 0.02)), bins=18, color=BLUE,
            edgecolor='white')
    ax.axvline(np.log10(3.0), color=RED, lw=2.2, ls='--')
    _lo, _hi = ax.get_ylim()
    ax.set_ylim(_lo, _hi * 1.35)
    ax.text(np.log10(3.0), _hi * 1.05, ' 3 小時', color=RED, fontsize=9,
            fontweight='bold', ha='left')
    ax.text(0.03, 0.96, '沖洗若存在，應在左側形成一叢', transform=ax.transAxes,
            fontsize=9, color=INK2, ha='left', va='top')
    style(ax, 'a　相鄰排氣事件的間隔', 'log₁₀(間隔 / 小時)', '次數')

    ax = axes[1]
    drops = np.array([d['drop'] for d in rec])
    rs_all = np.array([d['ratio'] if d['ratio'] else np.nan for d in rec])
    ax.scatter(drops, rs_all, s=60, color=BLUE, edgecolors='white', zorder=4)
    ax.axhline(FEED_RATIO, color=RED, lw=2.2, ls='--')
    ax.axvline(0.05, color=MUTED, lw=1.8, ls=':')
    _lo, _hi = ax.get_ylim()
    ax.set_ylim(0, _hi * 1.25)
    ax.text(0.03, 0.96,
            '紅虛線＝只有產甲烷時應有的位置 (0.25)\n'
            '點散布於降幅全範圍，未集中於小降幅',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='top')
    style(ax, 'b　壓力降幅 vs 比值', '排氣的壓力降幅 (kgf/cm²)', 'CO₂:H₂')

    ax = axes[2]
    rs_v = np.array([d['ratio'] for d in valid])
    bp = ax.boxplot([rs_v, worst],
                    tick_labels=['實測\n(n=%d)' % len(rs_v),
                                 'CH₄當零\n(最壞情況)'],
                    patch_artist=True, widths=0.5)
    for bx, c in zip(bp['boxes'], (BLUE, MUTED)):
        bx.set_facecolor(c)
        bx.set_alpha(0.7)
    ax.axhline(FEED_RATIO, color=RED, lw=2.2, ls='--')
    ax.set_yscale('log')
    # ⚠ log 軸的刻度標籤走 mathtext（$10^{-1}$），**不受 axes.unicode_minus 管**；
    #   中文字型下的負號會缺字而顯示成方框。故手動指定刻度避開 mathtext。
    ax.set_yticks([0.1, FEED_RATIO, 1.0, 10.0])
    ax.set_yticklabels(['0.1', '0.25', '1', '10'])
    ax.minorticks_off()
    _lo, _hi = ax.get_ylim()
    ax.set_ylim(_lo, _hi * 9)
    ax.text(0.5, 0.97,
            '即使把甲烷讀數全當成零，\n'
            '中位仍為進料比的 %.2f 倍（%d/%d 高於）'
            % (np.median(worst) / FEED_RATIO,
               int((worst > FEED_RATIO).sum()), len(worst)),
            transform=ax.transAxes, fontsize=9, color=INK,
            fontweight='bold', ha='center', va='top')
    style(ax, 'c　對甲烷讀數品質的敏感度', '', 'CO₂:H₂（對數軸）')

    out = os.path.join(OUT, 'fig45_vent_forensics.png')
    fig.savefig(out)
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
