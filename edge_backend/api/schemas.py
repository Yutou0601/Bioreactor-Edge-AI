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
