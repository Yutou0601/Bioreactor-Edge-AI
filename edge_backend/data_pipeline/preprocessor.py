import numpy as np
import joblib
import os
from sklearn.preprocessing import MinMaxScaler


def _ema_series(values, alpha):
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return np.array(out)


def engineer_features(df):
    """
    從原始 ORP 衍生三個訊號特徵，並加入當前壓力作為輸入。
    必須在 fit_and_save_scalers 之前呼叫。

    新增欄位：
      orp_ema   — EMA(10)，平滑後的 ORP
      orp_slope — (ema[t] - ema[t-5]) / 5，mV/min，趨勢斜率
      orp_macd  — EMA(5) - EMA(30)，短長期動能差
    """
    df = df.copy()
    orp = df['ORP (mV)'].values.astype(float)
    n   = len(orp)

    ema10 = _ema_series(orp, 2 / 11)
    ema5  = _ema_series(orp, 2 / 6)
    ema30 = _ema_series(orp, 2 / 31)

    slopes        = np.zeros(n)
    slopes[5:]    = (ema10[5:] - ema10[:-5]) / 5   # mV/min

    df['orp_ema']   = ema10
    df['orp_slope'] = slopes
    df['orp_macd']  = ema5 - ema30
    return df


def create_sequences(data, target, seq_length=30, predict_ahead=5):
    """將連續資料切割成 LSTM 需要的滑動視窗 (Sliding Window)"""
    xs, ys = [], []
    for i in range(len(data) - seq_length - predict_ahead):
        xs.append(data[i:(i + seq_length)])
        ys.append(target[i + seq_length + predict_ahead])
    return np.array(xs), np.array(ys)

def fit_and_save_scalers(df, features, target_cols, save_dir="core/weights"):
    """訓練時使用：計算比例尺，並將其存為 .pkl 檔"""
    os.makedirs(save_dir, exist_ok=True)
    scaler_x = MinMaxScaler()
    scaler_y = MinMaxScaler()
    
    if isinstance(target_cols, str):
        target_cols = [target_cols]
        
    data_x = scaler_x.fit_transform(df[features].values)
    data_y = scaler_y.fit_transform(df[target_cols].values)
    
    # 儲存比例尺，供未來 API 推論使用
    joblib.dump(scaler_x, os.path.join(save_dir, 'scaler_x.pkl'))
    joblib.dump(scaler_y, os.path.join(save_dir, 'scaler_y.pkl'))
    
    return data_x, data_y

def load_scalers(save_dir="core/weights"):
    """推論時使用：直接載入訓練好的比例尺"""
    scaler_x = joblib.load(os.path.join(save_dir, 'scaler_x.pkl'))
    scaler_y = joblib.load(os.path.join(save_dir, 'scaler_y.pkl'))
    return scaler_x, scaler_y