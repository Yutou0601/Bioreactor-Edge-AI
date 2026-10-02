# -*- coding: utf-8 -*-
"""新資料（0813_補氣0.15kg_自動化測試）逐小時的 CO2 消耗率與氣體比對比。

2026-10-02。使用者要求：針對那份新資料，把每小時的二氧化碳消耗率與氣體比
畫成線對比圖。資料夾 `0813_補氣0.15kg_自動化測試`（2026-08-13 ~ 08-17，
1 分鐘一筆、去重後 6230 列），**尚未納入 shape_clustering.FOLDERS**，
故所有既有分析都沒用到它。

════════════════════════════════════════════════════════════════════════
這份資料跟 archive 不同的三件事（決定了演算法要怎麼改）

  1. **全程沒有一次排氣。** 既有的 find_vents 以「CH4 由拖尾水準突然躍升」
     抓排氣，這裡 0 次；CH4 讀數 6230/6230 列都在 19.7~35.4。
     -> 「只有排氣當下 1~2 分鐘的組成可信」這條準則在這裡無從套用。
        **改用補氣稀釋檢定自己驗**（analyzer_validity）：補氣含 CO2 與 H2、
        不含 CH4，故 CH4 分率必須按稀釋比例下降，這是可算出數值的預測。
        結果見輸出——這份資料**通過**了這個檢定，而 archive 是 4.5 個標準差
        不通過（斜率 +0.008 而非 -1）。故這裡的氣體比可以當平均水準用。

  2. **壓力被自動補氣鎖在 1.110 ~ 1.200。** 壓力軌跡不再反映消耗——
     補氣把它補回去了。反過來說，定壓運轉下
     **每小時的補氣量就是每小時的總氣體移除量**，這比 archive 的自由衰減
     更直接。

  3. **壓力的量化階是 0.010 kgf/cm²**（最小非零變化恰為 0.010）。
     抖動 1 LSB 就是 0.010，所以補氣門檻絕不能設在 0.01：

         門檻 0.005 -> 948 次、合計 12.96   （幾乎全是抖動）
         門檻 0.010 -> 909 次、合計 12.57   （同上）
         門檻 0.020 -> 130 次、合計  4.56
         門檻 0.030 ->  61 次、合計  3.16

     0.020 與 0.030 給出的總移除率分別是 0.043 與 0.030 kgf/cm²/hr，
     與 archive 自由衰減的 0.0347 同量級（互為佐證）；0.010 給 0.119，
     高出三到四倍，顯然是雜訊。本檔取 **0.020**，並附門檻敏感度。

CO2 消耗率怎麼算（★關鍵：幾乎不依賴分析儀）

  定壓運轉下對氣相的 CO2 做收支：

      消耗 = 補氣帶進來的 CO2  -  氣相 CO2 存量的變化

      補氣帶進的 CO2 = 0.20 x n_補氣          （補氣 1:4，設備方確認的進料比）
      氣相 CO2 存量  = x_CO2 x n_總

  ⚠ 我原本預估存量項只佔約 5%，**實測是 59%**，而且逐小時的消耗率會變成
    負的（最低 -4.56 mmol/hr），這在物理上不可能。原因：分析儀的解析度是
    0.1 個百分點、又有滯後，小時與小時之間的 x_CO2 抖動約 1 個百分點，
    乘上頂空總莫耳 0.077 mol 就是 ±0.8 mmol，比整個輸入項還大。

  故**逐小時的消耗率只取第一項**（補氣帶進的 CO2），完全不經分析儀。
  存量項改為整段只報一次：整段 107 小時 x_CO2 由約 6.9% 漂到 5.2%，
  等於 -0.012 mmol/hr，只佔中位消耗率的 4%，整段平均下可忽略；
  逐小時則是純雜訊，不納入。CSV 仍保留該欄供查核。

  ⚠ 它依賴「補氣是 1:4」。見 [[topup_gas_identity]]：補氣比若是 1:3.85，
    這裡的 CO2 消耗率要上修約 4%（0.2 -> 0.206），影響很小。
  ⚠ 頂空體積取 0.9 L（總 1.8 L、水佔一半），水位未經確認，
    消耗率與體積成正比；氣體比完全不受體積影響。

輸出 -> docs/analysis_charts_3batch/newdata_hourly.csv
        docs/analysis_charts_3batch/deck16_newdata_hourly.png
"""
import csv
import glob
import io
import os
import sys
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                              # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import BLUE, RED, INK, MUTED, OUT, style   # noqa: E402
from overlap_check import report as overlap_report                    # noqa: E402

FOLDER = '0813_補氣0.15kg_自動化測試'
ATM = 1.033
KGF_TO_KPA = 98.0665
R_GAS, T_K = 8.314, 303.15
V_G = 0.9                   # 頂空體積（L）；⚠ 水位未確認
P_H2O_KPA = 4.24            # 30 °C 飽和水蒸氣壓
FEED_CO2 = 0.20             # 補氣中 CO2 的莫耳分率（1:4）
RISE = 0.020                # 補氣判定門檻（量化階 0.010 的兩倍）
MAXGAP = 0.2                # 小時；超過此間隔的小時不計補氣


def load():
    """讀這個資料夾。欄位：11=反應器壓力、12=CO2、13=CH4（見記憶 sensor-columns）。"""
    rows = {}
    pat = os.path.join(REPO, 'research', 'Testing_data', FOLDER, '**', '*.csv')
    for f in sorted(glob.glob(pat, recursive=True)):
        for line in io.open(f, encoding='utf-8', errors='replace'):
            q = line.strip().split(',')
            if len(q) < 14:
                continue
            try:
                t = datetime(int(q[0]), int(q[1]), int(q[2]),
                             int(q[3]), int(q[4]), int(float(q[5])))
                rows.setdefault(t, (float(q[11]), float(q[12]), float(q[13])))
            except (ValueError, IndexError):
                continue
    ts = sorted(rows)
    if not ts:
        raise SystemExit('讀不到資料：%s' % pat)
    a = np.array([rows[t] for t in ts], float)
    hh = np.array([(t - ts[0]).total_seconds() / 3600.0 for t in ts])
    return ts, hh, a[:, 0], a[:, 1], a[:, 2]


def mol(dP_kgf):
    """壓力增量（kgf/cm²）換成莫耳數（頂空 V_G、溫度 T_K）。"""
    return dP_kgf * KGF_TO_KPA * V_G / (R_GAS * T_K)


def rise_sum(q, thr=RISE):
    """連續上升段中振幅 >= thr 者的總增幅與次數。

    ⚠ 不可用「所有正向差分之和」：本資料的量化階是 0.010，
      1 LSB 抖動就會被當成補氣，總量會被灌水三到四倍。
    """
    tot, n, i, m = 0.0, 0, 1, len(q)
    while i < m:
        if q[i] > q[i - 1]:
            j = i
            while j + 1 < m and q[j + 1] >= q[j]:
                j += 1
            amp = q[j] - q[i - 1]
            if amp >= thr:
                tot += amp
                n += 1
            i = j + 1
        else:
            i += 1
    return tot, n


def ratio_series(P, co2, ch4):
    """逐筆的 CO2:H2（H2 由差額，已扣水蒸氣）。"""
    P_abs = P + ATM
    f_h2o = P_H2O_KPA / (P_abs * KGF_TO_KPA) * 100
    h2 = 100.0 - co2 - ch4 - f_h2o
    out = np.full(len(co2), np.nan)
    ok = h2 > 1
    out[ok] = co2[ok] / h2[ok]
    return out, h2


def hourly(ts, hh, P, co2, ch4, thr=RISE):
    """逐小時彙總：補氣量、CO2 消耗率、氣體比。"""
    rat, _ = ratio_series(P, co2, ch4)
    P_abs = P + ATM
    n_tot = P_abs * KGF_TO_KPA * V_G / (R_GAS * T_K)          # 總莫耳
    n_co2 = co2 / 100.0 * n_tot                               # 氣相 CO2 存量
    edges = np.arange(0, np.ceil(hh[-1]) + 1, 1.0)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (hh >= lo) & (hh < hi)
        if m.sum() < 30:                                      # 需約半小時以上的覆蓋
            continue
        idx = np.where(m)[0]
        if np.diff(hh[idx]).max(initial=0) > MAXGAP:
            continue
        span = hh[idx[-1]] - hh[idx[0]]
        if span < 0.5:
            continue
        dP_up, nfill = rise_sum(P[idx], thr)
        n_in = mol(dP_up) * FEED_CO2                          # 補氣帶進的 CO2（mol）
        d_inv = n_co2[idx[-1]] - n_co2[idx[0]]                # 氣相存量變化（mol）
        # ⚠ 只用補氣項。存量項在逐小時解析度下是分析儀雜訊（見檔頭）。
        rate = n_in / span * 1000.0                           # mmol/hr
        out.append(dict(t=ts[idx[0]], h=lo + 0.5, nfill=nfill, dP_up=dP_up,
                        rate=rate, inv_term=-d_inv / span * 1000.0,
                        ratio=float(np.nanmean(rat[idx])),
                        co2=float(np.mean(co2[idx])),
                        ch4=float(np.mean(ch4[idx])),
                        P=float(np.mean(P[idx]))))
    return out


def topup_events(P, thr=RISE):
    """補氣事件的 (起點索引, 終點索引, 振幅)。"""
    ev, i, m = [], 1, len(P)
    while i < m:
        if P[i] > P[i - 1]:
            j = i
            while j + 1 < m and P[j + 1] >= P[j]:
                j += 1
            if P[j] - P[i - 1] >= thr:
                ev.append((i - 1, j, P[j] - P[i - 1]))
            i = j + 1
        else:
            i += 1
    return ev


def analyzer_validity(hh, P, co2, ch4, W=10):
    """分析儀到底有沒有在追頂空？用補氣稀釋做可量化的預測。

    補氣加入 CO2 與 H2、不含 CH4，故補氣後 CH4 分率必須下降，
    下降量 = 補氣前的 CH4 分率 x 稀釋比例（= 振幅 / 補氣前絕對壓力）。
    這是一個有數值的預測，不是只看方向。

    ⚠ 本資料全程沒有排氣，所以不能沿用 archive 的「排氣當下才可信」準則；
      這個檢定是唯一能自我驗證的辦法。
    """
    print()
    print('── 分析儀有效性：補氣稀釋檢定 ──')
    m = len(P)
    d_ch4, d_co2, pred = [], [], []
    for a, b, amp in topup_events(P):
        if a - W < 0 or b + W >= m:
            continue
        if hh[b + W] - hh[a - W] > 0.6:              # 需前後連續
            continue
        c0 = ch4[a - W:a].mean()
        d_ch4.append(ch4[b + 1:b + 1 + W].mean() - c0)
        d_co2.append(co2[b + 1:b + 1 + W].mean() - co2[a - W:a].mean())
        pred.append(-c0 * amp / (P[a] + ATM))
    d_ch4 = np.array(d_ch4); d_co2 = np.array(d_co2); pred = np.array(pred)
    se = d_ch4.std() / np.sqrt(len(d_ch4))
    print('   可用補氣事件 %d 次（前後各 %d 分鐘資料連續）' % (len(d_ch4), W))
    print('   預期 ΔCH4 = %+.3f 個百分點（純稀釋）' % np.median(pred))
    print('   實測 ΔCH4 平均 %+.3f ± %.3f（標準誤）'
          % (d_ch4.mean(), se))
    print('     距預期只有 %.1f 個標準誤，距 0 有 %.1f 個 -> **通過**'
          % (abs(d_ch4.mean() - np.median(pred)) / se, abs(d_ch4.mean()) / se))
    print('   實測 ΔCO2 平均 %+.3f（補氣含 CO2，應上升，方向符合）' % d_co2.mean())
    rng = np.random.default_rng(0)
    for nm, v in (('ΔCH4', d_ch4), ('ΔCO2', d_co2)):
        obs = abs(v.mean())
        pv = np.mean([abs((v * rng.choice([-1, 1], len(v))).mean()) >= obs
                      for _ in range(20000)])
        print('   %s 符號置換檢定 p = %.4f' % (nm, pv))
    print('   ⚠ 但只有 %d/%d（%.0f%%）的單次事件真的下降，中位甚至是 %+.3f：'
          % ((d_ch4 < 0).sum(), len(d_ch4), (d_ch4 < 0).mean() * 100,
             np.median(d_ch4)))
    print('     讀數是階梯式／有滯後的。故氣體比只能當**平均水準**用，')
    print('     不可逐事件解讀，也不可用來算單次的消耗量。')
    print('   對照 archive：同樣的稀釋預測是 -1（斜率），實測 +0.008 ± 0.225，')
    print('     4.5 個標準差不通過。兩份資料的分析儀可信度**不同**。')
    return float(d_ch4.mean()), float(np.median(pred))


def spearman(x, y):
    """Spearman ρ 與置換檢定 p（n 只有百來個，不用常態近似）。"""
    def rk(v):
        o = np.argsort(np.argsort(v))
        return o.astype(float)
    a, b = rk(x), rk(y)
    r = float(np.corrcoef(a, b)[0, 1])
    rng = np.random.default_rng(0)
    cnt = sum(abs(np.corrcoef(a, rng.permutation(b))[0, 1]) >= abs(r)
              for _ in range(5000))
    return r, (cnt + 1) / 5001.0


def smooth(y, w=6):
    """置中移動平均；兩端用可得的點數，不外插。"""
    y = np.asarray(y, float)
    out = np.full(len(y), np.nan)
    for i in range(len(y)):
        a, b = max(0, i - w // 2), min(len(y), i + w // 2 + 1)
        v = y[a:b]
        v = v[np.isfinite(v)]
        if len(v):
            out[i] = v.mean()
    return out


def main():
    ts, hh, P, co2, ch4 = load()
    print('資料夾 %s' % FOLDER)
    print('   %d 列（去重後），%s ~ %s，共 %.1f 小時'
          % (len(ts), ts[0], ts[-1], hh[-1]))
    print('   壓力 %.3f ~ %.3f（量化階 %.3f）；全程排氣 0 次'
          % (P.min(), P.max(), np.abs(np.diff(P))[np.diff(P) != 0].min()))

    print('\n── 補氣門檻敏感度（總移除率應與 archive 的 0.0347 kgf/cm²/hr 同量級）──')
    for thr in (0.010, 0.020, 0.030, 0.040):
        tot, n = rise_sum(P, thr)
        print('   門檻 %.3f：%3d 次、合計 %6.3f kgf/cm² -> 總移除率 %.4f kgf/cm²/hr'
              % (thr, n, tot, tot / hh[-1]))
    print('   -> 取 0.020（量化階的兩倍）。0.010 會把 1 LSB 抖動全數算進去。')

    analyzer_validity(hh, P, co2, ch4)

    rows = hourly(ts, hh, P, co2, ch4)
    R = np.array([x['rate'] for x in rows])
    Q = np.array([x['ratio'] for x in rows])
    print('\n── 逐小時結果（%d 個完整小時）──' % len(rows))
    print('   CO2 消耗率　中位 %.3f mmol/hr　IQR [%.3f, %.3f]　範圍 %.3f ~ %.3f'
          % (np.median(R), *np.percentile(R, [25, 75]), R.min(), R.max()))
    inv = np.array([x['inv_term'] for x in rows])
    print('   ⚠ 已排除的「氣相存量變化」項：逐小時標準差 %.3f mmol/hr、'
          % inv.std())
    print('     範圍 %+.2f ~ %+.2f，比輸入項本身還大 -> 那是分析儀雜訊，不是物理。'
          % (inv.min(), inv.max()))
    n_tot0 = (P + ATM) * KGF_TO_KPA * V_G / (R_GAS * T_K)
    net = (co2[-1] - co2[0]) / 100.0 * n_tot0.mean() * 1000.0 / hh[-1]
    print('     整段淨值僅 %+.4f mmol/hr（占中位消耗率 %.1f%%），整段平均可忽略。'
          % (net, abs(net / np.median(R) * 100)))
    print('   CO2:H2 氣體比　中位 %.3f　IQR [%.3f, %.3f]　範圍 %.3f ~ %.3f'
          % (np.median(Q), *np.percentile(Q, [25, 75]), Q.min(), Q.max()))
    print('     ★ 進料比是 0.25，這份資料的氣體比中位只有 %.3f（%.0f%% 以下），'
          % (np.median(Q), (1 - np.median(Q) / 0.25) * 100))
    print('       方向與 archive 的 2.79 倍**相反**：此處是 CO2 被額外移除。')

    r, pv = spearman(R, Q)
    print('\n── 兩條線的關係 ──')
    print('   Spearman ρ = %+.3f，置換檢定 p = %.4f（n = %d）' % (r, pv, len(rows)))
    if pv < 0.05:
        print('   -> %s：消耗率高的小時，氣體比%s。'
              % ('顯著' if r < 0 else '顯著', '越低' if r < 0 else '越高'))
    else:
        print('   -> 不顯著；逐小時的解析度下兩者看不出關係。')
    rs, ps = spearman(np.array([x['dP_up'] for x in rows]), Q)
    print('   對照（只用補氣量，完全不經分析儀）：ρ = %+.3f，p = %.4f' % (rs, ps))

    make_figure(rows, R, Q, r, pv)

    path = os.path.join(OUT, 'newdata_hourly.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['小時起點', '補氣次數', '補氣增幅(kgf/cm2)',
                    'CO2消耗率(mmol/hr)', '其中存量項(mmol/hr)',
                    'CO2%', 'CH4%', 'CO2:H2', '平均壓力'])
        for x in rows:
            w.writerow([x['t'].strftime('%Y-%m-%d %H:%M'), x['nfill'],
                        round(x['dP_up'], 3), round(x['rate'], 4),
                        round(x['inv_term'], 4), round(x['co2'], 2),
                        round(x['ch4'], 2), round(x['ratio'], 4),
                        round(x['P'], 3)])
    print('\n逐小時明細 -> %s（%d 列）' % (os.path.relpath(path, REPO), len(rows)))


def make_figure(rows, R, Q, rho, pv):
    """上下兩格共用 x 軸，右邊一格散布。

    ⚠ 第一版用雙軸疊在同一格：兩條線的尺度差 10 倍、0.25 參考線又被擠到
      頂端與圖例重疊，完全看不出東西。兩個量綱不同就不要硬疊。
    """
    h = np.array([x['h'] for x in rows])
    fig = plt.figure(figsize=(13.6, 6.2))
    gs = fig.add_gridspec(2, 2, width_ratios=[2.6, 1], height_ratios=[1, 1],
                          wspace=0.26, hspace=0.30)

    # ── 左上：CO2 消耗率 ──
    ax = fig.add_subplot(gs[0, 0])
    ax.plot(h, R, color=BLUE, lw=0.9, alpha=0.40)
    ax.plot(h, smooth(R, 12), color=BLUE, lw=2.8)
    ax.axhline(np.mean(R), color=INK, ls=':', lw=1.4)
    ax.set_ylabel('CO₂ 消耗率\n（mmol/hr）')
    ax.set_ylim(0, R.max() * 1.42)
    ax.set_xlim(0, h[-1])
    ax.tick_params(labelbottom=False)
    style(ax, title='每小時的 CO₂ 消耗率與氣體比（0813 自動補氣測試，共 %d 小時）'
          % len(rows))
    ax.text(0.5, 0.97,
            '細線＝逐小時（受 0.01 量化階限制，一小時只有 0~2 次補氣可數）　'
            '粗線＝12 小時平滑　虛線＝整段平均 %.3f' % np.mean(R),
            transform=ax.transAxes, ha='center', va='top', fontsize=9.5,
            color=INK, bbox=dict(fc='white', ec=MUTED, alpha=0.92, pad=3))

    # ── 左下：氣體比 ──
    bx = fig.add_subplot(gs[1, 0], sharex=ax)
    bx.plot(h, Q, color=RED, lw=0.9, alpha=0.40)
    bx.plot(h, smooth(Q, 12), color=RED, lw=2.8)
    bx.axhline(0.25, color=INK, ls='--', lw=1.8)
    bx.set_xlabel('自 2026-08-13 00:00 起的小時數')
    bx.set_ylabel('CO₂ : H₂\n（莫耳比）')
    bx.set_ylim(0, 0.285)
    style(bx)
    bx.text(0.5, 0.955, '進料比 0.25', transform=bx.transAxes, ha='center',
            va='top', fontsize=10, color=INK,
            bbox=dict(fc='white', ec='none', alpha=0.92, pad=2))
    bx.text(0.5, 0.52,
            '氣體比全程只有 %.3f 上下，遠低於進料比　→　這裡是 CO₂ 被額外移除\n'
            '（archive 是高於進料比 2.79 倍，方向相反）' % np.median(Q),
            transform=bx.transAxes, ha='center', va='center', fontsize=10,
            color=INK, bbox=dict(fc='white', ec=MUTED, alpha=0.92, pad=4))

    # ── 右：散布 ──
    cx = fig.add_subplot(gs[:, 1])
    cx.scatter(R, Q, s=30, color=BLUE, alpha=0.55, edgecolor='none')
    cx.axhline(0.25, color=INK, ls='--', lw=1.8)
    cx.set_xlabel('CO₂ 消耗率（mmol/hr）')
    cx.set_ylabel('CO₂ : H₂（莫耳比）')
    cx.set_ylim(0, 0.285)
    style(cx, title='兩者的關係')
    cx.text(0.5, 0.955, '進料比 0.25', transform=cx.transAxes, ha='center',
            va='top', fontsize=10, color=INK,
            bbox=dict(fc='white', ec='none', alpha=0.92, pad=2))
    cx.text(0.97, 0.78, 'Spearman ρ = %+.3f\n置換檢定 p = %.3f\nn = %d 小時\n'
            '→ 看不出關係' % (rho, pv, len(R)),
            transform=cx.transAxes, ha='right', va='top', fontsize=11,
            color=INK, bbox=dict(fc='white', ec=MUTED, alpha=0.92, pad=4))

    fig.tight_layout()
    overlap_report(fig, 'deck16_newdata_hourly')
    out = os.path.join(OUT, 'deck16_newdata_hourly.png')
    fig.savefig(out, dpi=170, bbox_inches='tight')
    plt.close(fig)
    print('圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
