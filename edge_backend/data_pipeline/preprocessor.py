import numpy as np
import joblib
import os
from sklearn.preprocessing import MinMaxScaler

def create_sequences(data, target, seq_length=30, predict_ahead=5):
    """將連續資料切割成 LSTM 需要的滑動視窗 (Sliding Window)"""
    xs, ys = [], []
    for i in range(len(data) - seq_length - predict_ahead):
        xs.append(data[i:(i + seq_length)])
        ys.append(target[i + seq_length + predict_ahead])
    return np.array(xs), np.array(ys)

def fit_and_save_scalers(df, features, target_col, save_dir="core/weights"):
    """訓練時使用：計算比例尺，並將其存為 .pkl 檔"""
    os.makedirs(save_dir, exist_ok=True)
    scaler_x = MinMaxScaler()
    scaler_y = MinMaxScaler()
    
    data_x = scaler_x.fit_transform(df[features].values)
    data_y = scaler_y.fit_transform(df[[target_col]].values)
    
    # 儲存比例尺，供未來 API 推論使用
    joblib.dump(scaler_x, os.path.join(save_dir, 'scaler_x.pkl'))
    joblib.dump(scaler_y, os.path.join(save_dir, 'scaler_y.pkl'))
    
    return data_x, data_y

def load_scalers(save_dir="core/weights"):
    """推論時使用：直接載入訓練好的比例尺"""
    scaler_x = joblib.load(os.path.join(save_dir, 'scaler_x.pkl'))
    scaler_y = joblib.load(os.path.join(save_dir, 'scaler_y.pkl'))
    return scaler_x, scaler_y