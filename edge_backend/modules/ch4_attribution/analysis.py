
# -*- coding: utf-8 -*-
"""CH4 峰值模型的特徵歸因：XGBoost + TreeSHAP，沒裝 xgboost 就退回 GA+Ridge。

⚠ 這段程式碼原本住在 `core/ch4_realtime.py`——也就是**常駐核心**裡，而且是用
  背景執行緒跑的。執行緒不是子行程：只要有人開過一次 CH4 面板，xgboost 就
  永久留在常駐行程裡。實測 `import xgboost` 單獨就 **+119.5 MB**，而
  `xgboost>=2.0.0` 列在 requirements.txt，照流程裝的機器一定有它。
  也就是說常駐核心會從 65.5 MB 變成約 185 MB，而預算是 60 MB。

  2026-09-10 搬成模組。切法沿用 r_b 那一套（架構文件 §5）：
    · **閉式、numpy 就能算的留在核心**，保持即時 —— CH4 峰值預測仍是
      每次請求現算，沒有變成每小時。
    · **重相依、跑得慢的進模組**，產出一個小結果（選中的特徵清單 +
      重要度），核心讀它。就像 Algorithm 2 產出 calibration.json，
      核心只是乘一個數字。

⚠ 這裡是**獨立子行程**，所以 import xgboost 不影響常駐核心。跑完就結束，
  記憶體由作業系統整個收回。

⚠ 例外說明：本檔會 import `core.ch4_realtime` 取 `_Ridge`、`_loo_rmse`、
  `FEATURE_NAMES`。模組契約說「不得依賴核心」，這裡刻意破例，理由是：
    · 那三樣是**模型本身的定義**。複製一份到模組，等於讓「歸因用的模型」
      和「預測用的模型」變成兩份會各自漂移的程式碼——而歸因選出來的特徵
      是要拿回去給核心擬合的，兩邊模型不一致不會報錯，只會靜默給出對不上
      的結果。
    · `core/ch4_realtime.py` 只 import typing 與 numpy，沒有副作用，
      所以這個 import 不會把任何東西拖進來（何況這是另一個行程）。
  真正重要的那個方向沒有被破壞：**核心從不 import 模組**（system_test
  第 10 組會靜態檢查）。
"""
import os
import sys
from typing import Optional

import numpy as np

# core/ 在 edge_backend/ 底下；本檔在 edge_backend/modules/ch4_attribution/
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from core.ch4_realtime import _Ridge, _loo_rmse, FEATURE_NAMES   # noqa: E402


# ── GA 特徵選擇（目標：最小化 LOO-CV RMSE）───────────────
GA_POP, GA_GEN, GA_MUT, GA_ELITE = 24, 25, 0.12, 2


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
# 部署現實：監控電腦的常駐預算是 60 MB，xgboost 光磁碟就 97 MB，所以不列為
# 必要相依。裝了就用它做更好的特徵歸因（非線性、原生 TreeSHAP），沒裝自動
# 退回 GA+Ridge。（2026-09-01 之前這裡寫的理由是「後端在 Jetson」，Jetson 已退場。）
def _xgb():
    try:
        import xgboost as xgb
        return xgb
    except Exception:
        return None


def _xgb_loo_rmse(xgb, X, y, params, rounds, max_folds: int = 12) -> float:
    """交叉驗證 RMSE（XGBoost 版）。小樣本用留一；樣本較多時只抽 max_folds 折，
    避免 LOO 的 O(n) 次 XGBoost 訓練隨排氣次數線性成長、拖慢即時端點。"""
    n = len(y)
    idx = np.arange(n)
    if n > max_folds:                     # 均勻抽樣固定折數，成本封頂
        idx = np.linspace(0, n - 1, max_folds).round().astype(int)
    errs = []
    for i in idx:
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


def attribute(X: np.ndarray, y: np.ndarray) -> dict:
    """算特徵歸因。有 xgboost 就用它，沒有或失敗就退回 GA+Ridge。

    ⚠ 回傳的 `selected` 會被核心拿去決定用哪些欄位擬合預測模型，所以它
      不只是「說明用的重要度」——它會改變預測值。選錯特徵不會報錯。
    """
    xgb = _xgb()
    if xgb is not None:
        try:
            return feature_analysis_xgb(xgb, X, y)
        except Exception:
            pass          # xgboost 失敗（罕見）→ 退回 GA+Ridge

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

    return {
        "method":        "ga_ridge",
        "selected":      [FEATURE_NAMES[i] for i in np.where(mask)[0]],
        "n_selected":    int(mask.sum()),
        "n_total":       len(FEATURE_NAMES),
        "rmse_selected": round(rmse_sel, 3) if rmse_sel is not None else None,
        "rmse_all":      round(rmse_all, 3) if rmse_all is not None else None,
        "ga_history":    [round(h, 3) for h in hist],
        "importances":   imp,
    }
