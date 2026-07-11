import pandas as pd
import glob

LEGACY_COLUMNS = ['年', '月', '日', '時', '分', '秒', '_', 'ORP (mV)', '反應器壓力 (kg/cm²)',
                   '酸鹼值 (pH)', '溫度 (°C)', '混合槽壓力 (kg/cm²)', 'CO2濃度 (%)', 'CH4濃度 (%)']

# usb_receiver.py::_write_csv_row 產生的每日備份 CSV 欄位（已完成訊號前處理）
BTP_NUMERIC_COLUMNS = ['orp', 'orp_raw', 'orp_cleaned', 'pressure', 'ph', 'temp',
                        'mixer_pressure', 'co2_pct', 'ch4_pct']


def _detect_schema(first_line: str) -> str:
    """依標題列判斷來源檔案格式：
    - 'btp_daily'         : usb_receiver.py 每日備份 CSV（含 timestamp/orp_raw 等英文標題）
    - 'legacy_header'      : 舊格式，含中文標題列（年/月/日/...）
    - 'legacy_headerless'  : 舊格式，無標題列，14 欄依序對應 LEGACY_COLUMNS
    """
    tokens = [t.strip() for t in first_line.strip().split(',')]
    if 'timestamp' in tokens and 'orp_raw' in tokens:
        return 'btp_daily'
    if '年' in tokens:
        return 'legacy_header'
    return 'legacy_headerless'


def read_btp_daily(path_or_buffer) -> pd.DataFrame:
    """讀取 usb_receiver.py / BTP_Sensor_log-*.csv 格式，欄位名稱維持原樣（不改名）。

    用於即時後端（sensor_records 已使用同一組欄位名稱，可直接沿用）；
    離線分析管線請改用 read_btp_daily_as_legacy()。
    """
    df = pd.read_csv(path_or_buffer, encoding='utf-8-sig')
    for col in BTP_NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    # orp_raw 缺值代表該行寫入中途被截斷（例如分析腳本讀到 usb_receiver.py 正在寫入的當日檔案）
    df = df.dropna(subset=['orp_raw']).reset_index(drop=True)
    if 'is_anomaly' in df.columns:
        df['is_anomaly'] = df['is_anomaly'].astype(str).str.strip().str.lower().isin(
            ['true', '1', 'yes'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


def read_btp_daily_as_legacy(path_or_buffer) -> pd.DataFrame:
    """讀取 BTP_Sensor_log 格式並轉換成離線分析管線（loader/ch4_peak_analysis）
    期待的舊版中文欄位格式，供 load_all_data() 內部使用。
    """
    df = read_btp_daily(path_or_buffer)
    out = pd.DataFrame({
        '年':  df['timestamp'].dt.year,
        '月':  df['timestamp'].dt.month,
        '日':  df['timestamp'].dt.day,
        '時':  df['timestamp'].dt.hour,
        '分':  df['timestamp'].dt.minute,
        '秒':  df['timestamp'].dt.second,
        '_':  0,
        # orp_cleaned：已做突波內插修正、但未經 EMA 平滑，語意上最接近舊版 'ORP (mV)' 欄位
        'ORP (mV)':          df['orp_cleaned'],
        '反應器壓力 (kg/cm²)': df['pressure'],
        '酸鹼值 (pH)':        df['ph'],
        '溫度 (°C)':          df['temp'],
        '混合槽壓力 (kg/cm²)': df['mixer_pressure'],
        'CO2濃度 (%)':        df['co2_pct'],
        'CH4濃度 (%)':        df['ch4_pct'],
    })
    if 'is_anomaly' in df.columns:
        out['is_anomaly'] = df['is_anomaly'].values
    if 'note' in df.columns:
        out['note'] = df['note'].values
    out['source_schema'] = 'btp_daily'
    return out


def load_all_data(data_dir="data/*.csv"):
    """讀取指定目錄下所有的 CSV 感測器資料，自動判斷格式（BTP 每日備份 / 舊版中文欄位）並合併"""
    all_files = glob.glob(data_dir)

    df_list = []
    for file in all_files:
        with open(file, 'r', encoding='utf-8-sig') as f:
            first_line = f.readline()
        schema = _detect_schema(first_line)

        if schema == 'btp_daily':
            df = read_btp_daily_as_legacy(file)
        elif schema == 'legacy_header':
            df = pd.read_csv(file)
        else:
            df = pd.read_csv(file, header=None, names=LEGACY_COLUMNS)
        df_list.append(df)

    if not df_list:
        raise ValueError(f"在 {data_dir} 找不到任何 CSV 檔案！請確認路徑。")

    combined_df = pd.concat(df_list, ignore_index=True, sort=False)
    combined_df = combined_df.sort_values(by=['年', '月', '日', '時', '分', '秒'])
    combined_df = combined_df.drop_duplicates(
        subset=['年', '月', '日', '時', '分', '秒'], keep='last'
    ).reset_index(drop=True)

    return combined_df
