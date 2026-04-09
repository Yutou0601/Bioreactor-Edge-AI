from fastapi import APIRouter
from core.inference import get_pressure_prediction
from api.schemas import PressurePredictionResponse, SensorDataPayload 

# 建立路由路由器
router = APIRouter()

# ==========================================
# 通道 1：前端來拿取預測結果
# ==========================================
@router.get("/predict_pressure", response_model=PressurePredictionResponse)
def predict_pressure_api():
    # 呼叫核心層進行預測
    result = get_pressure_prediction()
    
    # 封裝成前端需要的格式
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
    # FastAPI 會自動檢查傳來的資料有沒有符合 SensorDataPayload 的規定 (orp, ph, temp)
    # 如果格式正確，就會放進 payload 變數裡
    
    # 在 Jetson 的終端機印出收到的資料，方便我們確認
    print(f"[成功接收數據] ORP: {payload.orp:.1f} mV, pH: {payload.ph:.2f}, 溫度: {payload.temp:.1f} °C")
    
    # 實務上：你可以在這裡把資料寫進 SQLite、CSV，或是直接餵給 LSTM 更新狀態
    
    # 回傳成功訊息給前端
    return {
        "status": "success",
        "message": "感測器數據已成功寫入 Jetson 邊緣節點",
        "received_data": payload.dict()
    }