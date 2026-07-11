"""
CH4 排氣峰值預測分析
====================
提供兩種粒度的分析（--granularity cycle|minute|both）：

  cycle-level（baseline，沿用既有方法論）：
    1. 資料載入與時間索引建立
    2. 排氣事件偵測 (scipy.signal.find_peaks)
    3. 自適應 ORP 相位偵測 (Phase 1 / 2 / 3)  ← 週期內相對閾值，應對條件變動
    4. 週期級特徵萃取 (Cycle-level Features)，每週期一筆樣本（CH4 峰值）
    5. 特徵選擇 (GA，目標：LOO-CV RMSE on CH4 peak)
    6. Ridge Regression + Random Forest 建模比較
    7. 特徵重要性輸出 + 視覺化 (儲存至 reports/cycle_level/)

  minute-level（每分鐘連續記錄，ICEA 2026 投稿新增）：
    1. 沿用同一批資料，改以每分鐘為樣本單位（CH4 濃度本身即逐分鐘量測，
       不再只取每週期一個峰值），樣本數可從個位數暴增至數千筆
    2. ORP EMA/斜率/MACD 改以「連續區段」為單位計算，避免週期邊界處的 EMA 冷啟動失真
    3. 交叉驗證改用 GroupKFold（依週期分組）+ 時序 holdout，取代樣本量小時才適用、
       在大樣本下有分布偏誤疑慮的 LOO-CV
    4. 額外自動跑一組消融實驗電池（排除時間特徵 / 純 ORP / 排除 ORP 的基準 /
       最小感測器組合 / 納入 CH4 落後值），逐一拆解哪些訊號真的在解釋 CH4
    5. 結果輸出為 JSON + predictions CSV（而非僅 PNG），供監控 PC / Jetson 雙邊比較用

統計限制說明（cycle-level）：
  目前資料含 6 個完整排氣週期，樣本量極小。
  模型結果用於說明方法論與特徵重要性分析；
  實務預測穩定性需累積 ≥ 30 個週期的資料。
"""

import os
import sys
import json
import platform
import argparse
import warnings
import random
from datetime import datetime
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.signal import find_peaks
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import GroupKFold, TimeSeriesSplit
from sklearn.metrics import mean_squared_error

warnings.filterwarnings('ignore')
random.seed(42)
np.random.seed(42)

REPORT_DIR = os.path.join(os.path.dirname(__file__), 'reports')
CYCLE_REPORT_DIR = os.path.join(REPORT_DIR, 'cycle_level')
MINUTE_REPORT_DIR = os.path.join(REPORT_DIR, 'minute_level')
os.makedirs(CYCLE_REPORT_DIR, exist_ok=True)
os.makedirs(MINUTE_REPORT_DIR, exist_ok=True)

# ─────────────────────────────────────────────────
# 1. 資料載入
# ─────────────────────────────────────────────────

def load_data(data_dir="data/*.csv"):
    sys.path.insert(0, os.path.dirname(__file__))
    from data_pipeline.loader import load_all_data
    df = load_all_data(data_dir)
    df['timestamp'] = pd.to_datetime(
        df['年'].astype(int).astype(str).str.zfill(4) + '-' +
        df['月'].astype(int).astype(str).str.zfill(2) + '-' +
        df['日'].astype(int).astype(str).str.zfill(2) + ' ' +
        df['時'].astype(int).astype(str).str.zfill(2) + ':' +
        df['分'].astype(int).astype(str).str.zfill(2)
    )
    df = df.reset_index(drop=True)
    return df

# ─────────────────────────────────────────────────
# 2. 排氣事件偵測
# ─────────────────────────────────────────────────

def detect_vent_events(ch4: np.ndarray, prominence=10, min_distance=60):
    """
    偵測 CH4 局部極大值作為排氣事件。
    prominence : 峰值需高出周圍基線的最小 %
    min_distance: 兩次排氣之間的最短間隔（分鐘）
    """
    peaks, props = find_peaks(ch4, prominence=prominence, distance=min_distance)
    return peaks, props

# ─────────────────────────────────────────────────
# 3. ORP 特徵序列計算
# ─────────────────────────────────────────────────

def _ema(values: np.ndarray, alpha: float) -> np.ndarray:
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def compute_orp_features(orp_raw: np.ndarray):
    """
    回傳三組特徵序列：
      ema10   — EMA(10)，主平滑曲線
      slope   — (ema10[t] - ema10[t-5]) / 5  (mV/min)
      macd    — EMA(5) - EMA(30)
    """
    n      = len(orp_raw)
    ema10  = _ema(orp_raw, 2 / 11)
    ema5   = _ema(orp_raw, 2 / 6)
    ema30  = _ema(orp_raw, 2 / 31)

    slope       = np.zeros(n)
    slope[5:]   = (ema10[5:] - ema10[:-5]) / 5
    macd        = ema5 - ema30

    return ema10, slope, macd

# ─────────────────────────────────────────────────
# 4. 自適應相位偵測（週期內相對閾值）
# ─────────────────────────────────────────────────

def detect_phases(slope: np.ndarray, k: float = 0.5,
                  smooth_window: int = 60,
                  min_duration: int = 30):
    """
    以週期內 slope 的統計量作為自適應閾值。

    修正：
      1. smooth_window — 對原始斜率做滾動平均，消除分鐘級雜訊，
                         保留小時級生物相位趨勢（預設 60 min）
      2. min_duration  — Debounce：相位切換後需連續維持 N 分鐘才接受，
                         防止短暫越界觸發偽切換（預設 30 min）

    Phase 1 (底物利用期) : smoothed_slope < μ - k*σ
    Phase 2 (產甲烷活躍期): μ - k*σ ≤ smoothed_slope ≤ μ + k*σ
    Phase 3 (底物耗盡期) : smoothed_slope > μ + k*σ
    """
    # Step 1：滾動平均平滑斜率
    s = pd.Series(slope)
    smoothed = s.rolling(window=smooth_window, center=True,
                         min_periods=1).mean().values

    mu    = np.mean(smoothed)
    sigma = np.std(smoothed) + 1e-9
    lo    = mu - k * sigma
    hi    = mu + k * sigma

    raw_labels = np.where(smoothed < lo, 1,
                 np.where(smoothed > hi, 3, 2)).astype(int)

    # Step 2：Debounce — 短於 min_duration 的相位片段還原成前一相位
    labels = raw_labels.copy()
    n = len(labels)
    i = 0
    while i < n:
        current_phase = labels[i]
        j = i
        while j < n and labels[j] == current_phase:
            j += 1
        segment_len = j - i
        if segment_len < min_duration and i > 0:
            labels[i:j] = labels[i - 1]  # 回填為前一相位
        i = j

    return labels, (mu, sigma, lo, hi)

# ─────────────────────────────────────────────────
# 5. 週期級特徵萃取（cycle-level，baseline）
# ─────────────────────────────────────────────────

FEATURE_NAMES = [
    'cycle_length_min',       # 週期總長（分鐘）
    'phase2_duration_min',    # Phase 2 持續時間（分鐘）
    'phase2_fraction',        # Phase 2 佔週期比例
    'phase1_mean_slope',      # Phase 1 平均斜率 (mV/min)
    'phase2_orp_mean',        # Phase 2 ORP 均值 (mV)
    'phase2_orp_std',         # Phase 2 ORP 標準差（穩定度）
    'phase2_macd_mean',       # Phase 2 MACD 均值（動能）
    'orp_drop_magnitude',     # Phase 1 ORP 下降幅度（起始 - 最低值）
    'phase3_onset_fraction',  # Phase 3 開始位置（佔週期比例）
    'pressure_mean',          # 週期平均壓力
    'ph_mean',                # 週期平均 pH
    # temp_mean 排除：實驗恆溫 30°C，所有週期方差為零，
    # StandardScaler 後為全零列，對模型無貢獻且污染 GA 搜索空間。
]


def extract_cycle_features(cycle_df: pd.DataFrame) -> dict:
    """
    從一個完整週期的資料萃取 cycle-level 特徵。
    cycle_df 需含欄位：ORP (mV), 酸鹼值 (pH), 溫度 (°C), 反應器壓力 (kg/cm²)
    """
    orp_raw  = cycle_df['ORP (mV)'].values.astype(float)
    pressure = cycle_df['反應器壓力 (kg/cm²)'].values.astype(float)
    ph       = cycle_df['酸鹼值 (pH)'].values.astype(float)
    temp     = cycle_df['溫度 (°C)'].values.astype(float)
    n        = len(orp_raw)

    ema10, slope, macd = compute_orp_features(orp_raw)
    phase_labels, (mu, sigma, lo, hi) = detect_phases(slope)

    p1_mask = phase_labels == 1
    p2_mask = phase_labels == 2
    p3_mask = phase_labels == 3

    phase2_dur  = int(p2_mask.sum())
    phase3_idx  = np.where(p3_mask)[0]
    phase3_onset = (phase3_idx[0] / n) if len(phase3_idx) > 0 else 1.0

    feats = {
        'cycle_length_min':      n,
        'phase2_duration_min':   phase2_dur,
        'phase2_fraction':       phase2_dur / max(n, 1),
        'phase1_mean_slope':     float(slope[p1_mask].mean()) if p1_mask.any() else 0.0,
        'phase2_orp_mean':       float(ema10[p2_mask].mean()) if p2_mask.any() else float(ema10.mean()),
        'phase2_orp_std':        float(ema10[p2_mask].std())  if p2_mask.sum() > 1 else 0.0,
        'phase2_macd_mean':      float(macd[p2_mask].mean())  if p2_mask.any() else 0.0,
        'orp_drop_magnitude':    float(ema10[0] - ema10.min()),
        'phase3_onset_fraction': float(phase3_onset),
        'pressure_mean':         float(pressure.mean()),
        'ph_mean':               float(ph.mean()),
        'temp_mean':             float(temp.mean()),
    }
    return feats, phase_labels

# ─────────────────────────────────────────────────
# 6. GA 特徵選擇 + 交叉驗證
# ─────────────────────────────────────────────────

def loo_cv_rmse(X: np.ndarray, y: np.ndarray, model_fn) -> float:
    """Leave-One-Out Cross-Validation RMSE（樣本少時唯一可靠的評估方式，cycle-level 專用）"""
    n = len(y)
    preds = np.empty(n)
    for i in range(n):
        tr_idx = [j for j in range(n) if j != i]
        X_tr, y_tr = X[tr_idx], y[tr_idx]
        X_te = X[[i]]
        mdl = model_fn()
        mdl.fit(X_tr, y_tr)
        preds[i] = mdl.predict(X_te)[0]
    return float(np.sqrt(mean_squared_error(y, preds)))


def grouped_cv_rmse(X: np.ndarray, y: np.ndarray, groups: np.ndarray,
                     model_fn, n_splits: int = 10) -> float:
    """GroupKFold RMSE：整個週期（cycle_id）一起分進同一折，避免相鄰分鐘互相洩漏。
    每分鐘管線的 GA 適應度函式與模型評估都使用這個，取代樣本量暴增後不再適用的 LOO-CV。
    """
    n_groups = len(np.unique(groups))
    n_splits = max(2, min(n_splits, n_groups))
    gkf = GroupKFold(n_splits=n_splits)
    preds = np.empty(len(y))
    for tr_idx, te_idx in gkf.split(X, y, groups):
        mdl = model_fn()
        mdl.fit(X[tr_idx], y[tr_idx])
        preds[te_idx] = mdl.predict(X[te_idx])
    return float(np.sqrt(mean_squared_error(y, preds)))


def chronological_holdout_rmse(X: np.ndarray, y: np.ndarray, day_index: np.ndarray,
                                model_fn, n_splits: int = 5):
    """依日期做 TimeSeriesSplit，回傳最後一折（最近期天數）的 holdout RMSE。
    回應 Austin et al. (2025) 對 LOO-CV／隨機 CV 在小樣本、正則化模型下分布偏誤的疑慮，
    額外提供「訓練用較早的資料、驗證用較晚的資料」這個更貼近實務部署情境的穩健性指標。
    天數不足以切出至少 2 折時回傳 None。
    """
    unique_days = np.unique(day_index)
    max_splits = len(unique_days) - 1
    if max_splits < 2:
        return None
    n_splits = max(2, min(n_splits, max_splits))
    tscv = TimeSeriesSplit(n_splits=n_splits)
    day_order = {d: i for i, d in enumerate(unique_days)}
    day_pos = np.array([day_order[d] for d in day_index])

    last_rmse = None
    for tr_days_idx, te_days_idx in tscv.split(unique_days):
        tr_mask = np.isin(day_pos, tr_days_idx)
        te_mask = np.isin(day_pos, te_days_idx)
        if tr_mask.sum() == 0 or te_mask.sum() == 0:
            continue
        mdl = model_fn()
        mdl.fit(X[tr_mask], y[tr_mask])
        preds = mdl.predict(X[te_mask])
        last_rmse = float(np.sqrt(mean_squared_error(y[te_mask], preds)))
    return last_rmse


def ga_feature_selection(X: np.ndarray, y: np.ndarray,
                          feature_names: list,
                          pop_size: int = 20,
                          n_gen: int = 40,
                          cx_prob: float = 0.7,
                          mut_prob: float = 0.15,
                          evaluate_fn=None):
    """
    以 GA 在特徵集合中搜索最佳子集。

    染色體 : 長度 = n_features 的二進制向量，1 = 選用
    適應度 : evaluate_fn(X_selected, y) 的 RMSE（愈小愈好，取負值轉最大化）
             預設為 Ridge + LOO-CV（cycle-level 既有行為，維持不變）；
             每分鐘管線會傳入以 GroupKFold 評估的 evaluate_fn。
    選擇   : Tournament selection (size=3)
    交配   : Single-point crossover
    突變   : Bit-flip mutation
    """
    if evaluate_fn is None:
        evaluate_fn = lambda Xs, ys: loo_cv_rmse(Xs, ys, lambda: Ridge(alpha=1.0))

    n_feat = X.shape[1]

    def fitness(chrom):
        sel = [i for i, c in enumerate(chrom) if c]
        if not sel:
            return float('inf')
        return evaluate_fn(X[:, sel], y)

    # 初始族群
    pop = []
    for _ in range(pop_size):
        while True:
            c = [random.randint(0, 1) for _ in range(n_feat)]
            if any(c):
                break
        pop.append(c)

    best_chrom, best_fit = None, float('inf')
    history = []

    for gen in range(n_gen):
        scores = [fitness(c) for c in pop]
        gen_best = min(scores)
        history.append(gen_best)

        if gen_best < best_fit:
            best_fit   = gen_best
            best_chrom = pop[scores.index(gen_best)][:]

        # Tournament selection
        def tournament():
            candidates = random.sample(range(pop_size), 3)
            return min(candidates, key=lambda i: scores[i])

        new_pop = [best_chrom[:]]   # elitism
        while len(new_pop) < pop_size:
            p1 = pop[tournament()][:]
            p2 = pop[tournament()][:]
            # Crossover
            if random.random() < cx_prob:
                pt = random.randint(1, n_feat - 1)
                c1 = p1[:pt] + p2[pt:]
                c2 = p2[:pt] + p1[pt:]
            else:
                c1, c2 = p1[:], p2[:]
            # Mutation
            for child in [c1, c2]:
                for i in range(n_feat):
                    if random.random() < mut_prob:
                        child[i] = 1 - child[i]
                if not any(child):
                    child[random.randint(0, n_feat - 1)] = 1
            new_pop += [c1, c2]
        pop = new_pop[:pop_size]

    selected = [feature_names[i] for i, c in enumerate(best_chrom) if c]
    selected_idx = [i for i, c in enumerate(best_chrom) if c]

    return {
        'best_chromosome': best_chrom,
        'selected_features': selected,
        'selected_idx': selected_idx,
        'best_rmse': best_fit,
        'history': history,
    }

# ─────────────────────────────────────────────────
# 7. 視覺化
# ─────────────────────────────────────────────────

PHASE_COLORS = {1: '#e74c3c', 2: '#2ecc71', 3: '#e67e22'}
PHASE_LABELS = {1: 'Phase 1 – Substrate Utilization',
                2: 'Phase 2 – Active Methanogenesis',
                3: 'Phase 3 – Substrate Depletion'}


def plot_cycles_overview(df, peaks, peak_ch4, boundaries, out_path):
    """Full-dataset ORP + CH4 + phase-band overview."""
    fig, axes = plt.subplots(3, 1, figsize=(18, 10), sharex=True)
    fig.suptitle('ORP Signal × CH4 Venting Events × Phase Detection Overview',
                 fontsize=13, fontweight='bold')

    t = np.arange(len(df))
    ch4_arr = df['CH4濃度 (%)'].values
    orp_arr  = df['ORP (mV)'].values

    ax0 = axes[0]
    ema10, slope, macd = compute_orp_features(orp_arr)
    ax0.plot(t, orp_arr, color='#aaa', lw=0.4, alpha=0.6, label='ORP Raw')
    ax0.plot(t, ema10,   color='#3498db', lw=1.0, label='ORP EMA(10)')
    ax0.set_ylabel('ORP (mV)', fontsize=9)
    ax0.legend(fontsize=8, loc='upper right')

    ax1 = axes[1]
    ax1.plot(t, ch4_arr, color='#e67e22', lw=0.6, label='CH4 (%)')
    ax1.scatter(peaks, peak_ch4, color='red', zorder=5, s=40, label='Vent Peak')
    for p, v in zip(peaks, peak_ch4):
        ax1.annotate(f'{v:.1f}%', (p, v), textcoords='offset points',
                     xytext=(0, 6), ha='center', fontsize=7, color='red')
    ax1.set_ylabel('CH4 (%)', fontsize=9)
    ax1.legend(fontsize=8, loc='upper right')

    ax2 = axes[2]
    phase_labels, _ = detect_phases(slope)
    for ph in [1, 2, 3]:
        mask = phase_labels == ph
        ax2.fill_between(t, slope.min(), slope.max(),
                         where=mask, alpha=0.18, color=PHASE_COLORS[ph],
                         label=PHASE_LABELS[ph])
    ax2.plot(t, slope, color='#555', lw=0.5)
    ax2.axhline(0, color='#999', lw=0.6, ls='--')
    ax2.set_ylabel('ORP Slope (mV/min)', fontsize=9)
    ax2.set_xlabel('Time Step (min)', fontsize=9)
    ax2.legend(fontsize=8, loc='upper right')

    # 週期分隔線
    for b in boundaries[1:-1]:
        for ax in axes:
            ax.axvline(b, color='#8e44ad', lw=0.8, ls=':', alpha=0.7)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  [圖表] 已儲存 → {out_path}')


def plot_phase_detail(cycle_idx, cycle_df, phase_labels, ch4_peak, out_path):
    """Per-cycle ORP phase detail: raw/EMA, slope with phase bands, MACD."""
    orp    = cycle_df['ORP (mV)'].values.astype(float)
    ema10, slope, macd = compute_orp_features(orp)
    t = np.arange(len(orp))

    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    title = (f'Cycle {cycle_idx + 1}  |  CH4 Peak = {ch4_peak:.1f}%'
             f'  |  Length = {len(orp):,} min')
    fig.suptitle(title, fontsize=11, fontweight='bold')

    ax0 = axes[0]
    for ph in [1, 2, 3]:
        mask = phase_labels == ph
        ax0.fill_between(t, orp.min(), orp.max(),
                         where=mask, alpha=0.15, color=PHASE_COLORS[ph])
    ax0.plot(t, orp,   color='#aaa', lw=0.5, label='ORP Raw')
    ax0.plot(t, ema10, color='#3498db', lw=1.0, label='EMA(10)')
    ax0.set_ylabel('ORP (mV)', fontsize=9)
    ax0.legend(fontsize=8)

    ax1 = axes[1]
    for ph in [1, 2, 3]:
        mask = phase_labels == ph
        ax1.fill_between(t, slope.min(), slope.max(),
                         where=mask, alpha=0.15, color=PHASE_COLORS[ph],
                         label=PHASE_LABELS[ph])
    ax1.plot(t, slope, color='#555', lw=0.6)
    ax1.axhline(0, color='#999', lw=0.6, ls='--')
    ax1.set_ylabel('Slope (mV/min)', fontsize=9)
    ax1.legend(fontsize=8)

    ax2 = axes[2]
    ax2.plot(t, macd, color='#9b59b6', lw=0.8)
    ax2.axhline(0, color='#999', lw=0.6, ls='--')
    ax2.fill_between(t, 0, macd, where=(macd > 0), alpha=0.2, color='#2ecc71')
    ax2.fill_between(t, 0, macd, where=(macd < 0), alpha=0.2, color='#e74c3c')
    ax2.set_ylabel('MACD (mV)', fontsize=9)
    ax2.set_xlabel('Time Step (min)', fontsize=9)

    for ax in axes:
        for ph in [1, 2, 3]:
            mask = phase_labels == ph
            if mask.any():
                cx = int(np.where(mask)[0].mean())
                ax.text(cx, ax.get_ylim()[1] * 0.92, f'P{ph}',
                        ha='center', fontsize=7, color=PHASE_COLORS[ph], alpha=0.7)

    plt.tight_layout()
    plt.savefig(out_path, dpi=130, bbox_inches='tight')
    plt.close()


def plot_feature_importance(feature_names, importances, title, out_path):
    """特徵重要性橫條圖"""
    order = np.argsort(importances)
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = ['#e74c3c' if importances[i] == max(importances) else '#3498db'
              for i in order]
    ax.barh([feature_names[i] for i in order],
            [importances[i] for i in order], color=colors)
    ax.set_xlabel('Importance Score', fontsize=9)
    ax.set_title(title, fontsize=10, fontweight='bold')
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  [圖表] 已儲存 → {out_path}')


def plot_ga_history(history, out_path):
    """GA 搜索過程中每代最佳 RMSE"""
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(history, color='#3498db', lw=1.5)
    ax.set_xlabel('Generation', fontsize=9)
    ax.set_ylabel('Best CV RMSE (%)', fontsize=9)
    ax.set_title('GA Feature Selection – Convergence Curve', fontsize=10, fontweight='bold')
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  [圖表] 已儲存 → {out_path}')


def plot_prediction_vs_actual(y_true, y_pred_ridge, y_pred_rf,
                               cycle_ids, out_path):
    """LOO-CV 預測值 vs 實際值散點圖（cycle-level，樣本少可逐點標註）"""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, preds, title, color in zip(
            axes,
            [y_pred_ridge, y_pred_rf],
            ['Ridge Regression (LOO-CV)', 'Random Forest (LOO-CV)'],
            ['#3498db', '#e67e22']):
        ax.scatter(y_true, preds, color=color, s=80, zorder=3)
        for i, (yt, yp, cid) in enumerate(zip(y_true, preds, cycle_ids)):
            ax.annotate(f'C{cid}', (yt, yp), textcoords='offset points',
                        xytext=(4, 2), fontsize=8)
        lims = [min(y_true.min(), np.array(preds).min()) - 3,
                max(y_true.max(), np.array(preds).max()) + 3]
        ax.plot(lims, lims, 'k--', lw=0.8, alpha=0.5)
        ax.set_xlim(lims); ax.set_ylim(lims)
        ax.set_xlabel('Actual CH4 Peak (%)', fontsize=9)
        ax.set_ylabel('Predicted CH4 Peak (%)', fontsize=9)
        rmse = np.sqrt(mean_squared_error(y_true, preds))
        ax.set_title(f'{title}\nRMSE = {rmse:.2f}%', fontsize=9, fontweight='bold')
        ax.grid(True, alpha=0.25)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  [圖表] 已儲存 → {out_path}')


def plot_prediction_vs_actual_minute(y_true, y_pred_ridge, y_pred_rf, out_path):
    """每分鐘尺度預測 vs 實際值散點圖。樣本數以千計，逐點標註不可讀，改用透明度散點。"""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, preds, title, color in zip(
            axes,
            [y_pred_ridge, y_pred_rf],
            ['Ridge Regression (GroupKFold)', 'Random Forest (GroupKFold)'],
            ['#3498db', '#e67e22']):
        ax.scatter(y_true, preds, color=color, s=6, alpha=0.15, zorder=3, linewidths=0)
        lims = [min(y_true.min(), np.min(preds)) - 3,
                max(y_true.max(), np.max(preds)) + 3]
        ax.plot(lims, lims, 'k--', lw=0.8, alpha=0.5)
        ax.set_xlim(lims); ax.set_ylim(lims)
        ax.set_xlabel('Actual CH4 (%)', fontsize=9)
        ax.set_ylabel('Predicted CH4 (%)', fontsize=9)
        rmse = np.sqrt(mean_squared_error(y_true, preds))
        ax.set_title(f'{title}\nRMSE = {rmse:.2f}%  (n={len(y_true):,})',
                     fontsize=9, fontweight='bold')
        ax.grid(True, alpha=0.25)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  [圖表] 已儲存 → {out_path}')

# ─────────────────────────────────────────────────
# 8. Cycle-level 分析（baseline，既有邏輯原封不動搬進函式）
# ─────────────────────────────────────────────────

def run_cycle_level_analysis(df: pd.DataFrame, out_dir: str):
    SEP = '=' * 60
    print(SEP)
    print('CH4 排氣峰值預測分析（cycle-level baseline）')
    print(SEP)
    print(f'    總筆數: {len(df):,}  欄位: {list(df.columns)}')

    print('\n[2] 偵測排氣事件...')
    ch4_arr = df['CH4濃度 (%)'].values
    peaks, _ = detect_vent_events(ch4_arr, prominence=10, min_distance=60)
    peak_ch4 = ch4_arr[peaks]
    print(f'    偵測到 {len(peaks)} 個排氣事件')
    for i, (idx, v) in enumerate(zip(peaks, peak_ch4)):
        ts = df['timestamp'].iloc[idx]
        print(f'    事件 {i+1}: {ts}  CH4={v:.1f}%')

    boundaries = [0] + list(peaks) + [len(df) - 1]
    n_complete = len(peaks)   # 有已知 CH4 峰值的週期數

    print(f'\n    完整週期數（有已知排氣峰值）: {n_complete}')

    if n_complete < 2:
        print('    ⚠ 週期數不足 2，無法進行 GA/LOO-CV，略過 cycle-level 分析')
        return None

    print(f'    ⚠ 統計限制：{n_complete} 個樣本，所有模型評估使用 LOO-CV')

    # ── 相位偵測 + 特徵萃取 ───────────────────────────
    print('\n[3] 相位偵測 & 週期特徵萃取...')
    feature_records = []

    for i in range(n_complete):
        start, end = boundaries[i], boundaries[i + 1]
        cyc_df = df.iloc[start:end + 1].copy()
        orp_cyc = cyc_df['ORP (mV)'].values.astype(float)
        _, slope_cyc, _ = compute_orp_features(orp_cyc)
        phase_labels, (mu, sigma, lo, hi) = detect_phases(slope_cyc)

        feats, _ = extract_cycle_features(cyc_df)
        feats['ch4_peak'] = peak_ch4[i]
        feature_records.append(feats)

        p2_pct = feats['phase2_fraction'] * 100
        print(f'    週期 {i+1}: 長度={feats["cycle_length_min"]:>6,}min  '
              f'Phase2={feats["phase2_duration_min"]:>5,}min({p2_pct:.1f}%)  '
              f'CH4_peak={feats["ch4_peak"]:.1f}%  '
              f'slope_thresholds=[{lo:.3f}, {hi:.3f}]')

        # 儲存各週期相位詳細圖
        _, slope_full, _ = compute_orp_features(
            df.iloc[start:end + 1]['ORP (mV)'].values.astype(float))
        phase_full, _ = detect_phases(slope_full)
        plot_phase_detail(
            i, df.iloc[start:end + 1],
            phase_full, peak_ch4[i],
            os.path.join(out_dir, f'cycle_{i+1:02d}_phase.png')
        )

    feat_df = pd.DataFrame(feature_records)
    X_all   = feat_df[FEATURE_NAMES].values.astype(float)
    y_all   = feat_df['ch4_peak'].values.astype(float)

    # ── 全資料總覽圖 ──────────────────────────────────
    print('\n[4] 繪製總覽圖...')
    plot_cycles_overview(
        df, peaks, peak_ch4, boundaries,
        os.path.join(out_dir, 'overview.png')
    )

    # ── GA 特徵選擇 ──────────────────────────────────
    print('\n[5] GA 特徵選擇（Ridge LOO-CV）...')
    print(f'    搜索空間: 2^{len(FEATURE_NAMES)} = {2**len(FEATURE_NAMES)} 種組合')
    print(f'    族群大小: 20  |  世代數: 40  |  交配率: 0.7  |  突變率: 0.15')

    scaler_ga = StandardScaler()
    X_scaled  = scaler_ga.fit_transform(X_all)

    ga_result = ga_feature_selection(
        X_scaled, y_all, FEATURE_NAMES,
        pop_size=20, n_gen=40,
    )
    print(f'    Best LOO-CV RMSE: {ga_result["best_rmse"]:.3f}%')
    print(f'    選中特徵 ({len(ga_result["selected_features"])}/{len(FEATURE_NAMES)}):')
    for f in ga_result['selected_features']:
        print(f'      ✓ {f}')

    plot_ga_history(
        ga_result['history'],
        os.path.join(out_dir, 'ga_convergence.png')
    )

    # ── Ridge Regression（全特徵 vs GA 特徵）──────────
    print(f'\n[6] 模型訓練與 LOO-CV 評估...')
    sel_idx   = ga_result['selected_idx']
    X_ga      = X_scaled[:, sel_idx]
    X_full    = X_scaled

    ridge_full_rmse = loo_cv_rmse(X_full, y_all, lambda: Ridge(alpha=1.0))
    ridge_ga_rmse   = loo_cv_rmse(X_ga,   y_all, lambda: Ridge(alpha=1.0))
    rf_full_rmse    = loo_cv_rmse(X_full, y_all,
                                   lambda: RandomForestRegressor(n_estimators=50,
                                                                  random_state=42))
    rf_ga_rmse      = loo_cv_rmse(X_ga, y_all,
                                   lambda: RandomForestRegressor(n_estimators=50,
                                                                  random_state=42))

    print(f'    {"模型":30s}  LOO-CV RMSE')
    print(f'    {"-"*45}')
    print(f'    {"Ridge (全部特徵)":30s}  {ridge_full_rmse:.3f} %')
    print(f'    {"Ridge (GA 選擇特徵)":30s}  {ridge_ga_rmse:.3f} %  ← GA 結果')
    print(f'    {"Random Forest (全部特徵)":30s}  {rf_full_rmse:.3f} %')
    print(f'    {"Random Forest (GA 選擇特徵)":30s}  {rf_ga_rmse:.3f} %')

    # ── 取得 LOO-CV 逐筆預測值（用於繪圖）────────────
    def loo_preds(X, model_fn):
        n, preds = len(y_all), np.empty(len(y_all))
        for i in range(n):
            tr = [j for j in range(n) if j != i]
            m  = model_fn()
            m.fit(X[tr], y_all[tr])
            preds[i] = m.predict(X[[i]])[0]
        return preds

    preds_ridge = loo_preds(X_ga, lambda: Ridge(alpha=1.0))
    preds_rf    = loo_preds(X_ga, lambda: RandomForestRegressor(n_estimators=50,
                                                                  random_state=42))
    plot_prediction_vs_actual(
        y_all, preds_ridge, preds_rf,
        list(range(1, n_complete + 1)),
        os.path.join(out_dir, 'prediction_vs_actual.png')
    )

    # ── Random Forest 特徵重要性 ──────────────────────
    print('\n[7] 特徵重要性分析（Random Forest，全特徵，全資料 fit）...')
    rf_full = RandomForestRegressor(n_estimators=200, random_state=42)
    rf_full.fit(X_full, y_all)
    importances = rf_full.feature_importances_
    ranked = sorted(zip(FEATURE_NAMES, importances), key=lambda x: -x[1])

    print(f'    {"特徵名稱":35s}  重要性')
    print(f'    {"-"*50}')
    for name, imp in ranked:
        bar = '█' * int(imp * 50)
        print(f'    {name:35s}  {imp:.4f}  {bar}')

    plot_feature_importance(
        FEATURE_NAMES, importances,
        'Random Forest Feature Importances (full data fit)',
        os.path.join(out_dir, 'feature_importance.png')
    )

    # ── 相關係數矩陣 ───────────────────────────────────
    print('\n[8] 特徵 × CH4 峰值 相關係數...')
    corr_data = feat_df[FEATURE_NAMES + ['ch4_peak']]
    corr = corr_data.corr()['ch4_peak'].drop('ch4_peak').sort_values(key=abs, ascending=False)
    for feat, r in corr.items():
        direction = '↑' if r > 0 else '↓'
        print(f'    {feat:35s}  r = {r:+.3f}  {direction}')

    # ── 結論摘要 ──────────────────────────────────────
    print(f'\n{SEP}')
    print('分析結論摘要（cycle-level）')
    print(SEP)
    print(f'  排氣事件數        : {n_complete}')
    print(f'  CH4 峰值範圍      : {y_all.min():.1f} ~ {y_all.max():.1f} %')
    print(f'  GA 最佳特徵子集   : {ga_result["selected_features"]}')
    print(f'  Ridge LOO-CV RMSE : {ridge_ga_rmse:.2f} %')
    print(f'  RF    LOO-CV RMSE : {rf_ga_rmse:.2f} %')
    top_feat = ranked[0][0]
    print(f'  最重要特徵 (RF)   : {top_feat}  (importance={ranked[0][1]:.4f})')
    print()
    print('  ⚠ 統計限制說明：')
    print(f'    樣本量 n={n_complete}，LOO-CV 每折僅 {n_complete-1} 筆訓練。')
    print('    目前結果反映方法論的可行性，而非預測精度的最終指標。')
    print('    建議累積 ≥ 30 個排氣週期後重新評估。')
    print()
    print(f'  輸出圖表目錄: {out_dir}/')
    for f in sorted(os.listdir(out_dir)):
        print(f'    - {f}')
    print(SEP)

    return {
        'n_cycles': n_complete,
        'ga_selected_features': ga_result['selected_features'],
        'ridge_ga_loo_rmse': ridge_ga_rmse,
        'rf_ga_loo_rmse': rf_ga_rmse,
        'top_feature': top_feat,
    }

# ─────────────────────────────────────────────────
# 9. Minute-level 每分鐘連續 CH4 迴歸（新增）
# ─────────────────────────────────────────────────

def segment_by_gaps(df: pd.DataFrame, max_gap_minutes: int = 5) -> np.ndarray:
    """依時間斷點（斷線重啟等）把資料切成連續區段，回傳每列的 segment_id。"""
    gaps = df['timestamp'].diff().dt.total_seconds().div(60).fillna(0)
    return (gaps > max_gap_minutes).cumsum().values


def drop_zero_variance_features(X_df: pd.DataFrame, tol: float = 1e-6) -> list:
    """回傳去除零變異欄位後的特徵名稱清單（取代寫死排除 temp_mean 的做法）。"""
    return [c for c in X_df.columns if X_df[c].std(ddof=0) > tol]


def build_minute_level_dataset(df: pd.DataFrame, horizon: int = 0):
    """把整份逐分鐘資料轉換成每分鐘迴歸用的資料集：
      - 依連續區段（segment）各自重算 ORP EMA/斜率/MACD，避免週期邊界處的 EMA 冷啟動失真
      - 沿用既有 vent-peak 週期切割邏輯，逐列標上 cycle_id / 週期內時間位置 / 相位
      - CH4 迴歸目標使用 EMA(5) 平滑、依 horizon 位移（僅在同一 segment 內位移，不跨斷點）
    回傳 (feat_df, meta)。
    """
    df = df.sort_values('timestamp').reset_index(drop=True).copy()
    df['segment_id'] = segment_by_gaps(df)

    df['pressure']       = df['反應器壓力 (kg/cm²)'].astype(float)
    df['ph']             = df['酸鹼值 (pH)'].astype(float)
    df['temp']           = df['溫度 (°C)'].astype(float)
    df['mixer_pressure'] = df['混合槽壓力 (kg/cm²)'].astype(float)
    df['co2_pct']        = df['CO2濃度 (%)'].astype(float)

    orp_ema10 = np.empty(len(df))
    orp_slope = np.empty(len(df))
    orp_macd  = np.empty(len(df))
    ch4_ema5  = np.empty(len(df))
    for seg_id, idx in df.groupby('segment_id').groups.items():
        idx = idx.to_numpy()
        seg_orp = df.loc[idx, 'ORP (mV)'].values.astype(float)
        ema10, slope, macd = compute_orp_features(seg_orp)
        orp_ema10[idx] = ema10
        orp_slope[idx] = slope
        orp_macd[idx]  = macd
        seg_ch4 = df.loc[idx, 'CH4濃度 (%)'].values.astype(float)
        ch4_ema5[idx] = _ema(seg_ch4, 2 / 6)

    df['orp_ema10'] = orp_ema10
    df['orp_slope'] = orp_slope
    df['orp_macd']  = orp_macd
    df['ch4_ema5']  = ch4_ema5

    # 週期切割（沿用既有 vent-peak 定義；只有落在已知完整週期內的分鐘才有 cycle_id）
    ch4_arr = df['CH4濃度 (%)'].values
    peaks, _ = detect_vent_events(ch4_arr, prominence=10, min_distance=60)
    boundaries = [0] + list(peaks) + [len(df) - 1]
    n_cycles = len(peaks)

    cycle_id     = np.full(len(df), -1, dtype=int)
    elapsed_min  = np.full(len(df), np.nan)
    elapsed_frac = np.full(len(df), np.nan)
    phase_label  = np.zeros(len(df), dtype=int)

    for i in range(n_cycles):
        start, end = boundaries[i], boundaries[i + 1]
        n = end - start + 1
        cycle_id[start:end + 1]     = i
        elapsed_min[start:end + 1]  = np.arange(n)
        elapsed_frac[start:end + 1] = np.arange(n) / max(n - 1, 1)
        cyc_slope = orp_slope[start:end + 1]
        labels, _ = detect_phases(cyc_slope)
        phase_label[start:end + 1] = labels

    df['cycle_id']             = cycle_id
    df['elapsed_min_in_cycle'] = elapsed_min
    df['elapsed_frac_in_cycle'] = elapsed_frac
    df['phase_label']          = phase_label

    # label：horizon 分鐘後（0 = 當下）的 CH4 EMA(5)，僅在同一 segment 內位移
    df['ch4_pct_target'] = df.groupby('segment_id')['ch4_ema5'].shift(-horizon)

    # CH4 落後值（消融實驗用，預設特徵集不使用，理由見 FEATURE_NAMES_MINUTE_LAG 註解）
    df['ch4_lag1'] = df.groupby('segment_id')['ch4_ema5'].shift(1)
    df['ch4_lag2'] = df.groupby('segment_id')['ch4_ema5'].shift(2)

    meta = {'peaks': peaks, 'boundaries': boundaries, 'n_cycles': n_cycles}
    return df, meta


def filter_valid_minutes(df: pd.DataFrame, keep_anomalies: bool = False) -> pd.DataFrame:
    """預設丟掉 ORP 內插修正過的異常分鐘（is_anomaly=True），以及目標值為 NaN
    （週期外或位移後超出區段尾端）的列。"""
    if not keep_anomalies and 'is_anomaly' in df.columns:
        df = df[~df['is_anomaly'].fillna(False).astype(bool)]
    return df.dropna(subset=['ch4_pct_target']).reset_index(drop=True)


FEATURE_NAMES_MINUTE = [
    'orp_ema10', 'orp_slope', 'orp_macd', 'phase_label',
    'elapsed_min_in_cycle', 'elapsed_frac_in_cycle',
    'pressure', 'ph', 'temp', 'mixer_pressure', 'co2_pct',
]

# ── 消融實驗特徵集 ──────────────────────────────────────
# 主結果（FEATURE_NAMES_MINUTE）之外，另外跑一組消融實驗電池，逐一拆解
# 「哪些訊號真的在解釋 CH4，哪些只是巧合的高相關」。

_TIME_FEATURES = {'elapsed_min_in_cycle', 'elapsed_frac_in_cycle'}
_ORP_FEATURES = {'orp_ema10', 'orp_slope', 'orp_macd', 'phase_label'}

# 排除週期進度特徵：檢驗 ORP／操作參數在不知道「現在是週期第幾分鐘」時
# 是否仍有預測力，還是模型其實只是在學一條隨時間單調上升的趨勢線。
FEATURE_NAMES_MINUTE_NO_TIME = [f for f in FEATURE_NAMES_MINUTE if f not in _TIME_FEATURES]

# 只用 ORP 相關特徵：量化「ORP 相位動態」這個論文核心論點本身，
# 在完全拿掉時間與其他感測器資訊後，還能解釋多少 CH4 變異。
FEATURE_NAMES_MINUTE_ORP_ONLY = ['orp_ema10', 'orp_slope', 'orp_macd', 'phase_label']

# 排除所有 ORP 與時間特徵，只用其他操作參數：檢驗 ORP 感測器是否真的必要，
# 或者壓力／pH／CO2 這些更便宜的訊號本身就已經足夠預測 CH4。
FEATURE_NAMES_MINUTE_NON_ORP_BASELINE = [
    f for f in FEATURE_NAMES_MINUTE if f not in _ORP_FEATURES and f not in _TIME_FEATURES
]

# 最小感測器組合（僅 ORP + pH）：對應邊緣部署時「精簡感測器成本」的論述，
# 評估只保留最少感測器時精度犧牲多少。
FEATURE_NAMES_MINUTE_MINIMAL_SENSOR = ['orp_ema10', 'orp_slope', 'orp_macd', 'phase_label', 'ph']

# 額外納入 CH4 自身落後值。預設分析不使用（保持可解釋性 —
# 目的是用 ORP 相位動態解釋 CH4，而非讓模型單純學到 CH4 的自相關），
# 但另外輸出一組結果，預期 RMSE 會趨近於零但不具解釋力，作為「模型能否偷看
# 答案」的上界對照，佐證主結果沒有偷懶依賴自相關。
FEATURE_NAMES_MINUTE_LAG = FEATURE_NAMES_MINUTE + ['ch4_lag1', 'ch4_lag2']

# 消融實驗登記表：{標籤: {features, needs_lag_filter, desc}}。
# needs_lag_filter=True 代表該特徵集用到 ch4_lag1/2，須額外過濾掉每個
# 連續區段開頭無落後值可用的列。
MINUTE_ABLATIONS = {
    'no_time': {
        'features': FEATURE_NAMES_MINUTE_NO_TIME,
        'needs_lag_filter': False,
        'desc': '排除週期進度特徵（elapsed_min/frac_in_cycle），檢驗 ORP/操作參數'
                '在不知道「現在是週期第幾分鐘」時是否仍有預測力',
    },
    'orp_only': {
        'features': FEATURE_NAMES_MINUTE_ORP_ONLY,
        'needs_lag_filter': False,
        'desc': '只用 ORP 相關特徵，量化 ORP 訊號本身能解釋多少 CH4 變異',
    },
    'non_orp_baseline': {
        'features': FEATURE_NAMES_MINUTE_NON_ORP_BASELINE,
        'needs_lag_filter': False,
        'desc': '排除所有 ORP 與時間特徵，只用其他操作參數，檢驗 ORP 是否真的必要',
    },
    'minimal_sensor': {
        'features': FEATURE_NAMES_MINUTE_MINIMAL_SENSOR,
        'needs_lag_filter': False,
        'desc': '最小感測器組合（僅 ORP + pH），評估邊緣部署精簡感測器的可行性',
    },
    'with_lag': {
        'features': FEATURE_NAMES_MINUTE_LAG,
        'needs_lag_filter': True,
        'desc': '額外納入 CH4 落後值，作為「模型能否偷看答案」的上界對照',
    },
}


def export_results_json(results: dict, out_path: str) -> None:
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f'  [輸出] 已儲存 → {out_path}')


def _fit_minute_level(feat_df: pd.DataFrame, feature_names: list,
                       out_dir: str, host_tag: str, tag: str):
    """對一份每分鐘資料集跑完整的 GA + GroupKFold/時序 holdout 評估 + 圖表/JSON 輸出。"""
    os.makedirs(out_dir, exist_ok=True)

    available = drop_zero_variance_features(feat_df[feature_names], tol=1e-6)
    dropped = [f for f in feature_names if f not in available]
    if dropped:
        print(f'  [{tag}] 零變異特徵已排除: {dropped}')

    X_all  = feat_df[available].values.astype(float)
    y_all  = feat_df['ch4_pct_target'].values.astype(float)
    groups = feat_df['cycle_id'].values
    day_index = (
        feat_df['年'].astype(int).astype(str) + '-' +
        feat_df['月'].astype(int).astype(str).str.zfill(2) + '-' +
        feat_df['日'].astype(int).astype(str).str.zfill(2)
    ).values

    n_groups = len(np.unique(groups))
    n_splits = max(2, min(10, n_groups))

    def make_ridge():
        return Pipeline([('scaler', StandardScaler()), ('model', Ridge(alpha=1.0))])

    def make_rf():
        return Pipeline([('scaler', StandardScaler()),
                          ('model', RandomForestRegressor(n_estimators=50, random_state=42))])

    print(f'  [{tag}] GA 特徵選擇（GroupKFold={n_splits} 折，依週期分組，Ridge pipeline）...')
    evaluate_fn = lambda Xs, ys: grouped_cv_rmse(Xs, ys, groups, make_ridge, n_splits=n_splits)
    ga_result = ga_feature_selection(
        X_all, y_all, available,
        pop_size=20, n_gen=40,
        evaluate_fn=evaluate_fn,
    )
    print(f'    Best Grouped-CV RMSE: {ga_result["best_rmse"]:.3f}%')
    print(f'    選中特徵 ({len(ga_result["selected_features"])}/{len(available)}): '
          f'{ga_result["selected_features"]}')

    plot_ga_history(ga_result['history'], os.path.join(out_dir, f'ga_convergence_{tag}.png'))

    sel_idx = ga_result['selected_idx']
    X_ga   = X_all[:, sel_idx]
    X_full = X_all

    ridge_full_rmse = grouped_cv_rmse(X_full, y_all, groups, make_ridge, n_splits=n_splits)
    ridge_ga_rmse   = grouped_cv_rmse(X_ga,   y_all, groups, make_ridge, n_splits=n_splits)
    rf_full_rmse    = grouped_cv_rmse(X_full, y_all, groups, make_rf, n_splits=n_splits)
    rf_ga_rmse      = grouped_cv_rmse(X_ga,   y_all, groups, make_rf, n_splits=n_splits)

    chrono_ridge = chronological_holdout_rmse(X_ga, y_all, day_index, make_ridge)
    chrono_rf    = chronological_holdout_rmse(X_ga, y_all, day_index, make_rf)

    print(f'    {"模型":35s}  GroupKFold RMSE')
    print(f'    {"-"*55}')
    print(f'    {"Ridge (全部特徵)":35s}  {ridge_full_rmse:.3f} %')
    print(f'    {"Ridge (GA 選擇特徵)":35s}  {ridge_ga_rmse:.3f} %  ← GA 結果')
    print(f'    {"Random Forest (全部特徵)":35s}  {rf_full_rmse:.3f} %')
    print(f'    {"Random Forest (GA 選擇特徵)":35s}  {rf_ga_rmse:.3f} %')
    if chrono_ridge is not None:
        print(f'    {"Ridge (GA, 時序 holdout)":35s}  {chrono_ridge:.3f} %')
    if chrono_rf is not None:
        print(f'    {"Random Forest (GA, 時序 holdout)":35s}  {chrono_rf:.3f} %')

    # 逐折預測值（供繪圖 + predictions CSV）
    gkf = GroupKFold(n_splits=n_splits)
    y_pred_ridge = np.empty(len(y_all))
    y_pred_rf    = np.empty(len(y_all))
    fold_id      = np.empty(len(y_all), dtype=int)
    per_fold_rmse_ridge, per_fold_rmse_rf = [], []
    for fi, (tr, te) in enumerate(gkf.split(X_ga, y_all, groups)):
        mdl_r = make_ridge(); mdl_r.fit(X_ga[tr], y_all[tr])
        mdl_f = make_rf();    mdl_f.fit(X_ga[tr], y_all[tr])
        pr = mdl_r.predict(X_ga[te])
        pf = mdl_f.predict(X_ga[te])
        y_pred_ridge[te] = pr
        y_pred_rf[te]    = pf
        fold_id[te]      = fi
        per_fold_rmse_ridge.append(float(np.sqrt(mean_squared_error(y_all[te], pr))))
        per_fold_rmse_rf.append(float(np.sqrt(mean_squared_error(y_all[te], pf))))

    plot_prediction_vs_actual_minute(
        y_all, y_pred_ridge, y_pred_rf,
        os.path.join(out_dir, f'prediction_vs_actual_{tag}.png')
    )

    # RF 特徵重要性（全資料 fit，僅供解釋，非 CV 評估指標）
    rf_full_fit = Pipeline([('scaler', StandardScaler()),
                             ('model', RandomForestRegressor(n_estimators=200, random_state=42))])
    rf_full_fit.fit(X_full, y_all)
    importances = rf_full_fit.named_steps['model'].feature_importances_
    plot_feature_importance(
        available, importances,
        f'Random Forest Feature Importances ({tag}, full-data fit)',
        os.path.join(out_dir, f'feature_importance_{tag}.png')
    )

    corr_df = feat_df[available + ['ch4_pct_target']]
    corr = corr_df.corr()['ch4_pct_target'].drop('ch4_pct_target').sort_values(
        key=abs, ascending=False)

    results = {
        'tag': tag,
        'host_tag': host_tag,
        'n_rows': int(len(feat_df)),
        'n_cycles': int(n_groups),
        'n_splits': int(n_splits),
        'date_range': [str(day_index.min()), str(day_index.max())],
        'features_available': available,
        'features_dropped_zero_variance': dropped,
        'ga_selected_features': ga_result['selected_features'],
        'ga_best_rmse': ga_result['best_rmse'],
        'ga_history': ga_result['history'],
        'rmse': {
            'ridge_full_groupkfold': ridge_full_rmse,
            'ridge_ga_groupkfold': ridge_ga_rmse,
            'rf_full_groupkfold': rf_full_rmse,
            'rf_ga_groupkfold': rf_ga_rmse,
            'ridge_ga_chronological_holdout': chrono_ridge,
            'rf_ga_chronological_holdout': chrono_rf,
        },
        'per_fold_rmse': {
            'ridge_ga': per_fold_rmse_ridge,
            'rf_ga': per_fold_rmse_rf,
        },
        'feature_importance_rf_full': {f: float(i) for f, i in zip(available, importances)},
        'correlation_with_target': {f: float(r) for f, r in corr.items()},
        'generated_at': datetime.now().isoformat(timespec='seconds'),
    }

    export_results_json(
        results, os.path.join(out_dir, f'minute_level_results_{host_tag}_{tag}.json'))

    pred_df = pd.DataFrame({
        'timestamp':        feat_df['timestamp'],
        'cycle_id':         feat_df['cycle_id'],
        'phase_label':      feat_df['phase_label'],
        'fold_id':          fold_id,
        'y_true':           y_all,
        'y_pred_ridge_ga':  y_pred_ridge,
        'y_pred_rf_ga':     y_pred_rf,
    })
    pred_df.to_csv(
        os.path.join(out_dir, f'minute_level_predictions_{host_tag}_{tag}.csv'), index=False)

    return results


def run_minute_level_analysis(df: pd.DataFrame, out_dir: str, host_tag: str = 'local',
                               horizon: int = 0, keep_anomalies: bool = False):
    print(f'\n{"="*60}')
    print(f'每分鐘連續 CH4 迴歸分析（horizon={horizon} min，host={host_tag}）')
    print('='*60)

    feat_df, meta = build_minute_level_dataset(df, horizon=horizon)
    feat_df = filter_valid_minutes(feat_df, keep_anomalies=keep_anomalies)
    feat_df = feat_df[feat_df['cycle_id'] >= 0].reset_index(drop=True)

    n_rows = len(feat_df)
    n_cycles = feat_df['cycle_id'].nunique() if n_rows else 0
    print(f'  可用樣本數: {n_rows:,}（涵蓋 {n_cycles} 個完整週期，'
          f'相較 cycle-level 每週期僅 1 筆樣本大幅提升）')

    if n_rows < 20 or n_cycles < 2:
        print('  ⚠ 樣本或週期數過少（需要至少 2 個週期、20 筆樣本），略過每分鐘分析')
        return None

    results = {}

    print('\n  ── 主結果（完整每分鐘特徵集）──')
    results['main'] = _fit_minute_level(
        feat_df, FEATURE_NAMES_MINUTE, out_dir, host_tag, tag='main')

    for name, spec in MINUTE_ABLATIONS.items():
        print(f'\n  ── 消融實驗：{name} ──')
        print(f'    {spec["desc"]}')
        sub_df = feat_df
        if spec['needs_lag_filter']:
            sub_df = feat_df.dropna(subset=['ch4_lag1', 'ch4_lag2']).reset_index(drop=True)

        if len(sub_df) < 20 or sub_df['cycle_id'].nunique() < 2:
            print('    ⚠ 樣本不足，略過')
            results[name] = None
            continue

        sub_dir = os.path.join(out_dir, f'ablation_{name}')
        results[name] = _fit_minute_level(
            sub_df, spec['features'], sub_dir, host_tag, tag=f'ablation_{name}')

    return results

# ─────────────────────────────────────────────────
# 10. 主程式
# ─────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='CH4 排氣分析：cycle-level baseline 與每分鐘連續迴歸')
    parser.add_argument('--granularity', choices=['cycle', 'minute', 'both'], default='both',
                         help='要跑哪種粒度的分析（預設 both，維持既有裸執行行為）')
    parser.add_argument('--data-dir', default='data/*.csv',
                         help='CSV 資料來源 glob pattern（預設 data/*.csv）')
    parser.add_argument('--host-tag', default=platform.node(),
                         help='本次執行的機器標籤，供監控 PC / Jetson 結果比對用')
    parser.add_argument('--horizon', type=int, default=0,
                         help='每分鐘 CH4 迴歸目標的時間位移（分鐘），0=當下濃度（預設）')
    parser.add_argument('--keep-anomalies', action='store_true',
                         help='每分鐘分析預設會排除 ORP 內插修正過的異常分鐘，加此旗標則保留')
    return parser


def main():
    args = build_arg_parser().parse_args()

    print('[1] 載入資料...')
    df = load_data(args.data_dir)
    print(f'    總筆數: {len(df):,}  欄位: {list(df.columns)}')

    cycle_summary = None
    minute_summary = None

    if args.granularity in ('cycle', 'both'):
        cycle_summary = run_cycle_level_analysis(df, CYCLE_REPORT_DIR)

    if args.granularity in ('minute', 'both'):
        minute_summary = run_minute_level_analysis(
            df, MINUTE_REPORT_DIR,
            host_tag=args.host_tag, horizon=args.horizon,
            keep_anomalies=args.keep_anomalies,
        )

    print('\n' + '=' * 60)
    print('全部分析完成')
    print('=' * 60)
    if cycle_summary:
        print(f'  Cycle-level  : n={cycle_summary["n_cycles"]}  '
              f'Ridge={cycle_summary["ridge_ga_loo_rmse"]:.2f}%  '
              f'RF={cycle_summary["rf_ga_loo_rmse"]:.2f}%')
    if minute_summary and minute_summary.get('main'):
        m = minute_summary['main']
        print(f'  Minute-level (main) : n={m["n_rows"]:,} ({m["n_cycles"]} 週期)  '
              f'Ridge(GroupKFold)={m["rmse"]["ridge_ga_groupkfold"]:.2f}%  '
              f'RF(GroupKFold)={m["rmse"]["rf_ga_groupkfold"]:.2f}%')
    if minute_summary:
        for name, r in minute_summary.items():
            if name == 'main' or r is None:
                continue
            print(f'  Minute-level ablation[{name}]: '
                  f'Ridge(GroupKFold)={r["rmse"]["ridge_ga_groupkfold"]:.2f}%  '
                  f'RF(GroupKFold)={r["rmse"]["rf_ga_groupkfold"]:.2f}%')


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()
