<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import mqtt from 'mqtt' 

// ==============================
// 1. 系統狀態與資料變數
// ==============================
const currentPressure = ref(0.0)
const predictedPressure = ref(0.0)
const predictedCH4 = ref(0.0)
const systemStatus = ref('系統啟動中...')
const lastUpdateTime = ref('--:--:--')

// 模擬感測器特徵資料
const sensorData = ref({
  orp: -250,
  ph: 7.2,
  temp: 35.5,
  ch4: 20.0
})

// 🌟 【新增】動態節點狀態變數
const nodeStats = ref({
  device: 'Jetson Orin Nano',
  engine: 'PyTorch (CUDA)',
  latency: '--', // 預設顯示，等待後端傳入真實數據
  protocol: 'MQTT (WebSocket)',
  qos: 'Level 1'
})

// ==============================
// 2. 控制台變數
// ==============================
const isAutoFetch = ref(true)
const isInjectingAnomaly = ref(false)
const isUploading = ref(false) 

// ==============================
// 3. MQTT 客戶端設定
// ==============================
let mqttClient = null
const MQTT_BROKER_URL = 'ws://localhost:9001' 

const TOPIC_SUB_PREDICT = 'reactor/01/prediction' 
const TOPIC_PUB_SENSOR = 'reactor/01/sensors'     
const TOPIC_PUB_CONTROL = 'reactor/01/control'    

// ==============================
// 4. 圖表專用變數與設定
// ==============================
const chartRef = ref(null)
let myChart = null
const timeData = []
const actualData = []
const predictedData = []

const initChart = () => {
  if (!chartRef.value) {
    console.error('圖表容器不存在！')
    return
  }

  myChart = echarts.init(chartRef.value) 
  const option = {
    backgroundColor: 'transparent',
    tooltip: { 
      trigger: 'axis',
      backgroundColor: 'rgba(30, 30, 35, 0.9)',
      borderColor: '#3498db',
      textStyle: { color: '#fff', fontSize: 13 }
    },
    legend: { 
      data: ['實際壓力', 'AI 預測軌跡'], 
      top: 10, 
      textStyle: { color: '#bdc3c7' } 
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { 
      type: 'category', 
      data: timeData,
      axisLine: { lineStyle: { color: '#34495e' } },
      axisLabel: { color: '#bdc3c7' }
    },
    yAxis: { 
      type: 'value', 
      name: 'kg/cm²',
      min: 1.5, max: 3.5,
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
      axisLabel: { color: '#bdc3c7' }
    },
    series: [
      {
        name: '實際壓力',
        type: 'line',
        data: actualData,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 3, color: '#3498db' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(52, 152, 219, 0.2)' },
            { offset: 1, color: 'rgba(52, 152, 219, 0)' }
          ])
        }
      },
      {
        name: 'AI 預測軌跡',
        type: 'line',
        data: predictedData,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2, type: 'dashed', color: '#e74c3c' },
        itemStyle: { color: '#e74c3c' }
      }
    ]
  }
  myChart.setOption(option)
}

// ==============================
// 5. MQTT 核心邏輯
// ==============================
const initMqtt = () => {
  try {
    if (!mqtt || typeof mqtt.connect !== 'function') {
      throw new Error('MQTT 套件解析失敗，請確認是否透過 npm 安裝正確版本')
    }

    systemStatus.value = 'MQTT 連線中...'
    mqttClient = mqtt.connect(MQTT_BROKER_URL)

    mqttClient.on('connect', () => {
      console.log('✅ MQTT WebSocket 連線成功！')
      systemStatus.value = '連線正常 (Active)'
      
      mqttClient.subscribe(TOPIC_SUB_PREDICT, (err) => {
        if (err) console.error('❌ 訂閱失敗:', err)
        else console.log(`✅ 成功訂閱主題: ${TOPIC_SUB_PREDICT}`)
      })
    })

    mqttClient.on('message', (topic, message) => {
      if (!isAutoFetch.value) return 

      if (topic === TOPIC_SUB_PREDICT) {
        try {
          let rawData = message.toString()
          console.log('📥 收到原始 MQTT 資料:', rawData) 

          rawData = rawData.replace(/'/g, '"') 
          const payload = JSON.parse(rawData)
          updateDashboardData(payload)
        } catch (error) {
          console.error('❌ MQTT 資料解析錯誤:', error)
        }
      }
    })

    mqttClient.on('error', (err) => {
      console.error('❌ MQTT 連線發生錯誤:', err)
      systemStatus.value = '連線異常'
    })

    mqttClient.on('offline', () => {
      console.warn('⚠️ MQTT 失去連線')
      systemStatus.value = '等待重新連線...'
    })

  } catch (err) {
    console.error('❌ 系統初始化失敗:', err)
    systemStatus.value = 'MQTT 初始化失敗'
  }
}

// 更新儀表板與圖表資料
const updateDashboardData = (data) => {
  currentPressure.value = data.current_pressure_kg_cm2 || 2.5
  predictedPressure.value = data.predicted_pressure_5min || 2.5
  predictedCH4.value = data.predicted_ch4_5min || 20.0
  systemStatus.value = data.status || '監控中'

  // 🌟 【新增】抓取後端傳來的真實推論時間
  if (data.inference_time_ms !== undefined) {
    nodeStats.value.latency = parseFloat(data.inference_time_ms).toFixed(1)
  }
  
  sensorData.value.orp += (Math.random() - 0.5) * 4
  sensorData.value.ph += (Math.random() - 0.5) * 0.05
  sensorData.value.temp += (Math.random() - 0.5) * 0.1
  sensorData.value.ch4 += (Math.random() - 0.5) * 0.2

  const now = new Date().toLocaleTimeString('zh-TW', { hour12: false })
  lastUpdateTime.value = now

  timeData.push(now)
  actualData.push(currentPressure.value)
  predictedData.push(predictedPressure.value)

  if (timeData.length > 20) {
    timeData.shift(); actualData.shift(); predictedData.shift();
  }

  if (myChart) {
    myChart.setOption({
      xAxis: { data: timeData },
      series: [{ data: actualData }, { data: predictedData }]
    })
  }
}

const sendDataToJetson = () => {
  if (!mqttClient || !mqttClient.connected) {
    alert('MQTT 尚未連線')
    return
  }

  isUploading.value = true
  const payload = JSON.stringify({
    timestamp: new Date().toISOString(),
    orp: sensorData.value.orp,
    ph: sensorData.value.ph,
    temp: sensorData.value.temp,
    ch4: sensorData.value.ch4
  })

  mqttClient.publish(TOPIC_PUB_SENSOR, payload, { qos: 1 }, (err) => {
    if (!err) {
      setTimeout(() => { isUploading.value = false }, 500)
    } else {
      console.error('❌ 發布失敗:', err)
      isUploading.value = false
    }
  })
}

const triggerAnomaly = () => {
  if (mqttClient && mqttClient.connected) {
    isInjectingAnomaly.value = true
    const commandPayload = JSON.stringify({ command: 'inject_anomaly' })
    mqttClient.publish(TOPIC_PUB_CONTROL, commandPayload, { qos: 1 })
    
    setTimeout(() => { isInjectingAnomaly.value = false }, 2000)
  }
}

// ==============================
// 6. 生命週期
// ==============================
onMounted(() => {
  initChart()
  initMqtt()
  window.addEventListener('resize', () => myChart && myChart.resize())
})

onUnmounted(() => {
  if (mqttClient) mqttClient.end() 
  window.removeEventListener('resize', () => myChart && myChart.resize())
  if (myChart) myChart.dispose()
})
</script>

<template>
  <div class="war-room">
    <header class="header">
      <div class="brand">
        <h1>邊緣運算預測中樞 <small>Edge Node 01</small></h1>
        <div class="indicator-group">
          <span class="dot" :class="{ error: systemStatus.includes('危險') || systemStatus.includes('失敗') || systemStatus.includes('異常') }"></span>
          <span class="status-msg">{{ systemStatus }}</span>
        </div>
      </div>
      
      <div class="actions">
        <span class="clock">{{ lastUpdateTime }}</span>
        <button class="btn" @click="isAutoFetch = !isAutoFetch" :class="{ active: isAutoFetch }">
          {{ isAutoFetch ? '即時監控中' : '暫停接收' }}
        </button>
        <button class="btn primary-btn" :disabled="isUploading" @click="sendDataToJetson">
          {{ isUploading ? '發布中...' : '發布特徵資料' }}
        </button>
        <button class="btn alert-btn" :class="{ active: isInjectingAnomaly }" @click="triggerAnomaly">
          {{ isInjectingAnomaly ? '指令已送出' : '觸發異常指令' }}
        </button>
      </div>
    </header>

    <main class="dashboard-grid">
      <section class="panel chart-panel" :class="{ 'danger-border': systemStatus.includes('危險') }">
        <div class="panel-header">
          <h2 class="title">反應器壓力趨勢分析</h2>
        </div>
        
        <div class="metrics-row">
          <div class="metric">
            <span class="label">當前壓力</span>
            <div class="number text-blue">{{ currentPressure.toFixed(2) }} <small>kg/cm²</small></div>
          </div>
          <div class="v-line"></div>
          <div class="metric">
            <span class="label">AI 5min 預估壓力</span>
            <div class="number text-red">{{ predictedPressure.toFixed(2) }} <small>kg/cm²</small></div>
          </div>
          <div class="v-line"></div>
          <div class="metric">
            <span class="label">AI 5min 預估甲烷</span>
            <div class="number text-green">{{ predictedCH4.toFixed(1) }} <small>%</small></div>
          </div>
        </div>

        <div class="chart-container" ref="chartRef"></div>
      </section>

      <aside class="side-stack">
        <div class="panel">
          <h2 class="title">感測器輸入特徵 (Features)</h2>
          <div class="sensor-list">
            <div class="item">
              <span>ORP (氧化還原電位)</span>
              <strong>{{ sensorData.orp.toFixed(1) }} <small>mV</small></strong>
            </div>
            <div class="item">
              <span>pH (酸鹼值)</span>
              <strong>{{ sensorData.ph.toFixed(2) }}</strong>
            </div>
            <div class="item">
              <span>Temperature</span>
              <strong>{{ sensorData.temp.toFixed(1) }} <small>°C</small></strong>
            </div>
            <div class="item">
              <span>CH4 (甲烷)</span>
              <strong>{{ sensorData.ch4.toFixed(1) }} <small>%</small></strong>
            </div>
          </div>
        </div>

        <div class="panel">
          <h2 class="title">節點狀態</h2>
          <ul class="stats-list">
            <li><span>核心裝置</span> <span>{{ nodeStats.device }}</span></li>
            <li><span>推論引擎</span> <span class="text-green">{{ nodeStats.engine }}</span></li>
            <li><span>推論延遲</span> <span class="text-red">{{ nodeStats.latency }} ms</span></li>
            <li><span>連線協定</span> <span class="text-blue">{{ nodeStats.protocol }}</span></li>
            <li><span>QoS 等級</span> <span>{{ nodeStats.qos }}</span></li>
          </ul>
        </div>
      </aside>
    </main>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&display=swap');

.war-room {
  min-height: 100vh;
  background-color: #0d0d0d;
  color: #e0e0e0;
  font-family: 'Noto Sans TC', sans-serif;
  padding: 1.5rem;
  box-sizing: border-box;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
  padding: 0 0.5rem 1rem;
  border-bottom: 1px solid #262626;
}
.brand h1 { font-size: 1.4rem; font-weight: 700; margin: 0; color: #fff; }
.brand small { font-size: 0.8rem; font-weight: 400; color: #666; margin-left: 8px; }
.indicator-group { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background-color: #2ecc71; }
.dot.error { background-color: #e74c3c; box-shadow: 0 0 8px #e74c3c; }
.status-msg { font-size: 0.9rem; color: #888; }

.actions { display: flex; align-items: center; gap: 12px; }
.clock { font-family: monospace; font-size: 1.1rem; color: #555; margin-right: 10px; }

.btn {
  background: #1a1a1a;
  border: 1px solid #333;
  color: #ccc;
  padding: 6px 14px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.9rem;
  transition: all 0.2s;
}
.btn:hover { background: #262626; border-color: #444; }
.btn.active { border-color: #3498db; color: #3498db; }
.primary-btn { border-color: #3498db; color: #3498db; }
.primary-btn:hover { background: rgba(52, 152, 219, 0.1); }
.alert-btn { border-color: #555; color: #888; }
.alert-btn:hover { border-color: #e74c3c; color: #e74c3c; }

.dashboard-grid {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 1.5rem;
}

.panel {
  background: #141414;
  border: 1px solid #262626;
  border-radius: 8px;
  padding: 1.25rem;
}
.danger-border { border-color: #e74c3c; }
.title { 
  margin: 0 0 1.25rem; 
  font-size: 1rem; 
  font-weight: 500; 
  color: #aaa; 
  border-left: 3px solid #3498db; 
  padding-left: 10px; 
}

.metrics-row {
  display: flex;
  justify-content: space-around;
  align-items: center;
  background: #0a0a0a;
  padding: 1.5rem;
  border-radius: 6px;
  margin-bottom: 1.5rem;
}
.metric { text-align: center; }
.metric .label { font-size: 0.85rem; color: #666; display: block; margin-bottom: 4px; }
.metric .number { font-size: 2.5rem; font-weight: 700; }
.metric small { font-size: 1rem; color: #444; }
.v-line { width: 1px; height: 40px; background: #222; }

.chart-container { width: 100%; height: 320px; }

.side-stack { display: flex; flex-direction: column; gap: 1.5rem; }
.sensor-list .item {
  display: flex;
  justify-content: space-between;
  padding: 0.8rem 0;
  border-bottom: 1px solid #1f1f1f;
}
.sensor-list .item:last-child { border-bottom: none; }
.sensor-list span { color: #777; font-size: 0.9rem; }
.sensor-list strong { font-size: 1.1rem; color: #eee; }
.sensor-list small { color: #555; font-weight: 400; }

.stats-list { list-style: none; padding: 0; margin: 0; }
.stats-list li {
  display: flex;
  justify-content: space-between;
  font-size: 0.85rem;
  color: #666;
  margin-bottom: 12px;
}

.text-blue { color: #3498db; }
.text-red { color: #e74c3c; }
.text-green { color: #2ecc71; }

@media (max-width: 900px) {
  .dashboard-grid { grid-template-columns: 1fr; }
}
</style>