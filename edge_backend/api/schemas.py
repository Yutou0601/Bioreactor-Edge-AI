from pydantic import BaseModel

# 前端傳過來的資料格式
class SensorDataPayload(BaseModel):
    orp: float
    ph: float
    temp: float

# 後端傳回去的資料格式
class PressurePredictionResponse(BaseModel):
    device: str
    current_pressure_kg_cm2: float
    predicted_pressure_5min: float
    status: str
    message: str