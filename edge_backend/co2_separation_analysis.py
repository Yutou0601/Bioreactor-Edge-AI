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
    x_min = (x - x.iloc[0]).dt.total_seconds() / 60.0
    return float(np.polyfit(x_min, y, 1)[0])


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
    files = sorted(glob.glob(os.path.join(folder, '*.csv')))
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
                         help="資料夾批次模式：掃描資料夾下所有 CSV，輸出每日統計概覽"
                              "（壓力/CO2/CH4 範圍、事件數、平均區間長度與平均溶解/消耗量），"
                              "不輸出逐分鐘細節。與 --csv 二擇一。")
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
    args = parser.parse_args()

    if args.folder:
        summary = summarize_folder(args.folder, min_change=args.min_change)
        pd.set_option('display.width', 200)
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
