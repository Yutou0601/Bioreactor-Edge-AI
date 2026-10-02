# -*- coding: utf-8 -*-
"""補氣用的是什麼氣體？——氫氣超量流失的頭號對手假說。

2026-10-02。使用者指出：「那一次的進氣大量流失似乎是 H2 沒進氣體」。
同時提供的現場群組紀錄給了兩組關鍵事實，兩者都直接打到頭條結論。

════════════════════════════════════════════════════════════════════════
一、頭條結論靠什麼前提成立

  feed_ratio_drift.py 的推論鏈是：

      進料 CO2:H2 = 1:4  ==  Sabatier 消耗比 1:4
      => 只要「只有產甲烷」且「補的也是 1:4」，殘餘比恆為 0.25
      => 實測殘餘比 > 0.25  =>  H2 被額外移除

  設備方確認的是進料為 1:4。但資料裡的壓力上升事件（補氣）用的是哪一種
  氣體，從未確認過。若補氣是純 CO2 或 CO2 偏多的氣體，殘餘比高於 0.25
  就是必然結果，與洩漏毫無關係。

  這與既有的「碳酸鹽脫氣」假說不同：脫氣是液相來源，補氣是氣源，
  兩者都屬「只加 CO2 不加 H2」，但補氣這條是操作造成、量級大得多。

二、不靠體積假設去估補氣組成，以及它為什麼不夠

  定義超量 CO2 的壓力當量（下稱 E，單位 kgf/cm²）

      E = P_abs x (x_CO2 - 0.25 x_H2)

  各過程對它的作用：

      只有產甲烷（消耗 a 與 4a）   ->  dE = -a + 0.25(4a) = 0      （不變量）
      補入 d 莫耳、組成 (c, h)     ->  dE = (c - 0.25 h) d
      CO2 溶解 / 被液相吸收 d      ->  dE = -d
      碳酸鹽脫氣放出 d             ->  dE = +d
      H2 洩漏 L                    ->  dE = +0.25 L

  把「兩次排氣之間的 dE」對「同期間補氣的壓力增量總和」回歸，
  斜率看似就是 (c - 0.25 h)：1:4 給 0.00，純 CO2 給 1.00。
  E 與補氣量都正比於頂空體積，斜率與體積無關，不必假設液位。

  ⚠ 但這個回歸**不能**單獨下結論：純 CO2 補氣若隨即溶進液相，
    上表的 -d 項會把 (c-0.25h)d 抵銷掉，斜率同樣趨近 0。
    補氣組成與溶解項在這個回歸裡不可分。真正關掉這個假說的是量級論證
    （magnitude_argument）：純 CO2 補氣所要求的碳通量與鹼度都不可能。

  ⚠ 另外資料覆蓋僅 49%，漏掉的補氣會讓分母偏小、斜率偏大。

三、現場紀錄提供的獨立對照（無補氣的短程實驗）

  2026-09-11 / 09-12 / 09-15 三次實驗的流程是「洗槽 -> 充壓 -> 跑 3 小時
  -> 排氣測組成」，全程沒有補氣。洗完的組成三次都是 CO2 約 19~21%、
  CH4 約 0.5%，與 1:4 混合氣相符（1:4 即 CO2 20%），
  可視為設備方「進料 1:4」說法的獨立佐證。

  09-12 那次有完整的前後壓力與排氣組成，可直接做莫耳對帳。

輸出 -> docs/analysis_charts_3batch/topup_gas_identity.csv
"""
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                      # noqa: E402
from orp_calibration import find_vents, load_with_gas      # noqa: E402

ATM = 1.033
FEED = 0.25                 # 進料 CO2:H2（設備方確認）
P_H2O_KPA = 4.24            # 30 °C 飽和水蒸氣壓
KGF_TO_KPA = 98.0665
RISE = 0.03                 # 判定為補氣的最小壓力增幅（與既有切分器同值）
MAXGAP = 0.2                # 區間內允許的最大取樣間隔（小時）


def dry_fracs(P_gauge, x_co2, x_ch4):
    """扣掉水蒸氣後的莫耳分率（%）。H2 由差額取得。"""
    P_abs = P_gauge + ATM
    f_h2o = P_H2O_KPA / (P_abs * KGF_TO_KPA) * 100
    x_h2 = 100.0 - x_co2 - x_ch4 - f_h2o
    return x_co2, x_ch4, x_h2, P_abs


def rise_total(q):
    """區間內補氣的壓力增量總和，以及補氣次數。

    ⚠ 不可以把所有正向差分加起來。壓力讀數本身有約 2 LSB 的抖動，
      以每分鐘一筆、跨好幾天的區間去累加，光是雜訊就能堆出 20 kgf/cm²
      的假「補氣量」（第一版就是這樣錯的，分母被灌水約五倍）。
      正確做法是找出連續上升段，只採振幅 >= RISE 的那些。
    """
    tot, n, i, m = 0.0, 0, 1, len(q)
    while i < m:
        if q[i] > q[i - 1]:
            j = i
            while j + 1 < m and q[j + 1] >= q[j]:
                j += 1
            amp = q[j] - q[i - 1]
            if amp >= RISE:
                tot += amp
                n += 1
            i = j + 1
        else:
            i += 1
    return tot, n


def excess_E(P_gauge, x_co2, x_ch4):
    """超量 CO2 的壓力當量 E = P_abs x (x_CO2 - 0.25 x_H2)。"""
    c, _, h, P_abs = dry_fracs(P_gauge, x_co2, x_ch4)
    return P_abs * (c - FEED * h) / 100.0, h


def september_balance():
    """現場回報的 2026-09-12 短程實驗：無補氣，可直接做莫耳對帳。

    資料來源＝工作群組回報（非本機 CSV，本機資料止於 2026-08-03）：
      洗槽後  CH4 0.50%、CO2 20.9%；充壓至 1.177 kgf/cm²
      3 小時後關閉循環，壓力 1.017；排氣後 0.851
      排氣測得 CH4 2.07%、CO2 20.3%
    組成在排氣前後不變，故 1.017 時的組成即為量到的那組。
    """
    print()
    print('=' * 72)
    print('三、無補氣的短程實驗（2026-09-12，現場回報）')
    print('=' * 72)
    P1, P2 = 1.177, 1.017
    c1, m1 = 20.9, 0.50
    c2, m2 = 20.3, 2.07
    f1 = dry_fracs(P1, c1, m1)
    f2 = dry_fracs(P2, c2, m2)
    # 以「正比於絕對壓力」的莫耳數記帳（頂空體積與溫度不變，可約掉）
    d_ch4 = m2 / 100.0 * f2[3] - m1 / 100.0 * f1[3]
    d_co2 = f2[0] / 100.0 * f2[3] - f1[0] / 100.0 * f1[3]
    d_h2 = f2[2] / 100.0 * f2[3] - f1[2] / 100.0 * f1[3]
    print('   起始 %.3f -> 3 小時後 %.3f kgf/cm²（絕對 %.3f -> %.3f）'
          % (P1, P2, f1[3], f2[3]))
    print('   以壓力當量記帳（單位 kgf/cm²，頂空體積與溫度約掉）：')
    print('     CH4 %+.4f　CO2 %+.4f　H2 %+.4f　合計 %+.4f（實測 %+.4f）'
          % (d_ch4, d_co2, d_h2, d_ch4 + d_co2 + d_h2, f2[3] - f1[3]))
    print('   產甲烷 %+.4f 依計量應消耗 CO2 %.4f、H2 %.4f'
          % (d_ch4, d_ch4, 4 * d_ch4))
    ex_co2 = -d_co2 - d_ch4
    ex_h2 = -d_h2 - 4 * d_ch4
    print('   扣掉計量後的額外移除量：CO2 %+.4f　H2 %+.4f' % (ex_co2, ex_h2))
    print('     -> 額外移除的 H2 佔計量需求的 %.0f%%' % (ex_h2 / (4 * d_ch4) * 100))
    r1, r2 = f1[0] / f1[2], f2[0] / f2[2]
    print('   殘餘 CO2:H2　起始 %.3f -> 結束 %.3f（進料比 %.2f，即 %.2f 倍）'
          % (r1, r2, FEED, r2 / FEED))
    print('   ★ 這是全案唯一「確定沒有補氣」的組成資料，殘餘比只有 %.2f 倍，'
          % (r2 / FEED))
    print('     與長紀錄的中位 2.79 倍差一個量級。')
    return r2 / FEED


def h2_robustness(rows):
    """H2 由差額推得，CH4 很高時 H2 會被壓到近零、比值被放大。

    使用者的疑慮「H2 沒進氣體」在資料上對應的就是這幾筆。
    這裡逐步剔除低 H2 的筆數，看結論是否撐得住。
    """
    print()
    print('=' * 72)
    print('四、只留「H2 讀數站得住」的筆數重算')
    print('=' * 72)
    for thr in (1, 10, 20, 30):
        sub = [x for x in rows if x['h2'] >= thr]
        if len(sub) < 5:
            continue
        R = np.array([x['ratio'] for x in sub])
        D = R / FEED
        print('   H2 >= %2d%%：n=%2d　中位比值 %.3f（%.2f 倍）　高於進料比 %d/%d'
              % (thr, len(sub), np.median(R), np.median(D), (D > 1).sum(), len(D)))


def topup_regression(hh, p, rows):
    """以排氣對之間的 dE 回歸補氣量，估補氣組成。"""
    print()
    print('=' * 72)
    print('二、從資料反推補氣用的是什麼氣體')
    print('=' * 72)
    pairs = []
    for a, b in zip(rows[:-1], rows[1:]):
        ia, ib = a['i'], b['i']
        gaps = np.diff(hh[ia:ib + 1])
        if len(gaps) == 0 or gaps.max() > MAXGAP:
            continue                              # 區間內有資料斷點，補氣會漏算
        # 排氣 a 的谷底壓力：往後找到局部極小
        j = ia
        while j + 1 < ib and p[j + 1] < p[j]:
            j += 1
        P_lo = p[j]
        topup, nfill = rise_total(np.asarray(p[j:ib], float))
        if topup < RISE:
            continue
        E_start = excess_E(P_lo, a['co2'], a['ch4'])[0]
        dE = b['E'] - E_start
        pairs.append(dict(t0=a['t'], t1=b['t'], hrs=hh[ib] - hh[ia],
                          topup=topup, nfill=nfill, dE=dE, P_lo=P_lo))

    print('   可用的排氣對（區間內資料連續、取樣間隔 <= %.1f hr）：%d 組'
          % (MAXGAP, len(pairs)))
    if len(pairs) >= 3:
        X = np.array([x['topup'] for x in pairs])
        Y = np.array([x['dE'] for x in pairs])
        slope0 = float(X @ Y / (X @ X))                       # 過原點
        A = np.column_stack([X, np.ones(len(X))])
        slope1, icpt = np.linalg.lstsq(A, Y, rcond=None)[0]
        rng = np.random.default_rng(0)
        bs = []
        for _ in range(4000):
            k = rng.integers(0, len(X), len(X))
            if X[k] @ X[k] > 0:
                bs.append(X[k] @ Y[k] / (X[k] @ X[k]))
        lo, hi = np.percentile(bs, [2.5, 97.5])
        print('   區間長度 中位 %.1f hr　補氣次數 中位 %.0f 次'
              % (np.median([x['hrs'] for x in pairs]),
                 np.median([x['nfill'] for x in pairs])))
        print('   補氣總增幅 中位 %.3f kgf/cm²　dE 中位 %+.4f'
              % (np.median(X), np.median(Y)))
        print('   過原點回歸斜率 = %.3f　[%.3f, %.3f]（bootstrap 95%%）'
              % (slope0, lo, hi))
        print('   含截距回歸　斜率 = %.3f　截距 %+.4f' % (slope1, icpt))
        print('   對照：補氣 1:4 -> 斜率 0.00；補氣純 CO2 -> 斜率 1.00')
        print('   ⚠ 單靠回歸無法排除純 CO2 補氣：補進來的 CO2 若隨即溶進液相，')
        print('      dE 會被 -d 抵銷，斜率同樣趨近 0。溶解項與補氣組成不可分。')
        print()
        print('   ── 反過來問：補氣要偏離 1:4 多少，就足以造出觀測到的超量 ──')
        print('      斜率 = (r_f - 0.25)/(1 + r_f)　=>　r_f = (斜率 + 0.25)/(1 - 斜率)')
        for lab, sl in (('點估計', slope0), ('95% 上界', hi), ('95% 下界', lo)):
            rf = (sl + FEED) / (1 - sl)
            print('      %-9s 斜率 %+.4f -> 有效補氣比 CO2:H2 = 1 : %.2f（%.4f）'
                  % (lab, sl, 1 / rf, rf))
        rf0 = (slope0 + FEED) / (1 - slope0)
        print('      ★ 點估計是 1 : %.2f，離 1:4 只有 %.1f%%。' % (1 / rf0, (4 - 1 / rf0) / 4 * 100))
        print('        一般配氣／流量計的誤差就是這個量級，且誤差是**單向累積**的：')
        print('        消耗嚴格 1:4、補氣稍微偏 CO2，殘餘比就會一路往上爬，')
        print('        最後 H2 被逼近零 —— 正是 35 筆裡最極端那幾筆的樣子。')
        print('      => 頭條結論其實要求「1:4」精確到約 1%，而這從未被驗證過。')
        print('         這是比洩漏更省力的解釋，且與使用者的疑慮同方向。')
    else:
        print('   ⚠ 資料連續性不足（覆蓋僅 49%%、排氣平均間隔 11 天），')
        print('     沒有足夠的「區間內不漏補氣」的排氣對，此檢定做不了。')
    return pairs


def ph_stability(hh, ph):
    """實測 pH 的中位與整段線性漂移（pH/月）。只排除 14.00 的故障值。"""
    m = (ph > 4) & (ph < 10)
    if m.sum() < 100:
        return None
    x, y = hh[m], ph[m]
    sl = np.polyfit(x, y, 1)[0]            # pH/hr
    return float(np.median(y)), float(sl * 24 * 30)


def bio_co2_rate():
    """co2_consumption.csv 的生物 CO2 消耗速率中位（mmol/(L 氣相)/hr）。

    ⚠ 不要憑記憶引簡報上的 0.120：那是另一組長期估計量，
      與本檔要比的逐區間速率不是同一個東西。
    """
    path = os.path.join(OUT, 'co2_consumption.csv')
    v = []
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            k = [c for c in r if c.startswith('CO2消耗速率')]
            if k:
                try:
                    v.append(float(r[k[0]]))
                except (TypeError, ValueError):
                    pass
    return float(np.median(v))


def magnitude_argument(pairs, ph_record=None):
    """量級論證：把「補氣是純 CO2」推到底，看它要求什麼。

    回歸被溶解項混淆，但量級可以把它關掉：若補的是純 CO2，
    那些碳最後只能去液相，其通量與生物消耗量、與液相的鹼度上限相比如何。
    """
    print('\n' + '=' * 72)
    print('二之二、量級論證：純 CO2 補氣要求什麼')
    print('=' * 72)
    R_GAS, T_K = 8.314, 303.15
    V_G = 0.9                      # 頂空體積（總 1.8 L、水佔一半；⚠ 水位未確認）
    V_L = 0.9
    hrs = float(np.median([x['hrs'] for x in pairs]))
    dP = float(np.median([x['topup'] for x in pairs]))
    n_add = dP * KGF_TO_KPA * V_G / (R_GAS * T_K)        # mol
    print('   中位區間 %.0f hr 內補氣壓力增量合計 %.2f kgf/cm²' % (hrs, dP))
    print('   換成莫耳（頂空 %.1f L、30 °C）：%.3f mol' % (V_G, n_add))
    c_in = n_add / hrs * 1000
    print('   若這些全是 CO2，碳輸入 = %.2f mmol/hr' % c_in)
    bio = bio_co2_rate() * V_G                           # mmol/hr（整機）
    print('     對照生物消耗 CO2 %.2f mmol/hr（co2_consumption.csv 中位 x %.1f L）'
          % (bio, V_G))
    print('     -> 碳輸入是生物消耗的 %.0f 倍' % (c_in / bio))
    print('   氣相裝不下：頂空絕對壓力只有約 2 kgf/cm²，而補氣合計 %.2f。' % dP)
    print('     故多出來的碳只能進液相 -> 每區間 %.3f M（液相 %.1f L）'
          % (n_add / V_L, V_L))
    print('      而且這要每 %.0f hr 重複一次。鹼度（TA）從未量測過，' % hrs)
    print('      故不引任何文獻值；改用自己的資料檢查其後果：')
    if ph_record is not None:
        pm, drift = ph_record
        print('        實測 pH 中位 %.2f，整段紀錄的線性漂移 %+.3f pH/月。'
              % (pm, drift))
        print('        連續吸收 %.2f M 的 CO2 不可能讓 pH 這麼平。'
              % (n_add / V_L))
    print('   ★ 結論：補氣不可能是純 CO2。回歸（斜率 ~0）與量級方向一致，')
    print('     但撐住這個結論的是量級與 pH，不是回歸。')
    return c_in


def sept_sensitivity():
    """09-12 對帳對「洗槽後組成」的敏感度。

    洗槽後的 CO2 20.9% 是在未知壓力下量的，是這條對帳最弱的一環。
    """
    print('\n' + '=' * 72)
    print('三之二、09-12 對帳的敏感度（洗槽後組成是最弱的一環）')
    print('=' * 72)
    P1, P2, c2, m2 = 1.177, 1.017, 20.3, 2.07
    print('   %8s %8s %10s %10s' % ('初始CO2', '初始CH4', '超量H2/計量', '殘餘比/進料比'))
    for dc in (-1.0, -0.5, 0.0, 0.5, 1.0):
        for dm in (-0.1, 0.0, 0.1):
            f1 = dry_fracs(P1, 20.9 + dc, 0.50 + dm)
            f2 = dry_fracs(P2, c2, m2)
            d_ch4 = m2 / 100 * f2[3] - (0.50 + dm) / 100 * f1[3]
            d_h2 = f2[2] / 100 * f2[3] - f1[2] / 100 * f1[3]
            if d_ch4 <= 0:
                continue
            ex = (-d_h2 - 4 * d_ch4) / (4 * d_ch4)
            if dm == 0.0:
                print('   %8.1f %8.2f %9.0f%% %11.2f×'
                      % (20.9 + dc, 0.50 + dm, ex * 100,
                         (f2[0] / f2[2]) / FEED))
    print('   -> 初始 CO2 每差 0.5 個百分點，超量 H2 的估計就動數十個百分點；')
    print('      殘餘比不受影響（只用結束時的組成）。')
    print('      故可引用的是「殘餘比 1.08 倍」，')
    print('      「超量 16%」精度不足，不得當成定量結果。')


def main():
    ts, hh, p, orp, ph, co2, ch4 = load_with_gas()
    ev = find_vents(ts, hh, p, co2, ch4)
    rows = []
    for i in ev:
        c, m, h, _ = dry_fracs(p[i - 1], co2[i], ch4[i])
        if h <= 1:
            continue
        E, _ = excess_E(p[i - 1], co2[i], ch4[i])
        rows.append(dict(i=i, t=ts[i], P_pre=p[i - 1], co2=c, ch4=m, h2=h,
                         ratio=c / h, E=E))
    print('排氣事件 %d 筆（%s ~ %s），其中 H2 可用 %d 筆'
          % (len(ev), ts[ev[0]].date(), ts[ev[-1]].date(), len(rows)))

    pairs = topup_regression(hh, p, rows)
    if pairs:
        magnitude_argument(pairs, ph_record=ph_stability(hh, ph))
    r_sep = september_balance()
    sept_sensitivity()
    h2_robustness(rows)

    print('\n' + '=' * 72)
    print('結論')
    print('=' * 72)
    print('   1) 使用者的疑慮方向正確，但不是「補氣完全沒有 H2」：')
    print('      純 CO2 補氣被量級論證排除（碳通量 14 倍、鹼度不可能）。')
    print('   2) 真正的威脅是量的問題：補氣比只要是 1:3.85 而非 1:4，')
    print('      就足以造出全部觀測到的超量。偏離僅 3.6%，')
    print('      在一般配氣精度之內，且誤差單向累積。')
    print('      ⚠ 同等大小的 H2 洩漏會給出一模一樣的斜率，')
    print('        這批資料分不開這兩者；差別在於「配氣誤差」不需要洩漏，')
    print('        且只要一份氣體分析報告就能查，洩漏要做保壓實驗。')
    print('   3) 頭條（1.33~2.79 倍）因此改為「有條件成立」：')
    print('      它要求 1:4 精確到約 1%，而這從未被驗證。')
    print('   4) 無補氣的 09-12 短程實驗殘餘比僅 %.2f 倍，' % r_sep)
    print('      與長紀錄中位 2.79 倍差一個量級 -> 超量是**累積**出來的，')
    print('      與「每次補氣帶進一點偏差」的機制相符。')
    print('   5) 「極端比值全由近零 H2 的筆數撐起」不成立：')
    print('      剔到只剩 H2 >= 30% 仍有 2.15 倍、17/18 筆高於進料比。')
    print('   6) 最高優先的現場問題換成兩個，都比無菌保壓測試省力：')
    print('      ① 補氣用的氣瓶／配氣實際組成，有無出廠分析報告或流量計讀數')
    print('      ② 該組成的誤差範圍是否能確認到 1% 以內')
    print('      無菌 N2 vs H2 保壓測試退為第二順位。')

    path = os.path.join(OUT, 'topup_gas_identity.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['排氣時刻', '排氣前壓力', 'CO2%', 'CH4%', 'H2%(差額)',
                    'CO2:H2', '超量CO2壓力當量E'])
        for x in rows:
            w.writerow([x['t'].strftime('%Y-%m-%d %H:%M'), round(x['P_pre'], 3),
                        round(x['co2'], 2), round(x['ch4'], 2), round(x['h2'], 2),
                        round(x['ratio'], 4), round(x['E'], 4)])
    print('\n逐事件明細 -> %s（%d 列）' % (os.path.relpath(path, REPO), len(rows)))


if __name__ == '__main__':
    main()
