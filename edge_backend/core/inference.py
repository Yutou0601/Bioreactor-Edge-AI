import torch
import numpy as np
from collections import deque
from core.model import ReactorLSTM
from data_pipeline.preprocessor import load_scalers

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = None
scaler_x = None
scaler_y = None
features = ['ORP (mV)', '酸鹼值 (pH)', '溫度 (°C)']

# ==========================================
# 邊緣運算記憶體設定
# ==========================================
# 建立一個最多裝 30 筆的暫存區，超過會自動把最舊的擠掉 (FIFO)
sensor_buffer = deque(maxlen=30)

# 用來記錄最新收到的真實壓力 (如果 MQTT 沒傳，我們用模擬公式代替)
latest_actual_pressure = 0.0

def load_model_and_scalers():
    """系統啟動時呼叫：瞬間載入大腦與比例尺檔案"""
    global model, scaler_x, scaler_y
    
    # 載入模型
    model = ReactorLSTM(input_size=len(features), output_size=2).to(device)
    model.load_state_dict(torch.load("core/weights/reactor_lstm_weights.pth", map_location=device))
    model.eval()
    
    # 載入比例尺
    scaler_x, scaler_y = load_scalers("core/weights")
    print("[AI 核心] 模型與 Scaler 已成功載入 GPU/CPU 記憶體！")

def get_pressure_prediction(new_sensor_data=None):
    """執行即時推論並回傳結果"""
    global latest_actual_pressure
    
    if model is None or scaler_x is None or scaler_y is None:
        raise Exception("模型或比例尺尚未載入，請確認啟動流程！")

    # 1. 處理新收到的串流數據
    if new_sensor_data:
        # ⚠️ 提取特徵，注意順序要跟訓練時的 CSV 完全一樣！
        features_values = [
            new_sensor_data['orp'],
            new_sensor_data['ph'],
            new_sensor_data['temp']
        ]
        sensor_buffer.append(features_values)
        
        # 取得當前壓力 (如果感測器沒有傳壓力，我們用溫度做一個簡單的模擬值)
        latest_actual_pressure = new_sensor_data.get('pressure', 2.0 + (new_sensor_data['temp'] - 35.0) * 0.1)

    # 2. 檢查：資料湊滿 30 筆了嗎？
    if len(sensor_buffer) < 30:
        return {
            "current_pressure_kg_cm2": round(latest_actual_pressure, 2),
            "predicted_pressure_5min": 0.0,
            "status": f"資料緩衝中 ({len(sensor_buffer)}/30)"
        }

    # ==========================================
    # 3. 真實 AI 推論 Pipeline 
    # ==========================================
    # 轉成 numpy 陣列 (形狀: 30, 3)
    recent_data = np.array(sensor_buffer)
    
    # 使用預先載入的 scaler_x 轉換
    recent_data_scaled = scaler_x.transform(recent_data)
    
    # 轉成 PyTorch Tensor，增加 batch 維度 (形狀: 1, 30, 3)
    input_tensor = torch.tensor(np.array([recent_data_scaled]), dtype=torch.float32).to(device)
    
    # 執行神經網路推論
    with torch.no_grad():
        prediction_scaled = model(input_tensor)
        
    # 使用 scaler_y 將預測出的 0~1 數值還原 (會得到 [Pressure, CH4])
    predictions_unscaled = scaler_y.inverse_transform(prediction_scaled.cpu().numpy())
    future_pressure = float(predictions_unscaled[0][0])
    future_ch4 = float(predictions_unscaled[0][1])
    
    # 狀態判定 (超過 2.6 即亮紅燈)
    status = "危險 (Danger)" if future_pressure > 2.6 else "正常 (Normal)"
    
    return {
        "current_pressure_kg_cm2": round(latest_actual_pressure, 2),
        "predicted_pressure_5min": round(future_pressure, 2),
        "predicted_ch4_5min": round(future_ch4, 2),
        "status": status
    }