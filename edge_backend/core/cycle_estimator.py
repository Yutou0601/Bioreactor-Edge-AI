
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


class BatchFitter:
    """同一條時間軸 t 上、一次擬合很多條曲線的 Algorithm 1（向量化）。

    用途：模擬（論文檢定的快速模式）與 bootstrap 信賴區間——同一段循環的 t 不變，
    只有 y 換來換去。150 個 k 的設計矩陣與 3x3 正規方程只跟 t 有關，算一次就好；
    每條 y 只剩一次 (m×n)@(n×150) 的矩陣乘法。

    ⚠ 每個 k 預先做 QR（與 fit_le 的 lstsq 同一種數值方法），**不要改回正規方程**。
      2026-10-15 先寫了正規方程版：合成資料 k̂ 207/207 相同，但論文的 242 段真實
      循環有 4 段 k̂ 不同、r̂_b 差到 100%——全是 k̂ 在網格下限 0.01 的段。k 很小時
      e^{-kt} ≈ 1 − kt，與常數項和 t 兩欄幾乎共線，正規方程把條件數平方，精度不夠；
      兩個 k 的殘差差 1e-4，不是平手，是真的算錯。QR 不平方條件數。
    ⚠ y 先減掉平均再算（模型含常數項，殘差平方和不變），進一步減少相減損失。
    ⚠ 一律 float64。GPU 常用的 float32 在這裡會算錯（S(k) 很平，單精度足以改變
      argmin；實測 k̂ 只有 59/207 相同）。
    ⚠ 仍然不是逐位元相同（運算順序不同）。**存進 cycle 表的估計與論文重現一律用
      fit_le**，本類別只給「要很多次」的用途。
    """

    def __init__(self, t, kgrid=None):
        t = np.asarray(t, dtype=float)
        K = KGRID if kgrid is None else np.asarray(kgrid, dtype=float)
        self.t, self.K = t, K
        X = np.empty((len(K), len(t), 3))
        X[:, :, 0] = np.exp(-K[:, None] * t[None, :])
        X[:, :, 1] = t
        X[:, :, 2] = 1.0
        self.Q, self.R = np.linalg.qr(X)                         # (nk,n,3), (nk,3,3)
        # 攤平成 (nk*3, n) 給一次 BLAS 矩陣乘法用；einsum 版本實測慢 15 倍以上
        self.Qf = np.ascontiguousarray(self.Q.transpose(0, 2, 1).reshape(len(K) * 3, len(t)))

    def fit(self, Y):
        """Y：(m, n) 或 (n,)。回傳 dict，每個值是長度 m 的陣列。"""
        Y = np.atleast_2d(np.asarray(Y, dtype=float))
        m = len(Y)
        ym = Y.mean(1, keepdims=True)
        Yc = Y - ym
        QtY = (self.Qf @ Yc.T).T.reshape(m, len(self.K), 3)     # (m, nk, 3)
        sse = (Yc * Yc).sum(1)[:, None] - (QtY * QtY).sum(-1)
        j = sse.argmin(1)
        idx = np.arange(m)
        b = np.linalg.solve(self.R[j], QtY[idx, j][..., None])[..., 0]   # 只解選中的 k
        s = np.maximum(sse[idx, j], 0.0)
        return {'amp': b[:, 0], 'rb': -b[:, 1], 'peq': b[:, 2] + ym[:, 0], 'k': self.K[j],
                'sd': np.sqrt(s / max(len(self.t) - 4, 1))}


def fit_le_batch(t, Y):
    """BatchFitter 的便利寫法：fit_le_batch(t, Y)['rb'] 等。"""
    return BatchFitter(t).fit(Y)


def bootstrap_rb(t, y, n_boot=200, block_min=30, seed=0):
    """r_b 的區塊 bootstrap 信賴區間（給即時監控的「目前循環」用）。

    以 fit_le 的擬合為中心，殘差切成約 block_min 分鐘的區塊重抽（保留自相關——
    實測殘差 lag-1 約 0.26，不是白雜訊，逐點重抽會讓區間窄得不實）。
    回傳 (2.5%, 97.5%) 分位數與 k̂ 落在網格端點的比例。

    ⚠ 這是「同一個模型下的抽樣不確定度」，不含參數簡併的結構性偏誤
      （那由論文 Algorithm 2 處理）。區間窄不代表 r_b 可信。
    """
    t = np.asarray(t, dtype=float); y = np.asarray(y, dtype=float)
    f = fit_le(t, y)
    yhat = f['peq'] + f['amp'] * np.exp(-f['k'] * t) - f['rb'] * t
    r = y - yhat
    n = len(t)
    dt_min = max(np.median(np.diff(t)) * 60.0, 1e-6)
    L = max(2, int(round(block_min / dt_min)))
    nb = int(np.ceil(n / L))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, max(n - L, 1), size=(n_boot, nb))
    idx = (starts[:, :, None] + np.arange(L)[None, None, :]).reshape(n_boot, -1)[:, :n]
    Yb = yhat[None, :] + r[idx]
    g = BatchFitter(t).fit(Yb)
    edge = np.mean((g['k'] <= KGRID[0] + 1e-9) | (g['k'] >= KGRID[-1] - 1e-9))
    lo, hi = np.percentile(g['rb'], [2.5, 97.5])
    return {'rb': f['rb'], 'ci_lo': float(lo), 'ci_hi': float(hi), 'n_boot': n_boot,
            'block_min': block_min, 'k_edge_frac': float(edge)}


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
