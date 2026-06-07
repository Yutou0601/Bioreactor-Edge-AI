import time  # 🌟 新增：引入時間模組
import json
import threading
import paho.mqtt.client as mqtt
from core.inference import get_pressure_prediction

# MQTT 設定
BROKER_IP = "localhost" # 因為 Broker 就裝在 Jetson 上
MQTT_PORT = 1883
TOPIC_SUBSCRIBE = "reactor/01/sensors"
TOPIC_PUBLISH = "reactor/01/prediction"

# 當連上 Broker 時觸發
def on_connect(client, userdata, flags, reason_code, properties):
    print(f"🔗 [MQTT] 已連線至 Broker (狀態碼: {reason_code})")
    # 連線後馬上訂閱感測器主題
    client.subscribe(TOPIC_SUBSCRIBE)
    print(f"[MQTT] 已訂閱主題: {TOPIC_SUBSCRIBE}")

# 當收到訊息時觸發 (核心邏輯！)
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        print(f"📩 [MQTT] 收到數據: {payload}")

        # 🌟 新增：在進入神經網路推論前，按下碼表！
        start_time = time.time()

        # 把 payload 傳進大腦！
        result = get_pressure_prediction(payload)
        
        # 🌟 新增：推論一結束，立刻停止碼表，並算出花了幾毫秒 (ms)
        end_time = time.time()
        inference_time_ms = (end_time - start_time) * 1000

        # 如果是「資料收集中」的狀態，就先不要發布預測結果
        if result is None or "緩衝" in result["status"]:
            print(f"[系統] 資料收集緩衝中... 暫不推論")
            return

        # 準備要推廣出去的預測結果
        response_payload = {
            "device": "Jetson Orin Nano",
            "current_pressure_kg_cm2": round(result["current_pressure_kg_cm2"], 2),
            "predicted_pressure_5min": round(result["predicted_pressure_5min"], 2),
            "predicted_ch4_5min": round(result.get("predicted_ch4_5min", 0.0), 2),
            "status": result["status"],
            "inference_time_ms": round(inference_time_ms, 1) # 🌟 新增：把推論時間放進字典 (取到小數第一位)
        }

        # 把結果發布出去
        client.publish(TOPIC_PUBLISH, json.dumps(response_payload))
        print(f"[MQTT] 已發布預測結果至 {TOPIC_PUBLISH} (推論耗時: {round(inference_time_ms, 1)} ms)")

    except Exception as e:
        print(f"[MQTT] 訊息處理錯誤: {e}")

def start_mqtt_client():
    # 使用 MQTTv5 協定
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Jetson_Backend")
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(BROKER_IP, MQTT_PORT, 60)
        # 啟動一個背景執行緒來跑 MQTT loop，這樣才不會卡死 FastAPI
        client.loop_start()
    except Exception as e:
        print(f"無法連線到 MQTT Broker: {e}")

    return client