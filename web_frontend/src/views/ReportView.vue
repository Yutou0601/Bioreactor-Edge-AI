<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import apiClient from '../services/apiClient'

const loading = ref(true)
const error   = ref('')
const stats   = ref(null)

// chart DOM refs
const refOrpHist   = ref(null)
const refPressHist = ref(null)
const refCorr      = ref(null)
const refAnomaly   = ref(null)
const refGas       = ref(null)
const refScatter   = ref(null)

let charts = []

const DARK = {
  bg:         'transparent',
  grid:       { left: '8%', right: '4%', top: '10%', bottom: '14%' },
  xLabel:     { color: '#3a3a3a', fontSize: 10 },
  yLabel:     { color: '#3a3a3a', fontSize: 10 },
  splitLine:  { lineStyle: { color: 'rgba(255,255,255,0.03)' } },
  axisLine:   { lineStyle: { color: '#1e1e1e' } },
  tooltip: {
    backgroundColor: 'rgba(10,10,14,0.96)',
    borderColor: '#222', borderWidth: 1,
    textStyle: { color: '#bbb', fontSize: 12 },
  },
}

// ── 工具：初始化 ECharts 實例 ──
function initChart(el) {
  const c = echarts.init(el, null, { renderer: 'canvas' })
  charts.push(c)
  return c
}

// ── 1. ORP 分布直方圖 ──────────────────────────────────
function drawOrpHist(data) {
  const c = initChart(refOrpHist.value)
  c.setOption({
    backgroundColor: DARK.bg, animation: false,
    tooltip: { ...DARK.tooltip, formatter: p => `${p[0].axisValue} mV：<b>${p[0].value}</b> 筆` },
    grid: DARK.grid,
    xAxis: { type: 'category', data: data.bins, axisLine: DARK.axisLine,
             axisLabel: { ...DARK.xLabel, interval: 3, rotate: 30 }, axisTick: { show: false } },
    yAxis: { type: 'value', name: '筆數', nameTextStyle: { color: '#3a3a3a', fontSize: 10 },
             axisLabel: DARK.yLabel, splitLine: DARK.splitLine },
    series: [{
      type: 'bar', data: data.counts, barMaxWidth: 18,
      itemStyle: {
        color: new echarts.graphic.LinearGradient(0,0,0,1,[
          { offset: 0, color: '#3498db' },
          { offset: 1, color: 'rgba(52,152,219,0.25)' },
        ]),
      },
    }],
  })
}

// ── 2. 壓力分布直方圖 ─────────────────────────────────
function drawPressHist(data) {
  const c = initChart(refPressHist.value)
  const dangerIdx = data.bins.findIndex(b => b >= 2.6)
  const binStrs = data.bins.map(String)
  const barData = data.counts.map((v, i) => ({
    value: v,
    itemStyle: { color: i >= dangerIdx && dangerIdx >= 0 ? 'rgba(231,76,60,0.7)' : 'rgba(155,89,182,0.7)' },
  }))
  const markLine = dangerIdx >= 0 ? {
    silent: true, symbol: 'none',
    lineStyle: { color: '#e74c3c', type: 'dashed', width: 1.5 },
    label: { formatter: '危險 2.6', color: '#e74c3c', fontSize: 10, position: 'insideEndBottom' },
    data: [{ xAxis: binStrs[dangerIdx] }],
  } : undefined
  c.setOption({
    backgroundColor: DARK.bg, animation: false,
    tooltip: { ...DARK.tooltip, formatter: p => `${p[0].axisValue} kg/cm²：<b>${p[0].value}</b> 筆` },
    grid: DARK.grid,
    xAxis: { type: 'category', data: binStrs, axisLine: DARK.axisLine,
             axisLabel: { ...DARK.xLabel, interval: 3, rotate: 30 }, axisTick: { show: false } },
    yAxis: { type: 'value', name: '筆數', nameTextStyle: { color: '#3a3a3a', fontSize: 10 },
             axisLabel: DARK.yLabel, splitLine: DARK.splitLine },
    series: [{ type: 'bar', data: barData, barMaxWidth: 18, markLine }],
  })
}

// ── 3. 特徵相關係數熱力圖 ─────────────────────────────
function drawCorr(data) {
  const c = initChart(refCorr.value)
  const n = data.labels.length
  // ECharts heatmap 需要 [xIdx, yIdx, value] 格式
  const heatData = []
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++)
      heatData.push([j, i, data.matrix[i][j]])

  c.setOption({
    backgroundColor: DARK.bg, animation: false,
    tooltip: {
      ...DARK.tooltip,
      formatter: p => {
        const xi = p.data[0], yi = p.data[1], v = p.data[2]
        return `${data.labels[yi]} × ${data.labels[xi]}：<b>${v}</b>`
      },
    },
    grid: { left: '12%', right: '8%', top: '4%', bottom: '12%' },
    xAxis: { type: 'category', data: data.labels, axisLine: DARK.axisLine,
             axisLabel: { color: '#666', fontSize: 11 }, axisTick: { show: false },
             splitArea: { show: true, areaStyle: { color: ['rgba(255,255,255,0.01)', 'transparent'] } } },
    yAxis: { type: 'category', data: data.labels,
             axisLine: DARK.axisLine, axisLabel: { color: '#666', fontSize: 11 },
             splitArea: { show: true, areaStyle: { color: ['rgba(255,255,255,0.01)', 'transparent'] } } },
    visualMap: {
      min: -1, max: 1, calculable: false, show: false,
      inRange: { color: ['#3498db', '#1a1a1a', '#e74c3c'] },
    },
    series: [{
      type: 'heatmap', data: heatData,
      label: { show: true, formatter: p => p.data[2].toFixed(2), fontSize: 10, color: '#ccc' },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } },
    }],
  })
}

// ── 4. 每日異常統計 ──────────────────────────────────
function drawAnomaly(data) {
  const c = initChart(refAnomaly.value)
  const dates    = data.map(d => d.date)
  const totals   = data.map(d => d.total)
  const anomalies = data.map(d => d.anomalies)
  c.setOption({
    backgroundColor: DARK.bg, animation: false,
    tooltip: {
      ...DARK.tooltip, trigger: 'axis',
      formatter: params => {
        const date = params[0].axisValue
        return `${date}<br/>總計：<b>${params[0].value}</b> 筆<br/>突波：<b style="color:#e74c3c">${params[1].value}</b> 個`
      },
    },
    legend: { show: false },
    grid: { ...DARK.grid, bottom: '22%' },
    dataZoom: [{ type: 'slider', height: 18, bottom: 6,
      fillerColor: 'rgba(52,152,219,0.1)', borderColor: '#1e1e1e',
      handleStyle: { color: '#2980b9' }, textStyle: { color: '#333', fontSize: 9 } }],
    xAxis: { type: 'category', data: dates, axisLine: DARK.axisLine,
             axisLabel: { ...DARK.xLabel, rotate: 35 }, axisTick: { show: false } },
    yAxis: { type: 'value', name: '筆數', nameTextStyle: { color: '#3a3a3a', fontSize: 10 },
             axisLabel: DARK.yLabel, splitLine: DARK.splitLine },
    series: [
      { name: '總計', type: 'bar', data: totals, barMaxWidth: 20, stack: 'a',
        itemStyle: { color: 'rgba(52,152,219,0.25)' } },
      { name: '突波', type: 'bar', data: anomalies, barMaxWidth: 20, stack: 'b',
        itemStyle: { color: 'rgba(231,76,60,0.75)' } },
    ],
  })
}

// ── 5. CH4 / CO2 日均值趨勢 ─────────────────────────
function drawGas(data) {
  const c = initChart(refGas.value)
  const dates = data.map(d => d.date)
  c.setOption({
    backgroundColor: DARK.bg, animation: false,
    tooltip: { ...DARK.tooltip, trigger: 'axis' },
    legend: { show: false },
    grid: { ...DARK.grid, bottom: '22%' },
    dataZoom: [{ type: 'slider', height: 18, bottom: 6,
      fillerColor: 'rgba(52,152,219,0.1)', borderColor: '#1e1e1e',
      handleStyle: { color: '#2980b9' }, textStyle: { color: '#333', fontSize: 9 } }],
    xAxis: { type: 'category', data: dates, axisLine: DARK.axisLine,
             axisLabel: { ...DARK.xLabel, rotate: 35 }, axisTick: { show: false } },
    yAxis: { type: 'value', name: '%', min: 0,
             nameTextStyle: { color: '#3a3a3a', fontSize: 10 },
             axisLabel: DARK.yLabel, splitLine: DARK.splitLine },
    series: [
      {
        name: 'CH4 日均 %', type: 'line', data: data.map(d => d.avg_ch4),
        symbol: 'circle', symbolSize: 4, showSymbol: false,
        lineStyle: { width: 2, color: '#e67e22' }, itemStyle: { color: '#e67e22' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0,0,0,1,[
          { offset: 0, color: 'rgba(230,126,34,0.2)' }, { offset: 1, color: 'rgba(230,126,34,0)' }]) },
      },
      {
        name: 'CO2 日均 %', type: 'line', data: data.map(d => d.avg_co2),
        symbol: 'circle', symbolSize: 4, showSymbol: false,
        lineStyle: { width: 1.5, color: '#9b59b6', type: 'dashed' }, itemStyle: { color: '#9b59b6' },
      },
    ],
  })
}

// ── 6. pH-ORP 散點圖（顏色 = CH4 濃度）────────────────
function drawScatter(data) {
  const c = initChart(refScatter.value)
  const ch4Vals = data.map(d => d.ch4)
  const maxCh4  = Math.max(...ch4Vals, 1)
  const scatterData = data.map(d => [d.ph, d.orp, d.ch4])
  c.setOption({
    backgroundColor: DARK.bg, animation: false,
    tooltip: {
      ...DARK.tooltip,
      formatter: p => `pH: <b>${p.data[0]}</b>　ORP: <b>${p.data[1]}</b> mV　CH4: <b>${p.data[2]}</b> %`,
    },
    grid: { left: '10%', right: '5%', top: '10%', bottom: '12%' },
    visualMap: {
      min: 0, max: maxCh4, dimension: 2, show: true,
      right: 6, top: 'center', itemHeight: 80,
      inRange: { color: ['#1a4a7a', '#3498db', '#e67e22'] },
      text: [`CH4 ${maxCh4.toFixed(0)}%`, '0%'],
      textStyle: { color: '#444', fontSize: 10 },
    },
    xAxis: { type: 'value', name: 'pH', nameLocation: 'end',
             nameTextStyle: { color: '#555', fontSize: 10 }, min: 'dataMin', max: 'dataMax',
             axisLine: DARK.axisLine, axisLabel: DARK.xLabel, splitLine: DARK.splitLine },
    yAxis: { type: 'value', name: 'ORP (mV)', nameLocation: 'end',
             nameTextStyle: { color: '#555', fontSize: 10 },
             axisLabel: DARK.yLabel, splitLine: DARK.splitLine },
    series: [{
      type: 'scatter', data: scatterData,
      symbolSize: 4, opacity: 0.65,
    }],
  })
}

// ── 載入資料並畫圖 ────────────────────────────────────
// 每張圖用 rAF 逐幀繪製，主執行緒不凍結，使用者立刻看到第一張
function rafDraw(fns) {
  function next(i) {
    if (i >= fns.length) return
    requestAnimationFrame(() => { fns[i](); next(i + 1) })
  }
  next(0)
}

async function loadAndDraw() {
  // 銷毀舊實例，避免重新整理時重複 init
  charts.forEach(c => c?.dispose())
  charts = []

  loading.value = true
  error.value   = ''
  try {
    const res = await apiClient.get('/report/stats')
    if (res.data.error) { error.value = res.data.error; return }
    stats.value = res.data

    // 等 Vue patch 完成（v-if 插入 DOM）再初始化 ECharts
    await nextTick()

    const s = stats.value
    rafDraw([
      () => drawOrpHist(s.orp_histogram),
      () => drawPressHist(s.pressure_histogram),
      () => drawCorr(s.correlation),
      () => drawAnomaly(s.anomaly_by_date),
      () => drawGas(s.gas_daily),
      () => drawScatter(s.orp_ph_scatter),
    ])
  } catch (e) {
    error.value = e.message || '無法取得統計資料'
  } finally {
    loading.value = false
  }
}

const onResize = () => charts.forEach(c => c?.resize())

onMounted(() => {
  loadAndDraw()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  charts.forEach(c => c?.dispose())
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <div class="report-page">

    <!-- ── 頁頭 ── -->
    <header class="report-header">
      <div>
        <h1>研究分析儀表板</h1>
        <p class="subtitle">基於目前已載入的感測器記錄進行統計分析</p>
      </div>
      <button class="btn-refresh" @click="loadAndDraw" :disabled="loading">
        {{ loading ? '載入中...' : '重新整理' }}
      </button>
    </header>

    <!-- ── 載入 / 錯誤 ── -->
    <div v-if="loading" class="state-msg">計算中，請稍候...</div>
    <div v-else-if="error" class="state-msg error">{{ error }}</div>

    <!-- ── KPI 摘要列 ── -->
    <div v-if="stats && !loading" class="kpi-bar">
      <div class="kpi">
        <span class="kpi-val">{{ stats.summary.total_records.toLocaleString() }}</span>
        <span class="kpi-label">總筆數</span>
      </div>
      <div class="kpi">
        <span class="kpi-val" :class="stats.summary.anomaly_rate > 5 ? 'warn' : ''">
          {{ stats.summary.anomaly_rate }} %
        </span>
        <span class="kpi-label">突波率</span>
      </div>
      <div class="kpi">
        <span class="kpi-val">{{ stats.summary.orp_mean }} <small>mV</small></span>
        <span class="kpi-label">ORP 均值</span>
      </div>
      <div class="kpi">
        <span class="kpi-val">± {{ stats.summary.orp_std }} <small>mV</small></span>
        <span class="kpi-label">ORP σ</span>
      </div>
      <div class="kpi">
        <span class="kpi-val" :class="stats.summary.pressure_max > 2.6 ? 'danger' : ''">
          {{ stats.summary.pressure_mean }} <small>kg/cm²</small>
        </span>
        <span class="kpi-label">壓力均值（最大 {{ stats.summary.pressure_max }}）</span>
      </div>
      <div class="kpi">
        <span class="kpi-val">{{ stats.summary.ch4_mean }} <small>%</small></span>
        <span class="kpi-label">CH4 均值</span>
      </div>
    </div>

    <!-- ── 圖表網格 ── -->
    <div v-if="stats && !loading" class="chart-grid">

      <div class="chart-card">
        <h2 class="card-title">ORP 分布直方圖 <span class="card-sub">EMA 平滑後</span></h2>
        <div ref="refOrpHist" class="chart-box"></div>
      </div>

      <div class="chart-card">
        <h2 class="card-title">反應器壓力分布 <span class="card-sub">紅色 ≥ 2.6 kg/cm²</span></h2>
        <div ref="refPressHist" class="chart-box"></div>
      </div>

      <div class="chart-card">
        <h2 class="card-title">特徵相關係數熱力圖 <span class="card-sub">Pearson r</span></h2>
        <div ref="refCorr" class="chart-box"></div>
      </div>

      <div class="chart-card">
        <h2 class="card-title">每日突波統計 <span class="card-sub">灰 = 總計，紅 = 突波</span></h2>
        <div ref="refAnomaly" class="chart-box"></div>
      </div>

      <div class="chart-card">
        <h2 class="card-title">CH4 / CO2 日均值趨勢</h2>
        <div ref="refGas" class="chart-box"></div>
      </div>

      <div class="chart-card">
        <h2 class="card-title">pH–ORP 狀態空間 <span class="card-sub">顏色 = CH4 濃度</span></h2>
        <div ref="refScatter" class="chart-box"></div>
      </div>

    </div>
  </div>
</template>

<style scoped>
.report-page {
  min-height: 100vh;
  background: #0d0d0d;
  color: #e0e0e0;
  font-family: 'Noto Sans TC', sans-serif;
  padding: 1.25rem;
}

/* ── 頁頭 ── */
.report-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding-bottom: 1rem; margin-bottom: 1rem;
  border-bottom: 1px solid #1a1a1a;
}
.report-header h1 { font-size: 1.2rem; font-weight: 700; color: #fff; margin-bottom: 3px; }
.subtitle { font-size: 0.78rem; color: #444; }

.btn-refresh {
  background: #161616; border: 1px solid #262626; color: #aaa;
  padding: 6px 16px; border-radius: 4px; cursor: pointer;
  font-size: 0.82rem; transition: all 0.15s; font-family: inherit;
}
.btn-refresh:hover:not(:disabled) { background: #1e1e1e; color: #ccc; }
.btn-refresh:disabled { opacity: 0.35; cursor: not-allowed; }

/* ── 狀態訊息 ── */
.state-msg { text-align: center; padding: 3rem; color: #444; font-size: 0.9rem; }
.state-msg.error { color: #c0392b; }

/* ── KPI 摘要列 ── */
.kpi-bar {
  display: flex; gap: 0; flex-wrap: wrap;
  background: #111; border: 1px solid #1a1a1a; border-radius: 6px;
  margin-bottom: 1.25rem; overflow: hidden;
}
.kpi {
  flex: 1 1 140px; display: flex; flex-direction: column;
  padding: 14px 20px; border-right: 1px solid #1a1a1a;
  min-width: 120px;
}
.kpi:last-child { border-right: none; }
.kpi-val {
  font-size: 1.4rem; font-weight: 700; font-family: monospace; color: #ccc; line-height: 1.2;
}
.kpi-val small { font-size: 0.7rem; font-weight: 400; color: #555; margin-left: 2px; }
.kpi-val.warn   { color: #e67e22; }
.kpi-val.danger { color: #e74c3c; }
.kpi-label { font-size: 0.7rem; color: #3a3a3a; margin-top: 4px; }

/* ── 圖表網格 ── */
.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1.25rem;
}

.chart-card {
  background: #111; border: 1px solid #1a1a1a;
  border-radius: 6px; padding: 1rem;
}
.card-title {
  font-size: 0.85rem; font-weight: 600; color: #888;
  border-left: 3px solid #8e44ad; padding-left: 9px;
  margin-bottom: 0.75rem;
}
.card-sub { font-size: 0.72rem; font-weight: 400; color: #444; margin-left: 6px; }

.chart-box { width: 100%; height: 280px; }

/* ── 相關係數圖略高一點 ── */
.chart-card:nth-child(3) .chart-box { height: 300px; }

/* ── 散點圖略高 ── */
.chart-card:nth-child(6) .chart-box { height: 300px; }

/* ── Responsive ── */
@media (max-width: 900px) {
  .chart-grid { grid-template-columns: 1fr; }
  .kpi-bar { flex-direction: column; }
  .kpi { border-right: none; border-bottom: 1px solid #1a1a1a; }
}
</style>
