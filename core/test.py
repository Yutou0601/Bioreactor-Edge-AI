# -*- coding: utf-8 -*-
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os

# 設定中文字型 (Windows 常見的微軟正黑體)
plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei', 'Arial']
plt.rcParams['axes.unicode_minus'] = False # 解決負號變方塊的問題

csv_path = r"C:\Users\User\Desktop\NKUST\金屬中心\專題\Bioreactor-Edge-AI\pic\processed_data_with_diffs.csv"
output_dir = r"C:\Users\User\Desktop\NKUST\金屬中心\專題\Bioreactor-Edge-AI\pic"

print("正在讀取先前處理過的資料...")
try:
    df = pd.read_csv(csv_path)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime')
    df = df.sort_index()

    # 擷取最後 3 天的資料作為變化分析
    last_date = df.index.max()
    start_date = last_date - pd.Timedelta(days=3)
    df_3d = df.loc[start_date:last_date]
    
    print(f"篩選出最後 3 天的區段: {start_date.strftime('%Y-%m-%d %H:%M:%S')} ~ {last_date.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"該區段共有 {len(df_3d)} 筆數據。")
    print("資料讀取完成，開始繪製圖表...")

    # 共用 X 軸時間格式設定函式 (針對 3 天，顯示到 月-日 小時:分)
    def format_x_axis(ax):
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

    # 1. 繪製 ORP 原始資料與變化量 (3天)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    ax1.plot(df_3d.index, df_3d['ORP (mV)'], color='blue', alpha=0.8, linewidth=1.5)
    ax1.set_title('ORP (mV) 趨勢變化 (最後 3 天)', fontsize=15, fontweight='bold')
    ax1.set_ylabel('ORP (mV)', fontsize=13)
    ax1.grid(True, linestyle='--', alpha=0.6)

    ax2.plot(df_3d.index, df_3d['ORP變化量'], color='orange', alpha=0.8, linewidth=1.5)
    ax2.set_title('ORP 單步變化量 (最後 3 天)', fontsize=15, fontweight='bold')
    ax2.set_ylabel('變化量 (mV)', fontsize=13)
    ax2.set_xlabel('時間', fontsize=13)
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.axhline(y=0, color='black', alpha=0.5, linestyle='-') # 加入 0 基準線

    format_x_axis(ax2)
    plt.tight_layout()
    orp_path = os.path.join(output_dir, 'ORP_Chart_3Days.png')
    plt.savefig(orp_path, dpi=150)
    plt.close()
    print(f"已儲存圖表: ORP_Chart_3Days.png")

    # 2. 繪製 反應器壓力 原始資料與變化量 (3天)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    ax1.plot(df_3d.index, df_3d['反應器壓力 (kg/cm²)'], color='green', alpha=0.8, linewidth=1.5)
    ax1.set_title('反應器壓力 趨勢變化 (最後 3 天)', fontsize=15, fontweight='bold')
    ax1.set_ylabel('壓力 (kg/cm²)', fontsize=13)
    ax1.grid(True, linestyle='--', alpha=0.6)

    ax2.plot(df_3d.index, df_3d['反應器壓力變化量'], color='red', alpha=0.8, linewidth=1.5)
    ax2.set_title('反應器壓力 變化量 (最後 3 天)', fontsize=15, fontweight='bold')
    ax2.set_ylabel('變化量 (kg/cm²)', fontsize=13)
    ax2.set_xlabel('時間', fontsize=13)
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.axhline(y=0, color='black', alpha=0.5, linestyle='-')

    format_x_axis(ax2)
    plt.tight_layout()
    pressure_reactor_path = os.path.join(output_dir, 'Reactor_Pressure_Chart_3Days.png')
    plt.savefig(pressure_reactor_path, dpi=150)
    plt.close()
    print(f"已儲存圖表: Reactor_Pressure_Chart_3Days.png")

    # 3. 繪製 混合槽壓力 原始資料與變化量 (3天)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    ax1.plot(df_3d.index, df_3d['混合槽壓力 (kg/cm²)'], color='purple', alpha=0.8, linewidth=1.5)
    ax1.set_title('混合槽壓力 趨勢變化 (最後 3 天)', fontsize=15, fontweight='bold')
    ax1.set_ylabel('壓力 (kg/cm²)', fontsize=13)
    ax1.grid(True, linestyle='--', alpha=0.6)

    ax2.plot(df_3d.index, df_3d['混合槽壓力變化量'], color='brown', alpha=0.8, linewidth=1.5)
    ax2.set_title('混合槽壓力 變化量 (最後 3 天)', fontsize=15, fontweight='bold')
    ax2.set_ylabel('變化量 (kg/cm²)', fontsize=13)
    ax2.set_xlabel('時間', fontsize=13)
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.axhline(y=0, color='black', alpha=0.5, linestyle='-')

    format_x_axis(ax2)
    plt.tight_layout()
    pressure_mixer_path = os.path.join(output_dir, 'Mixer_Pressure_Chart_3Days.png')
    plt.savefig(pressure_mixer_path, dpi=150)
    plt.close()
    print(f"已儲存圖表: Mixer_Pressure_Chart_3Days.png")

    print("\n所有 3 天微觀圖表輸出完畢！")

except Exception as e:
    print(f"發生錯誤: {e}")
