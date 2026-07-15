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

使用方式：
    python co2_separation_analysis.py --csv "C:\\path\\to\\BTP_Sensor_log-2026-04-20.csv"
"""

import argparse
import sys
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


def main():
    parser = argparse.ArgumentParser(description="CO2 溶解/生物消耗定量分離分析（相對單位，未乘 V_gas/R）")
    parser.add_argument('--csv', required=True, help="BTP_Sensor_log CSV 檔案路徑")
    parser.add_argument('--start', default=None,
                         help="分析區間起點（單一週期的 t0，例如進氣完成時間），格式 'YYYY-MM-DD HH:MM:SS'。"
                              "不指定則用檔案第一筆——注意：若區間跨過進氣事件，質量守恆會失真，"
                              "務必指定為單一週期內的起點。")
    parser.add_argument('--end', default=None, help="分析區間終點，格式同 --start，不指定則到檔案結尾")
    args = parser.parse_args()

    df = load_csv(args.csv)
    if args.start:
        df = df[df['timestamp'] >= pd.Timestamp(args.start)].reset_index(drop=True)
    if args.end:
        df = df[df['timestamp'] <= pd.Timestamp(args.end)].reset_index(drop=True)
    if df.empty:
        print("[錯誤] 指定的時間區間內沒有資料")
        sys.exit(1)

    result = compute_separation(df)

    cols = ['timestamp', 'reactor_pressure', 'co2_pct', 'ch4_pct',
            'delta_ch4_rel', 'delta_co2_total_lost_rel', 'delta_co2_dissolved_rel']
    print(result[cols].to_string(index=False))

    out_path = args.csv.rsplit('.', 1)[0] + '_co2_separation.csv'
    result[cols].to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\n已輸出：{out_path}")


if __name__ == '__main__':
    main()
