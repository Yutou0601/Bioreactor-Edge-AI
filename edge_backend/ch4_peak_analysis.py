"""
CH4 排氣峰值預測分析
====================
Pipeline:
  1. 資料載入與時間索引建立
  2. 排氣事件偵測 (scipy.signal.find_peaks)
  3. 自適應 ORP 相位偵測 (Phase 1 / 2 / 3)  ← 週期內相對閾值，應對條件變動
  4. 週期級特徵萃取 (Cycle-level Features)
  5. 特徵選擇 (GA，目標：LOO-CV RMSE on CH4 peak)
  6. Ridge Regression + Random Forest 建模比較
  7. 特徵重要性輸出 + 視覺化 (儲存至 reports/)

統計限制說明：
  目前資料含 6 個完整排氣週期，樣本量極小。
  模型結果用於說明方法論與特徵重要性分析；
  實務預測穩定性需累積 ≥ 30 個週期的資料。
"""

import os
import sys
import warnings
import random
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.signal import find_peaks
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error

warnings.filterwarnings('ignore')
random.seed(42)
np.random.seed(42)

REPORT_DIR = os.path.join(os.path.dirname(__file__), 'reports')
os.makedirs(REPORT_DIR, exist_ok=True)

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
# 5. 週期級特徵萃取
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
# 6. GA 特徵選擇
# ─────────────────────────────────────────────────

def loo_cv_rmse(X: np.ndarray, y: np.ndarray, model_fn) -> float:
    """Leave-One-Out Cross-Validation RMSE（樣本少時唯一可靠的評估方式）"""
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


def ga_feature_selection(X: np.ndarray, y: np.ndarray,
                          feature_names: list,
                          pop_size: int = 20,
                          n_gen: int = 40,
                          cx_prob: float = 0.7,
                          mut_prob: float = 0.15,
                          model_fn=None):
    """
    以 GA 在 cycle-level 特徵集合中搜索最佳子集。

    染色體 : 長度 = n_features 的二進制向量，1 = 選用
    適應度 : LOO-CV RMSE（愈小愈好，取負值轉最大化）
    選擇   : Tournament selection (size=3)
    交配   : Single-point crossover
    突變   : Bit-flip mutation
    """
    if model_fn is None:
        model_fn = lambda: Ridge(alpha=1.0)

    n_feat = X.shape[1]

    def fitness(chrom):
        sel = [i for i, c in enumerate(chrom) if c]
        if not sel:
            return float('inf')
        return loo_cv_rmse(X[:, sel], y, model_fn)

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
    ax.set_ylabel('Best LOO-CV RMSE (%)', fontsize=9)
    ax.set_title('GA Feature Selection – Convergence Curve', fontsize=10, fontweight='bold')
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  [圖表] 已儲存 → {out_path}')


def plot_prediction_vs_actual(y_true, y_pred_ridge, y_pred_rf,
                               cycle_ids, out_path):
    """LOO-CV 預測值 vs 實際值散點圖"""
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

# ─────────────────────────────────────────────────
# 8. 主程式
# ─────────────────────────────────────────────────

def main():
    SEP = '=' * 60

    # ── 載入 ────────────────────────────────────────
    print(SEP)
    print('CH4 排氣峰值預測分析')
    print(SEP)
    print('[1] 載入資料...')
    df = load_data()
    print(f'    總筆數: {len(df):,}  欄位: {list(df.columns)}')

    # ── 排氣事件 ─────────────────────────────────────
    print('\n[2] 偵測排氣事件...')
    ch4_arr = df['CH4濃度 (%)'].values
    peaks, _ = detect_vent_events(ch4_arr, prominence=10, min_distance=60)
    peak_ch4 = ch4_arr[peaks]
    print(f'    偵測到 {len(peaks)} 個排氣事件')
    for i, (idx, v) in enumerate(zip(peaks, peak_ch4)):
        ts = df['timestamp'].iloc[idx]
        print(f'    事件 {i+1}: {ts}  CH4={v:.1f}%')

    # ── 週期切割 ─────────────────────────────────────
    boundaries = [0] + list(peaks) + [len(df) - 1]
    n_complete = len(peaks)   # 有已知 CH4 峰值的週期數

    print(f'\n    完整週期數（有已知排氣峰值）: {n_complete}')
    print(f'    ⚠ 統計限制：{n_complete} 個樣本，所有模型評估使用 LOO-CV')

    # ── 相位偵測 + 特徵萃取 ───────────────────────────
    print('\n[3] 相位偵測 & 週期特徵萃取...')
    feature_records = []
    all_phase_labels = []

    for i in range(n_complete):
        start, end = boundaries[i], boundaries[i + 1]
        cyc_df = df.iloc[start:end + 1].copy()
        orp_cyc = cyc_df['ORP (mV)'].values.astype(float)
        _, slope_cyc, _ = compute_orp_features(orp_cyc)
        phase_labels, (mu, sigma, lo, hi) = detect_phases(slope_cyc)
        all_phase_labels.append(phase_labels)

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
            os.path.join(REPORT_DIR, f'cycle_{i+1:02d}_phase.png')
        )

    feat_df = pd.DataFrame(feature_records)
    X_all   = feat_df[FEATURE_NAMES].values.astype(float)
    y_all   = feat_df['ch4_peak'].values.astype(float)

    # ── 全資料總覽圖 ──────────────────────────────────
    print('\n[4] 繪製總覽圖...')
    plot_cycles_overview(
        df, peaks, peak_ch4, boundaries,
        os.path.join(REPORT_DIR, 'overview.png')
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
        model_fn=lambda: Ridge(alpha=1.0)
    )
    print(f'    Best LOO-CV RMSE: {ga_result["best_rmse"]:.3f}%')
    print(f'    選中特徵 ({len(ga_result["selected_features"])}/{len(FEATURE_NAMES)}):')
    for f in ga_result['selected_features']:
        print(f'      ✓ {f}')

    plot_ga_history(
        ga_result['history'],
        os.path.join(REPORT_DIR, 'ga_convergence.png')
    )

    # ── Ridge Regression（全特徵 vs GA 特徵）──────────
    print(f'\n[6] 模型訓練與 LOO-CV 評估...')
    sel_idx   = ga_result['selected_idx']
    X_ga      = X_scaled[:, sel_idx]
    X_full    = X_scaled

    # LOO-CV RMSE
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
        os.path.join(REPORT_DIR, 'prediction_vs_actual.png')
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
        os.path.join(REPORT_DIR, 'feature_importance.png')
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
    print('分析結論摘要')
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
    print(f'  輸出圖表目錄: {REPORT_DIR}/')
    for f in sorted(os.listdir(REPORT_DIR)):
        print(f'    - {f}')
    print(SEP)


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()
