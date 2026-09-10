<script setup>
/*
 * 生物移除速率 r_b —— 論文 Algorithm 1 的線上結果。
 *
 * ⚠ 三件必須顯示、不能省的事：
 *   1 報中位數不報平均。逐段估計約兩成為負（簡併在單一循環上的表現），
 *     平均數沒有意義。
 *   2 未校準與已校準要分開列。校準常數來自離線的 Algorithm 2，
 *     並標明版本，否則看的人不知道那 −4.8% 是哪來的。
 *   3 落在繪圖範圍外的值要標明「堆在端點」，否則最外側那根柱子
 *     會被誤讀成一個真實的眾數。
 */
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import apiClient from '../services/apiClient'

const loading = ref(true)
const error   = ref('')
const rate    = ref(null)
const cycles  = ref([])

const refSeries = ref(null)
const refKHist  = ref(null)
const refRbHist = ref(null)
let charts = []

const AX = {
  xLabel: { color: '#8a8a8a', fontSize: 10 },
  yLabel: { color: '#8a8a8a', fontSize: 10 },
  splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
  axisLine:  { lineStyle: { color: '#2a2a2a' } },
  tooltip: {
    backgroundColor: 'rgba(10,10,14,0.96)',
    borderColor: '#222', borderWidth: 1,
    textStyle: { color: '#ccc', fontSize: 12 },
  },
}

function initChart(el) {
  const c = echarts.init(el, null, { renderer: 'canvas' })
  charts.push(c)
  return c
}

function fmt (v, n = 4) {
  return (v === null || v === undefined) ? '—' : Number(v).toFixed(n)
}

/* 直方圖：把落在範圍外的值夾到端點，並回報各有幾個。
 * 不夾的話極端值會把 x 軸拉長到看不出主體；夾了不說，
 * 端點那根柱子又會被誤讀。所以兩件事要一起做。 */
function histogram (values, lo, hi, bins) {
  const counts = new Array(bins).fill(0)
  let nLo = 0, nHi = 0
  const w = (hi - lo) / bins
  for (const v of values) {
    if (v < lo) nLo++
    else if (v > hi) nHi++
    const c = Math.min(Math.max(v, lo), hi)
    let i = Math.floor((c - lo) / w)
    if (i >= bins) i = bins - 1
    counts[i]++
  }
  const centers = counts.map((_, i) => lo + w * (i + 0.5))
  return { counts, centers, nLo, nHi }
}

function drawSeries () {
  const rows = cycles.value
    .filter(r => r.screened && r.rb !== null)
    .slice().sort((a, b) => a.ts_start.localeCompare(b.ts_start))
  const c = initChart(refSeries.value)
  c.setOption({
    backgroundColor: 'transparent',
    grid: { left: 62, right: 20, top: 28, bottom: 46 },
    tooltip: { trigger: 'axis', ...AX.tooltip },
    xAxis: {
      type: 'category',
      data: rows.map(r => r.ts_start.slice(0, 16)),
      axisLabel: { ...AX.xLabel, rotate: 40 },
      axisLine: AX.axisLine,
    },
    yAxis: {
      type: 'value', name: 'r_b  (kg/cm²/hr)',
      nameTextStyle: { color: '#8a8a8a', fontSize: 10 },
      axisLabel: AX.yLabel, splitLine: AX.splitLine, axisLine: AX.axisLine,
    },
    series: [{
      type: 'line', showSymbol: true, symbolSize: 5,
      data: rows.map(r => r.rb),
      lineStyle: { width: 1.2, color: '#4a90d9' },
      itemStyle: { color: '#4a90d9' },
      markLine: rate.value?.calibration ? {
        silent: true, symbol: 'none',
        label: { formatter: '聚合中位', color: '#c0504d', fontSize: 10 },
        lineStyle: { color: '#c0504d', width: 1.2, type: 'solid' },
        data: [{ yAxis: rate.value.median_rb }],
      } : undefined,
    }],
  })
}

function drawKHist () {
  const ks = cycles.value.filter(r => r.screened && r.k_hat !== null)
                         .map(r => Math.log10(r.k_hat))
  if (!ks.length) return
  const h = histogram(ks, -2, 0.5, 24)
  const c = initChart(refKHist.value)
  c.setOption({
    backgroundColor: 'transparent',
    grid: { left: 52, right: 16, top: 28, bottom: 42 },
    tooltip: { trigger: 'axis', ...AX.tooltip },
    xAxis: {
      type: 'category',
      data: h.centers.map(v => Math.pow(10, v).toPrecision(2)),
      axisLabel: { ...AX.xLabel, interval: 3 }, axisLine: AX.axisLine,
      name: 'k̂  (/hr, 對數軸)',
      nameLocation: 'middle', nameGap: 28,
      nameTextStyle: { color: '#8a8a8a', fontSize: 10 },
    },
    yAxis: {
      type: 'value', name: '段數',
      nameTextStyle: { color: '#8a8a8a', fontSize: 10 },
      axisLabel: AX.yLabel, splitLine: AX.splitLine, axisLine: AX.axisLine,
    },
    series: [{ type: 'bar', data: h.counts, itemStyle: { color: '#5b8db8' } }],
  })
}

const rbClip = ref({ nLo: 0, nHi: 0 })

function drawRbHist () {
  const rb = cycles.value.filter(r => r.screened && r.rb_hat !== null)
                         .map(r => r.rb_hat)
  if (!rb.length) return
  const LO = -0.02, HI = 0.06
  const h = histogram(rb, LO, HI, 32)
  rbClip.value = { nLo: h.nLo, nHi: h.nHi }
  const c = initChart(refRbHist.value)
  c.setOption({
    backgroundColor: 'transparent',
    grid: { left: 52, right: 16, top: 28, bottom: 42 },
    tooltip: { trigger: 'axis', ...AX.tooltip },
    xAxis: {
      type: 'category',
      data: h.centers.map(v => v.toFixed(3)),
      axisLabel: { ...AX.xLabel, interval: 5 }, axisLine: AX.axisLine,
      name: 'r̂_b  (kg/cm²/hr, 未校準)',
      nameLocation: 'middle', nameGap: 28,
      nameTextStyle: { color: '#8a8a8a', fontSize: 10 },
    },
    yAxis: {
      type: 'value', name: '段數',
      nameTextStyle: { color: '#8a8a8a', fontSize: 10 },
      axisLabel: AX.yLabel, splitLine: AX.splitLine, axisLine: AX.axisLine,
    },
    series: [{
      type: 'bar', data: h.counts, itemStyle: { color: '#5b8db8' },
      markLine: {
        silent: true, symbol: 'none',
        label: { formatter: '零', color: '#888', fontSize: 10 },
        lineStyle: { color: '#888', width: 1, type: 'dotted' },
        data: [{ xAxis: h.centers.findIndex(v => v >= 0) }],
      },
    }],
  })
}

async function load () {
  loading.value = true
  error.value = ''
  try {
    const [r, c] = await Promise.all([
      apiClient.get('/rate'),
      apiClient.get('/cycles', { params: { limit: 2000 } }),
    ])
    rate.value = r.data
    cycles.value = c.data
    await nextTick()
    charts.forEach(x => x.dispose())
    charts = []
    if (cycles.value.length) { drawSeries(); drawKHist(); drawRbHist() }
  } catch (e) {
    error.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

const onResize = () => charts.forEach(c => c.resize())
onMounted(() => { load(); window.addEventListener('resize', onResize) })
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  charts.forEach(c => c.dispose())
})
</script>

<template>
  <div class="rate-page">
    <header class="hdr">
      <div>
        <h1>生物移除速率 <small>r_b · 逐循環估計</small></h1>
        <p class="sub">
          每次補氣之後的下降段各自估一次；曲率不足的段不估計。
        </p>
      </div>
      <button class="btn" :disabled="loading" @click="load">
        {{ loading ? '載入中…' : '重新整理' }}
      </button>
    </header>

    <p v-if="error" class="err">讀取失敗：{{ error }}</p>

    <section v-if="rate" class="cards">
      <div class="card">
        <div class="lab">聚合速率（已校準）</div>
        <div class="val">{{ fmt(rate.median_rb) }}</div>
        <div class="unit" v-if="rate.median_ci">
          {{ fmt(rate.median_ci[0]) }} ~ {{ fmt(rate.median_ci[1]) }}
          <b :class="'u-' + rate.usability">±{{ rate.precision_pct }}%</b>
        </div>
        <div class="unit" v-else>kg/cm²/hr　中位數</div>
      </div>
      <div class="card">
        <div class="lab">未校準</div>
        <div class="val dim">{{ fmt(rate.median_rb_hat) }}</div>
        <div class="unit">
          校準 {{ rate.calibration
            ? ((rate.calibration.correction * 100).toFixed(1) + '%')
            : '未套用' }}
        </div>
      </div>
      <div class="card">
        <div class="lab">循環數</div>
        <div class="val">{{ rate.n_screened }} <span class="dim">/ {{ rate.n_cycles }}</span></div>
        <div class="unit">通過曲率預篩 / 總切段</div>
      </div>
      <div class="card">
        <div class="lab">逐段負值</div>
        <div class="val">{{ (rate.negative_fraction * 100).toFixed(0) }}%</div>
        <div class="unit">故報中位數，不報平均</div>
      </div>
    </section>

    <!-- ⚠ 單一循環的 r_b 不可用：實測 17.9% 的段算出負值（物理上不可能）。
         r_b 只有作為多段的中位數才有意義，而精度強烈取決於段數。介面若只
         顯示中位數，累積 8 段時看起來會跟 179 段一樣有自信。 -->
    <p v-if="rate" class="usability" :class="'u-' + rate.usability">
      <template v-if="rate.usability === 'usable'">
        ✓ 累積 <b>{{ rate.n_screened }}</b> 段，中位數精度 <b>±{{ rate.precision_pct }}%</b>，可引用。
      </template>
      <template v-else-if="rate.usability === 'indicative'">
        △ 累積 <b>{{ rate.n_screened }}</b> 段，精度僅 <b>±{{ rate.precision_pct }}%</b>——只能當趨勢看，不要引用數值。
      </template>
      <template v-else>
        ⚠ 累積 <b>{{ rate.n_screened }}</b> 段，精度 <b>±{{ rate.precision_pct ?? '—' }}%</b>，<b>尚不可用</b>。
      </template>
      單一循環的 r_b 沒有意義（{{ (rate.negative_fraction * 100).toFixed(0) }}% 的段算出負值），
      這個數字要多段累積才成立；循環中位長約 18 小時，一天約 1.3 段。
    </p>

    <p v-if="rate?.calibration" class="calib">
      校準常數版本 <b>{{ rate.calibration.calibrated_at }}</b>，
      來自離線分析（{{ rate.calibration.n_cycles }} 段）：
      速率 {{ rate.calibration.rate }}
      ，95% 信賴區間 [{{ rate.calibration.ci95[0] }}, {{ rate.calibration.ci95[1] }}]
      ，純物理虛無 p = {{ rate.calibration.null_p }}。
    </p>
    <p v-else class="calib warn">
      ⚠ 找不到 calibration.json，顯示的是<b>未校準</b>的估計值。
    </p>

    <p v-if="!loading && !cycles.length" class="empty">
      尚無循環資料。先用 <code>POST /api/ingest_folder?folder=…</code>
      匯入一個期間的 CSV。
    </p>

    <section v-show="cycles.length" class="charts">
      <div class="panel wide">
        <h3>r_b 隨時間</h3>
        <div ref="refSeries" class="chart tall"></div>
      </div>
      <div class="panel">
        <h3>弛豫常數 k̂ 的分布</h3>
        <div ref="refKHist" class="chart"></div>
        <p class="note">橫跨約兩個數量級，故用對數軸。</p>
      </div>
      <div class="panel">
        <h3>未校準速率 r̂_b 的分布</h3>
        <div ref="refRbHist" class="chart"></div>
        <p class="note">
          ⚠ 範圍外的值堆在兩端：低於 −0.02 有 {{ rbClip.nLo }} 段、
          高於 0.06 有 {{ rbClip.nHi }} 段。端點那根柱子是堆積，不是眾數。
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.rate-page {
  min-height: 100vh; background: #0d0d0d; color: #e0e0e0;
  font-family: 'Noto Sans TC', sans-serif; padding: 1.25rem;
}
.hdr {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding-bottom: .9rem; margin-bottom: 1rem;
  border-bottom: 1px solid #1e1e1e;
}
h1 { font-size: 1.25rem; margin: 0; font-weight: 600; }
h1 small { color: #7a7a7a; font-size: .8rem; font-weight: 400; margin-left: .5rem; }
.sub { color: #6a6a6a; font-size: .8rem; margin: .35rem 0 0; }
.btn {
  background: #1a1a1a; color: #ccc; border: 1px solid #2e2e2e;
  border-radius: 4px; padding: .4rem .9rem; cursor: pointer; font-size: .82rem;
}
.btn:disabled { opacity: .5; cursor: default; }
.err { color: #c0504d; font-size: .85rem; }
.empty { color: #7a7a7a; font-size: .85rem; }
.empty code { background: #161616; padding: .1rem .35rem; border-radius: 3px; }

.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: .8rem; }
.card {
  background: #131313; border: 1px solid #1e1e1e; border-radius: 6px;
  padding: .85rem 1rem;
}
.lab  { color: #7a7a7a; font-size: .75rem; }
.val  { font-size: 1.5rem; font-weight: 600; margin: .25rem 0; }
.val.dim, .dim { color: #8a8a8a; font-weight: 400; }
.unit { color: #6a6a6a; font-size: .72rem; }

.usability { margin: 0 0 1rem; padding: 9px 12px; border-radius: 5px;
             font-size: 0.78rem; line-height: 1.6; }
.usability.u-usable     { background: #eef8f1; border: 1px solid #bfe0c9; color: #2f6b45; }
.usability.u-indicative { background: #fdf6e6; border: 1px solid #e6d29a; color: #86682a; }
.usability.u-unusable   { background: #fceceb; border: 1px solid #e5b8b4; color: #93392f; }
.unit .u-usable     { color: #2f6b45; }
.unit .u-indicative { color: #86682a; }
.unit .u-unusable   { color: #93392f; }
.calib { color: #7a7a7a; font-size: .78rem; margin: .9rem 0 0; }
.calib b { color: #a0a0a0; }
.calib.warn { color: #c9a227; }

.charts {
  display: grid; grid-template-columns: 1fr 1fr; gap: .9rem; margin-top: 1rem;
}
.panel {
  background: #131313; border: 1px solid #1e1e1e; border-radius: 6px;
  padding: .8rem .9rem;
}
.panel.wide { grid-column: 1 / -1; }
.panel h3 { font-size: .85rem; margin: 0 0 .5rem; font-weight: 500; color: #c0c0c0; }
.chart { width: 100%; height: 220px; }
.chart.tall { height: 280px; }
.note { color: #6a6a6a; font-size: .72rem; margin: .5rem 0 0; }

@media (max-width: 900px) {
  .cards { grid-template-columns: repeat(2, 1fr); }
  .charts { grid-template-columns: 1fr; }
}
</style>
