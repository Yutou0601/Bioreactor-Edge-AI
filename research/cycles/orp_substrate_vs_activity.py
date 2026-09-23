# -*- coding: utf-8 -*-
"""ORP 量的是「菌有多活躍」還是「有沒有及時補到料」？

2026-09-21。使用者提問：ORP 代表生物活性，但有沒有及時開啟循環、把 CO2/H2 補足？

════════════════════════════════════════════════════════════════════════
為什麼一定要分開這兩件事

  兩者在 ORP 讀數上長得一樣，意義卻相反：

      菌很活躍      -> 消耗 H2 -> 應該讓 ORP **往正走**
      剛補了 H2     -> 溶進液相 -> 讓 ORP **往負走**

  若 ORP 主要跟著補料走，那它是**料位計**不是活性計。
  線索：ORP 通量與「每天幾個循環」相關 −0.884（見 orp_calibration），
  而循環數就是補料頻率 -> 高度可疑。

四個檢定

  一、補氣當下 ORP 有沒有反應？（補料 -> ORP 該往負走）
  二、泵開／泵停 ORP 有沒有差？（循環 -> 氣液接觸 -> H2 進液相）
  三、碳源斷掉時 ORP 垮不垮？（若是活性計，沒碳源就該垮；
      若是料位計，H2 照補就不會垮）—— 這是最決定性的一個
  四、反過來當診斷：能不能用 ORP 偵測「補料晚了」

輸出 -> docs/analysis_charts_3batch/orp_substrate_vs_activity.csv
        docs/analysis_charts_3batch/fig41_orp_substrate.png
"""
import csv
import datetime as dt
import glob
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (                      # noqa: E402
    BLUE, YELLOW, AQUA, RED, INK, INK2, MUTED, BASELINE, OUT, style)
from ph_orp_discriminator import descents, load_full     # noqa: E402
from shape_clustering import GAPH, RISE                  # noqa: E402

AUTO_A = (dt.date(2026, 8, 11), dt.date(2026, 8, 22))    # 碳源充足
AUTO_B = (dt.date(2026, 8, 25), dt.date(2026, 8, 31))    # 碳源斷掉（進料 CO2 被切）
WIN = 60                                                  # 補氣前後各看幾分鐘


def auto_descents(hh, p):
    """自動化批專用的較寬門檻：≥30 點、降幅 ≥0.05、≥1 hr。"""
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
            if e - s >= 30 and p[s] - p[e] >= 0.05 and hh[e] - hh[s] >= 1.0]


def refills(ts, hh, p):
    return [i for i in range(1, len(ts))
            if p[i] - p[i - 1] > RISE and hh[i] - hh[i - 1] < GAPH]


def stack_around(idx, hh, orp, win=WIN):
    """以事件為原點疊加 ORP（相對於事件前一分鐘）。回傳 (偏移分鐘, 平均, 標準誤)。"""
    rows = []
    for i in idx:
        if i - win < 0 or i + win >= len(orp):
            continue
        sl = slice(i - win, i + win + 1)
        if np.max(np.diff(hh[sl])) > GAPH:          # 中間有資料缺口就不用
            continue
        rows.append(orp[sl] - orp[i - 1])
    if not rows:
        return None
    R = np.array(rows)
    return (np.arange(-win, win + 1), R.mean(0),
            R.std(0, ddof=1) / np.sqrt(len(R)), len(R))


def perm_mean_p(v, n_iter=20000, seed=0):
    rng = np.random.default_rng(seed)
    obs = abs(np.mean(v))
    return float(np.mean([abs(np.mean(v * rng.choice([-1, 1], len(v)))) >= obs
                          for _ in range(n_iter)]))


def main():
    ts, hh, p, orp, ph = load_full()
    print('合併去重後 %d 筆　%s ~ %s' % (len(ts), ts[0].date(), ts[-1].date()))
    print('（ORP 已還原為負值。往更負 = 更還原 = 液相 H2 較多）')

    # ══ 檢定一：補氣當下 ══
    print('\n══ 檢定一　補氣當下 ORP 有沒有反應 ══')
    print('   若 ORP 跟著補料走 -> 補氣後應**往更負**（H2 溶進液相）')
    ref = refills(ts, hh, p)
    got = stack_around(ref, hh, orp)
    if got:
        off, mu, se, n = got
        pre = mu[off < 0].mean()
        p10 = mu[(off > 0) & (off <= 10)].mean()
        p60 = mu[off >= 50].mean()
        print('   %d 次補氣　補氣前 %+.2f mV ->  +10 分 %+.2f ->  +60 分 %+.2f'
              % (n, pre, p10, p60))
        v = np.array([orp[i + 10] - orp[i - 1] for i in ref
                      if i + 10 < len(orp) and hh[i + 10] - hh[i - 1] < 0.5])
        print('   補氣後 10 分鐘的變化　中位 %+.2f mV　置換 p = %.4f'
              % (np.median(v), perm_mean_p(v)))
        print('   -> %s' % ('補氣讓 ORP 往更負 = ORP 跟著料走' if np.median(v) < 0
                            else ('補氣讓 ORP 往更正 = 不是單純的料位計'
                                  if np.median(v) > 0 else '沒反應')))

    # ══ 檢定二：泵開 vs 泵停 ══
    print('\n══ 檢定二　泵開／泵停 ORP 有沒有差（τ 三批）══')
    from pump_rhythm import BATCHES, minute_profile, pump_window
    for nm, tau, d0, d1 in BATCHES:
        m = np.array([d0 <= t.date() <= d1 for t in ts])
        ix = np.flatnonzero(m)
        if len(ix) < 100:
            continue
        mu_p, se_p, n_p = minute_profile(ts, hh, p, d0, d1)
        on, off_, gap = pump_window(mu_p)
        d_on, d_off = [], []
        for j in ix[1:]:
            if hh[j] - hh[j - 1] > 0.05 or p[j] - p[j - 1] > RISE:
                continue
            k = (ts[j].minute - on) % 60
            (d_on if k < gap else d_off).append(orp[j] - orp[j - 1])
        d_on, d_off = np.array(d_on), np.array(d_off)
        print('   %-6s 泵開 %+.4f mV/分（n=%d）　泵停 %+.4f mV/分（n=%d）　差 %+.4f'
              % (nm, d_on.mean(), len(d_on), d_off.mean(), len(d_off),
                 d_on.mean() - d_off.mean()))

    # ══ 檢定三：碳源斷掉時 ORP 垮不垮 ══（最決定性）
    print('\n══ 檢定三　碳源斷掉時 ORP 垮不垮（最決定性）══')
    print('   活性計 -> 沒碳源就該垮；料位計 -> H2 照補就不會垮')
    res = {}
    for lab, (da, db) in (('碳源充足', AUTO_A), ('碳源斷掉', AUTO_B)):
        m = np.array([da <= t.date() <= db for t in ts])
        ix = np.flatnonzero(m)
        # ⚠ 自動化批的循環只有約 2hr、降幅 0.05~0.08，會被全archive 用的
        #   「≥0.10、≥2hr」門檻整批濾掉（實測只剩 1 個）。此處改用該批自己的門檻。
        segs = [(s, e) for s, e in auto_descents(hh, p)
                if ix[0] <= s and e <= ix[-1]]
        exc = []
        for s, e in segs:
            t_ = hh[s:e + 1]
            if len(t_) > 20 and t_.std() > 0:
                exc.append(float(np.polyfit(t_ - t_[0], orp[s:e + 1], 1)[0]
                                 * (t_[-1] - t_[0])))
        res[lab] = (float(np.median(orp[ix])), np.array(exc))
        print('   %-8s ORP 水準中位 %+.0f mV　每循環位移中位 %+.1f mV（%d 個循環）'
              % (lab, res[lab][0], np.median(exc) if exc else np.nan, len(exc)))
    if all(len(res[k][1]) > 3 for k in res):
        a, b = res['碳源充足'][1], res['碳源斷掉'][1]
        rng = np.random.default_rng(0)
        obs = abs(np.median(b) - np.median(a))
        pool = np.concatenate([a, b])
        pv = float(np.mean([abs(np.median(q[len(a):]) - np.median(q[:len(a)])) >= obs
                            for q in (rng.permutation(pool) for _ in range(20000))]))
        print('   每循環位移 差 %+.1f mV　置換 p = %.4f' % (np.median(b) - np.median(a), pv))
        print('   水準差 %+.0f mV' % (res['碳源斷掉'][0] - res['碳源充足'][0]))
        print('   -> %s' % ('ORP 在沒碳源時仍照走 = 它跟的是 H2 料位，不是產甲烷活性'
                            if pv > 0.05 else 'ORP 在沒碳源時確實改變 = 帶有活性資訊'))

    # ══ 檢定四：能不能偵測「補料晚了」 ══
    print('\n══ 檢定四　能不能用 ORP 偵測「補料晚了」══')
    print('   定義：一個循環的谷底壓力低於該期間常態 -> 補氣晚了')
    segs = descents(hh, p)
    end_p = np.array([p[e] for s, e in segs])
    dur = np.array([hh[e] - hh[s] for s, e in segs])
    late = end_p < np.percentile(end_p, 15)
    orp_end = np.array([float(np.median(orp[max(s, e - 30):e + 1])) for s, e in segs])
    print('   晚補的循環 %d／%d　谷底壓力 %.2f vs 常態 %.2f'
          % (late.sum(), len(segs), np.median(end_p[late]), np.median(end_p[~late])))
    print('   末段 ORP　晚補 %+.0f mV　常態 %+.0f mV　差 %+.0f'
          % (np.median(orp_end[late]), np.median(orp_end[~late]),
             np.median(orp_end[late]) - np.median(orp_end[~late])))
    rng = np.random.default_rng(1)
    obs = abs(np.median(orp_end[late]) - np.median(orp_end[~late]))
    pv = float(np.mean([abs(np.median(orp_end[q][:late.sum()])
                            - np.median(orp_end[q][late.sum():])) >= obs
                        for q in (rng.permutation(len(segs)) for _ in range(20000))]))
    print('   置換 p = %.4f　-> %s' % (pv, '晚補的循環 ORP 確實不同，可當告警'
                                       if pv < 0.05 else '分不出來，ORP 當不了補料告警'))

    make_figure(ts, hh, p, orp, got, res, segs, late, orp_end, end_p)
    path = os.path.join(OUT, 'orp_substrate_vs_activity.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['起始時刻', '時長hr', '谷底壓力', '末段ORP', '是否晚補'])
        for i, (s, e) in enumerate(segs):
            w.writerow([ts[s].strftime('%Y-%m-%d %H:%M'), round(dur[i], 2),
                        round(end_p[i], 3), round(orp_end[i], 1),
                        '晚' if late[i] else '常態'])
    print('\n逐週期明細 -> %s（%d 列）' % (os.path.relpath(path, REPO), len(segs)))


def make_figure(ts, hh, p, orp, got, res, segs, late, orp_end, end_p):
    fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.6), gridspec_kw={'wspace': 0.32})

    ax = axes[0]
    if got:
        off, mu, se, n = got
        ax.fill_between(off, mu - 2 * se, mu + 2 * se, color=BLUE, alpha=0.2, lw=0)
        ax.plot(off, mu, color=BLUE, lw=2.2)
    ax.axvline(0, color=RED, lw=1.4, ls='--')
    ax.axhline(0, color=BASELINE, lw=1)
    lo, hi = ax.get_ylim()
    ax.set_ylim(lo - (hi - lo) * 0.06, hi + (hi - lo) * 0.30)    # 先留空間再放字
    ax.text(2, ax.get_ylim()[1] * 0.78, ' 補氣', color=RED, fontsize=10,
            ha='left', va='top')          # 壓低，讓開左上角的說明文字
    ax.text(0.03, 0.97, '往下 = 更還原（液相 H2 變多）\n'
                        '若 ORP 是料位計，補氣後應該往下掉',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='top')
    style(ax, 'a　補氣前後，ORP 怎麼動', '離補氣多少分鐘', 'ORP 相對變化 (mV)')

    ax = axes[1]
    labs = ['碳源充足', '碳源斷掉']
    cols = [MUTED, RED]
    for i, lab in enumerate(labs):
        v = res[lab][1]
        if len(v) == 0:
            continue
        x = np.full(len(v), i) + np.random.default_rng(i).uniform(-0.12, 0.12, len(v))
        ax.scatter(x, v, s=28, color=cols[i], alpha=0.7, lw=0)
        ax.hlines(np.median(v), i - 0.26, i + 0.26, color=INK, lw=2.6, zorder=5)
        # 標籤放在點雲與橫線之外，否則會壓在資料點與線端上
        ax.text(i + 0.42, np.median(v), '%+.1f mV' % np.median(v), ha='left',
                va='center', fontsize=10, color=INK, fontweight='bold')
    ax.axhline(0, color=BASELINE, lw=1)
    ax.set_xticks(range(2))
    ax.set_xticklabels(labs)
    ax.set_xlim(-0.55, 1.95)                     # 右側留給中位數標籤
    _lo, _hi = ax.get_ylim()
    ax.set_ylim(_lo - (_hi - _lo) * 0.18, _hi)   # 下方留給說明文字
    ax.text(0.03, 0.06, '每個點 = 一個循環裡 ORP 走了多少\n'
                        '若 ORP 是活性計，右邊（沒碳源）應該明顯變小',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='bottom')
    style(ax, 'b　碳源斷掉之後，ORP 還照走嗎', None, '一個循環內 ORP 位移 (mV)')

    ax = axes[2]
    ax.scatter(end_p[~late], orp_end[~late], s=20, color=MUTED, alpha=0.6, lw=0,
               label='常態')
    ax.scatter(end_p[late], orp_end[late], s=26, color=RED, alpha=0.75, lw=0,
               label='谷底特別低（疑似補料晚了）')
    _v = np.concatenate([orp_end[~late], orp_end[late]])
    _lo, _hi = float(np.percentile(_v, 0.5)), float(np.percentile(_v, 99.5))
    ax.set_ylim(_lo - (_hi - _lo) * 0.14, _hi + (_hi - _lo) * 0.50)  # 上方留給說明
    ax.legend(loc='lower left', fontsize=9, frameon=False)
    ax.text(0.97, 0.97, '若兩群在縱軸上分得開，\nORP 就能當「補料晚了」的告警。',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='right', va='top')
    style(ax, 'c　ORP 能不能告訴你「該補料了」', '循環谷底壓力 (kg/cm²)', '循環末段 ORP (mV)')

    out = os.path.join(OUT, 'fig41_orp_substrate.png')
    fig.savefig(out)
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
