import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import glob

# ==========================================
# 1. 繪圖環境設定 (Configuration)
# ==========================================
plt.rcParams['font.sans-serif'] = ['Arial', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False 

try:
    plt.style.use('seaborn-v0_8-darkgrid')
except OSError:
    try:
        plt.style.use('seaborn-darkgrid')
    except OSError:
        plt.style.use('ggplot')

# ==========================================
# 2. 自動讀取真實資料 (Data Loading & Processing)
# ==========================================
print("Loading CSV files...")
files = glob.glob("data/BTP_Sensor_log-*.csv")
df_list = []
columns = ['年', '月', '日', '時', '分', '秒', '_', 'ORP (mV)', '反應器壓力 (kg/cm²)', '酸鹼值 (pH)', '溫度 (°C)', '混合槽壓力 (kg/cm²)', 'CO2濃度 (%)', 'CH4濃度 (%)']

for f in files:
    try:
        with open(f, 'r', encoding='utf-8') as file:
            first_line = file.readline()
        # 兼容有標題與無標題的 CSV 格式
        if '年' in first_line:
            temp_df = pd.read_csv(f)
        else:
            temp_df = pd.read_csv(f, names=columns)
        df_list.append(temp_df)
    except Exception as e:
        print(f"Error reading {f}: {e}")

df = pd.concat(df_list, ignore_index=True)

# 將時間欄位合併為標準 Datetime 格式
df['Datetime'] = pd.to_datetime(df[['年', '月', '日', '時', '分', '秒']].rename(
    columns={'年': 'year', '月': 'month', '日': 'day', '時': 'hour', '分': 'minute', '秒': 'second'}
))
df = df.sort_values('Datetime').reset_index(drop=True)

# ==========================================
# 3. 萃取發生壓力暴增的視窗 (Feb 13, 09:00 - 10:00)
# ==========================================
# 真實事件：在 09:32 發生壓力由 1.08 飆升至 2.99
mask = (df['Datetime'] >= '2026-02-13 09:00:00') & (df['Datetime'] <= '2026-02-13 10:00:00')
plot_df = df[mask].copy()

# 將 Datetime 轉換為相對的分鐘數 (0 到 60 分鐘)，方便簡報呈現
start_time = plot_df['Datetime'].iloc[0]
plot_df['Relative_Minutes'] = (plot_df['Datetime'] - start_time).dt.total_seconds() / 60.0

# ==========================================
# 4. 繪製圖表：Biological Imbalance (使用真實數據)
# ==========================================
fig, ax1 = plt.subplots(figsize=(10, 6))

# 設定左 Y 軸 (pH 值)
color_ph = '#3498db'
ax1.set_xlabel('Time (Minutes)', fontsize=12)
ax1.set_ylabel('pH Level', color=color_ph, fontsize=12)

# 繪製【真實 pH 數據】
ax1.plot(plot_df['Relative_Minutes'].to_numpy(), plot_df['酸鹼值 (pH)'].to_numpy(), color=color_ph, linewidth=2.5, label='Actual pH Trend')
ax1.tick_params(axis='y', labelcolor=color_ph)

# 固定 Y 軸範圍，確保 pH = 6.5 的危險線能清楚顯示
ax1.set_ylim(6.4, 7.4)
ax1.axhline(y=6.5, color='gray', linestyle='--', alpha=0.7)
ax1.text(2, 6.55, 'pH Danger Threshold', color='gray')

# 設定右 Y 軸 (反應器壓力)
ax2 = ax1.twinx()  
color_press = '#e74c3c'
ax2.set_ylabel('Reactor Pressure (kg/cm²)', color=color_press, fontsize=12)

# 繪製【真實壓力數據】
ax2.plot(plot_df['Relative_Minutes'].to_numpy(), plot_df['反應器壓力 (kg/cm²)'].to_numpy(), color=color_press, linewidth=2.5, label='Actual System Pressure')
ax2.tick_params(axis='y', labelcolor=color_press)

# 動態尋找壓力飆升的起點，並標示危險紅色區塊
spike_start = plot_df[plot_df['反應器壓力 (kg/cm²)'] > 2.0]['Relative_Minutes'].min()
if pd.notna(spike_start):
    ax2.axvspan(spike_start - 2, plot_df['Relative_Minutes'].max(), color='red', alpha=0.1)
    ax2.text(spike_start + 1, 2.5, 'Hazardous Gas\nExpansion Zone', color='darkred', fontsize=12, fontweight='bold')

# 設定標題與合併圖例
ax1.set_title('Impact of Biological Imbalance on Reactor Pressure (Real Data)', fontsize=15, fontweight='bold', pad=15)

lines_1, labels_1 = ax1.get_legend_handles_labels()
lines_2, labels_2 = ax2.get_legend_handles_labels()
ax2.legend(lines_1 + lines_2, labels_1 + labels_2, loc='center left')

# ==========================================
# 5. 排版輸出與存檔
# ==========================================
fig.tight_layout()
fig.savefig('1_RealData_Biological_Imbalance.png', dpi=300, bbox_inches='tight')
plt.close()

print("✅ Standalone graph 1 (Real Data) generated successfully!")