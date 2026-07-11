import io
import re
import time
import numpy as np
from fastapi import APIRouter, HTTPException, File, UploadFile
from core.inference import get_pressure_prediction, sensor_buffer as _lstm_buffer
from core.data_store import sensor_records, append_record, clear_all
from core.signal_processor import ORPSignalProcessor
from core.feature_extractor import ORPFeatureExtractor
from data_pipeline.loader import _detect_schema, read_btp_daily
from api.schemas import PressurePredictionResponse, SensorDataPayload, SensorRecord

_feature_extractor = ORPFeatureExtractor(
    window=30,
    sigma_threshold=5.0,
    orp_low=480.0,
    orp_high=650.0,
    drift_window=120,
)

router = APIRouter()


# ==========================================
# 通道 1：前端來拿取預測結果
# ==========================================
@router.get("/predict_pressure")
def predict_pressure_api():
    # buffer 不足時，從 sensor_records 最近 35 筆自動補齊（MIN_BUF=35）
    if len(_lstm_buffer) < 35 and len(sensor_records) >= 35:
        sorted_recs = sorted(sensor_records, key=lambda r: r.get('timestamp') or '')
        for r in sorted_recs[-35:]:
            _lstm_buffer.append([
                r.get('orp_raw') or r['orp'],
                r['ph'],
                r['temp'],
                r.get('pressure', 0.0),
            ])

    try:
        t0 = time.time()
        result = get_pressure_prediction()
        inference_ms = round((time.time() - t0) * 1000, 1)
        return {
            "device":                   "Jetson Orin Nano",
            "current_pressure_kg_cm2":  round(result["current_pressure_kg_cm2"], 2),
            "predicted_pressure_5min":  round(result["predicted_pressure_5min"], 2),
            "predicted_ch4_5min":       round(result.get("predicted_ch4_5min", 0.0), 2),
            "status":                   result["status"],
            "inference_time_ms":        inference_ms,
            "message": (
            "預測即將超標，請緊急處理！" if result["status"] == "危險 (Danger)"
            else "壓力上升趨勢，請留意！" if result["status"] == "警告 (Warning)"
            else "系統穩定運行中"
        ),
        }
    except Exception as e:
        return {
            "device": "Jetson Orin Nano",
            "current_pressure_kg_cm2": 0.0, "predicted_pressure_5min": 0.0,
            "predicted_ch4_5min": 0.0, "inference_time_ms": 0.0,
            "status": "模型未載入", "message": str(e),
        }


# ==========================================
# 通道 2：前端/感測器傳送最新數據過來
# ==========================================
@router.post("/upload_sensor")
def upload_sensor_data(payload: SensorDataPayload):
    print(f"[成功接收數據] ORP: {payload.orp:.1f} mV, pH: {payload.ph:.2f}, 溫度: {payload.temp:.1f} °C")
    try:
        result = get_pressure_prediction({
            'orp':      payload.orp,
            'ph':       payload.ph,
            'temp':     payload.temp,
            'pressure': payload.pressure,   # None 時 inference 會沿用上次壓力
        })
        prediction = result
    except Exception:
        prediction = None
    return {
        "status":     "success",
        "message":    "感測器數據已成功寫入 Jetson 邊緣節點",
        "prediction": prediction,
    }


# ==========================================
# 通道 3：感測器記錄 CRUD
# ==========================================
# 研究分析統計端點
# ==========================================
@router.get("/report/stats")
def get_report_stats():
    recs = _sorted_records()
    if len(recs) < 10:
        return {"error": "資料不足（至少需 10 筆）"}

    orp      = np.array([r['orp']                    for r in recs], dtype=float)
    pressure = np.array([r.get('pressure', 0)        for r in recs], dtype=float)
    ph       = np.array([r.get('ph', 7)              for r in recs], dtype=float)
    temp     = np.array([r.get('temp', 30)           for r in recs], dtype=float)
    ch4      = np.array([r.get('ch4_pct', 0)         for r in recs], dtype=float)
    co2      = np.array([r.get('co2_pct', 0)         for r in recs], dtype=float)
    anomaly  = np.array([1 if r.get('is_anomaly') else 0 for r in recs], dtype=int)

    # 1. ORP 分布直方圖
    cnt, edges = np.histogram(orp, bins=24)
    orp_histogram = {
        "bins":   [round((edges[i]+edges[i+1])/2, 1) for i in range(len(cnt))],
        "counts": cnt.tolist(),
    }

    # 2. 壓力分布直方圖
    p_cnt, p_edges = np.histogram(pressure, bins=24)
    pressure_histogram = {
        "bins":   [round((p_edges[i]+p_edges[i+1])/2, 3) for i in range(len(p_cnt))],
        "counts": p_cnt.tolist(),
    }

    # 3. 相關係數熱力圖（6×6）
    matrix   = np.array([orp, ph, temp, pressure, ch4, co2])
    labels   = ['ORP', 'pH', '溫度', '壓力', 'CH4', 'CO2']
    corr_raw = np.corrcoef(matrix)
    # NaN 替換為 0（全常數欄位）
    corr_raw = np.where(np.isnan(corr_raw), 0.0, corr_raw)
    correlation = {
        "labels": labels,
        "matrix": [[round(float(v), 3) for v in row] for row in corr_raw],
    }

    # 4. 每日異常統計
    date_total   = {}
    date_anomaly = {}
    for r in recs:
        d = (r.get('timestamp') or '')[:10] or 'unknown'
        date_total[d]   = date_total.get(d, 0) + 1
        if r.get('is_anomaly'):
            date_anomaly[d] = date_anomaly.get(d, 0) + 1
    anomaly_by_date = [
        {"date": d, "total": date_total[d], "anomalies": date_anomaly.get(d, 0)}
        for d in sorted(date_total)
    ]

    # 5. CH4 / CO2 日均值趨勢
    date_ch4 = {}
    date_co2 = {}
    for r in recs:
        d = (r.get('timestamp') or '')[:10] or 'unknown'
        date_ch4.setdefault(d, []).append(r.get('ch4_pct', 0))
        date_co2.setdefault(d, []).append(r.get('co2_pct', 0))
    gas_daily = [
        {
            "date":    d,
            "avg_ch4": round(float(np.mean(date_ch4[d])), 2),
            "avg_co2": round(float(np.mean(date_co2[d])), 2),
        }
        for d in sorted(date_ch4)
    ]

    # 6. pH-ORP 散點（最多取 600 點，避免前端過載）
    step    = max(1, len(recs) // 600)
    scatter = [
        {"orp": round(float(orp[i]), 1), "ph": round(float(ph[i]), 2), "ch4": round(float(ch4[i]), 1)}
        for i in range(0, len(recs), step)
    ]

    # 7. 摘要統計
    summary = {
        "total_records":  len(recs),
        "anomaly_count":  int(anomaly.sum()),
        "anomaly_rate":   round(float(anomaly.mean()) * 100, 1),
        "orp_mean":       round(float(orp.mean()), 1),
        "orp_std":        round(float(orp.std()), 2),
        "pressure_mean":  round(float(pressure.mean()), 3),
        "pressure_max":   round(float(pressure.max()), 3),
        "ch4_mean":       round(float(ch4.mean()), 2),
    }

    return {
        "summary":          summary,
        "orp_histogram":    orp_histogram,
        "pressure_histogram": pressure_histogram,
        "correlation":      correlation,
        "anomaly_by_date":  anomaly_by_date,
        "gas_daily":        gas_daily,
        "orp_ph_scatter":   scatter,
    }


# ==========================================
def _sorted_records() -> list:
    """依 timestamp 排序，確保時間軸正確（支援跨日期多次匯入的情境）。"""
    return sorted(sensor_records, key=lambda r: r.get("timestamp") or "")


# ==========================================
# 通道 5：生物相位偵測
# ==========================================

def _compute_phases_from_records(recs: list):
    """
    從 sensor_records 的 EMA-ORP 序列計算生物相位標籤序列。
    移植自 ch4_peak_analysis.detect_phases()，不引入 matplotlib。
    """
    import pandas as pd

    n = len(recs)
    orp_ema = np.array([r['orp'] for r in recs], dtype=float)

    slope = np.zeros(n)
    if n > 5:
        slope[5:] = (orp_ema[5:] - orp_ema[:-5]) / 5

    smooth_window = min(60, n)
    smoothed = (pd.Series(slope)
                .rolling(window=smooth_window, center=True, min_periods=1)
                .mean().values)

    mu    = float(np.mean(smoothed))
    sigma = float(np.std(smoothed)) + 1e-9
    k     = 0.5
    lo    = mu - k * sigma
    hi    = mu + k * sigma

    raw_labels = np.where(smoothed < lo, 1,
                 np.where(smoothed > hi, 3, 2)).astype(int)

    labels  = raw_labels.copy()
    min_dur = min(30, max(1, n // 10))
    i = 0
    while i < n:
        cur = labels[i]
        j = i
        while j < n and labels[j] == cur:
            j += 1
        if (j - i) < min_dur and i > 0:
            labels[i:j] = labels[i - 1]
        i = j

    return labels, (mu, sigma, lo, hi), smoothed


_PHASE_META = {
    1: ('底物利用期',    'Phase 1 – Substrate Utilization', '#e74c3c'),
    2: ('產甲烷活躍期',  'Phase 2 – Active Methanogenesis', '#2ecc71'),
    3: ('底物耗盡期',    'Phase 3 – Substrate Depletion',   '#e67e22'),
}


@router.get("/phase")
def get_phase():
    recs = _sorted_records()
    n = len(recs)
    if n < 10:
        return {
            'phase': 0, 'label_zh': '資料不足', 'label_en': 'Insufficient Data',
            'color': '#666', 'duration_min': 0, 'slope_current': 0.0,
            'thresholds': {'mu': 0, 'sigma': 0, 'lo': 0, 'hi': 0},
            'transitions': [], 'total_records': n,
            'message': f'需至少 10 筆資料（目前 {n} 筆）',
        }

    labels, (mu, sigma, lo, hi), smoothed = _compute_phases_from_records(recs)

    # 建立相位切換歷史（合併連續相同相位）
    transitions = []
    prev, seg_start = int(labels[0]), 0
    for idx in range(1, n):
        if int(labels[idx]) != prev:
            meta = _PHASE_META.get(prev, ('未知', '?', '#666'))
            transitions.append({
                'phase': prev, 'label_zh': meta[0], 'color': meta[2],
                'start': (recs[seg_start].get('timestamp') or '')[:16],
                'duration_min': idx - seg_start, 'is_current': False,
            })
            prev, seg_start = int(labels[idx]), idx

    meta = _PHASE_META.get(prev, ('未知', '?', '#666'))
    transitions.append({
        'phase': prev, 'label_zh': meta[0], 'color': meta[2],
        'start': (recs[seg_start].get('timestamp') or '')[:16],
        'duration_min': n - seg_start, 'is_current': True,
    })

    current_meta = _PHASE_META.get(prev, ('未知', 'Unknown', '#666'))
    return {
        'phase':         prev,
        'label_zh':      current_meta[0],
        'label_en':      current_meta[1],
        'color':         current_meta[2],
        'duration_min':  n - seg_start,
        'slope_current': round(float(smoothed[-1]), 4),
        'thresholds': {
            'mu': round(mu, 4), 'sigma': round(sigma, 4),
            'lo': round(lo, 4), 'hi':    round(hi, 4),
        },
        'transitions':   transitions[-14:],
        'total_records': n,
        'message': f'基於 {n} 筆 ORP 序列，當前相位持續 {n - seg_start} 分鐘',
    }


@router.get("/analysis")
def get_analysis():
    """
    對目前 data_store 的 EMA 序列進行穩態判定與基準漂移分析。
    回傳：穩態旗標、σ、均值、漂移率 (mV/hr)、持續穩態時間。
    """
    result = _feature_extractor.analyze(_sorted_records())
    return {
        "is_steady":       result.is_steady,
        "sigma":           result.sigma,
        "orp_mean":        result.orp_mean,
        "drift_rate":      result.drift_rate,
        "steady_minutes":  result.steady_minutes,
        "window_size":     result.window_size,
        "record_count":    len(sensor_records),
        "message":         result.message,
    }


@router.get("/records")
def get_records():
    return _sorted_records()


@router.post("/records")
def add_record(record: SensorRecord):
    new_record = record.dict()
    return append_record(new_record)


@router.delete("/records")
def clear_records():
    deleted = clear_all()
    return {"status": "cleared", "deleted": deleted}


@router.delete("/records/{record_id}")
def delete_record(record_id: int):
    original_len = len(sensor_records)
    to_remove = [r for r in sensor_records if r["id"] == record_id]
    if not to_remove:
        raise HTTPException(status_code=404, detail="Record not found")
    sensor_records.remove(to_remove[0])
    return {"status": "deleted", "id": record_id}


# ==========================================
# 通道 4：CSV 批次匯入（含訊號前處理）
# ==========================================
def _import_csv_btp_daily(text: str, detected_date: str) -> dict:
    """處理 usb_receiver.py 產生的 BTP_Sensor_log 格式：資料已完成訊號前處理，
    直接沿用 orp/orp_raw/orp_cleaned/is_anomaly 等既有結果寫入 sensor_records，
    不重跑 ORPSignalProcessor（避免對已處理過的訊號二次處理）。
    """
    df = read_btp_daily(io.StringIO(text))
    if df.empty:
        return {
            'status': 'skipped', 'date': detected_date, 'imported': 0,
            'anomalies_detected': 0, 'message': '檔案中沒有可用資料列',
            'orp_stats': {'min': 0, 'max': 0, 'avg': 0},
        }

    df = df.copy()
    df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    existing_ts = {r['timestamp'] for r in sensor_records}
    df = df[~df['timestamp'].isin(existing_ts)]

    if df.empty:
        return {
            'status': 'skipped', 'date': detected_date, 'imported': 0,
            'anomalies_detected': 0, 'message': '所有資料已存在，無新資料匯入',
            'orp_stats': {'min': 0, 'max': 0, 'avg': 0},
        }

    rows = df.to_dict('records')
    imported = 0
    anomaly_count = 0
    ema_values: list[float] = []

    for row in rows:
        is_anomaly = bool(row.get('is_anomaly', False))
        note_val = row.get('note')
        note = note_val if isinstance(note_val, str) and note_val else f'CSV · {detected_date}'
        append_record({
            'timestamp':      row['timestamp'],
            'orp':            row['orp'],
            'orp_raw':        row['orp_raw'],
            'orp_cleaned':    row['orp_cleaned'],
            'is_anomaly':     is_anomaly,
            'pressure':       row.get('pressure', 0.0),
            'ph':             row.get('ph', 7.0),
            'temp':           row.get('temp', 30.0),
            'mixer_pressure': row.get('mixer_pressure', 0.0),
            'co2_pct':        row.get('co2_pct', 0.0),
            'ch4_pct':        row.get('ch4_pct', 0.0),
            'note':           note,
        })
        imported += 1
        if is_anomaly:
            anomaly_count += 1
        ema_values.append(row['orp'])

    # 預熱 LSTM buffer：前 N-1 筆直接 append，最後一筆透過正式介面傳入
    for row in rows[-35:-1]:
        _lstm_buffer.append([row['orp_raw'], row['ph'], row['temp'], row['pressure']])

    try:
        last = rows[-1]
        pred = get_pressure_prediction({
            'orp':      last['orp_raw'],
            'ph':       last['ph'],
            'temp':     last['temp'],
            'pressure': last['pressure'],
        })
    except Exception:
        pred = None

    prediction_payload = None
    if pred and '緩衝' not in pred.get('status', ''):
        prediction_payload = {
            'current_pressure_kg_cm2': pred['current_pressure_kg_cm2'],
            'predicted_pressure_5min': pred['predicted_pressure_5min'],
            'predicted_ch4_5min':      pred.get('predicted_ch4_5min', 0.0),
            'status':                  pred['status'],
        }

    return {
        'status':             'success',
        'date':               detected_date,
        'imported':           imported,
        'anomalies_detected': anomaly_count,
        'prediction':         prediction_payload,
        'orp_stats': {
            'min': round(min(ema_values), 1) if ema_values else 0,
            'max': round(max(ema_values), 1) if ema_values else 0,
            'avg': round(sum(ema_values) / len(ema_values), 1) if ema_values else 0,
        },
    }


@router.post("/import_csv")
async def import_csv(file: UploadFile = File(...)):
    """
    接受兩種來源格式：
      1. BTP_Sensor_log-YYYY-MM-DD.csv — usb_receiver.py 的每日備份（已完成訊號前處理，
         含 timestamp/orp/orp_raw/orp_cleaned/is_anomaly 等標題列），直接沿用其處理結果寫入
         sensor_records，不重跑訊號前處理。
      2. 感測板原始序列埠格式（無標題列，14 欄），套用一階差分突波排除 + 線性內插重建 +
         EMA 濾波後寫入 sensor_records（沿用既有流程）。
    """
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', file.filename or '')
    detected_date = date_match.group(1) if date_match else 'unknown'

    content = await file.read()
    text = content.decode('utf-8-sig', errors='ignore')

    first_line = text.splitlines()[0] if text.strip() else ''
    if _detect_schema(first_line) == 'btp_daily':
        return _import_csv_btp_daily(text, detected_date)

    # 每次匯入建立獨立的處理器實例（不共用 USB 那個）
    processor = ORPSignalProcessor(ema_window=10, spike_threshold=-20.0, spike_max_minutes=15)

    # ── 解析 CSV ──────────────────────────────────
    parsed_rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(',')
        if len(parts) < 14:
            continue
        try:
            ts = (
                f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                f" {int(parts[3]):02d}:{int(parts[4]):02d}:{int(parts[5]):02d}"
            )
            parsed_rows.append({
                'timestamp':      ts,
                'orp_raw':        float(parts[7]),
                'pressure':       float(parts[8]),   # 反應器壓力
                'ph':             float(parts[9]),
                'temp':           float(parts[10]),
                'mixer_pressure': float(parts[11]),  # 混合槽壓力
                'co2_pct':        float(parts[12]),
                'ch4_pct':        float(parts[13]),
            })
        except (ValueError, IndexError):
            continue

    # ── 去重：過濾掉 sensor_records 中已存在的 timestamp ──
    existing_ts = {r['timestamp'] for r in sensor_records}
    parsed_rows = [r for r in parsed_rows if r['timestamp'] not in existing_ts]

    if not parsed_rows:
        return {
            'status':             'skipped',
            'date':               detected_date,
            'imported':           0,
            'anomalies_detected': 0,
            'message':            '所有資料已存在，無新資料匯入',
            'orp_stats':          {'min': 0, 'max': 0, 'avg': 0},
        }

    row_by_ts = {r['timestamp']: r for r in parsed_rows}

    # ── 訊號前處理 ────────────────────────────────
    all_points = []
    for row in parsed_rows:
        all_points.extend(processor.process(row['timestamp'], row['orp_raw']))
    all_points.extend(processor.flush())  # 檔案結尾強制 flush 突波緩衝

    # ── 寫入記憶體 ────────────────────────────────
    imported = 0
    anomaly_count = 0
    ema_values: list[float] = []

    for pt in all_points:
        src = row_by_ts.get(pt.timestamp, {})
        append_record({
            'timestamp':      pt.timestamp,
            'orp':            pt.ema,
            'orp_raw':        pt.raw,
            'orp_cleaned':    pt.cleaned,
            'is_anomaly':     pt.is_anomaly,
            'pressure':       src.get('pressure', 0.0),
            'ph':             src.get('ph', 7.0),
            'temp':           src.get('temp', 30.0),
            'mixer_pressure': src.get('mixer_pressure', 0.0),
            'co2_pct':        src.get('co2_pct', 0.0),
            'ch4_pct':        src.get('ch4_pct', 0.0),
            'note':           f'CSV · {detected_date}',
        })
        imported += 1
        if pt.is_anomaly:
            anomaly_count += 1
        ema_values.append(pt.ema)

    # ── 預熱 LSTM buffer：前 29 筆直接 append，最後一筆透過正式介面傳入
    #    這樣 latest_actual_pressure 也能被正確更新
    for row in parsed_rows[-35:-1]:
        _lstm_buffer.append([row['orp_raw'], row['ph'], row['temp'], row['pressure']])

    try:
        last = parsed_rows[-1]
        pred = get_pressure_prediction({
            'orp':      last['orp_raw'],
            'ph':       last['ph'],
            'temp':     last['temp'],
            'pressure': last['pressure'],
        })
    except Exception:
        pred = None

    prediction_payload = None
    if pred and '緩衝' not in pred.get('status', ''):
        prediction_payload = {
            'current_pressure_kg_cm2': pred['current_pressure_kg_cm2'],
            'predicted_pressure_5min': pred['predicted_pressure_5min'],
            'predicted_ch4_5min':      pred.get('predicted_ch4_5min', 0.0),
            'status':                  pred['status'],
        }

    return {
        'status':             'success',
        'date':               detected_date,
        'imported':           imported,
        'anomalies_detected': anomaly_count,
        'prediction':         prediction_payload,
        'orp_stats': {
            'min': round(min(ema_values), 1) if ema_values else 0,
            'max': round(max(ema_values), 1) if ema_values else 0,
            'avg': round(sum(ema_values) / len(ema_values), 1) if ema_values else 0,
        },
    }
