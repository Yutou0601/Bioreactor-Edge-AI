from fastapi import FastAPI
from api.routes import router
from core.inference import load_model_and_scalers
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="邊緣 AI 反應器預測系統", description="Jetson Orin Nano 即時推論 API")

# 允許前端 (如 Vue/React) 跨網域存取 API (CORS 設定)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 啟動時載入模型
@app.on_event("startup")
def startup_event():
    print("啟動中：正在呼叫 Jetson AI ...")
    load_model_and_scalers()
    print("API 伺服器已就緒！")

# 掛載 API 路由
app.include_router(router, prefix="/api")

if __name__ == "__main__":
    # 在 8000 埠口啟動伺服器
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)