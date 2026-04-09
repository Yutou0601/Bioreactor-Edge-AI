import pandas as pd
import glob

def load_all_data(data_dir="data/*.csv"):
    """讀取指定目錄下所有的 CSV 感測器資料，並自動處理標題列"""
    all_files = glob.glob(data_dir)
    columns = ['年', '月', '日', '時', '分', '秒', '_', 'ORP (mV)', '反應器壓力 (kg/cm²)', 
               '酸鹼值 (pH)', '溫度 (°C)', '混合槽壓力 (kg/cm²)', 'CO2濃度 (%)', 'CH4濃度 (%)']
    
    df_list = []
    for file in all_files:
        temp_df = pd.read_csv(file, nrows=1)
        if '年' in temp_df.columns or (len(temp_df) > 0 and str(temp_df.iloc[0, 0]) == '年'):
            df = pd.read_csv(file)
        else:
            df = pd.read_csv(file, header=None, names=columns)
        df_list.append(df)
        
    if not df_list:
        raise ValueError(f"在 {data_dir} 找不到任何 CSV 檔案！請確認路徑。")
        
    combined_df = pd.concat(df_list, ignore_index=True)
    combined_df = combined_df.sort_values(by=['月', '日', '時', '分', '秒'])
    
    return combined_df