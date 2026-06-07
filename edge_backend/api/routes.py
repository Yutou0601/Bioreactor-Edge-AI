import re
from fastapi import APIRouter, HTTPException, File, UploadFile
from core.inference import get_pressure_prediction
from core.data_store import sensor_records, append_record, clear_all
from core.signal_processor import ORPSignalProcessor
from core.feature_extractor import ORPFeatureExtractor
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
@router.get("/predict_pressure", response_model=PressurePredictionResponse)
def predict_pressure_api():
    result = get_pressure_prediction()
    return PressurePredictionResponse(
        device="Jetson Orin Nano",
        current_pressure_kg_cm2=round(result["current_pressure_kg_cm2"], 2),
        predicted_pressure_5min=round(result["predicted_pressure_5min"], 2),
        status=result["status"],
        message="預測即將超標，請注意！" if result["status"] == "危險 (Danger)" else "系統穩定運行中"
    )


# ==========================================
# 通道 2：前端/感測器傳送最新數據過來
# ==========================================
@router.post("/upload_sensor")
def upload_sensor_data(payload: SensorDataPayload):
    print(f"[成功接收數據] ORP: {payload.orp:.1f} mV, pH: {payload.ph:.2f}, 溫度: {payload.temp:.1f} °C")
    return {
        "status": "success",
        "message": "感測器數據已成功寫入 Jetson 邊緣節點",
        "received_data": payload.dict()
    }


# ==========================================
# 通道 3：感測器記錄 CRUD
# ==========================================
def _sorted_records() -> list:
    """依 timestamp 排序，確保時間軸正確（支援跨日期多次匯入的情境）。"""
    return sorted(sensor_records, key=lambda r: r.get("timestamp") or "")


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
@router.post("/import_csv")
async def import_csv(file: UploadFile = File(...)):
    """
    接受 BTP_Sensor_log-YYYY-MM-DD.csv 上傳，
    套用一階差分突波排除 + 線性內插重建 + EMA 濾波，
    批次寫入 sensor_records。
    """
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', file.filename or '')
    detected_date = date_match.group(1) if date_match else 'unknown'

    content = await file.read()
    text = content.decode('utf-8-sig', errors='ignore')

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

    return {
        'status':             'success',
        'date':               detected_date,
        'imported':           imported,
        'anomalies_detected': anomaly_count,
        'orp_stats': {
            'min': round(min(ema_values), 1) if ema_values else 0,
            'max': round(max(ema_values), 1) if ema_values else 0,
            'avg': round(sum(ema_values) / len(ema_values), 1) if ema_values else 0,
        },
    }
