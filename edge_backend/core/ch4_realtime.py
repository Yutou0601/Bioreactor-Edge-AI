"""
CH4 峰值即時預測
================
把 ch4_peak_analysis.py 的 cycle-level 方法搬到線上：從記憶體中的 sensor_records
即時萃取特徵、即時訓練、對「進行中的週期」預測排氣時的 CH4 峰值。

**為什麼要特別小心**（務必連同結果一起呈現，不可只給數字）：
  - 特徵端可信：ORP / 反應槽壓力 / pH 皆為逐分鐘連續且可信的訊號。
  - **目標端不可信**：CH4 濃度僅在排氣瞬間短暫有效，其餘 99.98% 為取樣管路
    的延遲拖尾；且排氣為人工操作、感測器每分鐘才記一筆，很可能錯過真實峰值。
  - 樣本數極少：歷史上完整排氣週期僅個位數，遠低於穩定建模所需（≥30）。

因此本模組一律回報 n_train / cv_rmse / reliability，並在樣本不足時
**回傳 status="insufficient" 且不給預測值**——寧可不顯示，也不給一個看起來
很篤定、實際上沒有統計基礎的數字。這是刻意的設計，不是尚未完成。
"""

from typing import Optional

import numpy as np

MIN_TRAIN_CYCLES = 3        # 低於此完全不預測
RELIABLE_CYCLES = 30        # 達到此才視為「可用」（沿用 2026-07-16 日報的判準）
EARLY_CYCLE_RATIO = 0.85    # 進度低於此不給預測值：特徵強烈依賴週期長度，等同外插
VENT_PROMINENCE = 10.0      # CH4 峰值判定的最小突起（%）
VENT_MIN_DISTANCE = 60      # 兩次排氣至少相隔幾分鐘


def _ema(x: np.ndarray, alpha: float) -> np.ndarray:
    out = np.empty_like(x, dtype=float)
    acc = x[0]
    for i, v in enumerate(x):
        acc = alpha * v + (1 - alpha) * acc
        out[i] = acc
    return out


def _orp_features(orp: np.ndarray):
    """與 ch4_peak_analysis.compute_orp_features 相同定義（EMA10 / 斜率 / MACD）。"""
    ema10 = _ema(orp, 2 / 11)
    ema5 = _ema(orp, 2 / 6)
    ema30 = _ema(orp, 2 / 31)
    slope = np.zeros(len(orp))
    if len(orp) > 5:
        slope[5:] = (ema10[5:] - ema10[:-5]) / 5
    return ema10, slope, ema5 - ema30


def _phase_labels(slope: np.ndarray) -> np.ndarray:
    """自適應相位：以週期內斜率的 μ±0.5σ 為界，並濾掉過短的雜訊段。"""
    n = len(slope)
    if n < 10:
        return np.full(n, 2, dtype=int)
    w = min(60, n)
    kernel = np.ones(w) / w
    sm = np.convolve(slope, kernel, mode="same")
    mu, sigma = float(sm.mean()), float(sm.std()) + 1e-9
    lo, hi = mu - 0.5 * sigma, mu + 0.5 * sigma
    lab = np.where(sm < lo, 1, np.where(sm > hi, 3, 2)).astype(int)

    min_dur = min(30, max(1, n // 10))
    i = 0
    while i < n:
        j = i
        while j < n and lab[j] == lab[i]:
            j += 1
        if (j - i) < min_dur and i > 0:
            lab[i:j] = lab[i - 1]
        i = j
    return lab


FEATURE_NAMES = [
    "cycle_length_min", "phase2_duration_min", "phase2_fraction",
    "phase1_mean_slope", "phase2_orp_mean", "phase2_orp_std",
    "phase2_macd_mean", "orp_drop_magnitude", "phase3_onset_fraction",
    "pressure_mean", "ph_mean",
]


def extract_features(seg: list) -> Optional[dict]:
    """從一段記錄萃取 cycle-level 特徵。與離線版同定義，便於兩邊比對。"""
    if len(seg) < 10:
        return None
    orp = np.array([float(r.get("orp") or 0.0) for r in seg])
    pressure = np.array([float(r.get("pressure") or 0.0) for r in seg])
    ph = np.array([float(r.get("ph") or 0.0) for r in seg])

    ema10, slope, macd = _orp_features(orp)
    lab = _phase_labels(slope)
    p1, p2, p3 = lab == 1, lab == 2, lab == 3
    n = len(seg)
    p3_idx = np.where(p3)[0]

    return {
        "cycle_length_min":      float(n),
        "phase2_duration_min":   float(p2.sum()),
        "phase2_fraction":       float(p2.sum()) / max(n, 1),
        "phase1_mean_slope":     float(slope[p1].mean()) if p1.any() else 0.0,
        "phase2_orp_mean":       float(ema10[p2].mean()) if p2.any() else float(ema10.mean()),
        "phase2_orp_std":        float(ema10[p2].std()) if p2.sum() > 1 else 0.0,
        "phase2_macd_mean":      float(macd[p2].mean()) if p2.any() else 0.0,
        "orp_drop_magnitude":    float(ema10[0] - ema10.min()),
        "phase3_onset_fraction": float(p3_idx[0] / n) if len(p3_idx) else 1.0,
        "pressure_mean":         float(pressure.mean()),
        "ph_mean":               float(ph.mean()),
    }


# ── 尖峰偵測（純 numpy，取代 scipy.signal.find_peaks）──────────────
# ⚠ 這裡刻意不用 scipy。`from scipy.signal import find_peaks` 雖然寫在函式
#   裡（延遲載入），但 detect_vents 在**即時請求路徑**上——只要有人開過一次
#   CH4 面板，scipy 就永久留在常駐行程裡。實測 numpy 之後再加 scipy.signal
#   是 **+69.6 MB**，比整個 60 MB 預算還大。Python 不卸載模組，延遲 import
#   只是把付款時間往後挪。
#
# ⚠ 這是行為必須**逐位元相同**的替換，不是「差不多的實作」。驗證方式：
#   · 真實資料 338 個 CSV、55 個峰 → 與 scipy 完全一致
#   · 隨機差分測試 4000 組訊號、83372 個峰（含平台、全平訊號、邊界）→ 零不一致
#   system_test 第 12 組會在有裝 scipy 的機器上重跑這個比對。


def _local_maxima(x):
    """局部極大值的索引。平台（連續相等）取中點，與 scipy 的 _local_maxima_1d 一致。"""
    n = len(x)
    out = []
    i = 1
    i_max = n - 1
    while i < i_max:
        if x[i - 1] < x[i]:
            i_ahead = i + 1
            while i_ahead < i_max and x[i_ahead] == x[i]:
                i_ahead += 1
            if x[i_ahead] < x[i]:                 # 兩側都比它低才算峰
                out.append((i + i_ahead - 1) // 2)  # 平台取中點（向下取整）
                i = i_ahead
        i += 1
    return np.asarray(out, dtype=int)


def _prominences(x, peaks):
    """地形突出度。與 scipy.signal.peak_prominences（wlen=None）同演算法。"""
    out = np.empty(len(peaks), dtype=float)
    n = len(x)
    for k, pk in enumerate(peaks):
        h = x[pk]
        i = pk
        left_min = h
        while i >= 0 and x[i] <= h:
            if x[i] < left_min:
                left_min = x[i]
            i -= 1
        i = pk
        right_min = h
        while i < n and x[i] <= h:
            if x[i] < right_min:
                right_min = x[i]
            i += 1
        out[k] = h - max(left_min, right_min)
    return out


def _select_by_distance(peaks, priority, distance):
    """距離篩選。與 scipy 的 _select_by_peak_distance 一致：
    依 priority 由高到低保留，並把距離內的其他峰剔除。"""
    n = len(peaks)
    keep = np.ones(n, dtype=bool)
    order = np.argsort(priority)[::-1]        # 高的先選
    for j in order:
        if not keep[j]:
            continue
        k = j - 1
        while k >= 0 and peaks[j] - peaks[k] < distance:
            keep[k] = False
            k -= 1
        k = j + 1
        while k < n and peaks[k] - peaks[j] < distance:
            keep[k] = False
            k += 1
    return keep


def find_peaks_np(x, prominence, distance):
    """find_peaks(x, prominence=..., distance=...) 的純 numpy 版。

    ⚠ 篩選順序必須是「先距離、後突出度」——scipy 就是這個順序，反過來會
      得到不同的峰集合，而且不會報錯。
    """
    x = np.asarray(x, dtype=float)
    peaks = _local_maxima(x)
    if len(peaks) == 0:
        return peaks
    if distance is not None and distance > 1:
        peaks = peaks[_select_by_distance(peaks, x[peaks], distance)]
    if prominence is not None and len(peaks):
        peaks = peaks[_prominences(x, peaks) >= prominence]
    return peaks


def detect_vents(recs: list) -> list:
    """以 CH4 濃度的尖峰判定排氣事件。

    這是少數 CH4 讀數**可以**使用的場合：排氣瞬間的尖峰正是那 0.025% 的有效值，
    其餘時間的拖尾不會形成突起，find_peaks 天然會略過。
    """
    ch4 = np.array([float(r.get("ch4_pct") or 0.0) for r in recs])
    if len(ch4) < VENT_MIN_DISTANCE:
        return []
    return find_peaks_np(ch4, VENT_PROMINENCE, VENT_MIN_DISTANCE).tolist()


def build_training_set(recs: list):
    """以排氣事件切出已完成的週期，取「該週期特徵 → 該次排氣 CH4 峰值」為樣本。"""
    vents = detect_vents(recs)
    X, y, meta = [], [], []
    prev = 0
    for vi in vents:
        seg = recs[prev:vi + 1]
        feats = extract_features(seg)
        if feats is not None:
            X.append([feats[k] for k in FEATURE_NAMES])
            y.append(float(recs[vi].get("ch4_pct") or 0.0))
            meta.append({"vent_time": recs[vi].get("timestamp", "")[:16],
                         "actual_peak": round(y[-1], 2)})
        prev = vi + 1
    return (np.array(X, dtype=float) if X else np.empty((0, len(FEATURE_NAMES))),
            np.array(y, dtype=float), meta, vents)


class _Ridge:
    """標準化 + Ridge 迴歸的閉式解，純 numpy 實作。

    刻意不依賴 sklearn：本模組是選配的分析功能，不應讓後端多背一個重依賴，
    且實測 sklearn 在部分機器會因系統政策擋住編譯後的 DLL 而無法載入
    （Jetson 的科學計算環境也特殊）。Ridge 閉式解本身就是幾行線性代數。
    """

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha

    def fit(self, X: np.ndarray, y: np.ndarray):
        self.mu = X.mean(axis=0)
        self.sd = X.std(axis=0)
        self.sd[self.sd < 1e-12] = 1.0        # 零變異特徵：標準化後恆為 0，不影響解
        Z = (X - self.mu) / self.sd
        self.y_mean = float(y.mean())
        yc = y - self.y_mean
        d = Z.shape[1]
        # β = (ZᵀZ + αI)⁻¹ Zᵀy；截距由 y 置中吸收，故不對截距做正則化
        self.beta = np.linalg.solve(Z.T @ Z + self.alpha * np.eye(d), Z.T @ yc)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return ((X - self.mu) / self.sd) @ self.beta + self.y_mean


def _loo_rmse(X: np.ndarray, y: np.ndarray) -> Optional[float]:
    """留一交叉驗證 RMSE。樣本極少時這是唯一還說得過去的估計方式。"""
    n = len(y)
    if n < 3 or X.shape[1] == 0:
        return None
    errs = []
    for i in range(n):
        m = np.ones(n, dtype=bool)
        m[i] = False
        if len(np.unique(y[m])) < 2:
            continue
        try:
            pred = _Ridge().fit(X[m], y[m]).predict(X[~m])[0]
        except np.linalg.LinAlgError:
            continue
        errs.append((pred - y[i]) ** 2)
    return float(np.sqrt(np.mean(errs))) if errs else None


def predict(recs: list, selected=None) -> dict:
    """對「進行中（最後一次排氣之後）」的週期預測其排氣時的 CH4 峰值。

    `selected`：要拿哪些特徵擬合。由呼叫端從 ch4_attribution 模組最近一次的
    結果取得；傳 None 就用全部特徵。

    ⚠ 特徵歸因（XGBoost + TreeSHAP，或退回 GA 搜尋）**不在這裡算**。它原本
      是在常駐行程裡開背景執行緒跑的，而執行緒不是子行程——只要有人開過一次
      CH4 面板，xgboost 就永久留在常駐核心裡（實測單獨 +119.5 MB，而預算是
      60 MB）。2026-09-10 搬成 modules/ch4_attribution/ 的短命子行程。

      切法沿用 r_b 那一套：閉式、numpy 就能算的留在核心保持**即時**，重相依
      的進模組產出一個小結果。所以這支預測仍然是每次請求現算，沒有變成每小時。
    """
    out = {
        "status":        "insufficient",
        "n_train":       0,
        "predicted_peak": None,
        "cv_rmse":       None,
        "reliability":   "",
        "current_phase": None,
        "features":      None,
        "history":       [],
        "cycle_progress": None,
        "too_early":     False,
        "feature_selection": None,
        "caveat":        "CH4 為參考級訊號（排氣瞬間外皆為管路拖尾），"
                         "預測僅供操作參考，不作為證據。",
    }
    if len(recs) < 30:
        out["reliability"] = "資料不足，無法預測"
        return out

    X, y, meta, vents = build_training_set(recs)
    out["n_train"] = len(y)

    # 進行中的週期＝最後一次排氣之後的資料
    cur_seg = recs[vents[-1] + 1:] if vents else recs
    cur = extract_features(cur_seg)
    if cur:
        out["features"] = {k: round(v, 4) for k, v in cur.items()}
        lab = _phase_labels(_orp_features(
            np.array([float(r.get("orp") or 0.0) for r in cur_seg]))[1])
        out["current_phase"] = int(lab[-1]) if len(lab) else None

    if len(y) < MIN_TRAIN_CYCLES:
        out["reliability"] = (f"已完成週期 {len(y)} 個，少於 {MIN_TRAIN_CYCLES} 個，"
                              f"不提供預測值")
        return out
    if cur is None:
        out["reliability"] = "目前週期資料過短，尚無法預測"
        return out

    # ⚠ 訓練集指紋要回報出去。歸因是模組排程算的，可能落後於目前的訓練集；
    #   呼叫端拿它和模組結果裡的指紋比對，就知道這次用的選擇是不是舊的。
    out["training_fingerprint"] = f"{len(y)}|{meta[-1]['vent_time'] if meta else ''}"

    # 預測用歸因選中的子集——特徵選擇的意義就在於用它來建模。
    # ⚠ 「用全部特徵」與「用選中的子集」會給出**不同的預測值**，所以
    #   n_features_used 也要回報，否則看的人分不出眼前這個數字是哪一種。
    try:
        cols = ([FEATURE_NAMES.index(f) for f in selected]
                if selected else list(range(len(FEATURE_NAMES))))
    except ValueError as e:
        # 模組給的特徵名核心不認得（兩邊版本不一致）→ 退回全部特徵。
        # 靜默錯配比退回更糟：那會拿錯的欄位去擬合，而且不會報錯。
        out["feature_note"] = "歸因結果的特徵名對不上，已改用全部特徵：%s" % e
        cols = list(range(len(FEATURE_NAMES)))
    out["n_features_used"] = len(cols)

    try:
        model = _Ridge().fit(X[:, cols], y)
        pred = float(model.predict(np.array([[cur[FEATURE_NAMES[i]] for i in cols]]))[0])
    except np.linalg.LinAlgError:
        out["reliability"] = "特徵矩陣退化（樣本間變異不足），無法求解"
        return out

    rmse = _loo_rmse(X[:, cols], y)
    out["cv_rmse"] = round(rmse, 2) if rmse is not None else None

    # ── 週期進度：部分特徵（週期長度、Phase2 時長）會隨週期進行才長大，
    # 進行中的週期在這些維度上遠小於訓練樣本，模型等同在特徵空間外**外插**。
    # 實測進度 4% 時預測值可達 703%（CH4 濃度物理上不可能超過 100%）。
    train_len = float(np.median(X[:, FEATURE_NAMES.index("cycle_length_min")]))
    progress = len(cur_seg) / train_len if train_len > 0 else 0.0
    out["cycle_progress"] = round(min(progress, 1.5), 2)

    # ── 外插防護：落在物理範圍外或遠離訓練值域的預測一律不顯示。
    # 加警語仍顯示 320% 這種數字比不顯示更糟——看的人會先看到數字才看到警語。
    band = 2.0 * (rmse if rmse else 5.0)
    lo = max(0.0, float(y.min()) - band)
    hi = min(100.0, float(y.max()) + band)
    if not (lo <= pred <= hi):
        out["status"] = "unreliable"
        out["reliability"] = (
            f"預測值 {pred:.0f}% 落在合理範圍 {lo:.0f}~{hi:.0f}% 之外，判定為外插，不予顯示"
            + (f"（本週期才進行 {progress:.0%}）" if progress < 1.0 else ""))
        return out
    if progress < EARLY_CYCLE_RATIO:
        out["status"] = "too_early"
        out["too_early"] = True
        out["reliability"] = (f"本週期才進行 {progress:.0%}"
                              f"（需 ≥{EARLY_CYCLE_RATIO:.0%} 才有參考價值），暫不提供預測值")
        return out

    out["status"] = "ok"
    out["predicted_peak"] = round(pred, 2)
    if len(y) < RELIABLE_CYCLES:
        out["reliability"] = (f"⚠ 參考級：樣本僅 {len(y)} 週期"
                              f"（穩定建模需 ≥{RELIABLE_CYCLES}），不確定性高")
    else:
        out["reliability"] = f"樣本 {len(y)} 週期，達穩定建模門檻"

    # 樣本內配適值供對照——不是樣本外效能，僅用來看模型有沒有抓到趨勢
    fitted = model.predict(X[:, cols])
    out["history"] = [{**m, "fitted": round(float(f), 2)} for m, f in zip(meta, fitted)]
    return out
