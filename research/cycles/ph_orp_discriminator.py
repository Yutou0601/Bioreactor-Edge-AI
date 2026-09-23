# -*- coding: utf-8 -*-
"""用 pH 的「符號」分開溶解與生物 —— 壓力一個通道做不到的事。

2026-09-21。使用者指出：單靠壓力是論文那條路，而且曲率法的前提（生物定速）
本來就不成立，所以必須把 ORP／pH 當量測用進來。

════════════════════════════════════════════════════════════════════════
為什麼 pH 是對的通道 —— 兩個過程的符號相反

  CO2 溶進水裡：   CO2 + H2O -> H2CO3 -> H+ + HCO3−        **pH 下降**
  產甲烷消耗 CO2： CO2 + 4H2 -> CH4 + 2H2O                  **pH 上升**
                  （移除溶解的 CO2／碳酸氫根，酸被拿走）

  壓力通道看不出差別：兩者都讓壓力下降，所以才會簡併。
  **pH 通道的符號直接相反**，而且判讀符號不需要任何校準常數。

  ORP 則是 H2 的指標（H2 溶解 -> 更還原 -> 更負；H2 被吃掉 -> 回升）。
  ⚠ 本專案的紀錄只存 ORP 的絕對值，真值為負。故「數值變大 = 更還原」。

════════════════════════════════════════════════════════════════════════
⚠ 為什麼曲率那條路已經作廢（本檔取代它的結論）

  曲率法的前提是「生物項是定速（直線），故二階微分為零」。但生物會變動。
  數值示範（curvature_inverse 的同一套估計量）：

      真物理份額 0.00 + 生物速率在週期內衰減  ->  曲率法報出物理份額 1.01

  也就是完全沒有物理溶解，曲率法照樣宣稱 100% 是物理。故曲率不可當分離工具。

檢定設計（都不需要校準常數，只看符號與相關）

  一、每個下降週期內 pH 往哪走？往下 = 溶解主導；往上 = 生物主導
  二、pH 變化的大小與壓降的大小成比例嗎？（若壓降是溶解造成的，兩者應成正比）
  三、ORP 往哪走？與 pH 一致嗎？
  四、安慰劑：把 pH 序列整段時間平移後重做，確認看到的不是慢漂移

輸出 -> docs/analysis_charts_3batch/ph_orp_discriminator.csv
        docs/analysis_charts_3batch/fig39_ph_discriminator.png
"""
import csv
import glob
import os
import sys
from datetime import datetime

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
from shape_clustering import FOLDERS, GAPH, RISE        # noqa: E402

NGRID = 30
I_ORP, I_PH, I_P = 7, 9, 11


def load_full():
    """壓力 + ORP + pH。欄位常數不可自行推測（見 cycle_store）。

    ⚠ 必須整批讀完再依時間戳去重：現場資料夾會重疊，不去重是靜默算錯。
    """
    rows = {}
    for f in FOLDERS:
        for path in sorted(glob.glob(os.path.join(REPO, 'research', 'Testing_data',
                                                  f, '**', '*.csv'), recursive=True)):
            with open(path, encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    q = line.strip().split(',')
                    if len(q) < 14:
                        continue
                    try:
                        t = datetime(int(q[0]), int(q[1]), int(q[2]),
                                     int(q[3]), int(q[4]), int(float(q[5])))
                        v = (float(q[I_P]), float(q[I_ORP]), float(q[I_PH]))
                    except (ValueError, IndexError):
                        continue
                    rows.setdefault(t, v)          # 先寫的保留
    ts = sorted(rows)
    a = np.array([rows[t] for t in ts], float)
    hh = np.array([(t - ts[0]).total_seconds() / 3600.0 for t in ts])
    # ORP 紀錄只存絕對值，真值為負
    return ts, hh, a[:, 0], -np.abs(a[:, 1]), a[:, 2]


def descents(hh, p):
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
            if e - s >= 40 and p[s] - p[e] >= 0.10 and hh[e] - hh[s] >= 2.0]


PH_FAULT = 8.0        # pH > 8 為感測器故障值（實測佔 5.6%，多為 14.00）


def robust_change(x, hh, s, e, frac=0.15):
    """週期內的淨變化＝最小平方斜率 × 時長。

    ⚠ 不可用「頭尾各取中位數相減」：pH 量化步階 0.01，而週期內全距中位僅
      0.050（5 個階），端點式估計量會被量化壓成恰好 0.0000，得到假的虛無。
      改用整條曲線的斜率，數百個點平均下來可解析到次量化階。
    """
    t = hh[s:e + 1]
    y = np.asarray(x[s:e + 1], float)
    ok = np.isfinite(y)
    if ok.sum() < 20 or t[ok].std() == 0:
        return np.nan
    sl = np.polyfit(t[ok] - t[ok][0], y[ok], 1)[0]
    return float(sl * (t[-1] - t[0]))


def perm_sign_p(v, n_iter=20000, seed=0):
    """符號檢定的置換版：隨機翻轉每個值的符號，看中位數多極端。"""
    rng = np.random.default_rng(seed)
    obs = abs(np.median(v))
    hit = sum(abs(np.median(v * rng.choice([-1, 1], len(v)))) >= obs
              for _ in range(n_iter))
    return hit / n_iter


def main():
    ts, hh, p, orp, ph = load_full()
    ph = np.where(ph > PH_FAULT, np.nan, ph)        # 故障值不可參與任何統計
    print('合併去重後 %d 筆　%s ~ %s' % (len(ts), ts[0].date(), ts[-1].date()))
    print('pH 範圍 %.2f ~ %.2f（中位 %.2f）　ORP 範圍 %.0f ~ %.0f mV（中位 %.0f）'
          % (np.nanpercentile(ph, 1), np.nanpercentile(ph, 99), np.nanmedian(ph),
             np.percentile(orp, 1), np.percentile(orp, 99), np.median(orp)))

    segs = descents(hh, p)
    grid = np.linspace(0, 1, NGRID)
    rows, Pp, Ph, Oo = [], [], [], []
    for s, e in segs:
        seg_ph = ph[s:e + 1]
        if np.mean(seg_ph > PH_FAULT) > 0.05:      # 故障值太多就整段不用
            continue
        if not np.all(np.isfinite(seg_ph)) or seg_ph.std() == 0:
            continue
        dP = p[s] - p[e]
        dph = robust_change(ph, hh, s, e)
        dor = robust_change(orp, hh, s, e)
        u = (hh[s:e + 1] - hh[s]) / (hh[e] - hh[s])
        Ph.append(np.interp(grid, u, np.nan_to_num(ph[s:e + 1] - np.nanmedian(ph[s:s + 5]))))
        Oo.append(np.interp(grid, u, orp[s:e + 1] - np.median(orp[s:s + 5])))
        Pp.append(np.interp(grid, u, (p[s:e + 1] - p[e]) / dP))
        rows.append(dict(t0=ts[s], dur=hh[e] - hh[s], dP=dP, dph=dph, dorp=dor))
    keep = [i for i, r in enumerate(rows) if np.isfinite(r['dph'])]
    rows = [rows[i] for i in keep]
    Ph = np.array([Ph[i] for i in keep])
    Oo = np.array([Oo[i] for i in keep])
    Pp = np.array([Pp[i] for i in keep])
    dP = np.array([r['dP'] for r in rows])
    dph = np.array([r['dph'] for r in rows])
    dor = np.array([r['dorp'] for r in rows])
    print('\n可用下降週期 %d 條' % len(rows))

    print('\n══ 檢定一　每個週期內 pH 往哪走 ══')
    print('   溶解主導 -> pH 下降（碳酸）；生物主導 -> pH 上升（酸被消耗）')
    print('   pH 淨變化  中位 %+.4f　IQR [%+.4f, %+.4f]　上升的比例 %.0f%%'
          % (np.median(dph), *np.percentile(dph, [25, 75]), (dph > 0).mean() * 100))
    print('   置換檢定（隨機翻符號）p = %.4f' % perm_sign_p(dph))
    print('   -> %s' % ('pH 在週期內顯著上升 = 生物主導'
                        if np.median(dph) > 0 and perm_sign_p(dph) < 0.05 else
                        ('pH 在週期內顯著下降 = 溶解主導'
                         if np.median(dph) < 0 and perm_sign_p(dph) < 0.05
                         else '方向不顯著')))

    print('\n══ 檢定二　pH 變化與壓降成比例嗎 ══')
    r_pp = float(np.corrcoef(dP, dph)[0, 1])
    rng = np.random.default_rng(1)
    pv = float(np.mean([abs(np.corrcoef(dP, rng.permutation(dph))[0, 1]) >= abs(r_pp)
                        for _ in range(5000)]))
    print('   壓降 vs pH 變化　相關 %+.3f　p = %.4f' % (r_pp, pv))
    print('   若壓降主要是 CO2 溶解 -> 壓降越大越酸 -> 應為顯著負相關')

    print('\n══ 檢定三　ORP 往哪走（H2 的指標；數值越負越還原）══')
    print('   ORP 淨變化  中位 %+.1f mV　IQR [%+.1f, %+.1f]　置換 p = %.4f'
          % (np.median(dor), *np.percentile(dor, [25, 75]), perm_sign_p(dor)))
    r_oo = float(np.corrcoef(dP, dor)[0, 1])
    print('   壓降 vs ORP 變化　相關 %+.3f' % r_oo)
    r_op = float(np.corrcoef(dph, dor)[0, 1])
    print('   pH 變化 vs ORP 變化　相關 %+.3f' % r_op)

    print('\n══ 檢定四　安慰劑：把 pH 整段時間平移 6 小時後重做 ══')
    sh = int(6 * 60)
    ph2 = np.roll(ph, sh)
    fake = []
    for s, e in segs:
        if e + 1 <= len(ph2) and np.all(np.isfinite(ph2[s:e + 1])):
            fake.append(robust_change(ph2, hh, s, e))
    fake = np.array(fake)
    print('   平移後的 pH 淨變化　中位 %+.4f（真實為 %+.4f）　置換 p = %.4f'
          % (np.median(fake), np.median(dph), perm_sign_p(fake)))
    print('   -> %s' % ('⚠ 安慰劑也顯著：看到的是慢漂移，不是週期內的訊號'
                        if perm_sign_p(fake) < 0.05 and
                        np.sign(np.median(fake)) == np.sign(np.median(dph))
                        else '安慰劑不顯著：訊號確實鎖在週期內'))

    make_figure(grid, Pp, Ph, Oo, dP, dph, dor, fake)
    path = os.path.join(OUT, 'ph_orp_discriminator.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['起始時刻', '時長hr', '壓降', 'pH淨變化', 'ORP淨變化mV'])
        for r in rows:
            w.writerow([r['t0'].strftime('%Y-%m-%d %H:%M'), round(r['dur'], 2),
                        round(r['dP'], 3), round(r['dph'], 4), round(r['dorp'], 1)])
    print('\n逐週期明細 -> %s（%d 列）' % (os.path.relpath(path, REPO), len(rows)))


def make_figure(grid, Pp, Ph, Oo, dP, dph, dor, fake):
    fig, axes = plt.subplots(1, 3, figsize=(15.4, 4.7),
                             gridspec_kw={'wspace': 0.46})  # a 的右軸標籤與 b 的左軸標籤會撞

    ax = axes[0]
    for arr, col, lab, scale in ((Ph, BLUE, 'pH（左軸）', 1),):
        mu = arr.mean(0)
        se = arr.std(0, ddof=1) / np.sqrt(len(arr))
        ax.fill_between(grid, mu - 2 * se, mu + 2 * se, color=col, alpha=0.2, lw=0)
        ax.plot(grid, mu, color=col, lw=2.4, label=lab)
    ax.axhline(0, color=BASELINE, lw=1)
    ax2 = ax.twinx()
    mu = Oo.mean(0)
    se = Oo.std(0, ddof=1) / np.sqrt(len(Oo))
    ax2.fill_between(grid, mu - 2 * se, mu + 2 * se, color=RED, alpha=0.18, lw=0)
    ax2.plot(grid, mu, color=RED, lw=2.4, label='ORP（右軸）')
    ax2.set_ylabel('ORP 相對變化 (mV)', color=RED, labelpad=10)
    ax2.tick_params(axis='y', colors=RED)
    ax2.spines['top'].set_visible(False)
    # 兩軸都往下留白，把說明文字放在曲線之下，避免壓到線
    for _a in (ax, ax2):
        _lo, _hi = _a.get_ylim()
        _a.set_ylim(_lo - (_hi - _lo) * 0.45, _hi)
    ax.text(0.03, 0.03, '藍 = pH（左軸）　紅 = ORP（右軸）　陰影為 95% 範圍\n'
                        'pH 往上 = 酸被消耗 = 像生物；往下 = 生成碳酸 = 像溶解',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='bottom')
    style(ax, 'a　一個週期裡，酸鹼與氧化還原往哪走', '一個週期走完的進度', 'pH 相對變化')

    ax = axes[1]
    ax.scatter(dP, dph, s=16, color=BLUE, alpha=0.55, lw=0)
    b, a0 = np.polyfit(dP, dph, 1)
    xs = np.linspace(dP.min(), dP.max(), 20)
    ax.plot(xs, a0 + b * xs, color=INK, lw=2)
    ax.axhline(0, color=BASELINE, lw=1)
    r = float(np.corrcoef(dP, dph)[0, 1])
    ax.text(0.03, 0.97, '若壓力是被液體吸走的，\n掉得越多就應該越酸（往右下）。\n'
                        '實際相關 %+.2f' % r,
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='top')
    style(ax, 'b　壓力掉得多，是不是就比較酸', '一個週期的壓降 (kg/cm²)', 'pH 淨變化')

    ax = axes[2]
    bins = np.linspace(min(np.percentile(dph, 1), np.percentile(fake, 1)),
                       max(np.percentile(dph, 99), np.percentile(fake, 99)), 30)
    ax.hist(fake, bins=bins, color=MUTED, alpha=0.75, lw=0, label='安慰劑（時間平移 6 小時）')
    ax.hist(dph, bins=bins, color=BLUE, alpha=0.75, lw=0, label='真實週期')
    ax.axvline(0, color=INK, lw=1.4, ls='--')
    ax.axvline(np.median(dph), color=BLUE, lw=2)
    ax.axvline(np.median(fake), color=MUTED, lw=2)
    ax.legend(loc='center right', fontsize=9, frameon=False)
    ax.text(0.03, 0.97, '真實與安慰劑若長得一樣，\n代表看到的只是慢慢的漂移，\n不是週期內的變化。',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='top')
    style(ax, 'c　這是週期內的變化，還是慢漂移', 'pH 淨變化', '週期數')

    out = os.path.join(OUT, 'fig39_ph_discriminator.png')
    fig.savefig(out)
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
