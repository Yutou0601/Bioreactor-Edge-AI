from pydantic import BaseModel
from typing import Optional


class SensorDataPayload(BaseModel):
    orp:      float
    ph:       float
    temp:     float
    pressure: Optional[float] = None   # 反應器壓力，有傳才更新


class PressurePredictionResponse(BaseModel):
    device: str
    current_pressure_kg_cm2: float
    predicted_pressure_5min: float
    status: str
    message: str


class SensorRecord(BaseModel):
    timestamp:       Optional[str]   = None
    orp:             float
    orp_raw:         Optional[float] = None
    orp_cleaned:     Optional[float] = None
    is_anomaly:      Optional[bool]  = False
    pressure:        float                    # 反應器壓力 kg/cm²
    ph:              float
    temp:            float
    mixer_pressure:  float                    # 混合槽壓力 kg/cm²
    co2_pct:         float                    # CO2 濃度 %
    ch4_pct:         float                    # CH4 濃度 %
    note:            Optional[str]   = ""


# ── 實驗批次 ─────────────────────────────────────────
class ExperimentRunCreate(BaseModel):
    run_id:            str                      # 批次編號，如 "1.1"
    n_minutes:         float                    # 循環時間（每時幾分）— 控制因子
    gas_ratio:         Optional[str]   = "4:1"
    intake_lower:      Optional[float] = 0.90   # 自動補氣下限 kg/cm²
    intake_upper:      Optional[float] = 1.185  # 自動補氣上限 kg/cm²
    baseline_ch4:      Optional[float] = 9.0    # 基準 CH4 %
    baseline_co2:      Optional[float] = 21.0   # 基準 CO2 %
    baseline_pressure: Optional[float] = 1.185  # 基準壓力 kg/cm²
    target_hours:      Optional[float] = 48.0   # 預計實驗時長 hr
    scheduled_start:   Optional[str]   = None   # 排定開始時間 YYYY-MM-DD HH:MM:SS
    note:              Optional[str]   = ""


class ExperimentRunUpdate(BaseModel):
    n_minutes:         Optional[float] = None
    gas_ratio:         Optional[str]   = None
    intake_lower:      Optional[float] = None
    intake_upper:      Optional[float] = None
    baseline_ch4:      Optional[float] = None
    baseline_co2:      Optional[float] = None
    baseline_pressure: Optional[float] = None
    target_hours:      Optional[float] = None
    scheduled_start:   Optional[str]   = None
    start_time:        Optional[str]   = None
    end_time:          Optional[str]   = None
    status:            Optional[str]   = None
    note:              Optional[str]   = None


class ExperimentStartPayload(BaseModel):
    at: Optional[str] = None                    # 指定開始時間；未填用排程或當下
