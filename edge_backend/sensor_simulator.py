import time
import json
import random
import paho.mqtt.client as mqtt

# MQTT 設定
BROKER_IP = "127.0.0.1"  # 因為我們都在 Jetson 上跑，所以指向本機
MQTT_PORT = 1883
PUBLISH_TOPIC = "reactor/01/sensors"

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"🔌 [虛擬機台] 已連線至 MQTT Broker (狀態碼: {reason_code})")

def start_simulation():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Virtual_Sensor_01")
    client.on_connect = on_connect
    
    try:
        client.connect(BROKER_IP, MQTT_PORT, 60)
        client.loop_start() # 在背景保持連線
    except Exception as e:
        print(f"無法連線到 Broker: {e}")
        return

    # 初始感測器數值
    current_orp = -250.0
    current_ph = 7.2
    current_temp = 35.5

    print("開始模擬發送感測器數據... (按 Ctrl+C 停止)")
    
    try:
        while True:
            # 1. 模擬環境的微幅波動
            current_orp += random.uniform(-2.0, 2.0)
            current_ph += random.uniform(-0.05, 0.05)
            current_temp += random.uniform(-0.1, 0.1)

            # 2. 打包成 JSON 格式
            payload = {
                "orp": round(current_orp, 1),
                "ph": round(current_ph, 2),
                "temp": round(current_temp, 1)
            }
            
            # 3. 發布 (Publish) 到指定的頻道
            client.publish(PUBLISH_TOPIC, json.dumps(payload))
            print(f"發布數據 -> {PUBLISH_TOPIC}: {payload}")
            
            # 休息 3 秒後再發送下一筆
            time.sleep(3)
            
    except KeyboardInterrupt:
        print("\n停止模擬發送。")
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    start_simulation()