from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from core.mqtt_client import start_mqtt_client
from usb_receiver import start_usb_listener

mqtt_client_instance = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────
    # LSTM 模型載入（可選：模型檔案不存在時不影響其他功能）
    try:
        from core.inference import load_model_and_scalers
        load_model_and_scalers()
    except Exception as e:
        print(f"[AI 核心] 模型載入跳過（{e}）")

    # MQTT 客戶端
    global mqtt_client_instance
    print("[MQTT] 啟動背景客戶端...")
    mqtt_client_instance = start_mqtt_client()

    # USB 感測器接收器（daemon 執行緒，感測器未接時不阻塞服務）
    print("[USB] 啟動感測器接收執行緒...")
    start_usb_listener()

    yield

    # ── Shutdown ───────────────────────────────────────
    if mqtt_client_instance:
        print("[MQTT] 關閉連線...")
        mqtt_client_instance.loop_stop()
        mqtt_client_instance.disconnect()


app = FastAPI(title="生物反應器 Edge AI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
