import os
import torch
import numpy as np
from collections import deque
from core.model import ReactorLSTM
from data_pipeline.preprocessor import load_scalers

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # edge_backend/
_WEIGHTS_DIR = os.path.join(_BASE_DIR, "core", "weights")

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model    = None
scaler_x = None
scaler_y = None

# ── 特徵定義（須與 train.py 完全一致）──────────────────────
FEATURES   = ['orp_ema', 'orp_slope', 'orp_macd', 'ph', 'temp', 'pressure']
INPUT_SIZE = len(FEATURES)   # 6
SEQ_LEN    = 30              # LSTM 輸入視窗
WARMUP     = 5               # slope 計算所需的額外前置點數
MIN_BUF    = SEQ_LEN + WARMUP  # 35 筆才能開始推論

# ── 原始資料緩衝區：存 [orp_raw, ph, temp, pressure] ──────
sensor_buffer = deque(maxlen=65)
latest_actual_pressure = 0.0

# ── 推論結果追蹤（用於遲滯 + 輸出平滑）─────────────────────
_pred_history       = deque(maxlen=3)   # 最近 3 次原始預測壓力
_ema_pressure       = None              # 輸出 EMA(α=0.5) 平滑後壓力
_ema_ch4            = None              # 輸出 EMA 平滑後 CH4
_EMA_OUT_ALPHA      = 0.5


def load_model_and_scalers():
    global model, scaler_x, scaler_y
    model = ReactorLSTM(input_size=INPUT_SIZE, output_size=2).to(device)
    weights_path = os.path.join(_WEIGHTS_DIR, "reactor_lstm_weights.pth")
    model.load_state_dict(torch.load(weights_path, map_location=device))
    model.eval()
    scaler_x, scaler_y = load_scalers(_WEIGHTS_DIR)
    print("[推論核心] 模型與 Scaler 已成功載入！")


# ── 內部工具：EMA 序列計算 ────────────────────────────────
def _ema_series(values, alpha):
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def _smooth_scalar(old, new, alpha=_EMA_OUT_ALPHA):
    return new if old is None else alpha * new + (1 - alpha) * old


# ── 特徵工程：從原始 buffer 計算 6 維輸入矩陣 ──────────────
def _extract_features(buf):
    """
    buf: list of [orp_raw, ph, temp, pressure]，長度 >= MIN_BUF (35)
    回傳: np.ndarray，shape (SEQ_LEN, 6) = (30, 6)
    """
    orp      = [r[0] for r in buf]
    ph       = [r[1] for r in buf]
    temp     = [r[2] for r in buf]
    pressure = [r[3] for r in buf]
    n        = len(buf)

    ema10 = _ema_series(orp, 2 / 11)
    ema5  = _ema_series(orp, 2 / 6)
    ema30 = _ema_series(orp, 2 / 31)

    # 斜率：(ema[t] - ema[t-5]) / 5，前 5 筆補 0
    slopes = [0.0] * 5 + [(ema10[i] - ema10[i - 5]) / 5 for i in range(5, n)]
    macd   = [e5 - e30 for e5, e30 in zip(ema5, ema30)]

    # 取最後 SEQ_LEN (30) 個時間步
    rows = []
    for i in range(n - SEQ_LEN, n):
        rows.append([ema10[i], slopes[i], macd[i], ph[i], temp[i], pressure[i]])
    return np.array(rows, dtype=np.float32)


# ── 主推論函式 ────────────────────────────────────────────
def get_pressure_prediction(new_sensor_data=None):
    global latest_actual_pressure, _ema_pressure, _ema_ch4

    if model is None or scaler_x is None or scaler_y is None:
        raise Exception("模型或比例尺尚未載入，請確認啟動流程！")

    # 1. 將新資料加入 buffer
    if new_sensor_data:
        latest_actual_pressure = new_sensor_data.get('pressure', latest_actual_pressure)
        sensor_buffer.append([
            new_sensor_data['orp'],
            new_sensor_data['ph'],
            new_sensor_data['temp'],
            latest_actual_pressure,
        ])

    # 2. buffer 未滿 MIN_BUF (35) 筆，尚無法計算斜率特徵
    if len(sensor_buffer) < MIN_BUF:
        return {
            "current_pressure_kg_cm2": round(latest_actual_pressure, 2),
            "predicted_pressure_5min": 0.0,
            "status": f"資料緩衝中 ({len(sensor_buffer)}/{MIN_BUF})"
        }

    # 3. 特徵工程
    feat = _extract_features(list(sensor_buffer))          # (30, 6)
    feat_scaled = scaler_x.transform(feat)                 # 歸一化
    tensor = torch.tensor(feat_scaled[np.newaxis], dtype=torch.float32).to(device)

    # 4. LSTM 推論
    with torch.no_grad():
        pred_scaled = model(tensor)
    pred = scaler_y.inverse_transform(pred_scaled.cpu().numpy())
    raw_pressure = float(pred[0][0])
    raw_ch4      = float(pred[0][1])

    # 5. 輸出平滑（EMA，減少單點抖動）
    _ema_pressure = _smooth_scalar(_ema_pressure, raw_pressure)
    _ema_ch4      = _smooth_scalar(_ema_ch4,      raw_ch4)

    # 6. 遲滯警報：連續 3 次原始預測超閾值 + 仍在上升才觸發危險
    _pred_history.append(raw_pressure)
    hist = list(_pred_history)

    is_danger = (
        len(hist) == 3 and
        all(p > 2.6 for p in hist) and
        hist[-1] >= hist[0]          # 確認趨勢持續上升
    )

    # 警告：平滑後壓力 > 2.4，或近 3 筆預測斜率急升
    pred_slope = (hist[-1] - hist[0]) / len(hist) if len(hist) > 1 else 0.0
    is_warning = _ema_pressure > 2.4 or pred_slope > 0.05

    if is_danger:
        status = "危險 (Danger)"
    elif is_warning:
        status = "警告 (Warning)"
    else:
        status = "正常 (Normal)"

    return {
        "current_pressure_kg_cm2": round(latest_actual_pressure, 2),
        "predicted_pressure_5min": round(_ema_pressure, 2),
        "predicted_ch4_5min":      round(_ema_ch4, 2),
        "status":                  status,
    }
