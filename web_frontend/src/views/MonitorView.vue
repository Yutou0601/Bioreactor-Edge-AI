<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import mqtt from 'mqtt'
import apiClient from '../services/apiClient'

// ==========================================
// 系統狀態
// ==========================================
const currentPressure   = ref(0.0)
const predictedPressure = ref(0.0)
const predictedCH4      = ref(0.0)
const predStatus        = ref('')
const inferenceTimeMs   = ref(0.0)
const lastUpdateTime    = ref('--:--:--')
const isAutoFetch       = ref(true)
const isMqttConnected   = ref(false)
const isBackendOnline   = ref(true)   // HTTP 後端是否可達
const isLoadingRecords  = ref(false)
let   _fetchPending     = false       // 防止 poll 重疊

// 系統狀態文字：HTTP 為主，MQTT 為輔
const systemStatus = computed(() => {
  if (!isBackendOnline.value) return '後端無回應'
  if (isMqttConnected.value)  return '連線正常 (Active)'
  return 'HTTP 正常 · MQTT 離線'
})

// ==========================================
// 記錄資料 + 排序
// ==========================================
const records  = ref([])
const sortKey  = ref('id')
const sortDesc = ref(true)

const sortedRecords = computed(() => {
  const arr = [...records.value]
  arr.sort((a, b) => {
    const va = a[sortKey.value]
    const vb = b[sortKey.value]
    if (va < vb) return sortDesc.value ? 1 : -1
    if (va > vb) return sortDesc.value ? -1 : 1
    return 0
  })
  return arr
})

const setSort = (key) => {
  if (sortKey.value === key) sortDesc.value = !sortDesc.value
  else { sortKey.value = key; sortDesc.value = true }
}
const sortIndicator = (key) =>
  sortKey.value !== key ? '' : (sortDesc.value ? ' ↓' : ' ↑')

// ==========================================
// 手動輸入表單
// ==========================================
const showForm     = ref(true)
const isSubmitting = ref(false)
const formData     = ref({ orp: 550, pressure: 2.35, ph: 7.10, temp: 30.0, mixer_pressure: 1.00, co2_pct: 0.0, ch4_pct: 0.0, note: '' })

// ==========================================
// CSV 匯入
// ==========================================
const csvFile         = ref(null)
const csvFilename     = ref('')
const csvDetectedDate = ref('')
const csvImporting    = ref(false)
const csvResult       = ref(null)
const csvError        = ref('')
const csvFileInput    = ref(null)

const onCsvFileSelect = (e) => {
  const file = e.target.files[0]
  if (!file) return
  csvFile.value         = file
  csvFilename.value     = file.name
  const m               = file.name.match(/(\d{4}-\d{2}-\d{2})/)
  csvDetectedDate.value = m ? m[1] : '（無法識別）'
  csvResult.value = null
  csvError.value  = ''
}

const importCsv = async () => {
  if (!csvFile.value) return
  csvImporting.value = true
  csvError.value     = ''
  try {
    const fd = new FormData()
    fd.append('file', csvFile.value)
    const res = await apiClient.post('/import_csv', fd, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    csvResult.value = res.data
    // 若後端已預熱 LSTM buffer 並完成推論，直接更新壓力預測面板
    const p = res.data?.prediction
    if (p) {
      if (p.current_pressure_kg_cm2 != null) currentPressure.value   = p.current_pressure_kg_cm2
      if (p.predicted_pressure_5min != null) predictedPressure.value = p.predicted_pressure_5min
      if (p.predicted_ch4_5min      != null) predictedCH4.value      = p.predicted_ch4_5min
      if (p.status                  != null) predStatus.value        = p.status
    }
    await fetchRecords()
  } catch (e) {
    csvError.value = e.response?.data?.detail || e.message || '匯入失敗'
  } finally {
    csvImporting.value = false
  }
}

// ==========================================
// 壓力推論（HTTP fallback，補 MQTT 不在時的空白）
// ==========================================
const fetchPrediction = async () => {
  try {
    const res = await apiClient.get('/predict_pressure')
    const d = res.data
    if (d.current_pressure_kg_cm2 != null) currentPressure.value   = d.current_pressure_kg_cm2
    if (d.predicted_pressure_5min != null) predictedPressure.value = d.predicted_pressure_5min
    if (d.predicted_ch4_5min      != null) predictedCH4.value      = d.predicted_ch4_5min
    if (d.status                  != null) predStatus.value        = d.status
    if (d.inference_time_ms       != null) inferenceTimeMs.value   = d.inference_time_ms
  } catch { /* server 未啟動時靜默略過 */ }
}

// ==========================================
// 生物相位偵測
// ==========================================
const phaseData = ref(null)

const fetchPhase = async () => {
  try {
    const res = await apiClient.get('/phase')
    phaseData.value = res.data
  } catch (e) {
    console.warn('相位分析取得失敗:', e.message)
  }
}

const phaseBadgeClass = computed(() => {
  const p = phaseData.value?.phase
  return p === 1 ? 'badge-red' : p === 2 ? 'badge-green' : p === 3 ? 'badge-orange' : 'badge-gray'
})

const phaseTimeline = computed(() => {
  const list = phaseData.value?.transitions
  if (!list?.length) return []
  const total = list.reduce((s, t) => s + t.duration_min, 0) || 1
  return list.map(t => ({ ...t, pct: Math.max(2, Math.round(t.duration_min / total * 100)) }))
})

// ==========================================
// CH4 峰值預測靜態結果（GA 特徵 LOO-CV，Ridge α=1.0）
// ==========================================
const CH4_PEAK_CYCLES = [
  { id: 'C1', date: '2026-02-23', actual: 66.22, predicted: 65.81, error: -0.41 },
  { id: 'C2', date: '2026-03-03', actual: 65.16, predicted: 59.45, error: -5.71 },
  { id: 'C3', date: '2026-03-10', actual: 52.77, predicted: 52.60, error: -0.17 },
  { id: 'C4', date: '2026-03-16', actual: 51.91, predicted: 53.42, error:  1.51 },
  { id: 'C5', date: '2026-03-19', actual: 33.87, predicted: 37.58, error:  3.71 },
  { id: 'C6', date: '2026-03-24', actual: 48.15, predicted: 51.28, error:  3.13 },
]
const CH4_RMSE = 3.13
const CH4_GA_FEATURES = ['cycle_length_min', 'phase2_duration_min', 'phase2_fraction', 'phase3_onset_fraction', 'pressure_mean']
const showCh4Panel = ref(false)

// ==========================================
// 特徵分析（穩態 + 漂移率）
// ==========================================
const analysis = ref(null)

const activeAnalysis = computed(() => rangeAnalysis.value ?? analysis.value ?? {})

const fetchAnalysis = async () => {
  try {
    const res = await apiClient.get('/analysis')
    analysis.value = res.data
  } catch (e) {
    console.error('分析取得失敗:', e)
  }
}

// ==========================================
// API 操作
// ==========================================
const fetchRecords = async () => {
  if (_fetchPending) return          // 上一輪還在跑，跳過
  _fetchPending = true
  isLoadingRecords.value = true
  try {
    const res = await apiClient.get('/records')
    isBackendOnline.value = true
    records.value = res.data
    updateChart()
    lastUpdateTime.value = new Date().toLocaleTimeString('zh-TW', { hour12: false })
    await fetchAnalysis()
  } catch (e) {
    isBackendOnline.value = false
    console.warn('後端無回應:', e.message)
  } finally {
    isLoadingRecords.value = false
    _fetchPending = false
  }
}

const submitRecord = async (andPublish = false) => {
  isSubmitting.value = true
  try {
    const res = await apiClient.post('/records', formData.value)
    records.value.push(res.data)
    updateChart()
    if (andPublish) publishViaMqtt(res.data)
    lastUpdateTime.value = new Date().toLocaleTimeString('zh-TW', { hour12: false })
  } catch (e) {
    alert('新增失敗，請確認後端連線 (http://192.168.55.1:8000)')
  } finally {
    isSubmitting.value = false
  }
}

const deleteRecord = async (id) => {
  if (!confirm('確定要刪除這筆記錄？')) return
  try {
    await apiClient.delete(`/records/${id}`)
    records.value = records.value.filter(r => r.id !== id)
    updateChart()
  } catch (e) { console.error('刪除失敗:', e) }
}

const publishViaMqtt = (record) => {
  if (!mqttClient?.connected) { alert('MQTT 尚未連線'); return }
  const payload = JSON.stringify({
    timestamp:      record.timestamp,
    orp:            record.orp,
    pressure:       record.pressure,
    ph:             record.ph,
    temp:           record.temp,
    mixer_pressure: record.mixer_pressure,
    co2_pct:        record.co2_pct,
    ch4_pct:        record.ch4_pct,
  })
  mqttClient.publish('reactor/01/sensors', payload, { qos: 1 })
}

// ==========================================
// ORP 分析圖表（原始 / 去突波 / SG 濾波 / EMA + 突波標注）
// ==========================================
const chartRef    = ref(null)
const gasChartRef = ref(null)
let myChart    = null
let myGasChart = null

// ── 點選分析 ──────────────────────────────
const rangeAnalysis = ref(null)   // 點選結果（null = 使用全段 analysis）
const clickedIndex  = ref(null)   // 目前點選的資料索引

const computeLocalAnalysis = (subset, centerIdx = null) => {
  const n = subset.length
  if (n < 5) return null
  const vals = subset.map(r => r.orp)
  const mean = vals.reduce((a, b) => a + b, 0) / n
  const sigma = Math.sqrt(vals.reduce((s, v) => s + (v - mean) ** 2, 0) / (n - 1))
  const is_steady = sigma < 5.0 && mean >= 480 && mean <= 650
  // 線性回歸 → mV/hr
  const tMean = (n - 1) / 2
  const num = vals.reduce((s, v, i) => s + (i - tMean) * (v - mean), 0)
  const den = vals.reduce((s, _, i) => s + (i - tMean) ** 2, 0)
  const drift = den === 0 ? 0 : (num / den) * 60
  const centerRec = centerIdx != null ? records.value[centerIdx] : null
  const ts = centerRec?.timestamp?.slice(11, 16) ?? ''
  return {
    is_steady,
    sigma:          sigma.toFixed(2),
    orp_mean:       mean.toFixed(1),
    drift_rate:     parseFloat(drift.toFixed(3)),
    steady_minutes: n,
    record_count:   n,
    message:        ts ? `點選 ${ts}，前後共 ${n} 筆資料（視窗 ±15 min）` : `分析 ${n} 筆資料`,
    is_range:       true,
  }
}

const clearPoint = () => {
  rangeAnalysis.value = null
  clickedIndex.value  = null
  if (myChart) myChart.setOption({ series: [{}, {}, { markLine: { data: [] } }] })
}

// SG 濾波（window=11, poly=2）—— 應用於去突波後的 cleaned 數據
// 係數來源：Savitzky-Golay table, M=5, degree=2, normalization=429
const SG_COEFFS = [-36, 9, 44, 69, 84, 89, 84, 69, 44, 9, -36].map(c => c / 429)
const SG_HALF   = 5

const applySGFilter = (data) => {
  const n = data.length
  return data.map((v, i) => {
    if (i < SG_HALF || i >= n - SG_HALF) return v   // 邊界直接保留原值
    let sum = 0
    for (let k = -SG_HALF; k <= SG_HALF; k++) sum += SG_COEFFS[k + SG_HALF] * data[i + k]
    return sum
  })
}

// 四條線的顯示狀態
const seriesVisible = ref({ raw: true, cleaned: true, sg: true, ema: true })
const SERIES_NAMES  = { raw: '原始數據', cleaned: '去突波', sg: 'SG 濾波', ema: 'EMA' }

const toggleSeries = (key) => {
  if (!myChart) return
  seriesVisible.value[key] = !seriesVisible.value[key]
  myChart.dispatchAction({
    type: seriesVisible.value[key] ? 'legendSelect' : 'legendUnSelect',
    name: SERIES_NAMES[key],
  })
}

// 清除所有記錄
const isClearing = ref(false)
const clearRecords = async () => {
  if (!confirm('確定要清除所有記錄？此操作無法還原。')) return
  isClearing.value = true
  try {
    await apiClient.delete('/records')
    // 重新拉一次確認後端已清空，再更新 UI
    await fetchRecords()
    // 同步重置 CSV 匯入面板狀態
    csvResult.value  = null
    csvFile.value    = null
    csvFilename.value     = ''
    csvDetectedDate.value = ''
  } catch (e) {
    console.error('清除失敗:', e)
    alert('清除失敗，請確認後端連線 (http://192.168.55.1:8000)')
  } finally {
    isClearing.value = false
  }
}

const initChart = () => {
  if (!chartRef.value) return
  myChart = echarts.init(chartRef.value, null, { renderer: 'canvas' })
  myChart.setOption({
    backgroundColor: 'transparent',
    animation: false,
    // legend 不顯示但定義名稱供 dispatchAction 使用
    legend: {
      show: false,
      data: Object.values(SERIES_NAMES),
      selected: { '原始數據': true, '去突波': true, 'SG 濾波': true, 'EMA': true },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(10,10,14,0.96)',
      borderColor: '#222', borderWidth: 1,
      textStyle: { color: '#bbb', fontSize: 12 },
      formatter: (params) => {
        const ts = params[0]?.axisValue || ''
        let html = `<div style="color:#444;font-size:11px;margin-bottom:4px">${ts}</div>`
        params.forEach(p => {
          if (p.value == null) return
          html += `<div style="display:flex;justify-content:space-between;gap:20px">
            <span style="color:${p.color}">● ${p.seriesName}</span>
            <b style="color:#ddd">${p.value} mV</b>
          </div>`
        })
        return html
      }
    },
    grid: { left: '7%', right: '3%', bottom: '20%', top: '8%' },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
      {
        type: 'slider', xAxisIndex: 0,
        height: 20, bottom: 8,
        fillerColor: 'rgba(52,152,219,0.1)', borderColor: '#1e1e1e',
        handleStyle: { color: '#2980b9' }, moveHandleStyle: { color: '#2980b9' },
        textStyle: { color: '#333', fontSize: 10 }, showDataShadow: true,
        dataBackground: { lineStyle: { color: '#222' }, areaStyle: { color: '#181818' } },
      }
    ],
    xAxis: {
      type: 'category', data: [],
      axisLine: { lineStyle: { color: '#1e1e1e' } },
      axisTick: { show: false },
      axisLabel: { color: '#3a3a3a', fontSize: 10, interval: 'auto', hideOverlap: true },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value', name: 'mV', scale: true,
      nameTextStyle: { color: '#3a3a3a', fontSize: 10, padding: [0, 6, 0, 0] },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } },
      axisLabel: { color: '#3a3a3a', fontSize: 10 },
    },
    series: [
      {
        name: '原始數據', type: 'line', data: [],
        symbol: 'circle', symbolSize: 3, showSymbol: false,
        lineStyle: { width: 1, color: 'rgba(231,76,60,0.45)' },
        itemStyle: { color: 'rgba(231,76,60,0.45)' },
        z: 1,
      },
      {
        name: '去突波', type: 'line', data: [],
        symbol: 'circle', symbolSize: 3, showSymbol: false,
        lineStyle: { width: 1, color: '#27ae60', type: 'dashed' },
        itemStyle: { color: '#27ae60' },
        z: 2,
      },
      {
        name: 'SG 濾波', type: 'line', data: [],
        symbol: 'circle', symbolSize: 4, showSymbol: false,
        lineStyle: { width: 2, color: '#f39c12' },
        itemStyle: { color: '#f39c12' },
        z: 3,
      },
      {
        name: 'EMA', type: 'line', data: [],
        symbol: 'circle', symbolSize: 4, showSymbol: false,
        lineStyle: { width: 2.5, color: '#3498db' },
        itemStyle: { color: '#3498db' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(52,152,219,0.12)' },
            { offset: 1, color: 'rgba(52,152,219,0)' },
          ]),
        },
        z: 4,
      },
    ],
  })

  // 點擊事件 → 計算前後 ±15 筆（共 30 筆）的局部分析
  myChart.on('click', (params) => {
    if (params.dataIndex == null) return
    const i = params.dataIndex
    clickedIndex.value = i
    const half  = 15
    const start = Math.max(0, i - half)
    const end   = Math.min(records.value.length, i + half + 1)
    const subset = records.value.slice(start, end)
    rangeAnalysis.value = computeLocalAnalysis(subset, i)
    // 在點選位置畫垂直虛線
    const xData = records.value.map(r => {
      const ts = r.timestamp || ''
      const m = ts.match(/\d{4}-(\d{2}-\d{2}) (\d{2}:\d{2})/)
      return m ? `${m[1]} ${m[2]}` : ts.slice(5, 16)
    })
    myChart.setOption({
      series: [{}, {}, {
        markLine: {
          silent: true, symbol: 'none',
          lineStyle: { color: 'rgba(52,152,219,0.55)', type: 'dashed', width: 1.5 },
          data: [{ xAxis: xData[i] }],
        },
      }],
    })
  })
}

const initGasChart = () => {
  if (!gasChartRef.value) return
  myGasChart = echarts.init(gasChartRef.value, null, { renderer: 'canvas' })
  myGasChart.setOption({
    backgroundColor: 'transparent',
    animation: false,
    legend: { show: false },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(10,10,14,0.96)',
      borderColor: '#222', borderWidth: 1,
      textStyle: { color: '#bbb', fontSize: 12 },
      formatter: (params) => {
        const ts = params[0]?.axisValue || ''
        let html = `<div style="color:#444;font-size:11px;margin-bottom:4px">${ts}</div>`
        params.forEach(p => {
          if (p.value == null) return
          html += `<div style="display:flex;justify-content:space-between;gap:20px">
            <span style="color:${p.color}">● ${p.seriesName}</span>
            <b style="color:#ddd">${p.value.toFixed(1)} %</b>
          </div>`
        })
        return html
      }
    },
    grid: { left: '7%', right: '3%', bottom: '22%', top: '10%' },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
      { type: 'slider', xAxisIndex: 0, height: 18, bottom: 6,
        fillerColor: 'rgba(52,152,219,0.1)', borderColor: '#1e1e1e',
        handleStyle: { color: '#2980b9' }, textStyle: { color: '#333', fontSize: 10 } }
    ],
    xAxis: {
      type: 'category', data: [],
      axisLine: { lineStyle: { color: '#1e1e1e' } },
      axisTick: { show: false },
      axisLabel: { color: '#3a3a3a', fontSize: 10, interval: 'auto', hideOverlap: true },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value', name: '%', min: 0, max: 100,
      nameTextStyle: { color: '#3a3a3a', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } },
      axisLabel: { color: '#3a3a3a', fontSize: 10 },
    },
    series: [
      {
        name: 'CH4 %', type: 'line', data: [],
        symbol: 'circle', symbolSize: 3, showSymbol: false,
        lineStyle: { width: 2, color: '#e67e22' },
        itemStyle: { color: '#e67e22' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0,0,0,1,[
          { offset: 0, color: 'rgba(230,126,34,0.18)' },
          { offset: 1, color: 'rgba(230,126,34,0)' },
        ])},
        z: 2,
      },
      {
        name: 'CO2 %', type: 'line', data: [],
        symbol: 'circle', symbolSize: 3, showSymbol: false,
        lineStyle: { width: 1.5, color: '#9b59b6', type: 'dashed' },
        itemStyle: { color: '#9b59b6' },
        z: 1,
      }
    ]
  })
}

const updateGasChart = () => {
  if (!myGasChart) return
  const data = records.value
  if (data.length === 0) {
    myGasChart.setOption({ xAxis: { data: [] }, series: [{ data: [] }, { data: [] }] })
    return
  }
  const xData   = data.map(r => {
    const ts = r.timestamp || ''
    const m = ts.match(/\d{4}-(\d{2}-\d{2}) (\d{2}:\d{2})/)
    return m ? `${m[1]} ${m[2]}` : ts.slice(5, 16)
  })
  const ch4Data = data.map(r => r.ch4_pct ?? null)
  const co2Data = data.map(r => r.co2_pct ?? null)
  myGasChart.setOption({ xAxis: { data: xData }, series: [{ data: ch4Data }, { data: co2Data }] })
}

const updateChart = () => {
  if (!myChart) return
  const data = records.value
  if (data.length === 0) {
    myChart.setOption({
      xAxis: { data: [] },
      series: [
        { data: [] },
        { data: [] },
        { data: [], markArea: { data: [] } }   // 明確清除突波底色
      ]
    })
    return
  }

  const xData = data.map(r => {
    const ts = r.timestamp || ''
    const m = ts.match(/\d{4}-(\d{2}-\d{2}) (\d{2}:\d{2})/)
    return m ? `${m[1]} ${m[2]}` : ts.slice(5, 16)
  })

  // 四個資料序列
  const rawData     = data.map(r => r.orp_raw     != null ? r.orp_raw     : r.orp)
  const cleanedData = data.map(r => r.orp_cleaned  != null ? r.orp_cleaned : r.orp)
  const sgData      = applySGFilter(cleanedData)   // SG 濾波套用在去突波後的數據
  const emaData     = data.map(r => r.orp)

  // 突波區間 markArea
  const markAreas = []
  let sIdx = null
  data.forEach((r, i) => {
    if (r.is_anomaly && sIdx === null) sIdx = i
    else if (!r.is_anomaly && sIdx !== null) {
      markAreas.push([{ xAxis: xData[sIdx] }, { xAxis: xData[i - 1] }])
      sIdx = null
    }
  })
  if (sIdx !== null) markAreas.push([{ xAxis: xData[sIdx] }, { xAxis: xData[data.length - 1] }])

  myChart.setOption({
    xAxis: { data: xData },
    series: [
      { data: rawData },
      { data: cleanedData },
      { data: sgData },
      {
        data: emaData,
        markArea: {
          silent: true,
          itemStyle: { color: 'rgba(231,76,60,0.07)' },
          label: { show: false },
          data: markAreas,
        },
      },
    ],
  })
  updateGasChart()
}

// ==========================================
// MQTT
// ==========================================
let mqttClient = null

const initMqtt = () => {
  try {
    mqttClient = mqtt.connect('ws://192.168.55.1:9001', {
      reconnectPeriod: 15000,   // 15s 重試一次，不要每秒洗狀態
      connectTimeout:  4000,
    })

    mqttClient.on('connect', () => {
      isMqttConnected.value = true
      mqttClient.subscribe('reactor/01/prediction', () => {})
    })
    mqttClient.on('message', (topic, message) => {
      if (topic === 'reactor/01/prediction') {
        try {
          const d = JSON.parse(message.toString())
          if (d.current_pressure_kg_cm2  != null) currentPressure.value   = d.current_pressure_kg_cm2
          if (d.predicted_pressure_5min  != null) predictedPressure.value = d.predicted_pressure_5min
          if (d.predicted_ch4_5min       != null) predictedCH4.value      = d.predicted_ch4_5min
          if (d.status                   != null) predStatus.value        = d.status
          if (d.inference_time_ms        != null) inferenceTimeMs.value   = d.inference_time_ms
        } catch {}
      }
      if (isAutoFetch.value)
        lastUpdateTime.value = new Date().toLocaleTimeString('zh-TW', { hour12: false })
    })
    mqttClient.on('connect', () => { isMqttConnected.value = true  })
    mqttClient.on('error',   () => { isMqttConnected.value = false })
    mqttClient.on('offline', () => { isMqttConnected.value = false })
  } catch {
    isMqttConnected.value = false
  }
}

// ==========================================
// 生命週期
// ==========================================
let pollTimer = null

onMounted(async () => {
  await fetchRecords()
  await fetchPrediction()
  await fetchPhase()
  initChart()
  initGasChart()
  initMqtt()
  // USB 每分鐘一筆，60 秒輪詢一次即可 (目前先測試 5 秒一次)
  pollTimer = setInterval(() => {
    if (isAutoFetch.value) {
      fetchRecords()
      fetchPrediction()
      fetchPhase()
    }
  }, 5000)
  window.addEventListener('resize', () => { myChart?.resize(); myGasChart?.resize() })
})
onUnmounted(() => {
  mqttClient?.end()
  clearInterval(pollTimer)
  window.removeEventListener('resize', () => { myChart?.resize(); myGasChart?.resize() })
  myChart?.dispose()
  myGasChart?.dispose()
})
</script>

<template>
  <div class="app">

    <!-- ===== Header ===== -->
    <header class="header">
      <div class="brand">
        <h1>生物反應器感測器數據管理 <small>ORP Edge Monitor · Jetson Orin NANO</small></h1>
        <div class="status-group">
          <span class="dot" :class="{ connected: isMqttConnected && isBackendOnline, error: !isBackendOnline }"></span>
          <span class="status-text">{{ systemStatus }}</span>
        </div>
      </div>
      <div class="header-actions">
        <span class="clock">{{ lastUpdateTime }}</span>
        <button class="btn" :class="{ active: isAutoFetch }" @click="isAutoFetch = !isAutoFetch">
          {{ isAutoFetch ? '即時接收中' : '已暫停' }}
        </button>
        <button class="btn" @click="fetchRecords" :disabled="isLoadingRecords">
          {{ isLoadingRecords ? '同步中...' : '重新整理' }}
        </button>
      </div>
    </header>

    <!-- ===== Main Layout ===== -->
    <main class="main-grid">

      <!-- ── Left Column ── -->
      <aside class="left-col">

        <!-- 手動輸入 -->
        <div class="panel">
          <div class="panel-header">
            <h2 class="panel-title">手動輸入感測器數據</h2>
            <button class="toggle-btn" @click="showForm = !showForm">
              {{ showForm ? '▲ 收起' : '▼ 展開' }}
            </button>
          </div>
          <div v-show="showForm" class="form-body">
            <div class="form-grid">
              <div class="form-group">
                <label>ORP <span class="unit">mV</span></label>
                <input type="number" v-model.number="formData.orp" step="1" />
              </div>
              <div class="form-group">
                <label>壓力 <span class="unit">kg/cm²</span></label>
                <input type="number" v-model.number="formData.pressure" step="0.01" />
              </div>
              <div class="form-group">
                <label>pH</label>
                <input type="number" v-model.number="formData.ph" step="0.01" min="0" max="14" />
              </div>
              <div class="form-group">
                <label>溫度 <span class="unit">°C</span></label>
                <input type="number" v-model.number="formData.temp" step="0.1" />
              </div>
              <div class="form-group">
                <label>混合槽壓力 <span class="unit">kg/cm²</span></label>
                <input type="number" v-model.number="formData.mixer_pressure" step="0.01" />
              </div>
              <div class="form-group">
                <label>CO2 <span class="unit">%</span></label>
                <input type="number" v-model.number="formData.co2_pct" step="0.1" min="0" max="100" />
              </div>
              <div class="form-group full">
                <label>CH4 <span class="unit">%</span></label>
                <input type="number" v-model.number="formData.ch4_pct" step="0.1" min="0" max="100" />
              </div>
              <div class="form-group full">
                <label>備注</label>
                <input type="text" v-model="formData.note" placeholder="選填（事件說明、批次號…）" />
              </div>
            </div>
            <div class="form-actions">
              <button class="btn primary-btn" @click="submitRecord(false)" :disabled="isSubmitting">
                {{ isSubmitting ? '新增中...' : '新增到列表' }}
              </button>
              <button class="btn publish-btn" @click="submitRecord(true)"
                :disabled="isSubmitting || !isMqttConnected"
                :title="isMqttConnected ? '新增並透過 MQTT 發布' : 'MQTT 未連線'">
                新增並發布
              </button>
            </div>
            <p v-if="!isMqttConnected" class="mqtt-hint">⚠ MQTT 未連線，「新增並發布」暫不可用</p>
          </div>
        </div>

        <!-- CSV 匯入 -->
        <div class="panel import-panel">
          <h2 class="panel-title">CSV 資料匯入</h2>

          <div class="import-body">
            <!-- 檔案選擇區 -->
            <div class="file-drop" @click="csvFileInput?.click()">
              <input ref="csvFileInput" type="file" accept=".csv" style="display:none" @change="onCsvFileSelect" />
              <span class="file-icon">📂</span>
              <span class="file-name" :class="{ 'has-file': csvFilename }">
                {{ csvFilename || '點擊選擇 BTP_Sensor_log CSV 檔' }}
              </span>
            </div>

            <!-- 識別結果 -->
            <div v-if="csvFilename" class="file-meta">
              <span class="meta-label">識別日期</span>
              <span class="meta-date">{{ csvDetectedDate }}</span>
            </div>

            <!-- 匯入按鈕 -->
            <button class="btn import-btn"
              @click="importCsv"
              :disabled="!csvFile || csvImporting">
              <span v-if="csvImporting" class="spinner">⟳</span>
              {{ csvImporting ? '匯入中...' : '開始匯入並分析' }}
            </button>

            <!-- 結果 -->
            <div v-if="csvResult" class="import-result">
              <div class="result-row">
                <span class="result-icon ok">✓</span>
                匯入 <b>{{ csvResult.imported }}</b> 筆資料
              </div>
              <div class="result-row" v-if="csvResult.anomalies_detected > 0">
                <span class="result-icon warn">⚠</span>
                偵測突波 <b>{{ csvResult.anomalies_detected }}</b> 個，已線性內插修復
              </div>
              <div class="orp-stat-bar">
                <span title="最低">↓ {{ csvResult.orp_stats.min }}</span>
                <span title="平均">≈ {{ csvResult.orp_stats.avg }}</span>
                <span title="最高">↑ {{ csvResult.orp_stats.max }}</span>
                <span class="stat-unit">mV (EMA)</span>
              </div>
            </div>

            <div v-if="csvError" class="import-error">❌ {{ csvError }}</div>
          </div>
        </div>

      </aside>

      <!-- ── Right Column ── -->
      <section class="right-col">

        <!-- 壓力預測卡片 -->
        <div class="panel pred-panel">
          <div class="pred-header">
            <h2 class="panel-title">壓力 / CH4 預測 <small>LSTM · 未來 5 min</small></h2>
            <span class="an-badge"
              :class="predStatus.includes('危險') ? 'badge-red'
                    : predStatus.includes('警告') ? 'badge-yellow'
                    : predStatus.includes('正常') ? 'badge-green'
                    : 'badge-gray'">
              {{ predStatus || '等待推論...' }}
            </span>
          </div>
          <div class="pred-body">
            <div class="pred-block">
              <span class="an-label">即時壓力</span>
              <span class="an-value pred-val">{{ currentPressure.toFixed(2) }}<span class="pred-unit"> kg/cm²</span></span>
            </div>
            <div class="pred-divider"></div>
            <div class="pred-block">
              <span class="an-label">預測壓力（+5min）</span>
              <span class="an-value pred-val"
                :class="predictedPressure > 2.6 ? 'val-danger' : ''">
                {{ predictedPressure.toFixed(2) }}<span class="pred-unit"> kg/cm²</span>
              </span>
            </div>
            <div class="pred-divider"></div>
            <div class="pred-block">
              <span class="an-label">預測 CH4（+5min）</span>
              <span class="an-value pred-val">{{ predictedCH4.toFixed(1) }}<span class="pred-unit"> %</span></span>
            </div>
            <div class="pred-divider"></div>
            <div class="pred-block">
              <span class="an-label">推論耗時</span>
              <span class="an-value pred-val">{{ inferenceTimeMs.toFixed(1) }}<span class="pred-unit"> ms</span></span>
            </div>
          </div>
        </div>

        <!-- 生物相位面板 -->
        <div class="panel phase-panel">
          <div class="phase-header">
            <h2 class="panel-title">生物相位偵測 <small>ORP Adaptive Phase Detection</small></h2>
            <span v-if="phaseData" class="an-badge" :class="phaseBadgeClass">
              {{ phaseData.phase === 0 ? '資料不足' : `P${phaseData.phase} · ${phaseData.label_zh}` }}
            </span>
            <span v-else class="an-badge badge-gray">等待資料...</span>
          </div>

          <div v-if="phaseData && phaseData.phase > 0" class="phase-body">

            <!-- 指標列 -->
            <div class="phase-metrics">
              <div class="pm-block">
                <span class="an-label">當前相位</span>
                <span class="an-value phase-num" :style="{ color: phaseData.color }">
                  Phase {{ phaseData.phase }}
                </span>
              </div>
              <div class="pm-block">
                <span class="an-label">持續時間</span>
                <span class="an-value">{{ phaseData.duration_min }} <span class="pred-unit">min</span></span>
              </div>
              <div class="pm-block">
                <span class="an-label">目前斜率</span>
                <span class="an-value"
                  :class="phaseData.slope_current > phaseData.thresholds.hi ? 'val-up'
                         : phaseData.slope_current < phaseData.thresholds.lo ? 'val-down' : 'val-flat'">
                  {{ phaseData.slope_current > 0 ? '+' : '' }}{{ phaseData.slope_current.toFixed(3) }}
                  <span class="pred-unit">mV/min</span>
                </span>
              </div>
              <div class="pm-block">
                <span class="an-label">閾值 lo / hi</span>
                <span class="an-value" style="font-size:0.78rem">
                  {{ phaseData.thresholds.lo.toFixed(3) }} /
                  {{ phaseData.thresholds.hi.toFixed(3) }}
                </span>
              </div>
              <div class="pm-block pm-wide">
                <span class="an-label">{{ phaseData.label_en }}</span>
                <span class="phase-desc" :style="{ color: phaseData.color }">
                  {{ phaseData.phase === 1 ? '嗜氫菌活躍，ORP 下降中'
                   : phaseData.phase === 2 ? '甲烷菌代謝活躍，ORP 穩定'
                   : '底物耗盡，ORP 回升' }}
                </span>
              </div>
            </div>

            <!-- 相位時間軸 -->
            <div v-if="phaseTimeline.length" class="phase-timeline-wrap">
              <div class="phase-timeline-label">相位歷程（最近 {{ phaseTimeline.length }} 段）</div>
              <div class="phase-timeline">
                <div v-for="(seg, i) in phaseTimeline" :key="i"
                  class="pt-seg"
                  :class="{ 'pt-current': seg.is_current }"
                  :style="{ width: seg.pct + '%', background: seg.color + (seg.is_current ? '' : '55') }"
                  :title="`P${seg.phase} ${seg.label_zh}\n開始：${seg.start}\n持續：${seg.duration_min} min`">
                  <span v-if="seg.pct >= 8" class="pt-label">P{{ seg.phase }}</span>
                </div>
              </div>
              <div class="phase-timeline-times">
                <span v-for="(seg, i) in phaseTimeline" :key="i"
                  class="pt-time" :style="{ width: seg.pct + '%' }">
                  <span v-if="seg.pct >= 10">{{ seg.duration_min }}m</span>
                </span>
              </div>
            </div>

          </div>

          <div v-else-if="phaseData" class="phase-empty">
            {{ phaseData.message }}
          </div>
        </div>

        <!-- ORP 訊號分析圖 -->
        <div class="panel chart-panel">
          <div class="chart-toolbar">
            <h2 class="panel-title">ORP 訊號分析</h2>

            <!-- 系列 toggle chips -->
            <div class="series-chips">
              <button class="chip chip-raw"
                :class="{ 'chip-off': !seriesVisible.raw }"
                @click="toggleSeries('raw')">原始數據</button>
              <button class="chip chip-cleaned"
                :class="{ 'chip-off': !seriesVisible.cleaned }"
                @click="toggleSeries('cleaned')">去突波</button>
              <button class="chip chip-sg"
                :class="{ 'chip-off': !seriesVisible.sg }"
                @click="toggleSeries('sg')">SG 濾波</button>
              <button class="chip chip-ema"
                :class="{ 'chip-off': !seriesVisible.ema }"
                @click="toggleSeries('ema')">EMA</button>
            </div>

            <div class="chart-meta">
              <span class="record-count">{{ records.length }} 筆</span>
              <span class="click-hint">點擊曲線上的點查看局部分析</span>
              <button class="btn clear-btn"
                @click="clearRecords"
                :disabled="isClearing || records.length === 0"
                title="清除所有記錄（無法還原）">
                {{ isClearing ? '清除中...' : '清除資料' }}
              </button>
            </div>
          </div>
          <div ref="chartRef" class="chart-container"></div>

          <!-- 特徵分析列 -->
          <div v-if="analysis || rangeAnalysis" class="analysis-bar"
               :class="{ 'analysis-bar-range': rangeAnalysis }">

            <!-- 來源標籤 -->
            <div class="an-source">
              <span v-if="rangeAnalysis" class="source-tag source-range">點選分析</span>
              <span v-else class="source-tag source-all">全段分析</span>
              <button v-if="rangeAnalysis" class="clear-range-btn" @click="clearPoint" title="清除點選">×</button>
            </div>

            <!-- 穩態狀態燈 -->
            <div class="an-block">
              <span class="an-label">反應槽狀態</span>
              <span class="an-badge"
                :class="activeAnalysis.record_count < 30 ? 'badge-gray'
                       : activeAnalysis.is_steady        ? 'badge-green'
                                                         : 'badge-orange'">
                {{ activeAnalysis.record_count < 30 ? '資料不足' : activeAnalysis.is_steady ? '穩態' : '擾動中' }}
              </span>
            </div>
            <!-- 漂移率 -->
            <div class="an-block">
              <span class="an-label">基準漂移率</span>
              <span class="an-value"
                :class="activeAnalysis.drift_rate < -0.1 ? 'val-down'
                       : activeAnalysis.drift_rate >  0.1 ? 'val-up'
                                                           : 'val-flat'">
                {{ activeAnalysis.drift_rate > 0 ? '+' : '' }}{{ Number(activeAnalysis.drift_rate).toFixed(2) }} mV/hr
              </span>
            </div>
            <!-- σ -->
            <div class="an-block">
              <span class="an-label">σ{{ rangeAnalysis ? '' : '（30min）' }}</span>
              <span class="an-value">{{ activeAnalysis.sigma }} mV</span>
            </div>
            <!-- EMA 均值 -->
            <div class="an-block">
              <span class="an-label">EMA 均值</span>
              <span class="an-value">{{ activeAnalysis.orp_mean }} mV</span>
            </div>
            <!-- 持續/筆數 -->
            <div class="an-block">
              <span class="an-label">{{ rangeAnalysis ? '分析筆數' : '穩態持續' }}</span>
              <span class="an-value">{{ activeAnalysis.steady_minutes }} {{ rangeAnalysis ? '筆' : 'min' }}</span>
            </div>
            <!-- 說明文字 -->
            <div class="an-message">{{ activeAnalysis.message }}</div>
          </div>
        </div>

        <!-- CH4 / CO2 趨勢圖 -->
        <div class="panel chart-panel">
          <div class="chart-toolbar">
            <h2 class="panel-title">CH4 / CO2 濃度趨勢</h2>
            <span class="record-count" style="margin-left:auto">
              {{ records.length > 0 ? `最新 CH4: ${records[records.length-1]?.ch4_pct?.toFixed(1) ?? '--'} %` : '' }}
            </span>
          </div>
          <div ref="gasChartRef" class="chart-container" style="height:180px"></div>
        </div>

        <!-- CH4 峰值預測結果 -->
        <div class="panel ch4-panel">
          <div class="ch4-header">
            <h2 class="panel-title">CH4 峰值預測結果 <small>GA + Ridge LOO-CV · 6 排氣週期</small></h2>
            <div class="ch4-badges">
              <span class="rmse-badge">RMSE = {{ CH4_RMSE }}%</span>
              <span class="ga-badge">GA 選出 5/11 特徵</span>
              <button class="btn toggle-ch4-btn" @click="showCh4Panel = !showCh4Panel">
                {{ showCh4Panel ? '▲ 收起' : '▼ 展開' }}
              </button>
            </div>
          </div>

          <div v-show="showCh4Panel" class="ch4-body">

            <!-- GA 特徵標籤 -->
            <div class="ga-features">
              <span class="ga-label">GA 選出特徵：</span>
              <span v-for="f in CH4_GA_FEATURES" :key="f" class="ga-feat-tag">{{ f }}</span>
            </div>

            <!-- 預測 vs 實際表格 -->
            <table class="ch4-table">
              <thead>
                <tr>
                  <th>週期</th>
                  <th>日期</th>
                  <th class="ta-r">實際 CH4 峰值</th>
                  <th class="ta-r">預測值</th>
                  <th class="ta-r">誤差</th>
                  <th class="ta-r">誤差條</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="c in CH4_PEAK_CYCLES" :key="c.id"
                  :class="{ 'ch4-row-warn': Math.abs(c.error) > 4 }">
                  <td class="cy-id">{{ c.id }}</td>
                  <td class="cy-date">{{ c.date }}</td>
                  <td class="ta-r cy-val">{{ c.actual.toFixed(2) }}%</td>
                  <td class="ta-r cy-pred">{{ c.predicted.toFixed(2) }}%</td>
                  <td class="ta-r cy-err"
                    :class="c.error < -4 || c.error > 4 ? 'err-large' : 'err-ok'">
                    {{ c.error > 0 ? '+' : '' }}{{ c.error.toFixed(2) }}%
                  </td>
                  <td class="ta-r cy-bar">
                    <div class="err-bar-wrap">
                      <div class="err-bar-track">
                        <div class="err-bar-fill"
                          :style="{
                            width: Math.min(Math.abs(c.error) / 7 * 100, 100) + '%',
                            background: Math.abs(c.error) > 4 ? '#e74c3c' : '#2ecc71',
                            marginLeft: c.error < 0 ? 'auto' : '0',
                          }">
                        </div>
                      </div>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>

            <!-- RMSE 計算說明 -->
            <div class="rmse-formula">
              RMSE = √[(0.41² + 5.71² + 0.17² + 1.51² + 3.71² + 3.13²) / 6]
              = √(58.64 / 6) = √9.77 = <b>3.13%</b>
              <span class="rmse-note">（C2 誤差最大；其餘均 &lt; 4%）</span>
            </div>
          </div>
        </div>

        <!-- 資料表格 -->
        <div class="panel table-panel">
          <div class="panel-header">
            <h2 class="panel-title">
              感測器記錄列表
              <span class="badge">{{ records.length }} 筆</span>
            </h2>
          </div>

          <div class="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th class="th-id sortable" @click="setSort('id')">#{{ sortIndicator('id') }}</th>
                  <th class="th-time sortable" @click="setSort('timestamp')">時間{{ sortIndicator('timestamp') }}</th>
                  <th class="th-num sortable" @click="setSort('orp')">ORP (mV){{ sortIndicator('orp') }}</th>
                  <th class="th-num sortable" @click="setSort('pressure')">P反<br><span class="unit">kg/cm²</span>{{ sortIndicator('pressure') }}</th>
                  <th class="th-num sortable" @click="setSort('mixer_pressure')">P混<br><span class="unit">kg/cm²</span>{{ sortIndicator('mixer_pressure') }}</th>
                  <th class="th-num sortable" @click="setSort('ph')">pH{{ sortIndicator('ph') }}</th>
                  <th class="th-num sortable" @click="setSort('temp')">溫度<br><span class="unit">°C</span>{{ sortIndicator('temp') }}</th>
                  <th class="th-num sortable" @click="setSort('co2_pct')">CO2<br><span class="unit">%</span>{{ sortIndicator('co2_pct') }}</th>
                  <th class="th-num sortable" @click="setSort('ch4_pct')">CH4<br><span class="unit">%</span>{{ sortIndicator('ch4_pct') }}</th>
                  <th class="th-note">備注</th>
                  <th class="th-action">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="sortedRecords.length === 0">
                  <td colspan="11" class="empty-state">尚無記錄 — 請匯入 CSV 或使用左側表單新增</td>
                </tr>
                <tr v-for="record in sortedRecords" :key="record.id" class="data-row"
                  :class="{ 'row-anomaly': record.is_anomaly }">
                  <td class="td-id">{{ record.id }}</td>
                  <td class="td-time">{{ record.timestamp }}</td>
                  <td class="td-orp" :class="{ 'orp-warn': record.orp < 500, 'orp-high': record.orp > 580 }">
                    {{ typeof record.orp === 'number' ? record.orp.toFixed(1) : record.orp }}
                    <span v-if="record.is_anomaly" class="anomaly-tag" title="突波修正區間（線性內插）">⚠</span>
                  </td>
                  <td>{{ record.pressure?.toFixed(2) ?? '-' }}</td>
                  <td>{{ record.mixer_pressure?.toFixed(2) ?? '-' }}</td>
                  <td>{{ record.ph?.toFixed(2) ?? '-' }}</td>
                  <td>{{ record.temp?.toFixed(1) ?? '-' }}</td>
                  <td class="td-co2">{{ record.co2_pct?.toFixed(1) ?? '-' }}</td>
                  <td class="td-ch4">{{ record.ch4_pct?.toFixed(1) ?? '-' }}</td>
                  <td class="td-note">{{ record.note || '—' }}</td>
                  <td class="td-action">
                    <button class="btn-sm publish" @click="publishViaMqtt(record)"
                      :disabled="!isMqttConnected" title="發布至 MQTT">發布</button>
                    <button class="btn-sm del" @click="deleteRecord(record.id)" title="刪除">刪除</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

      </section>
    </main>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&display=swap');

*, *::before, *::after { box-sizing: border-box; }

.app {
  min-height: 100vh;
  background: #0d0d0d;
  color: #e0e0e0;
  font-family: 'Noto Sans TC', sans-serif;
  padding: 1.25rem;
}

/* ─── Header ─── */
.header {
  display: flex; justify-content: space-between; align-items: center;
  padding-bottom: 1rem; margin-bottom: 1.25rem;
  border-bottom: 1px solid #1a1a1a;
}
.brand h1 { font-size: 1.2rem; font-weight: 700; margin: 0 0 4px; color: #fff; }
.brand small { font-size: 0.72rem; font-weight: 400; color: #444; margin-left: 8px; }
.status-group { display: flex; align-items: center; gap: 7px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #333; flex-shrink: 0; }
.dot.connected { background: #2ecc71; box-shadow: 0 0 6px #2ecc71; }
.dot.error      { background: #e74c3c; box-shadow: 0 0 6px #e74c3c; }
.status-text { font-size: 0.83rem; color: #555; }
.header-actions { display: flex; align-items: center; gap: 10px; }
.clock { font-family: monospace; font-size: 0.95rem; color: #3a3a3a; margin-right: 4px; }

/* ─── Buttons ─── */
.btn {
  background: #161616; border: 1px solid #262626; color: #aaa;
  padding: 5px 13px; border-radius: 4px; cursor: pointer;
  font-size: 0.83rem; transition: all 0.15s; font-family: inherit;
}
.btn:hover:not(:disabled)  { background: #1e1e1e; border-color: #383838; color: #ccc; }
.btn:disabled              { opacity: 0.35; cursor: not-allowed; }
.btn.active                { border-color: #2980b9; color: #3498db; }
.primary-btn               { border-color: #2980b9; color: #3498db; }
.primary-btn:hover:not(:disabled) { background: rgba(52,152,219,0.08); }
.publish-btn               { border-color: #27ae60; color: #2ecc71; }
.publish-btn:hover:not(:disabled) { background: rgba(46,204,113,0.08); }
.publish-btn:disabled      { border-color: #222; color: #333; }

/* ─── Layout ─── */
.main-grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 1.25rem;
  align-items: start;
}

/* ─── Panel ─── */
.panel {
  background: #111; border: 1px solid #1a1a1a;
  border-radius: 6px; padding: 1rem; margin-bottom: 1.25rem;
}
.panel:last-child { margin-bottom: 0; }
.panel-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 0.9rem;
}
.panel-title {
  margin: 0; font-size: 0.88rem; font-weight: 600; color: #999;
  border-left: 3px solid #2980b9; padding-left: 9px;
}
.badge {
  display: inline-block; margin-left: 8px; font-size: 0.72rem;
  background: #1a2a3a; color: #3498db;
  padding: 1px 7px; border-radius: 10px; font-weight: 400;
}
.toggle-btn {
  background: none; border: none; color: #444; font-size: 0.76rem;
  cursor: pointer; font-family: inherit;
}
.toggle-btn:hover { color: #777; }
.unit { font-size: 0.68rem; color: #3a3a3a; margin-left: 3px; }

/* ─── Form ─── */
.form-body { margin-top: 0.4rem; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; }
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group.full { grid-column: 1 / -1; }
.form-group label { font-size: 0.76rem; color: #555; }
.form-group input {
  background: #0d0d0d; border: 1px solid #222; border-radius: 4px;
  color: #ccc; padding: 5px 8px; font-size: 0.86rem; font-family: monospace;
  transition: border-color 0.15s; width: 100%;
}
.form-group input:focus { outline: none; border-color: #2980b9; }
.form-actions { display: flex; gap: 8px; margin-top: 0.85rem; }
.mqtt-hint { margin: 6px 0 0; font-size: 0.73rem; color: #6a5a1f; }

/* ─── CSV Import Panel ─── */
.import-panel .panel-title { border-left-color: #16a085; }

.import-body { display: flex; flex-direction: column; gap: 0.7rem; margin-top: 0.5rem; }

.file-drop {
  display: flex; align-items: center; gap: 10px;
  background: #0d0d0d; border: 1px dashed #252525;
  border-radius: 5px; padding: 10px 12px; cursor: pointer;
  transition: border-color 0.2s;
}
.file-drop:hover { border-color: #2c6e49; }

.file-icon { font-size: 1.1rem; flex-shrink: 0; }

.file-name {
  font-size: 0.8rem; color: #444; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}
.file-name.has-file { color: #2ecc71; }

.file-meta {
  display: flex; align-items: center; justify-content: space-between;
  padding: 4px 10px; background: #0d0d0d; border-radius: 4px;
  font-size: 0.8rem;
}
.meta-label { color: #444; }
.meta-date { color: #3498db; font-family: monospace; }

.import-btn {
  width: 100%; border-color: #16a085; color: #1abc9c;
  padding: 7px;
}
.import-btn:hover:not(:disabled) { background: rgba(26,188,156,0.08); }

.spinner { display: inline-block; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.import-result {
  background: #0a1a14; border: 1px solid #163d2a;
  border-radius: 5px; padding: 10px 12px;
  display: flex; flex-direction: column; gap: 5px;
  font-size: 0.82rem; color: #888;
}
.result-row { display: flex; align-items: center; gap: 7px; }
.result-icon.ok   { color: #27ae60; font-weight: bold; }
.result-icon.warn { color: #e67e22; }

.orp-stat-bar {
  display: flex; gap: 10px; align-items: center;
  padding-top: 5px; margin-top: 3px;
  border-top: 1px solid #1a2e22; color: #3498db;
  font-family: monospace; font-size: 0.8rem;
}
.stat-unit { color: #333; font-size: 0.72rem; margin-left: auto; }

.import-error {
  background: #1a0a0a; border: 1px solid #3d1a1a;
  border-radius: 5px; padding: 8px 10px;
  font-size: 0.8rem; color: #c0392b;
}

/* ─── Right Column ─── */
.right-col { display: flex; flex-direction: column; gap: 1.25rem; }

/* ─── Chart ─── */
.chart-panel { padding-bottom: 0.6rem; margin-bottom: 0; }

.chart-toolbar {
  display: flex; align-items: center; gap: 12px;
  flex-wrap: wrap; margin-bottom: 0.65rem;
}

.series-chips { display: flex; gap: 6px; flex-shrink: 0; }

.chip {
  padding: 3px 11px; border-radius: 20px; font-size: 0.74rem;
  cursor: pointer; border: 1px solid; transition: all 0.2s;
  font-family: inherit; font-weight: 500; line-height: 1.6;
}
.chip-raw     { color: rgba(231,76,60,0.9);  border-color: rgba(231,76,60,0.35); background: rgba(231,76,60,0.1); }
.chip-cleaned { color: #27ae60;              border-color: #1a5232;              background: rgba(39,174,96,0.1); }
.chip-sg      { color: #f39c12;              border-color: #5c3d05;              background: rgba(243,156,18,0.1); }
.chip-ema     { color: #3498db;              border-color: #1a4a7a;              background: rgba(52,152,219,0.1); }
.chip-off     { color: #333 !important; border-color: #1e1e1e !important; background: transparent !important; }
.chip:hover:not(.chip-off) { filter: brightness(1.2); }

.chart-meta {
  display: flex; align-items: center; gap: 10px; margin-left: auto;
}
.record-count { font-size: 0.75rem; color: #2980b9; font-family: monospace; }

.clear-btn {
  border-color: #3d1616; color: #c0392b; padding: 3px 10px; font-size: 0.76rem;
}
.clear-btn:hover:not(:disabled) { background: rgba(192,57,43,0.1); border-color: #5a2020; }

.click-hint {
  font-size: 0.73rem; color: #2a4a6a; font-style: italic; margin-left: 2px;
}

.chart-container { width: 100%; height: 300px; }

/* ─── Table ─── */
.table-panel { padding: 0; overflow: hidden; margin-bottom: 0; }
.table-panel .panel-header {
  padding: 0.85rem 1rem;
  border-bottom: 1px solid #191919;
  margin-bottom: 0;
}
.table-wrapper { overflow-x: auto; max-height: 420px; overflow-y: auto; }

table { width: 100%; border-collapse: collapse; font-size: 0.83rem; white-space: nowrap; }
thead tr { background: #0d0d0d; position: sticky; top: 0; z-index: 1; }
th {
  padding: 8px 11px; text-align: left;
  color: #444; font-weight: 500; font-size: 0.76rem;
  border-bottom: 1px solid #1a1a1a; line-height: 1.35;
}
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: #777; }

.th-id     { width: 38px; }
.th-time   { width: 148px; }
.th-num    { width: 76px; text-align: right; }
.th-note   { width: auto; }
.th-action { width: 108px; text-align: center; }

td {
  padding: 7px 11px; border-bottom: 1px solid #141414;
  color: #bbb; vertical-align: middle;
}
.data-row:hover td         { background: #141414; }
.data-row.row-anomaly td   { background: rgba(231,76,60,0.03); }

.td-id   { color: #333; font-size: 0.73rem; }
.td-time { font-family: monospace; font-size: 0.78rem; color: #555; }
.td-orp  { text-align: right; font-weight: 600; color: #3498db; font-family: monospace; position: relative; }
.td-orp.orp-warn { color: #e67e22; }
.td-orp.orp-high { color: #9b59b6; }
.td-ch4  { text-align: right; font-weight: 600; color: #e67e22; font-family: monospace; }
.td-co2  { text-align: right; color: #9b59b6; font-family: monospace; }

.anomaly-tag {
  font-size: 0.6rem; color: #e67e22;
  margin-left: 3px; vertical-align: super;
  cursor: help;
}

td:nth-child(4),
td:nth-child(5),
td:nth-child(6),
td:nth-child(7) { text-align: right; font-family: monospace; color: #888; }

.td-note {
  color: #444; font-size: 0.78rem;
  max-width: 160px; overflow: hidden; text-overflow: ellipsis;
}
.td-action { text-align: center; }

.empty-state {
  text-align: center; color: #2a2a2a;
  padding: 3rem 0; font-size: 0.88rem;
}

.btn-sm {
  border: none; border-radius: 3px; padding: 3px 8px;
  font-size: 0.73rem; cursor: pointer; font-family: inherit;
  margin: 0 2px; transition: opacity 0.15s;
}
.btn-sm:disabled { opacity: 0.25; cursor: not-allowed; }
.btn-sm.publish { background: #0d2018; color: #27ae60; border: 1px solid #163d24; }
.btn-sm.publish:hover:not(:disabled) { background: #152d1e; }
.btn-sm.del     { background: #1e0d0d; color: #c0392b; border: 1px solid #3d1616; }
.btn-sm.del:hover:not(:disabled) { background: #2d1212; }

/* ─── Analysis Bar ─── */
.analysis-bar {
  display: flex; align-items: center; flex-wrap: wrap; gap: 6px 20px;
  padding: 10px 14px; margin-top: 8px;
  background: #0c0c0c; border-top: 1px solid #1a1a1a;
  border-radius: 0 0 5px 5px;
}

.an-block {
  display: flex; flex-direction: column; gap: 2px; min-width: 90px;
}

.an-label {
  font-size: 0.68rem; color: #3a3a3a; text-transform: uppercase; letter-spacing: 0.04em;
}

.an-value {
  font-size: 0.9rem; font-family: monospace; color: #ccc; font-weight: 600;
}

.val-down { color: #3498db; }
.val-up   { color: #e67e22; }
.val-flat { color: #888; }

.an-badge {
  display: inline-block; font-size: 0.76rem; font-weight: 600;
  padding: 1px 10px; border-radius: 10px; width: fit-content;
}
.badge-green  { background: rgba(46,204,113,0.12); color: #2ecc71; border: 1px solid #1a5c35; }
.badge-orange { background: rgba(230,126,34,0.12);  color: #e67e22; border: 1px solid #5c3a1a; }
.badge-gray   { background: rgba(80,80,80,0.12);    color: #666;    border: 1px solid #333; }

.an-message {
  flex: 1 1 100%; font-size: 0.75rem; color: #444; font-style: italic;
  padding-top: 4px; border-top: 1px solid #161616; margin-top: 2px;
}

.analysis-bar-range { border-top-color: rgba(52,152,219,0.4); }

.an-source {
  display: flex; align-items: center; gap: 6px;
  flex: 0 0 auto;
}
.source-tag {
  font-size: 0.68rem; font-weight: 600; padding: 1px 8px; border-radius: 8px;
}
.source-all   { background: rgba(80,80,80,0.15); color: #555; border: 1px solid #2a2a2a; }
.source-range { background: rgba(52,152,219,0.15); color: #3498db; border: 1px solid #1a4a7a; }

.clear-range-btn {
  background: none; border: 1px solid #2a2a2a; color: #555;
  border-radius: 50%; width: 18px; height: 18px; font-size: 0.7rem;
  cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 0;
  line-height: 1; font-family: inherit;
}
.clear-range-btn:hover { border-color: #555; color: #ccc; }

/* ─── Phase Panel ─── */
.phase-panel { border-top: 3px solid #2ecc71; }

.phase-header {
  display: flex; align-items: center; gap: 12px; margin-bottom: 12px;
}
.phase-header .panel-title { margin: 0; flex: 1; }
.phase-header small { font-size: 0.7rem; color: #444; margin-left: 6px; font-weight: 400; }

.phase-body { display: flex; flex-direction: column; gap: 10px; }

.phase-metrics {
  display: flex; gap: 0; flex-wrap: wrap;
}
.pm-block {
  display: flex; flex-direction: column; gap: 3px;
  flex: 1 1 0; min-width: 90px; padding: 0 14px;
  border-right: 1px solid #1a1a1a;
}
.pm-block:first-child { padding-left: 0; }
.pm-block:last-child  { border-right: none; }
.pm-wide { flex: 2 1 180px; }
.phase-num { font-size: 1.05rem; font-weight: 700; }
.phase-desc { font-size: 0.8rem; font-style: italic; margin-top: 2px; }

.phase-timeline-wrap { padding-top: 4px; }
.phase-timeline-label {
  font-size: 0.68rem; color: #333; text-transform: uppercase;
  letter-spacing: 0.05em; margin-bottom: 5px;
}
.phase-timeline {
  display: flex; width: 100%; height: 22px;
  border-radius: 4px; overflow: hidden; gap: 1px;
}
.pt-seg {
  display: flex; align-items: center; justify-content: center;
  overflow: hidden; transition: filter 0.2s; cursor: default;
  min-width: 2%;
}
.pt-seg.pt-current { box-shadow: inset 0 0 0 2px rgba(255,255,255,0.25); }
.pt-seg:hover { filter: brightness(1.25); }
.pt-label { font-size: 0.65rem; font-weight: 700; color: rgba(255,255,255,0.85); }

.phase-timeline-times {
  display: flex; width: 100%; margin-top: 2px;
}
.pt-time {
  font-size: 0.62rem; color: #333; text-align: center;
  overflow: hidden; text-overflow: clip; white-space: nowrap;
}

.phase-empty {
  font-size: 0.8rem; color: #333; padding: 12px 0; text-align: center;
}

/* ─── CH4 Peak Panel ─── */
.ch4-panel { border-top: 3px solid #e67e22; }
.ch4-header {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
}
.ch4-header .panel-title { margin: 0; flex: 1; }
.ch4-header small { font-size: 0.7rem; color: #444; margin-left: 6px; font-weight: 400; }
.ch4-badges { display: flex; align-items: center; gap: 8px; }

.rmse-badge {
  font-size: 0.8rem; font-weight: 700; padding: 2px 11px; border-radius: 10px;
  background: rgba(46,204,113,0.12); color: #2ecc71; border: 1px solid #1a5c35;
}
.ga-badge {
  font-size: 0.72rem; padding: 1px 9px; border-radius: 10px;
  background: rgba(52,152,219,0.1); color: #3498db; border: 1px solid #1a4a7a;
}
.toggle-ch4-btn { font-size: 0.73rem; padding: 3px 9px; }

.ch4-body { margin-top: 10px; display: flex; flex-direction: column; gap: 10px; }

.ga-features {
  display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
  font-size: 0.75rem;
}
.ga-label { color: #444; flex-shrink: 0; }
.ga-feat-tag {
  background: #0d1a2a; border: 1px solid #1a3a5a;
  color: #3498db; padding: 1px 8px; border-radius: 8px; font-family: monospace;
  font-size: 0.72rem;
}

.ch4-table {
  width: 100%; border-collapse: collapse; font-size: 0.83rem;
}
.ch4-table th {
  padding: 5px 10px; color: #444; font-size: 0.72rem; font-weight: 500;
  border-bottom: 1px solid #1a1a1a; background: #0d0d0d;
}
.ch4-table td { padding: 6px 10px; border-bottom: 1px solid #141414; color: #bbb; }
.ch4-table tr:hover td { background: #141414; }
.ch4-row-warn td { background: rgba(231,76,60,0.03); }
.ta-r { text-align: right; }
.cy-id   { color: #555; font-family: monospace; font-size: 0.76rem; }
.cy-date { color: #555; font-family: monospace; font-size: 0.76rem; }
.cy-val  { color: #bbb; font-family: monospace; font-weight: 600; }
.cy-pred { color: #3498db; font-family: monospace; font-weight: 600; }
.cy-err  { font-family: monospace; font-weight: 700; }
.err-ok    { color: #2ecc71; }
.err-large { color: #e74c3c; }

.cy-bar { width: 90px; }
.err-bar-wrap { display: flex; align-items: center; height: 100%; }
.err-bar-track {
  width: 100%; height: 6px; background: #1a1a1a; border-radius: 3px;
  display: flex; align-items: center; overflow: hidden;
}
.err-bar-fill { height: 100%; border-radius: 3px; min-width: 3px; }

.rmse-formula {
  font-size: 0.75rem; color: #444; font-family: monospace;
  padding: 8px 10px; background: #0a0a0a;
  border: 1px solid #1a1a1a; border-radius: 4px; line-height: 1.6;
}
.rmse-formula b { color: #2ecc71; }
.rmse-note { color: #333; margin-left: 8px; }

/* ─── Responsive ─── */
@media (max-width: 1024px) {
  .main-grid { grid-template-columns: 1fr; }
  .chart-container { height: 240px; }
  .table-wrapper { max-height: 380px; }
}

/* ── 壓力預測卡片 ── */
.pred-panel { border-top: 3px solid #8e44ad; }
.pred-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 12px;
}
.pred-header .panel-title { margin: 0; }
.pred-header small { font-size: 0.72rem; color: #555; margin-left: 6px; font-weight: 400; }
.pred-body {
  display: flex; align-items: center; gap: 0; flex-wrap: wrap;
}
.pred-block {
  display: flex; flex-direction: column; gap: 4px;
  flex: 1 1 0; min-width: 100px; padding: 0 16px;
}
.pred-block:first-child { padding-left: 0; }
.pred-divider {
  width: 1px; height: 40px; background: #222; flex-shrink: 0;
}
.pred-val { font-size: 1.15rem; }
.pred-unit { font-size: 0.72rem; color: #555; font-weight: 400; margin-left: 2px; }
.val-danger { color: #e74c3c !important; }
.badge-red    { background: rgba(231,76,60,0.12);  color: #e74c3c; border: 1px solid #5c1a1a; }
.badge-yellow { background: rgba(241,196,15,0.12); color: #f1c40f; border: 1px solid #5c4a00; }
</style>
