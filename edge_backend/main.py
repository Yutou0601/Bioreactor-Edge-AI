from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from core.mqtt_client import start_mqtt_client
from core.inference import load_model_and_scalers

# 全域變數用來存放 MQTT 客戶端
mqtt_client_instance = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ==========================
    # 這裡放 Startup (啟動時) 的邏輯
    # ==========================
    load_model_and_scalers()
    global mqtt_client_instance
    print("啟動背景 MQTT 客戶端...")
    mqtt_client_instance = start_mqtt_client()
    
    yield  # 讓 FastAPI 開始運行接單 (這個 yield 不能省略！)
    
    # ==========================
    # 這裡放 Shutdown (關閉時) 的邏輯
    # ==========================
    if mqtt_client_instance:
        print("關閉 MQTT 連線...")
        mqtt_client_instance.loop_stop()
        mqtt_client_instance.disconnect()

# 在建立 FastAPI 實體時，把 lifespan 綁定進去
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
    # 指定 host 讓外部可以連線
    uvicorn.run(app, host="0.0.0.0", port=8000)