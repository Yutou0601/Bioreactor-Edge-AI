
# -*- coding: utf-8 -*-
"""每段下降的統計與化學計量換算（2026-09-11 會議需求）。

⚠ 常駐核心的一部分：只用 numpy 與標準函式庫。全部是閉式計算，
  沒有擬合迴圈、沒有模擬，一批資料跑完不到一秒。

需求（會議筆記）：丟 CSV → 找每段壓力 → 每段的總下降、平均下降速率、斜率。
再由壓降反推「用掉多少 CO2、產生多少 CH4」。

════════════════════════════════════════════════════════════════════════
一、為什麼算式全部走「壓力」而不是「莫耳」

反應式（Sabatier）：

    CO2 + 4 H2 → CH4 + 2 H2O(液)

氣相少掉 5 mol、多出 1 mol（水離開氣相），**淨少 4 mol**。所以在同一個
頭空裡，每產生 1 單位分壓的 CH4，總壓就要掉 4 單位：

    CH4 產量 / 總壓降  ≤  1/4 = 0.25

⚠ 這是**上限不是等號**。壓降還有物理來源（CO2 溶進液相），那會消耗氣體
  卻不產生 CH4。所以比值越接近 0.25，生物佔的份額越高：

    生物份額 = (CH4 產量 / 總壓降) / 0.25

  比值 > 0.25（份額 > 100%）在物理上不可能，代表某個輸入有誤——不要把它
  當成「效率很好」。

**頭空體積在這個比值裡自動消掉**（分子分母是同一個頭空的分壓），所以
算份額不需要知道容器體積。體積只在你要「絕對量」（幾 mL CH4／天）時才需要。

二、CH4 濃度只有排氣瞬間可信

紀錄裡 99.98% 的 CH4 讀數是管路拖尾，不是頭空組成。可用的是**排氣當下**
那個尖峰。會議確認的操作是：在 1.1 kgf/cm² 排掉 0.16，那個排氣量足以把
分析儀沖到讀得出真正的最高值。

⚠ 取樣是一分鐘一筆，排氣過程可能只有幾分鐘——**峰很容易被錯過**。所以
  本模組不自己去猜峰，CH4 濃度由呼叫端明確給進來（量到的那兩個值）。

三、⚠ 10 分鐘視窗量不到東西（實測，不是推測）

感測器的量化階是 0.01 kgf/cm²，而典型下降速率中位數是 0.033 kgf/cm²/hr，
10 分鐘只掉約 0.005。實測 202607至08 那批 46 段下降：

    視窗    中位 ΔP    完全沒有變化的比例
    10 分   0.0000     59%
    30 分   0.0100     37%
    60 分   0.0100     21%
    180 分  0.0600      3%

也就是說 10 分鐘視窗裡有六成**壓力一個數字都沒動**，算出來的斜率是量化
雜訊不是速率。會議上說的「3–4 hr 排一次氣」正好落在量得到的區間。

所以 `window_min` 預設 180。仍然可以指定 10，但每個視窗會帶
`below_quantum` 旗標，低於一個量化階的視窗要當作「量不到」而不是「沒有變化」。
"""
import numpy as np

from core import cycle_estimator as ce

# 大氣壓（kgf/cm²）。錶壓 + 這個 = 絕對壓。會議筆記：1.2 + 1.033 = 2.233
ATM = 1.033

# 感測器量化階（kgf/cm²）。實測相鄰差的最小非零值。
QUANT = 0.01

# 化學計量上限：CO2 + 4H2 → CH4 + 2H2O，氣相淨少 4 mol／產 1 mol CH4
CH4_PER_CONSUMED_MAX = 0.25

# 理想氣體常數與單位換算（只在要算絕對莫耳數時用得到）
R_GAS = 8.314462618            # J/(mol·K)
KGF_CM2_TO_PA = 98066.5        # 1 kgf/cm² = 98066.5 Pa
LITRE_TO_M3 = 1e-3


def _slope(t, y):
    """最小平方斜率與 R²。t 單位小時，回傳 kgf/cm² per hr（下降為正）。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(t) < 3 or t[-1] == t[0]:
        return None, None
    A = np.vstack([t, np.ones_like(t)]).T
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ coef
    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = None if ss_tot <= 0 else 1.0 - ss_res / ss_tot
    return -float(coef[0]), r2          # 取負：下降速率報成正值


def _windows(t, y, window_min):
    """把一段切成固定長度的視窗，各自算下降與斜率。

    ⚠ 低於一個量化階的視窗要標出來。壓力「沒有變化」與「變化量小於感測器
      分辨得出的最小值」是兩回事，混在一起會讓人把量化雜訊當成速率。
    """
    w = float(window_min) / 60.0
    out = []
    base = float(t[0])          # 視窗時間報**段內相對**小時，段的絕對時刻看 ts_start
    t0 = base
    while t0 + w <= float(t[-1]) + 1e-9:
        m = (t >= t0) & (t < t0 + w)
        if m.sum() >= 2:
            yy = y[m]
            drop = float(yy[0] - yy[-1])
            sl, r2 = _slope(t[m], yy)
            out.append({
                'hour_start': round(t0 - base, 3),
                'hour_end': round(t0 + w - base, 3),
                'n': int(m.sum()),
                'drop': round(drop, 4),
                'rate': round(drop / w, 4),
                'slope': None if sl is None else round(sl, 4),
                'r2': None if r2 is None else round(r2, 3),
                # ⚠ True＝這個視窗的變化量在感測器分辨力以下，斜率不可用
                'below_quantum': abs(drop) < QUANT,
            })
        t0 += w
    return out


# 容器總容積（L）。2026-09-11 設備方確認：1.99 L 是**總容積**，不是頭空。
TOTAL_VOLUME_L = 1.99

# 頭空體積（L）。由兩支壓力計反推：閥開時 V_premix·ΔP_premix = V_head·ΔP_reactor，
# 預混槽 V_premix = 1 L。實測 71 次配對事件，中位 1.00 L。
#
# ⚠ 四分位 0.60~2.14，很寬。原因是兩邊的 ΔP 都只有 3~6 個量化階
#   （量化階 0.01 kgf/cm²），比值的相對誤差因此被放大。這個數字只能當
#   「約一半」用，不要當精確值引用。
HEADSPACE_L = 1.00


def moles_from_pressure(dp_kgf_cm2, volume_l, temp_c):
    """由分壓變化換算莫耳數。n = ΔP·V / (R·T)

    ⚠ V 必須是**頭空體積**（氣相），不是容器總容積。
      2026-09-11 確認：容器總容積 1.99 L，而實測頭空約 **1.00 L**
      （液體約佔一半）。**傳總容積進來會讓莫耳數高估約 99%**，也就是差不多
      兩倍，而且不會有任何錯誤訊息。
    ⚠ 這個函式只在要報「絕對量」時才用得到。生物份額那個比值不需要體積
      ——分子分母是同一個頭空的分壓，體積自己消掉。
    """
    if not volume_l or temp_c is None:
        return None
    t_k = float(temp_c) + 273.15
    if t_k <= 0:
        return None
    pa = float(dp_kgf_cm2) * KGF_CM2_TO_PA
    v_m3 = float(volume_l) * LITRE_TO_M3
    return pa * v_m3 / (R_GAS * t_k)


def stoichiometry(total_drop, ch4_start_pct, ch4_end_pct,
                  p_gauge_start, p_gauge_end, volume_l=None, temp_c=None):
    """由壓降與 CH4 濃度變化反推生物份額與 CO2 消耗。

    ch4_*_pct 是**分率**（0~1）還是百分比（0~100）都接受，自動判斷。

    回傳的 `bio_share` 是「壓降裡有多少比例來自產甲烷」。剩下的是物理溶解。
    """
    if None in (ch4_start_pct, ch4_end_pct, p_gauge_start, p_gauge_end):
        return {'status': 'no_ch4', 'reason': 'CH4 濃度或壓力端點缺值'}
    if not total_drop or total_drop <= 0:
        return {'status': 'no_drop', 'reason': '這一段沒有淨下降'}

    f1, f2 = float(ch4_start_pct), float(ch4_end_pct)
    scale = 100.0 if max(f1, f2) > 1.0 else 1.0     # 給的是 % 就換成分率
    f1, f2 = f1 / scale, f2 / scale

    # CH4 分壓 = CH4 分率 × 絕對壓。兩端相減＝這段累積的 CH4（壓力單位）
    ch4_gain = f2 * (float(p_gauge_end) + ATM) - f1 * (float(p_gauge_start) + ATM)
    ratio = ch4_gain / float(total_drop)
    share = ratio / CH4_PER_CONSUMED_MAX

    out = {
        'status': 'ok',
        'ch4_gain_kgf_cm2': round(ch4_gain, 5),
        'ch4_per_consumed': round(ratio, 4),
        'ch4_per_consumed_max': CH4_PER_CONSUMED_MAX,
        'bio_share': round(share, 4),
        # CO2 : CH4 = 1 : 1（CO2 + 4H2 → CH4）。所以用掉的 CO2 就等於產出的 CH4。
        'co2_consumed_kgf_cm2': round(ch4_gain, 5),
        'h2_consumed_kgf_cm2': round(4.0 * ch4_gain, 5),
    }
    # ⚠ 份額落在 [0, 100%] 以外都代表輸入有錯，兩個方向都要擋。
    #   · 超過 100%：不是「效率好」，是超過化學計量上限，物理上不可能。
    #   · 負值：CH4 分壓變低了。產甲烷只會讓 CH4 累積，不會讓它減少——
    #     幾乎一定是端點取到的是管路拖尾而不是排氣尖峰。實測整批資料直接
    #     用段落端點時大多是負的，所以這個守門不是理論上的顧慮。
    if share > 1.0:
        out['status'] = 'implausible'
        out['warning'] = ('生物份額 %.0f%% 超過化學計量上限（%.2f）。物理上不可能——'
                          '請檢查 CH4 濃度是否取自排氣尖峰、壓力端點是否對應同一段。'
                          % (share * 100, CH4_PER_CONSUMED_MAX))
    elif ch4_gain < 0:
        out['status'] = 'implausible'
        out['warning'] = ('CH4 分壓不升反降（%.5f kgf/cm²），份額算出 %.0f%%。'
                          '產甲烷不會讓 CH4 減少——這一段的端點 CH4 讀數幾乎確定是'
                          '管路拖尾而不是排氣尖峰，數值不可引用。'
                          % (ch4_gain, share * 100))
    if volume_l and temp_c is not None:
        out['ch4_mol'] = moles_from_pressure(ch4_gain, volume_l, temp_c)
        out['co2_mol'] = out['ch4_mol']
        out['consumed_mol'] = moles_from_pressure(total_drop, volume_l, temp_c)
        out['volume_l'] = volume_l
        out['note_volume'] = ('莫耳數用的是 %.2f L；份額與比值不需要體積'
                              '（分子分母同一個頭空，體積自己消掉）。' % volume_l)
        # ⚠ 最容易犯的錯：把容器總容積當頭空傳進來。實測頭空只有總容積的
        #   一半，傳錯莫耳數就是兩倍，而且看起來完全正常。
        if abs(volume_l - TOTAL_VOLUME_L) < 0.05:
            out['volume_warning'] = (
                '⚠ %.2f L 是容器**總容積**，不是頭空。實測頭空約 %.2f L'
                '（液體約佔一半），用總容積會讓莫耳數高估約 %.0f%%。'
                % (volume_l, HEADSPACE_L, (TOTAL_VOLUME_L / HEADSPACE_L - 1) * 100))
    return out


def analyze(ts, hours, pressure, window_min=180, temps=None,
            ch4_pct=None, volume_l=None):
    """主入口：切段 → 每段統計 → 視窗斜率 →（有 CH4 就）化學計量。

    ts       每筆的 datetime
    hours    以第一筆為 0 的小時數
    pressure 反應器錶壓 kgf/cm²
    ch4_pct  每筆的 CH4 濃度（可省略）。只在段落端點取值——
             ⚠ 中間的讀數是管路拖尾，不是頭空組成。
    """
    hours = np.asarray(hours, dtype=float)
    pressure = np.asarray(pressure, dtype=float)
    segs = ce.segment(hours, pressure)

    rows = []
    for a, b in segs:
        t = hours[a:b + 1]
        y = pressure[a:b + 1]
        dur = float(t[-1] - t[0])
        drop = float(y[0] - y[-1])
        sl, r2 = _slope(t, y)
        row = {
            'ts_start': ts[a].isoformat(sep=' '),
            'ts_end': ts[b].isoformat(sep=' '),
            'duration_hr': round(dur, 3),
            'n_samples': int(b - a + 1),
            'p_start': round(float(y[0]), 3),
            'p_end': round(float(y[-1]), 3),
            'p_start_abs': round(float(y[0]) + ATM, 3),
            'p_end_abs': round(float(y[-1]) + ATM, 3),
            'total_drop': round(drop, 4),
            'mean_rate': round(drop / dur, 4) if dur > 0 else None,
            'slope': None if sl is None else round(sl, 4),
            'r2': None if r2 is None else round(r2, 3),
            'windows': _windows(t, y, window_min),
        }
        if temps is not None:
            seg_t = [x for x in temps[a:b + 1] if x is not None]
            row['temp_mean'] = round(float(np.mean(seg_t)), 2) if seg_t else None
        if ch4_pct is not None:
            row['ch4_start_pct'] = ch4_pct[a]
            row['ch4_end_pct'] = ch4_pct[b]
            row['stoichiometry'] = stoichiometry(
                drop, ch4_pct[a], ch4_pct[b], y[0], y[-1],
                volume_l=volume_l, temp_c=row.get('temp_mean'))
        rows.append(row)

    return {'window_min': window_min, 'quantum': QUANT,
            'n_segments': len(rows), 'segments': rows,
            'coverage': coverage(ts),
            'summary': summarize(rows, window_min)}


def coverage(ts, expected_per_day=1440):
    """逐日資料覆蓋率。現場是一分鐘一筆，所以一天應有 1440 筆。

    ⚠ 為什麼要回報這個：記錄中斷不會讓分析報錯。切段邏輯遇到斷點會強制
      切開（GAP_HR），所以時長不會算錯——但**使用者看不出那一天其實只有
      三分之一的資料**，會把「因為沒資料所以沒有段」誤讀成「那天沒有反應」。
      實測 2026-08-31 只有 540/1440 筆（38%），現場照片註明「數據混亂」。
    """
    from collections import Counter
    per_day = Counter(t.date() for t in ts)
    days = sorted(per_day)
    rows = [{'date': str(d), 'n': per_day[d],
             'coverage': round(per_day[d] / expected_per_day, 3)}
            for d in days]
    low = [r for r in rows if r['coverage'] < 0.9]
    out = {'n_days': len(days), 'per_day': rows, 'n_days_incomplete': len(low)}
    if low:
        out['incomplete'] = low
        out['note'] = ('⚠ 有 %d 天資料不完整（覆蓋率 < 90%%）：%s。'
                       '記錄中斷不會讓分析報錯，但那幾天的段數會偏少——'
                       '不要把「沒有段」讀成「沒有反應」。'
                       % (len(low), '、'.join('%s %.0f%%' % (r['date'],
                                                            r['coverage'] * 100)
                                              for r in low[:6])))
    return out


def summarize(rows, window_min):
    """整批的匯總，以及「這個視窗量得到嗎」的誠實回報。"""
    if not rows:
        return {'n_segments': 0}
    drops = np.array([r['total_drop'] for r in rows], dtype=float)
    rates = np.array([r['mean_rate'] for r in rows
                      if r['mean_rate'] is not None], dtype=float)
    durs = np.array([r['duration_hr'] for r in rows], dtype=float)
    wins = [w for r in rows for w in r['windows']]
    n_blind = sum(1 for w in wins if w['below_quantum'])

    out = {
        'n_segments': len(rows),
        'total_drop_sum': round(float(drops.sum()), 4),
        'total_drop_median': round(float(np.median(drops)), 4),
        'mean_rate_median': round(float(np.median(rates)), 4) if len(rates) else None,
        'duration_hr_median': round(float(np.median(durs)), 2),
        'n_windows': len(wins),
        'n_windows_below_quantum': n_blind,
    }
    if wins:
        frac = n_blind / len(wins)
        out['frac_windows_below_quantum'] = round(frac, 3)
        # ⚠ 這句要顯示出來。視窗選得太短時，畫面上會出現一堆「斜率 0」，
        #   看起來像「反應停了」，其實是感測器分辨不出來。
        if frac > 0.5:
            out['window_verdict'] = (
                '⚠ %d 分鐘視窗有 %.0f%% 低於感測器分辨力（量化階 %.2f kgf/cm²），'
                '這些視窗的斜率是量化雜訊不是速率。建議改用 180 分鐘。'
                % (window_min, frac * 100, QUANT))
        elif frac > 0.2:
            out['window_verdict'] = (
                '%d 分鐘視窗有 %.0f%% 低於分辨力，勉強可看趨勢，不宜逐窗解讀。'
                % (window_min, frac * 100))
        else:
            out['window_verdict'] = (
                '%d 分鐘視窗只有 %.0f%% 低於分辨力，逐窗數值可用。'
                % (window_min, frac * 100))
    return out


# ══════════════════════════════════════════════════════════════════
# 排氣錨點之間的轉換量（會議：「長時間轉換排氣知道濃度，排完才知道剩多少」）
# ══════════════════════════════════════════════════════════════════
# ⚠ 為什麼要另外做一套，不能直接用段落端點：
#   段落端點的 CH4 幾乎一定是管路拖尾。實測 202607至08 那批直接用端點，
#   **46 段全部**算出負的生物份額（CH4 分壓不升反降），物理上不可能。
#   可用的錨點只有排氣當下那個尖峰——整批 33 天只有 5 個，落在段內的只有
#   2 段（4%）。CH4 讀數中位數 0.55%，尖峰是 14.6~50.1%，差兩個數量級。
#
#   這就是「自動化不太穩定」的量化原因，也是為什麼會議決定改成 3–4 小時
#   排一次氣：**排氣次數變多，錨點才夠**。目前的資料撐不起逐段歸因。


def find_vent_anchors(ch4_pct, prominence=None, distance=None):
    """找 CH4 尖峰＝可用的濃度錨點。回傳索引。

    ⚠ 用 core.ch4_realtime 的偵測器，不要另寫一套。那支已經與 scipy 的
      find_peaks 逐點比對過（真實資料 338 檔＋隨機 4000 組零不一致），
      而且參數與 CH4 面板共用——兩邊用不同的峰會讓數字對不起來。
    """
    from core import ch4_realtime as c4
    arr = np.array([float(v) if v is not None else 0.0 for v in ch4_pct])
    return c4.find_peaks_np(
        arr,
        c4.VENT_PROMINENCE if prominence is None else prominence,
        c4.VENT_MIN_DISTANCE if distance is None else distance).tolist()


def vent_intervals(ts, hours, pressure, ch4_pct, segments=None,
                   prominence=None, volume_l=None, temps=None):
    """相鄰兩個排氣錨點之間：轉換掉多少氣體、其中多少是生物的。

    「消耗量」用**該區間內各下降段的壓降總和**，不是 p_start − p_end。
    ⚠ 這個差別很重要：區間中間有補氣，壓力會跳回去。直接用頭尾相減會把
      補氣進來的氣體算成沒被消耗，消耗量嚴重低估、生物份額因此虛高。
    """
    hours = np.asarray(hours, dtype=float)
    pressure = np.asarray(pressure, dtype=float)
    if segments is None:
        segments = ce.segment(hours, pressure)
    anchors = find_vent_anchors(ch4_pct, prominence=prominence)

    out = []
    for i in range(len(anchors) - 1):
        a, b = anchors[i], anchors[i + 1]
        if b <= a:
            continue
        # 區間內各下降段的壓降總和（只算落在區間內的部分）
        consumed = 0.0
        n_seg = 0
        for s, e in segments:
            lo, hi = max(s, a), min(e, b)
            if hi - lo < 2:
                continue
            d = float(pressure[lo] - pressure[hi])
            if d > 0:
                consumed += d
                n_seg += 1
        dur = float(hours[b] - hours[a])
        f1 = float(ch4_pct[a] or 0.0)
        f2 = float(ch4_pct[b] or 0.0)
        temp_c = None
        if temps is not None:
            seg_t = [x for x in temps[a:b + 1] if x is not None]
            temp_c = float(np.mean(seg_t)) if seg_t else None
        row = {
            'ts_start': ts[a].isoformat(sep=' '),
            'ts_end': ts[b].isoformat(sep=' '),
            'duration_hr': round(dur, 2),
            'n_descents': n_seg,
            'ch4_start_pct': round(f1, 3),
            'ch4_end_pct': round(f2, 3),
            'p_start': round(float(pressure[a]), 3),
            'p_end': round(float(pressure[b]), 3),
            'consumed_kgf_cm2': round(consumed, 4),
            'consumed_rate': round(consumed / dur, 4) if dur > 0 else None,
            'temp_mean': round(temp_c, 2) if temp_c is not None else None,
        }
        row['stoichiometry'] = stoichiometry(
            consumed, f1, f2, float(pressure[a]), float(pressure[b]),
            volume_l=volume_l, temp_c=temp_c)
        out.append(row)

    usable = sum(1 for r in out
                 if (r['stoichiometry'] or {}).get('status') == 'ok')
    return {
        'n_anchors': len(anchors),
        'n_intervals': len(out),
        'n_usable': usable,
        'intervals': out,
        # ⚠ 這句要一起回。錨點太少時逐區間的數字沒有代表性，而畫面上
        #   看不出來——它只會顯示「幾筆結果」，不會顯示「只有幾筆」。
        'coverage_note': (
            '整段資料只偵測到 %d 個排氣錨點，可組成 %d 個區間、其中 %d 個'
            '通過化學計量檢查。CH4 濃度只有排氣瞬間可信，而取樣是一分鐘一筆，'
            '峰很容易被錯過——錨點數就是這個分析的樣本數。'
            % (len(anchors), len(out), usable)),
    }
