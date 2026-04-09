import torch
import numpy as np
import pandas as pd
import glob
from core.model import ReactorLSTM
from data_pipeline.preprocessor import load_scalers

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = None
scaler_x = None
scaler_y = None
features = ['ORP (mV)', '酸鹼值 (pH)', '溫度 (°C)']

def load_model_and_scalers():
    """系統啟動時呼叫：瞬間載入大腦與比例尺檔案"""
    global model, scaler_x, scaler_y
    
    # 載入模型
    model = ReactorLSTM(input_size=len(features)).to(device)
    model.load_state_dict(torch.load("core/weights/reactor_lstm_weights.pth", map_location=device))
    model.eval()
    
    # 直接讀取存好的比例尺，不用再重讀幾萬筆 CSV 了！
    scaler_x, scaler_y = load_scalers("core/weights")

def get_pressure_prediction():
    """執行推論並回傳結果"""
    # 實務上：只抓取最新的那一個檔案，或是直接接感測器串流
    all_files = sorted(glob.glob("data/*.csv"))
    latest_file = all_files[-1] # 只拿最後一個檔案
    
    df = pd.read_csv(latest_file)
    if df.columns[0] != '年':
        columns = ['年','月','日','時','分','秒','_','ORP (mV)','反應器壓力 (kg/cm²)','酸鹼值 (pH)','溫度 (°C)','混合槽壓力 (kg/cm²)','CO2濃度 (%)','CH4濃度 (%)']
        df = pd.read_csv(latest_file, header=None, names=columns)
        
    # 只拿檔案最後 30 筆資料就夠了
    recent_data = df[features].tail(30).values
    current_pressure = float(df['反應器壓力 (kg/cm²)'].iloc[-1])
    
    # 使用預先載入的 scaler 轉換
    recent_data_scaled = scaler_x.transform(recent_data)
    input_tensor = torch.tensor(np.array([recent_data_scaled]), dtype=torch.float32).to(device)
    
    with torch.no_grad():
        prediction_scaled = model(input_tensor)
        
    future_pressure = float(scaler_y.inverse_transform(prediction_scaled.cpu().numpy())[0][0])
    status = "危險 (Danger)" if future_pressure > 2.6 else "正常 (Normal)"
    
    return {
        "current_pressure_kg_cm2": current_pressure,
        "predicted_pressure_5min": future_pressure,
        "status": status
    }