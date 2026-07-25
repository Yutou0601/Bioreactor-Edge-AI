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


def detect_vents(recs: list) -> list:
    """以 CH4 濃度的尖峰判定排氣事件。

    這是少數 CH4 讀數**可以**使用的場合：排氣瞬間的尖峰正是那 0.025% 的有效值，
    其餘時間的拖尾不會形成突起，find_peaks 天然會略過。
    """
    ch4 = np.array([float(r.get("ch4_pct") or 0.0) for r in recs])
    if len(ch4) < VENT_MIN_DISTANCE:
        return []
    try:
        from scipy.signal import find_peaks
        idx, _ = find_peaks(ch4, prominence=VENT_PROMINENCE, distance=VENT_MIN_DISTANCE)
        return idx.tolist()
    except ImportError:
        return []


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


# ── GA 特徵選擇（目標：最小化 LOO-CV RMSE）───────────────
GA_POP, GA_GEN, GA_MUT, GA_ELITE = 24, 25, 0.12, 2
_ga_cache: dict = {}          # 以訓練集指紋為 key，避免每次輪詢都重跑


def _ga_select(X: np.ndarray, y: np.ndarray, seed: int = 42):
    """基因演算法挑特徵子集，適應度＝該子集的 LOO-CV RMSE（越小越好）。

    與 ch4_peak_analysis.ga_feature_selection 同一套目標函式，差別只在此處為
    線上即時計算、且用純 numpy 的 Ridge。加入子集大小的輕微懲罰，避免在
    小樣本下靠塞入更多特徵來壓低 LOO-CV（過度配適的常見表現）。
    """
    rng = np.random.default_rng(seed)
    d = X.shape[1]

    def fitness(mask: np.ndarray) -> float:
        if not mask.any():
            return 1e9
        r = _loo_rmse(X[:, mask], y)
        if r is None:
            return 1e9
        return r + 0.02 * mask.sum()          # 簡約性懲罰

    pop = rng.random((GA_POP, d)) < 0.5
    pop[0] = np.ones(d, dtype=bool)           # 全特徵基準也放進族群
    scores = np.array([fitness(m) for m in pop])
    history = [float(scores.min())]

    for _ in range(GA_GEN):
        order = np.argsort(scores)
        new = [pop[i].copy() for i in order[:GA_ELITE]]     # 菁英保留
        while len(new) < GA_POP:
            # 錦標賽選擇
            a, b = rng.integers(0, GA_POP, 2)
            p1 = pop[a] if scores[a] < scores[b] else pop[b]
            a, b = rng.integers(0, GA_POP, 2)
            p2 = pop[a] if scores[a] < scores[b] else pop[b]
            pt = rng.integers(1, d) if d > 1 else 1
            child = np.concatenate([p1[:pt], p2[pt:]])
            flip = rng.random(d) < GA_MUT
            child = np.where(flip, ~child, child)
            new.append(child)
        pop = np.array(new)
        scores = np.array([fitness(m) for m in pop])
        history.append(float(scores.min()))

    best = pop[int(np.argmin(scores))]
    if not best.any():
        best = np.ones(d, dtype=bool)
    return best, _loo_rmse(X[:, best], y), history


# ── XGBoost + TreeSHAP 特徵歸因（有裝 xgboost 才走，否則自動退回 GA+Ridge）──
# 部署現實：後端在 Jetson（ARM/資源受限），不強制安裝 xgboost。開發機/監控 PC
# 裝了就用它做更好的特徵歸因（處理非線性、原生 TreeSHAP），Jetson 沒裝也照跑。
def _xgb():
    try:
        import xgboost as xgb
        return xgb
    except Exception:
        return None


def _xgb_loo_rmse(xgb, X, y, params, rounds) -> float:
    """留一交叉驗證 RMSE（XGBoost 版）。小樣本下唯一誠實的樣本外估計。"""
    n = len(y)
    errs = []
    for i in range(n):
        m = np.ones(n, dtype=bool); m[i] = False
        if len(np.unique(y[m])) < 2:
            continue
        bst = xgb.train(params, xgb.DMatrix(X[m], label=y[m]), num_boost_round=rounds)
        pred = float(bst.predict(xgb.DMatrix(X[i:i+1]))[0])
        errs.append((pred - y[i]) ** 2)
    return float(np.sqrt(np.mean(errs))) if errs else None


def feature_analysis_xgb(xgb, X: np.ndarray, y: np.ndarray) -> dict:
    """訓練（強正則化的）XGBoost，用內建 TreeSHAP 算每特徵平均|SHAP|當重要度。
    小樣本（~27 循環）極易過擬合，故：淺樹 max_depth=2、少量 round、強 min_child_weight、
    子抽樣，並以 LOO-CV RMSE 據實回報樣本外誤差、不看漂亮的訓練內配適。"""
    params = {"max_depth": 2, "eta": 0.15, "min_child_weight": 3.0,
              "subsample": 0.8, "colsample_bytree": 0.8, "lambda": 1.0,
              "objective": "reg:squarederror", "seed": 42, "verbosity": 0}
    rounds = 40
    dall = xgb.DMatrix(X, label=y)
    bst = xgb.train(params, dall, num_boost_round=rounds)

    # 內建 TreeSHAP：每列每特徵的貢獻（最後一欄是基準值），平均|SHAP|＝重要度，
    # 平均帶符號 SHAP 與特徵值的相關方向＝推高(+)/壓低(−)
    contribs = bst.predict(dall, pred_contribs=True)[:, :len(FEATURE_NAMES)]
    mean_abs = np.abs(contribs).mean(axis=0)
    total = float(mean_abs.sum()) or 1.0
    imp = []
    for i, name in enumerate(FEATURE_NAMES):
        if mean_abs[i] <= 1e-9:
            continue
        # 方向：SHAP 值與該特徵值的相關符號（正=特徵越大越推高 CH4）
        col = X[:, i]
        sign = 1.0
        if np.std(col) > 1e-9 and np.std(contribs[:, i]) > 1e-9:
            sign = float(np.sign(np.corrcoef(col, contribs[:, i])[0, 1]) or 1.0)
        imp.append({"feature": name, "coef": round(sign * float(mean_abs[i]), 4),
                    "weight": round(float(mean_abs[i]) / total, 4)})
    imp.sort(key=lambda d: -d["weight"])

    rmse = _xgb_loo_rmse(xgb, X, y, params, rounds)
    selected = [d["feature"] for d in imp if d["weight"] >= 0.05]   # 佔比≥5% 視為有貢獻
    return {
        "method":        "xgboost_shap",
        "selected":      selected or [imp[0]["feature"]] if imp else [],
        "n_selected":    len(selected),
        "n_total":       len(FEATURE_NAMES),
        "rmse_selected": round(rmse, 3) if rmse is not None else None,
        "rmse_all":      round(rmse, 3) if rmse is not None else None,
        "importances":   imp,
        "cached":        False,
    }


def feature_analysis(X: np.ndarray, y: np.ndarray, fingerprint: str) -> dict:
    """特徵歸因，依訓練集指紋快取（每 15 秒輪詢不重算，只有新排氣週期進來才算）。
    有 xgboost → XGBoost+TreeSHAP；否則退回 GA 選特徵 + Ridge 係數重要度。"""
    if fingerprint in _ga_cache:
        return {**_ga_cache[fingerprint], "cached": True}

    xgb = _xgb()
    if xgb is not None:
        try:
            res = feature_analysis_xgb(xgb, X, y)
            _ga_cache.clear()
            _ga_cache[fingerprint] = res
            return res
        except Exception:
            pass          # xgboost 失敗（罕見）→ 退回 GA+Ridge，不讓分析中斷

    mask, rmse_sel, hist = _ga_select(X, y)
    rmse_all = _loo_rmse(X, y)

    # 特徵已標準化，故 |係數| 可直接互相比較，作為重要度
    model = _Ridge().fit(X[:, mask], y)
    coefs = model.beta
    total = float(np.abs(coefs).sum()) or 1.0
    imp = sorted(
        [{"feature": FEATURE_NAMES[i], "coef": round(float(c), 4),
          "weight": round(float(abs(c)) / total, 4)}
         for i, c in zip(np.where(mask)[0], coefs)],
        key=lambda d: -d["weight"])

    res = {
        "method":        "ga_ridge",
        "selected":      [FEATURE_NAMES[i] for i in np.where(mask)[0]],
        "n_selected":    int(mask.sum()),
        "n_total":       len(FEATURE_NAMES),
        "rmse_selected": round(rmse_sel, 3) if rmse_sel is not None else None,
        "rmse_all":      round(rmse_all, 3) if rmse_all is not None else None,
        "ga_history":    [round(h, 3) for h in hist],
        "importances":   imp,
        "cached":        False,
    }
    _ga_cache.clear()          # 只留最新一份，避免長期執行累積
    _ga_cache[fingerprint] = res
    return res


def predict(recs: list) -> dict:
    """對「進行中（最後一次排氣之後）」的週期預測其排氣時的 CH4 峰值。"""
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

    # GA 選特徵 + Ridge 重要度（即時計算，依訓練集指紋快取）
    fp = f"{len(y)}|{meta[-1]['vent_time'] if meta else ''}"
    try:
        fa = feature_analysis(X, y, fp)
        out["feature_selection"] = fa
    except Exception as e:
        out["feature_selection"] = {"error": f"{type(e).__name__}: {e}"}
        fa = None

    # 預測改用 GA 選中的子集——特徵選擇的意義就在於用它來建模
    try:
        cols = ([FEATURE_NAMES.index(f) for f in fa["selected"]]
                if fa and fa.get("selected") else list(range(len(FEATURE_NAMES))))
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
