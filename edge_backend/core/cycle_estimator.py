
# -*- coding: utf-8 -*-
"""循環切分與速率估計——論文 Algorithm 1 的線上實作。

⚠ 這支是**常駐核心**的一部分，只准 import numpy 與標準函式庫。
  不得 import pandas / scipy / sklearn / torch。詳見
  docs/system/系統重構架構_2026-08-31.md：核心的記憶體預算是 60 MB，
  而 pandas 一個就 62 MB。

⚠ 常數與演算法逐字對齊離線腳本，否則搬過來的數字不能與論文對照：

    KGRID     simulator_check.py:41    np.arange(0.01, 3.001, 0.02)
    CURV_MIN  degeneracy_matched.py:46 0.45
    QUANT     simulator_check.py:40    0.01
    切段門檻   clean_and_form.py:56     P[i] - valley > 0.03
    MIN_HR    clean_and_form.py:45     4.0
    MIN_AMP   clean_and_form.py:45     0.10
    SKIP_MIN  clean_and_form.py:43     3 分鐘
    自由度     simulator_check.py:57    sd = sqrt(SSE / (n-4))

  改動任何一個都必須同步改離線腳本，並重跑 verify_estimator 比對。
"""
import numpy as np

# ── 與離線腳本共用的常數（勿單方面修改）──────────────────────
KGRID = np.arange(0.01, 3.001, 0.02)     # 150 個 k 網格點
CURV_MIN = 0.45                          # 曲率預篩門檻 c*
QUANT = 0.01                             # 感測器量化階 kg/cm^2
REFILL_RISE = 0.03                       # 高於跑動最小值多少視為補氣
MIN_HR = 4.0                             # 段長下限（小時）
MIN_AMP = 0.10                           # 段落差下限 kg/cm^2
SKIP_MIN = 3.0 / 60                      # 掐掉每段開頭幾小時（＝3 分鐘）
GAP_HR = 1.0                             # 取樣中斷超過此值即強制切段
WASH_PER_DAY = 6                         # 每日起始次數超過此值視為洗管線


def segment(hours, pressure):
    """切出每一段下降。回傳 [(起, 迄)] 的索引對。

    補氣在單一取樣間隔內就把壓力抬高遠超過 REFILL_RISE，所以一個門檻
    就分得開補氣與雜訊，不需要任何變點偵測。
    """
    h = np.asarray(hours, dtype=float)
    p = np.asarray(pressure, dtype=float)
    out, valley, start = [], p[0], 0
    for i in range(1, len(p)):
        if h[i] - h[i - 1] > GAP_HR:            # 取樣中斷
            if h[i - 1] - h[start] > MIN_HR:
                out.append((start, i - 1))
            start, valley = i, p[i]
            continue
        if p[i] - valley > REFILL_RISE:         # 補氣
            if h[i - 1] - h[start] > MIN_HR:
                out.append((start, i - 1))
            start, valley = i, p[i]
        elif p[i] < valley:
            valley = p[i]
    if h[-1] - h[start] > MIN_HR:
        out.append((start, len(p) - 1))
    return [(a, b) for a, b in out
            if h[b] - h[a] >= MIN_HR and p[a] - p[b] >= MIN_AMP]


def curvature(t, y):
    """正規化中點曲率：只看形狀，與模型無關。

    c 接近 0 表示這段幾乎是直線——直線上 A·e^{-kt} 與 -r_b·t 完全可以
    互換，任何擬合都分不開它們，所以在擬合之前就要擋掉。
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    amp = y[0] - y[-1]
    if amp <= 0:
        return float('nan')
    tn = (t - t[0]) / (t[-1] - t[0])
    return float(np.interp(0.5, tn, (y[0] - y) / amp))


def fit_le(t, y):
    """Profiled least squares：P(t) = P_eq + A e^{-kt} - r_b t。

    模型只在 k 上非線性；k 固定之後對 (A, r_b, P_eq) 是線性的。因此
    掃過 k 的網格、每格解一次 3x3 最小平方，取殘差最小者即可——
    網格是窮舉的，所以回報的極小值在該網格上是全域的，不必猜起始值。
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    best = None
    for k in KGRID:
        A = np.vstack([np.exp(-k * t), t, np.ones_like(t)]).T
        c, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y - A @ c
        s = float(r @ r)
        if best is None or s < best[0]:
            best = (s, c, k, r)
    s, c, k, r = best
    return {
        'amp': float(c[0]),
        'rb': float(-c[1]),            # 線性項帶負號進模型，故取負
        'peq': float(c[2]),
        'k': float(k),
        'sd': float(np.sqrt(s / max(len(t) - 4, 1))),
    }


def estimate_cycle(hours, pressure):
    """對一段下降做完整的 Algorithm 1。

    回傳 dict；未通過曲率預篩者 screened=False 且不含擬合結果——
    論文的立場是「沒有估計勝過一個無意義的估計」。
    """
    t = np.asarray(hours, dtype=float)
    y = np.asarray(pressure, dtype=float)
    t = t - t[0]
    sel = t >= SKIP_MIN                     # 掐掉補氣本身那幾分鐘
    if sel.sum() < 20:
        return None
    t, y = t[sel] - t[sel][0], y[sel]

    cv = curvature(t, y)
    row = {
        'n_samples': int(len(t)),
        'duration_hr': float(t[-1]),
        'amplitude': float(y[0] - y[-1]),
        'curvature': None if not np.isfinite(cv) else float(cv),
        'screened': bool(np.isfinite(cv) and cv >= CURV_MIN),
    }
    if not row['screened']:
        return row
    row.update(fit_le(t, y))
    return row


def apply_calibration(rb_hat, calib):
    """套用離線校準：r_b = r̂_b x (1 + correction)。

    correction 由 Algorithm 2 的配對校準反解而來（目前 -0.048），
    存在 calibration.json 裡。**校準的計算永遠不在這台機器上跑。**
    """
    if rb_hat is None or calib is None:
        return None
    return float(rb_hat * (1.0 + float(calib.get('correction', 0.0))))
