"""
CO2 溶解 / 生物消耗定量分離分析
================
依質量守恆推算：頭空 CO2 總消失量 = 被生物消耗量（由 CH4 產量依 4H2+CO2→CH4+2H2O
之 1:1 計量比反推）+ 物理溶解量。方法詳見 docs/日報_2026-07-14.md 第 6 項。

因反應槽氣相體積 V_gas 尚未確認，本腳本輸出「相對莫耳數」（正比於 P(t)/T(t)，
與真實莫耳數只差一個常數 V_gas/R，之後 V_gas 確認後可直接乘上換算成絕對量）。

已知歷史 CSV 檔案的「反應器壓力」/「混合槽壓力」欄位標籤對調（2026-07-14 現場
比對 HMI 面板確認，詳見 docs/日報_2026-07-14.md 第 2 項），本腳本讀入後會自動
對調回正確語意，不需要額外處理。

**重要（2026-07-14 晚間確認）**：CO2%/CH4% 感測器只有在真正排氣時才會更新讀數，
排氣之間的分鐘讀數是上一次排氣的舊值，不能當成連續訊號逐分鐘套用質量守恆公式。
預設的 interval 模式會自動偵測排氣事件（CO2% 出現尖峰跳動處），只在「相鄰兩次
排氣之間」算一個總量，並附上該區間內 ORP/壓力/pH 的線性斜率（這幾個訊號才是
真正逐分鐘連續、可信的），供後續嘗試用斜率去逼近排氣間看不到的過程。

使用方式：
    python co2_separation_analysis.py --csv "C:\\path\\to\\BTP_Sensor_log-2026-04-20.csv"
    python co2_separation_analysis.py --csv "...csv" --mode per_minute --start "..." --end "..."
"""

import argparse
import glob
import os
import sys
import numpy as np
import pandas as pd

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

LEGACY_COLUMNS = ['年', '月', '日', '時', '分', '秒', '_', 'ORP (mV)', '反應器壓力 (kg/cm²)',
                   '酸鹼值 (pH)', '溫度 (°C)', '混合槽壓力 (kg/cm²)', 'CO2濃度 (%)', 'CH4濃度 (%)']


def load_csv(path: str) -> pd.DataFrame:
    with open(path, 'r', encoding='utf-8-sig') as f:
        first_line = f.readline()
    tokens = [t.strip() for t in first_line.strip().split(',')]

    if '年' in tokens:
        df = pd.read_csv(path, encoding='utf-8-sig')
    else:
        df = pd.read_csv(path, header=None, names=LEGACY_COLUMNS, encoding='utf-8-sig')

    df['timestamp'] = pd.to_datetime(dict(
        year=df['年'], month=df['月'], day=df['日'],
        hour=df['時'], minute=df['分'], second=df['秒'],
    ))

    # 欄位對調修正：「反應器壓力」欄實際是混合槽讀數、「混合槽壓力」欄實際是反應槽讀數
    df['reactor_pressure'] = df['混合槽壓力 (kg/cm²)']
    df['mixer_pressure']   = df['反應器壓力 (kg/cm²)']
    df['co2_pct']  = df['CO2濃度 (%)']
    df['ch4_pct']  = df['CH4濃度 (%)']
    df['temp_k']   = df['溫度 (°C)'] + 273.15

    return df.sort_values('timestamp').reset_index(drop=True)


def load_folder_combined(folder: str) -> pd.DataFrame:
    """把資料夾內所有 CSV 依時間串成一條連續時間軸（跨天），用於偵測跨天的巨觀
    事件週期（一次事件日 → 中間好幾天靜止 → 下一次事件日），逐檔案分開處理會
    把這種跨天的靜止期切斷，看不到完整週期。
    """
    files = sorted(f for f in glob.glob(os.path.join(folder, '*.csv'))
                   if not os.path.basename(f).startswith('_'))
    if not files:
        raise ValueError(f"{folder} 底下找不到任何 CSV 檔案")
    dfs = [load_csv(f) for f in files]
    combined = pd.concat(dfs, ignore_index=True)
    return combined.sort_values('timestamp').reset_index(drop=True)


def compute_separation(df: pd.DataFrame) -> pd.DataFrame:
    """新增欄位：n_total_rel（相對總莫耳數，正比於 P/T）、
    delta_ch4_rel（累積生物消耗 CO2，相對單位）、
    delta_co2_dissolved_rel（累積物理溶解 CO2，相對單位）。
    以資料第一筆為基準點 t0。
    """
    df = df.copy()
    df['n_total_rel'] = df['reactor_pressure'] / df['temp_k']

    n_co2 = df['n_total_rel'] * df['co2_pct'] / 100.0
    n_ch4 = df['n_total_rel'] * df['ch4_pct'] / 100.0

    df['delta_ch4_rel']            = n_ch4 - n_ch4.iloc[0]
    df['delta_co2_total_lost_rel'] = n_co2.iloc[0] - n_co2
    df['delta_co2_dissolved_rel']  = df['delta_co2_total_lost_rel'] - df['delta_ch4_rel']

    return df


def detect_reading_updates(df: pd.DataFrame, min_change: float = 0.5) -> list:
    """找出 CO2%／CH4% 實際發生跳動的列（判定為感測器真正更新讀數的時刻），
    回傳這些列在 df 裡的 index（含第一列）。中間分鐘的讀數視為前一次更新的
    舊值，不當作連續訊號使用。min_change：CO2% 或 CH4% 變化超過這個百分點
    才算一次更新（避免雜訊被誤判成事件）。
    """
    co2_diff = df['co2_pct'].diff().abs()
    ch4_diff = df['ch4_pct'].diff().abs()
    changed = (co2_diff > min_change) | (ch4_diff > min_change)
    idx = [0] + df.index[changed].tolist()
    return sorted(set(idx))


def _slope(x: pd.Series, y: pd.Series) -> float:
    """簡單線性回歸斜率（每分鐘變化量），資料點不足時回傳 NaN。"""
    if len(x) < 2:
        return float('nan')
    x_min = np.asarray((x - x.iloc[0]).dt.total_seconds() / 60.0, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    if np.isnan(y_arr).any() or np.ptp(x_min) == 0:
        mask = ~np.isnan(y_arr)
        if mask.sum() < 2 or np.ptp(x_min[mask]) == 0:
            return float('nan')
        x_min, y_arr = x_min[mask], y_arr[mask]
    return float(np.polyfit(x_min, y_arr, 1)[0])


def compute_intervals(df: pd.DataFrame, min_change: float = 0.5) -> pd.DataFrame:
    """把資料切成「相鄰兩次讀數更新之間」的區間，每段輸出：
    區間起訖時間、區間長度（分鐘）、該區間總 CO2 消失量／生物消耗量／物理溶解量
    （用區間頭尾兩個真實讀數點算質量守恆，不假設中間逐分鐘連續），以及區間內
    ORP／反應槽壓力／pH 的線性斜率（這幾個訊號逐分鐘皆為連續讀值，可信）。
    """
    df = df.reset_index(drop=True)
    boundaries = detect_reading_updates(df, min_change=min_change)
    if len(boundaries) < 2:
        raise ValueError("偵測不到至少兩個讀數更新點，無法切出任何區間；"
                          "可調整 --min-change 門檻，或確認資料本身是否真的有離散跳動")

    df['n_total_rel'] = df['reactor_pressure'] / df['temp_k']
    df['n_co2_rel'] = df['n_total_rel'] * df['co2_pct'] / 100.0
    df['n_ch4_rel'] = df['n_total_rel'] * df['ch4_pct'] / 100.0

    rows = []
    for start_i, end_i in zip(boundaries[:-1], boundaries[1:]):
        seg = df.iloc[start_i:end_i + 1]
        delta_ch4    = seg['n_ch4_rel'].iloc[-1] - seg['n_ch4_rel'].iloc[0]
        delta_co2_lost = seg['n_co2_rel'].iloc[0] - seg['n_co2_rel'].iloc[-1]
        rows.append({
            'start':          seg['timestamp'].iloc[0],
            'end':            seg['timestamp'].iloc[-1],
            'duration_min':   (seg['timestamp'].iloc[-1] - seg['timestamp'].iloc[0]).total_seconds() / 60.0,
            'delta_ch4_rel':            delta_ch4,
            'delta_co2_total_lost_rel': delta_co2_lost,
            'delta_co2_dissolved_rel':  delta_co2_lost - delta_ch4,
            'orp_slope_per_min':      _slope(seg['timestamp'], seg['ORP (mV)']),
            'pressure_slope_per_min': _slope(seg['timestamp'], seg['reactor_pressure']),
            'ph_slope_per_min':       _slope(seg['timestamp'], seg['酸鹼值 (pH)']),
        })
    return pd.DataFrame(rows)


def detect_pressure_refills(df: pd.DataFrame, min_jump: float = 0.05) -> list:
    """找出反應槽壓力『補氣』事件（單步跳升 > min_jump），回傳這些列的 index
    （含第一列）。依 2026-07-14 現場確認：補氣事件造成壓力大幅跳升，之後的
    緩慢下降才是循環把氣體推進液相的訊號，兩者是獨立動作，補氣後壓力才會
    真正開始（或繼續）下降。用補氣事件切區間，比用 CO2%/CH4% 切更適合用來
    觀察循環強度，因為補氣頻率遠高於（舊資料裡很少見的）自動排氣事件。
    """
    p_diff = df['reactor_pressure'].diff()
    jumped = p_diff > min_jump
    idx = [0] + df.index[jumped].tolist() + [len(df) - 1]
    return sorted(set(idx))


def compute_pressure_intervals(df: pd.DataFrame, min_jump: float = 0.05) -> pd.DataFrame:
    """把資料切成『相鄰兩次補氣之間』的區間，輸出各區間的壓力/ORP/pH 走勢，
    並依壓力斜率標記 likely_circulating（不是真正的答案，只是資料驅動的候選
    標記，需要跟實際操作記錄核對）。斜率門檻 -0.003 kg/cm²/hr 是初步經驗值，
    非官方定義。
    """
    df = df.reset_index(drop=True)
    boundaries = detect_pressure_refills(df, min_jump=min_jump)
    if len(boundaries) < 2:
        raise ValueError("偵測不到至少兩個補氣事件，無法切出任何區間；"
                          "可調整 --min-jump 門檻")

    rows = []
    for start_i, end_i in zip(boundaries[:-1], boundaries[1:]):
        seg = df.iloc[start_i:end_i + 1]
        if len(seg) < 5:
            continue
        dur_hr = (seg['timestamp'].iloc[-1] - seg['timestamp'].iloc[0]).total_seconds() / 3600.0
        p_slope_hr = _slope(seg['timestamp'], seg['reactor_pressure']) * 60
        orp_slope_hr = _slope(seg['timestamp'], seg['ORP (mV)']) * 60
        ph_slope_hr = _slope(seg['timestamp'], seg['酸鹼值 (pH)']) * 60
        rows.append({
            'start':            seg['timestamp'].iloc[0],
            'end':              seg['timestamp'].iloc[-1],
            'duration_hr':      round(dur_hr, 2),
            'p_start':          seg['reactor_pressure'].iloc[0],
            'p_end':            seg['reactor_pressure'].iloc[-1],
            'p_slope_per_hr':   round(p_slope_hr, 5),
            'orp_mean':         round(seg['ORP (mV)'].mean(), 1),
            'orp_slope_per_hr': round(orp_slope_hr, 3),
            'ph_mean':          round(seg['酸鹼值 (pH)'].mean(), 3),
            'ph_slope_per_hr':  round(ph_slope_hr, 4),
            'likely_circulating': bool(p_slope_hr < -0.003),
        })
    return pd.DataFrame(rows)


def build_feature_table(df: pd.DataFrame, min_change: float = 0.5, min_jump: float = 0.05) -> pd.DataFrame:
    """統一特徵表：邊界取「壓力補氣事件」∪「CO2%/CH4% 真正更新」的聯集，確保
    每一段都夠短、訊號夠乾淨。每段一定有連續訊號的斜率特徵（ORP/壓力/pH，這幾
    個逐分鐘皆可信）；如果該段頭尾剛好對到真正的 CO2/CH4 讀數更新，另外算出
    質量守恆的 delta_ch4_rel／delta_co2_dissolved_rel 當作交叉驗證的標籤，沒有
    對到就是 NaN（不能瞎猜）。這是模型化之前的特徵基礎，先確認這張表乾不乾淨，
    再考慮要不要進一步用它訓練東西。
    """
    df = df.reset_index(drop=True)
    df['n_total_rel'] = df['reactor_pressure'] / df['temp_k']
    df['n_co2_rel'] = df['n_total_rel'] * df['co2_pct'] / 100.0
    df['n_ch4_rel'] = df['n_total_rel'] * df['ch4_pct'] / 100.0

    p_boundaries = set(detect_pressure_refills(df, min_jump=min_jump))
    c_boundaries = set(detect_reading_updates(df, min_change=min_change))
    boundaries = sorted(p_boundaries | c_boundaries)
    if len(boundaries) < 2:
        raise ValueError("偵測不到至少兩個邊界點，無法切出任何區間")

    rows = []
    for start_i, end_i in zip(boundaries[:-1], boundaries[1:]):
        seg = df.iloc[start_i:end_i + 1]
        if len(seg) < 3:
            continue
        dur_hr = (seg['timestamp'].iloc[-1] - seg['timestamp'].iloc[0]).total_seconds() / 3600.0

        # 只有這段頭尾剛好對到 CO2/CH4 真正更新點，才算質量守恆數字，否則 NaN
        has_co2_update = start_i in c_boundaries and end_i in c_boundaries
        if has_co2_update:
            delta_ch4 = seg['n_ch4_rel'].iloc[-1] - seg['n_ch4_rel'].iloc[0]
            delta_co2_lost = seg['n_co2_rel'].iloc[0] - seg['n_co2_rel'].iloc[-1]
            delta_co2_dissolved = delta_co2_lost - delta_ch4
        else:
            delta_ch4 = delta_co2_lost = delta_co2_dissolved = float('nan')

        rows.append({
            'start':                    seg['timestamp'].iloc[0],
            'end':                      seg['timestamp'].iloc[-1],
            'duration_hr':              round(dur_hr, 3),
            'is_refill_boundary':       start_i in p_boundaries,
            'has_co2_ground_truth':     has_co2_update,
            'pressure_start':           seg['reactor_pressure'].iloc[0],
            'pressure_end':             seg['reactor_pressure'].iloc[-1],
            'pressure_slope_per_hr':    round(_slope(seg['timestamp'], seg['reactor_pressure']) * 60, 5),
            'ph_mean':                  round(seg['酸鹼值 (pH)'].mean(), 3),
            'ph_slope_per_hr':          round(_slope(seg['timestamp'], seg['酸鹼值 (pH)']) * 60, 4),
            'orp_mean':                 round(seg['ORP (mV)'].mean(), 1),
            'orp_slope_per_hr':         round(_slope(seg['timestamp'], seg['ORP (mV)']) * 60, 3),
            'delta_ch4_rel':            delta_ch4,
            'delta_co2_dissolved_rel':  delta_co2_dissolved,
        })
    return pd.DataFrame(rows)


def solve_dissolution_reaction(pressure_slope_per_hr: float, orp_slope_per_hr: float, m: float):
    """由壓力與 ORP 斜率反解 r_d（物理溶解速率）與 r_b（生物消耗速率），相對莫耳/小時單位。

    結構假設（2026-07-15 重新推導）：溶解→液相溶解池→生物消耗是「串聯」而非「平行」路徑
    ——氫氣甲烷菌吃的是已溶入水中的 CO2，不是直接吃氣相 CO2。因此：
      - 氣相 CO2 只會被「溶解」直接抽走；生物消耗抽走的是液相溶解池，不直接動氣相 CO2，
        但同時抽走氣相 H2（4x 計量比）、放出氣相 CH4（1x），淨影響氣相 3·r_b：
            pressure_slope = -(r_d + 3·r_b)
      - ORP 主要反映生物耗氫（還原劑消耗）程度，視為 r_b 的直接代理，與是否溶解無關：
            orp_slope = m · r_b
        m 為待校正常數（ORP mV/hr 對應 r_b 相對莫耳/hr 的比例），目前僅有粗略估計
        （見 calibrate_m_k），非正式校正值。
    """
    r_b = orp_slope_per_hr / m
    r_d = -pressure_slope_per_hr - 3 * r_b
    return r_d, r_b


def predicted_ph_slope(r_d: float, r_b: float, k: float) -> float:
    """由串聯結構推算的 pH 斜率：pH 反映液相溶解池的淨累積量 (r_d − r_b)
    ——溶解快於消耗則池子累積、酸化、pH 下降；消耗快於溶解則池子被掏空、pH 反而上升。
    跟實測 ph_slope_per_hr 的殘差，是未來若要加神經網路修正非線性殘差時的目標訊號。
    """
    return k * (r_d - r_b)


def calibrate_m_k(feature_table: pd.DataFrame) -> dict | None:
    """用 feature_table 裡 has_co2_ground_truth=True 的區段粗估 m、k。
    這些區段只有「總量」（delta_ch4_rel / delta_co2_dissolved_rel），换算成每小時速率
    後才能跟 orp_slope_per_hr / ph_slope_per_hr 對齊迴歸。樣本數少、橫跨數月資料，
    估出來的常數僅供 sanity check（數量級、正負號是否合理），不是正式校正值——正式校正
    要等新的短窗口實驗協定收集資料後才能做。
    """
    gt = feature_table[feature_table['has_co2_ground_truth']].copy()
    if len(gt) < 3:
        return None

    gt['r_b_obs_per_hr'] = gt['delta_ch4_rel'] / gt['duration_hr']
    gt['r_d_obs_per_hr'] = gt['delta_co2_dissolved_rel'] / gt['duration_hr']

    valid_m = gt[gt['r_b_obs_per_hr'].abs() > 1e-9]
    m_est = float((valid_m['orp_slope_per_hr'] / valid_m['r_b_obs_per_hr']).median()) if len(valid_m) else float('nan')

    net_obs = gt['r_d_obs_per_hr'] - gt['r_b_obs_per_hr']
    valid_k = gt[net_obs.abs() > 1e-9]
    k_est = float((valid_k['ph_slope_per_hr'] / net_obs[valid_k.index]).median()) if len(valid_k) else float('nan')

    return {'m_est': m_est, 'k_est': k_est, 'n_samples': len(gt), 'n_valid_m': len(valid_m), 'n_valid_k': len(valid_k)}


def apply_solver(feature_table: pd.DataFrame, m: float, k: float) -> pd.DataFrame:
    """把 solve_dissolution_reaction / predicted_ph_slope 套用到每一列，附上
    r_d_solved、r_b_solved、ph_slope_predicted、ph_residual，供 sanity check 用。"""
    ft = feature_table.copy()
    solved = ft.apply(
        lambda row: solve_dissolution_reaction(row['pressure_slope_per_hr'], row['orp_slope_per_hr'], m),
        axis=1, result_type='expand')
    ft['r_d_solved'] = solved[0]
    ft['r_b_solved'] = solved[1]
    ft['ph_slope_predicted'] = ft.apply(
        lambda row: predicted_ph_slope(row['r_d_solved'], row['r_b_solved'], k), axis=1)
    ft['ph_residual'] = ft['ph_slope_per_hr'] - ft['ph_slope_predicted']
    return ft


def detect_true_cycle_boundaries(df: pd.DataFrame, min_change: float = 5.0, merge_gap_min: float = 15.0) -> list:
    """跟 detect_reading_updates 一樣抓 CO2%/CH4% 跳動點，但用大門檻（真正排氣才會讓
    讀數跳這麼多，而不是排氣後幾分鐘內讀數還在抖動的雜訊步階），並把彼此間隔在
    merge_gap_min 分鐘內的多個跳動點合併成一個邊界（取最後一點，代表讀數已穩定）。
    這樣抓到的才是真正完整的「進氣→循環→排氣」循環邊界（實測約 2~7 天一次，
    對應舊研究海報上動輒上萬分鐘的循環長度），不是我最初用 min_change=0.5 誤抓的
    2~20 分鐘排氣雜訊步階。
    """
    raw = detect_reading_updates(df, min_change=min_change)
    if len(raw) < 2:
        return raw
    merged = [raw[0]]
    for idx in raw[1:]:
        gap_min = (df['timestamp'].iloc[idx] - df['timestamp'].iloc[merged[-1]]).total_seconds() / 60.0
        if gap_min <= merge_gap_min:
            merged[-1] = idx
        else:
            merged.append(idx)
    return merged


def build_cycle_table(df: pd.DataFrame, min_change: float = 5.0, merge_gap_min: float = 15.0,
                       min_duration_hr: float = 1.0) -> pd.DataFrame:
    """把資料切成真正完整的循環（見 detect_true_cycle_boundaries），每個循環輸出：
    質量守恆算出的總消耗量／總溶解量（僅用頭尾兩個真實讀數，不假設中間連續，
    這一層在頭尾皆為真值的前提下是嚴謹的算術，不是模型），以及整個循環期間的
    ORP／壓力／pH 統計量，做為之後 GA 特徵選擇 + Ridge 迴歸的候選特徵池雛型。
    這裡不試圖分離循環進行中任一時刻的瞬時溶解/消耗速率——那是欠定問題，
    沒有唯一解；這裡只用循環總量，交給啟發式演算法去找哪些連續訊號特徵
    最能預測這個總量，而不是預先假設一組物理方程式。
    """
    df = df.reset_index(drop=True)
    df['n_total_rel'] = df['reactor_pressure'] / df['temp_k']
    df['n_co2_rel'] = df['n_total_rel'] * df['co2_pct'] / 100.0
    df['n_ch4_rel'] = df['n_total_rel'] * df['ch4_pct'] / 100.0

    boundaries = detect_true_cycle_boundaries(df, min_change=min_change, merge_gap_min=merge_gap_min)
    if len(boundaries) < 2:
        return pd.DataFrame()

    rows = []
    for start_i, end_i in zip(boundaries[:-1], boundaries[1:]):
        seg = df.iloc[start_i:end_i + 1]
        dur_hr = (seg['timestamp'].iloc[-1] - seg['timestamp'].iloc[0]).total_seconds() / 3600.0
        if dur_hr < min_duration_hr or len(seg) < 5:
            continue

        delta_ch4 = seg['n_ch4_rel'].iloc[-1] - seg['n_ch4_rel'].iloc[0]
        delta_co2_lost = seg['n_co2_rel'].iloc[0] - seg['n_co2_rel'].iloc[-1]
        delta_co2_dissolved = delta_co2_lost - delta_ch4
        denom = delta_ch4 + delta_co2_dissolved
        consumed_fraction = delta_ch4 / denom if abs(denom) > 1e-9 else float('nan')

        rows.append({
            'start':                     seg['timestamp'].iloc[0],
            'end':                       seg['timestamp'].iloc[-1],
            'duration_hr':               round(dur_hr, 2),
            'n_rows':                    len(seg),
            'co2_start':                 seg['co2_pct'].iloc[0],
            'co2_end':                   seg['co2_pct'].iloc[-1],
            'ch4_start':                 seg['ch4_pct'].iloc[0],
            'ch4_end':                   seg['ch4_pct'].iloc[-1],
            'delta_ch4_rel':             round(delta_ch4, 6),
            'delta_co2_dissolved_rel':   round(delta_co2_dissolved, 6),
            'consumed_fraction':         round(consumed_fraction, 4) if pd.notna(consumed_fraction) else float('nan'),
            'pressure_start':            seg['reactor_pressure'].iloc[0],
            'pressure_end':              seg['reactor_pressure'].iloc[-1],
            'pressure_mean':             round(seg['reactor_pressure'].mean(), 4),
            'pressure_slope_per_hr':     round(_slope(seg['timestamp'], seg['reactor_pressure']) * 60, 5),
            'ph_mean':                   round(seg['酸鹼值 (pH)'].mean(), 3),
            'ph_slope_per_hr':           round(_slope(seg['timestamp'], seg['酸鹼值 (pH)']) * 60, 4),
            'orp_mean':                  round(seg['ORP (mV)'].mean(), 1),
            'orp_slope_per_hr':          round(_slope(seg['timestamp'], seg['ORP (mV)']) * 60, 3),
            'orp_min':                   seg['ORP (mV)'].min(),
            'orp_max':                   seg['ORP (mV)'].max(),
        })
    return pd.DataFrame(rows)


def mask_invalid_gas_readings(df: pd.DataFrame, min_jump: float = 5.0, peak_window: int = 3) -> pd.DataFrame:
    """把 co2_pct / ch4_pct 兩欄中「無效」的部分遮成 NaN，只保留排氣峰值。

    2026-07-16 洪博/使用者確認之感測器取樣架構（這不是感測器故障，是設計如此）：
      - 氣體只有在排氣（閥4開啟）時才會流到感測器 → 讀數只在排氣瞬間反映反應槽
      - 排氣後閘門關閉，感測器腔體內的氣體會慢慢往外流失 → 之後 1~2 小時的衰減
        「拖尾」**完全不反映反應槽，是無效資料**（不是「比較不準」，是無效）
      - 記錄頻率 1 筆/分鐘，而排氣僅數秒 → 可能整個錯過真正的峰值

    因此 co2_pct/ch4_pct 只有排氣峰值附近那一兩筆有意義，其餘全部無效。
    由於「記得不要用」不可靠（2026-07-16 當天就誤用了兩次：拿週期末的拖尾值算
    質量守恆、拿拖尾值當「週期末殘留CO2」去推翻計量比推導），這裡直接在資料
    層把無效值遮掉，讓它們在結構上無法被誤用。

    **即使是保留下來的峰值也只能當「參考」，不能當證據**：1 分鐘取樣可能抓到的
    是上升段或已開始衰減的點，故記錄到的峰值只是真實峰值的**下界**。

    參數：
        min_jump    -- CO2% 單步跳升超過此值視為一次排氣（預設 5 個百分點）
        peak_window -- 排氣後取幾分鐘內的最大值當峰值（預設 3）
    """
    df = df.copy()
    co2 = df['co2_pct'].to_numpy(dtype=float)
    jump = np.diff(co2, prepend=co2[0])
    vent_idx = np.where(jump > min_jump)[0]

    keep = np.zeros(len(df), dtype=bool)
    for i in vent_idx:
        j = min(i + peak_window, len(df))
        seg = co2[i:j]
        if len(seg) == 0 or np.all(np.isnan(seg)):
            continue
        keep[i + int(np.nanargmax(seg))] = True

    df.loc[~keep, ['co2_pct', 'ch4_pct']] = np.nan
    df['is_vent_peak'] = keep
    return df


def detect_intake_events(df: pd.DataFrame, min_mixer_drop: float = 0.1, min_reactor_rise: float = 0.05) -> list:
    """偵測進氣事件：混合槽壓力驟降、同一分鐘反應槽壓力同時上升。
    混合槽壓力下降量正比於打入反應槽的氣體量（4H2+1CO2 混合氣，比例固定），
    是精確量測值（氣體定律直接反推莫耳數），不像 CO2%/CH4%/pH 那樣要間接推測
    ——2026-07-16 這是比之前所有嘗試都更站得住腳的「已知輸入劑量」，可以拿
    來看反應槽對已知劑量的短期反應，而不是反過來用反應去猜輸入。"""
    mixer_diff = df['mixer_pressure'].diff()
    reactor_diff = df['reactor_pressure'].diff()
    is_intake = (mixer_diff < -min_mixer_drop) & (reactor_diff > min_reactor_rise)
    return df.index[is_intake].tolist()


def analyze_intake_response(df: pd.DataFrame, response_window_min: int = 60,
                             min_mixer_drop: float = 0.1, min_reactor_rise: float = 0.05) -> pd.DataFrame:
    """對每個進氣事件，取得注入劑量（混合槽壓力降幅）與事件後 response_window_min
    分鐘內反應槽壓力/pH/ORP 的變化。劑量已知、乾淨，事後只需要檢查「劑量」跟
    「短期反應」之間的關係，不用再靠假設的機制方程式間接推測。"""
    df = df.reset_index(drop=True)
    events = detect_intake_events(df, min_mixer_drop=min_mixer_drop, min_reactor_rise=min_reactor_rise)
    rows = []
    for idx in events:
        if idx == 0 or idx + response_window_min >= len(df):
            continue
        window = df.iloc[idx: idx + response_window_min + 1]
        rows.append({
            'timestamp':                          df['timestamp'].iloc[idx],
            'dose_mixer_pressure_drop':            round(df['mixer_pressure'].iloc[idx - 1] - df['mixer_pressure'].iloc[idx], 4),
            'reactor_pressure_jump':               round(df['reactor_pressure'].iloc[idx] - df['reactor_pressure'].iloc[idx - 1], 4),
            'reactor_pressure_start':               window['reactor_pressure'].iloc[0],
            'reactor_pressure_decline_in_window':  round(window['reactor_pressure'].iloc[0] - window['reactor_pressure'].iloc[-1], 4),
            'ph_start':                             window['酸鹼值 (pH)'].iloc[0],
            'ph_change_in_window':                 round(window['酸鹼值 (pH)'].iloc[-1] - window['酸鹼值 (pH)'].iloc[0], 4),
            'orp_start':                            window['ORP (mV)'].iloc[0],
            'orp_change_in_window':                round(window['ORP (mV)'].iloc[-1] - window['ORP (mV)'].iloc[0], 1),
            'orp_min_in_window':                   window['ORP (mV)'].min(),
        })
    return pd.DataFrame(rows)


def summarize_file(path: str, min_change: float = 0.5) -> dict:
    """單一檔案的統計概覽（不輸出逐分鐘/逐區間細節），用於資料夾批次掃描先建立全貌。"""
    df = load_csv(path)
    row = {
        'file':            os.path.basename(path),
        'rows':            len(df),
        'start':           df['timestamp'].iloc[0],
        'end':             df['timestamp'].iloc[-1],
        'reactor_p_min':   df['reactor_pressure'].min(),
        'reactor_p_max':   df['reactor_pressure'].max(),
        'reactor_p_mean':  df['reactor_pressure'].mean(),
        'co2_min':         df['co2_pct'].min(),
        'co2_max':         df['co2_pct'].max(),
        'ch4_min':         df['ch4_pct'].min(),
        'ch4_max':         df['ch4_pct'].max(),
        'n_events':        None,
        'mean_interval_min':          None,
        'mean_delta_ch4_rel':         None,
        'mean_delta_co2_dissolved_rel': None,
    }
    try:
        intervals = compute_intervals(df, min_change=min_change)
        row['n_events'] = len(intervals) + 1
        row['mean_interval_min'] = intervals['duration_min'].mean()
        row['mean_delta_ch4_rel'] = intervals['delta_ch4_rel'].mean()
        row['mean_delta_co2_dissolved_rel'] = intervals['delta_co2_dissolved_rel'].mean()
    except ValueError:
        pass
    return row


def summarize_folder(folder: str, min_change: float = 0.5) -> pd.DataFrame:
    files = sorted(f for f in glob.glob(os.path.join(folder, '*.csv'))
                   if not os.path.basename(f).startswith('_'))
    if not files:
        raise ValueError(f"{folder} 底下找不到任何 CSV 檔案")

    rows = []
    for f in files:
        try:
            rows.append(summarize_file(f, min_change=min_change))
        except Exception as e:
            rows.append({'file': os.path.basename(f), 'rows': 0, 'error': str(e)})
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="CO2 溶解/生物消耗定量分離分析（相對單位，未乘 V_gas/R）")
    parser.add_argument('--csv', default=None, help="單一 BTP_Sensor_log CSV 檔案路徑")
    parser.add_argument('--folder', default=None,
                         help="資料夾批次模式：掃描資料夾下所有 CSV。與 --csv 二擇一，"
                              "行為由 --folder-mode 決定。")
    parser.add_argument('--folder-mode',
                         choices=['daily_summary', 'combined_interval', 'pressure_interval', 'feature_table'],
                         default='daily_summary',
                         help="daily_summary（預設）：逐檔案算每日統計概覽，跨天的靜止期會被切斷；"
                              "combined_interval：串成連續時間軸、用 CO2%%/CH4%% 跳動切事件邊界；"
                              "pressure_interval：串成連續時間軸、改用壓力補氣跳升切邊界，"
                              "輸出每段補氣週期的壓力/ORP/pH 斜率與 likely_circulating 候選標記；"
                              "feature_table：合併上述兩種邊界，輸出統一特徵表（每段都有連續訊號"
                              "斜率，剛好對到真正 CO2/CH4 讀數更新的段落另外附上質量守恆數字當"
                              "交叉驗證標籤，此為模型化之前的特徵基礎）。")
    parser.add_argument('--mode', choices=['interval', 'per_minute'], default='interval',
                         help="interval（預設）：自動偵測 CO2%%/CH4%% 真正更新的時刻，只在相鄰兩次"
                              "更新之間算總量，並附上區間內 ORP/壓力/pH 斜率；"
                              "per_minute：假設 CO2%%/CH4%% 逐分鐘連續有效（適用於循環路徑本身"
                              "會經過感測器、讀數確實連續變化的資料，例如 04-20 那份歷史檔案）。")
    parser.add_argument('--min-change', type=float, default=0.5,
                         help="interval 模式：CO2%% 或 CH4%% 變化超過這個百分點才視為一次真正更新（預設 0.5）")
    parser.add_argument('--start', default=None,
                         help="分析區間起點，格式 'YYYY-MM-DD HH:MM:SS'，不指定則用檔案第一筆。"
                              "per_minute 模式務必指定為單一週期內的起點，跨過進氣事件會讓質量守恆失真。")
    parser.add_argument('--end', default=None, help="分析區間終點，格式同 --start，不指定則到檔案結尾")
    parser.add_argument('--min-jump', type=float, default=0.05,
                         help="pressure_interval 模式：壓力單步跳升超過這個值才視為一次補氣事件（預設 0.05）")
    args = parser.parse_args()

    if args.folder:
        pd.set_option('display.width', 200)
        if args.folder_mode == 'combined_interval':
            combined = load_folder_combined(args.folder)
            result = compute_intervals(combined, min_change=args.min_change)
            print(result.to_string(index=False))
            out_path = os.path.join(args.folder, '_combined_intervals.csv')
            result.to_csv(out_path, index=False, encoding='utf-8-sig')
            print(f"\n已輸出：{out_path}")
        elif args.folder_mode == 'pressure_interval':
            combined = load_folder_combined(args.folder)
            result = compute_pressure_intervals(combined, min_jump=args.min_jump)
            print(result.to_string(index=False))
            out_path = os.path.join(args.folder, '_pressure_intervals.csv')
            result.to_csv(out_path, index=False, encoding='utf-8-sig')
            print(f"\n已輸出：{out_path}")
            n_circ = int(result['likely_circulating'].sum())
            print(f"\n候選有循環區間：{n_circ} / {len(result)}")
        elif args.folder_mode == 'feature_table':
            combined = load_folder_combined(args.folder)
            result = build_feature_table(combined, min_change=args.min_change, min_jump=args.min_jump)
            print(result.to_string(index=False))
            out_path = os.path.join(args.folder, '_feature_table.csv')
            result.to_csv(out_path, index=False, encoding='utf-8-sig')
            print(f"\n已輸出：{out_path}")
            n_gt = int(result['has_co2_ground_truth'].sum())
            print(f"\n有 CO2/CH4 真實讀數可交叉驗證的區段：{n_gt} / {len(result)}")
            if n_gt >= 3:
                gt = result[result['has_co2_ground_truth']]
                print("\n交叉驗證相關係數（樣本數過少時僅供參考）：")
                print(f"  ph_slope_per_hr vs delta_co2_dissolved_rel: {gt['ph_slope_per_hr'].corr(gt['delta_co2_dissolved_rel']):.3f}")
                print(f"  orp_slope_per_hr vs delta_ch4_rel:          {gt['orp_slope_per_hr'].corr(gt['delta_ch4_rel']):.3f}")

                calib = calibrate_m_k(result)
                if calib:
                    print(f"\n粗估 m（ORP→r_b）與 k（pH→淨溶解池變化），樣本數={calib['n_samples']}"
                          f"（m 用了 {calib['n_valid_m']} 筆、k 用了 {calib['n_valid_k']} 筆，僅供 sanity check）：")
                    print(f"  m_est = {calib['m_est']:.4f}   k_est = {calib['k_est']:.4f}")
                    if not (np.isnan(calib['m_est']) or np.isnan(calib['k_est'])):
                        solved = apply_solver(result, m=calib['m_est'], k=calib['k_est'])
                        out_path2 = os.path.join(args.folder, '_feature_table_solved.csv')
                        solved.to_csv(out_path2, index=False, encoding='utf-8-sig')
                        print(f"已輸出：{out_path2}")

                        neg_rd = int((solved['r_d_solved'] < 0).sum())
                        neg_rb = int((solved['r_b_solved'] < 0).sum())
                        print(f"\n全部 {len(solved)} 段套用求解結果：")
                        print(f"  r_d_solved < 0（不合理，溶解速率不該為負）的段數：{neg_rd} / {len(solved)}")
                        print(f"  r_b_solved < 0（不合理，生物消耗速率不該為負）的段數：{neg_rb} / {len(solved)}")
                        resid = solved['ph_residual'].dropna()
                        if len(resid) >= 3:
                            print(f"  pH 殘差（實測−預測，n={len(resid)}）：mean={resid.mean():.4f}  std={resid.std():.4f}")
                else:
                    print("\nground truth 樣本數不足（<3），無法粗估 m、k")
        else:
            summary = summarize_folder(args.folder, min_change=args.min_change)
            print(summary.to_string(index=False))
            out_path = os.path.join(args.folder, '_folder_summary.csv')
            summary.to_csv(out_path, index=False, encoding='utf-8-sig')
            print(f"\n已輸出：{out_path}")
        return

    if not args.csv:
        print("[錯誤] 請指定 --csv 或 --folder 其中一個")
        sys.exit(1)

    df = load_csv(args.csv)
    if args.start:
        df = df[df['timestamp'] >= pd.Timestamp(args.start)].reset_index(drop=True)
    if args.end:
        df = df[df['timestamp'] <= pd.Timestamp(args.end)].reset_index(drop=True)
    if df.empty:
        print("[錯誤] 指定的時間區間內沒有資料")
        sys.exit(1)

    if args.mode == 'interval':
        result = compute_intervals(df, min_change=args.min_change)
        print(result.to_string(index=False))
        out_path = args.csv.rsplit('.', 1)[0] + '_co2_intervals.csv'
    else:
        result = compute_separation(df)
        cols = ['timestamp', 'reactor_pressure', 'co2_pct', 'ch4_pct',
                'delta_ch4_rel', 'delta_co2_total_lost_rel', 'delta_co2_dissolved_rel']
        result = result[cols]
        print(result.to_string(index=False))
        out_path = args.csv.rsplit('.', 1)[0] + '_co2_separation.csv'

    result.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\n已輸出：{out_path}")


if __name__ == '__main__':
    main()
