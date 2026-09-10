import os
import sys

# Windows 主控台/重導向輸出預設用系統 codepage（如 cp1252），無法編碼中文
# print 訊息，會直接讓整個服務啟動失敗。強制 stdout/stderr 走 UTF-8。
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────
    # ⚠ 啟動時把設定印出來。「指到錯的資料夾」是最容易發生又最難察覺的
    #   部署錯誤——2026-07-22 記錄靜默中斷 17.5 小時無人發現。
    from core import config
    print(config.describe())

    # ⚠ LSTM 預設不載入。這一段原本是無條件執行的，代價是每次啟動都
    #   `import torch`：實測常駐 RSS 54.1 → 313.8 MB，而監控電腦的預算
    #   是 60 MB。更關鍵的是，它要載的權重檔
    #   core/weights/reactor_lstm_weights.pth **全專案並不存在**——torch
    #   載完之後必定丟 FileNotFoundError，被下面那個 except 吞掉，只印一行
    #   「模型載入跳過」。也就是說：付 260 MB 換一次例外，而且沒有人會發現。
    #
    #   config 早就有 REACTOR_ENABLE_LSTM（預設 '0'），只是這裡沒讀它，
    #   所以旗標關著也照樣載入。要真的啟用：先把權重檔放進 core/weights/，
    #   再於 .env 設 REACTOR_ENABLE_LSTM=1。
    if config.get('REACTOR_ENABLE_LSTM') == '1':
        try:
            from core.inference import load_model_and_scalers
            load_model_and_scalers()
        except Exception as e:
            print(f"[AI 核心] 模型載入跳過（{e}）")
    else:
        print("[AI 核心] LSTM 未啟用（REACTOR_ENABLE_LSTM=0），不載入 torch")

    # ⚠ 2026-09-03 移除 USB 序列埠接收器。現場的流程是「記錄程式自己開埠
    #   寫 CSV，本系統只做 CSV 分析」，從來沒有走過序列埠。證據有三：
    #     · 埠路徑寫死 '/dev/ttyUSB0'（Jetson 的 Linux 路徑），在 Windows
    #       監控電腦上自 Jetson 退場後就一直開不起來，沒有人回報過
    #     · 它寫出的 CSV 是英文 DictWriter 表頭，與記錄程式的中文表頭
    #       （年,月,日,...,ORP (mV),...）完全不同格式
    #     · 全專案只有 main.py 這一行 import 它
    #   一併移除 pyserial 相依。

    # ⚠ 從 sample 表把感測資料還原回記憶體。在此之前資料只存在記憶體，
    #   後端一重開監控頁、批次分析、CH4 預測全部歸零，而且畫面上看不出是
    #   「沒資料」還是「重開過」。
    #
    # ⚠ 只還原**最近 N 筆**，不是全部。實測每筆在記憶體佔 517 bytes：
    #   一年的一分鐘取樣＝525,600 筆＝259 MB，而這台的常駐預算是 60 MB。
    #   要看更早的資料請查 sample 表（sample_store.load_window），不要把
    #   整段歷史載回記憶體。上限可用 REACTOR_SAMPLE_LIMIT 調整。
    try:
        from core import sample_store
        from core.data_store import append_record
        _limit = int(config.get('REACTOR_SAMPLE_LIMIT')
                     or sample_store.DEFAULT_MEMORY_LIMIT)
        _restored = sample_store.load_recent(_limit)
        for _r in _restored:
            append_record(_r)
        _st = sample_store.stats()
        print('[資料] 還原 %d 筆到記憶體（表內共 %d 筆%s）'
              % (len(_restored), _st['n_samples'],
                 '，%s → %s' % (_st['first_ts'], _st['last_ts'])
                 if _st['first_ts'] else ''))
    except Exception as e:
        # 還原失敗不擋啟動——記錄照收，只是舊資料看不到。
        print('[資料] sample 表還原失敗（從空白開始）：%s: %s'
              % (type(e).__name__, e))

    # 批次排程（daemon 執行緒）：到點自動開始／自動結束紀錄。
    # ⚠ 只對有勾 auto_start / auto_stop 的批次動作，預設全關；而且只結束
    #   **紀錄**——系統只讀不控，不會關閥或停機。
    from core import scheduler
    scheduler.start()

    # 分析模組排程（另一條 daemon 執行緒）：到點以**子行程**跑分析模組。
    # ⚠ 刻意與批次排程分開兩條執行緒。模組逾時上限 300 秒，共用的話一個
    #   慢模組會把批次的自動結束延後五分鐘。
    # ⚠ 核心從不 import 模組的程式碼，只用 subprocess 啟動——這條紅線是
    #   整個記憶體隔離的全部所在（見 core/module_runner.py）。
    from core import module_runner
    module_runner.start()

    yield

    # ── Shutdown ───────────────────────────────────────
    scheduler.stop()
    module_runner.stop()


app = FastAPI(title="生物反應器 Edge AI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

# ⚠ 前後端同機之後，前端 dist/ 由本服務直接供應，不必再起第二個伺服器。
#   必須在 include_router 之後才掛，否則會蓋掉 /api。
#
# ⚠ 不能只用 StaticFiles(html=True)：那只在請求命中目錄時回 index.html。
#   前端用 vue-router 的 createWebHistory，/rate、/report、/experiment
#   都是**前端**路由，伺服器上沒有對應檔案 —— 直接輸入網址或在該頁按
#   重新整理就會 404。所以要有 catch-all 回退。
_DIST = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "web_frontend", "dist")
if os.path.isdir(_DIST):
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST, "assets")),
              name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa(full_path: str):
        """未命中 /api 與 /assets 的路徑，一律交給前端 router。"""
        candidate = os.path.join(_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)          # favicon 等實體檔
        return FileResponse(os.path.join(_DIST, "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
