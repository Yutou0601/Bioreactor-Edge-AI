<script setup>
// 即時監控：選一天（預設跟隨最新、自動更新），看可信的四個訊號與目前循環的估計。
//
// ⚠ 只畫可信的訊號：反應槽壓力、混合槽壓力、ORP、pH。CO2／CH4 讀數 99.98% 是
//   管路拖尾，不畫成趨勢；CH4 只以「由壓降推算的上限與推估範圍」出現在目前循環區。
// ⚠ 前端跑在 4 GB 的監控電腦上：一天的圖只要 1200 點（後端 LTTB 降採樣，保留
//   驟降與排氣），完整逐筆只在按「下載當日 CSV」時才取。
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import echarts from '../lib/echarts'
import api from '../services/apiClient'
import { onThemeChange } from '../lib/theme'

const POLL_MS = 30000
const CHART_POINTS = 1200
// 三批排氣對帳實測的 CH4／壓降比（化學計量上限 0.25）。推估範圍＝上限 × 實測比/0.25。
const RATIO_LO = 0.17, RATIO_HI = 0.22, RATIO_MAX = 0.25
// Algorithm 1 的 k 網格是 0.01~2.99（cycle_estimator.KGRID）。估計值貼在端點上＝
// 殘差在網格內沒有內部極小，資料約束不了 k；此時 r_b 吸收了物理項，可以是負的
// 或大得離譜（實測 07-30 有 k̂=0.01、r̂_b=−0.27 的段）。這種段要標出來，不能混著看。
const K_LO = 0.01, K_HI = 2.99
const kAtEdge = k => k != null && (k <= K_LO + 1e-9 || k >= K_HI - 1e-9)

const days = ref([])
const day = ref('')
const follow = ref(true)
const records = ref([])
const cur = ref(null)
const status = ref(null)
const cycles = ref([])
const err = ref('')
const loading = ref(false)
const chartEl = ref(null)
let chart = null
let offTheme = null
let timer = null
let ro = null

const latestDay = computed(() => days.value[0]?.day || '')
const isLatest = computed(() => !!day.value && day.value === latestDay.value)
const station = computed(() => status.value?.stations?.[0]?.station || 'default')
const dayInfo = computed(() => days.value.find(d => d.day === day.value))

// ── 資料接收燈號 ──────────────────────────────────────────────
const fresh = computed(() => {
  const s = status.value?.stations?.[0]
  if (!s) return { cls: 'muted', icon: '○', label: '尚未收到任何上傳', detail: '' }
  const lag = s.data_lag_sec
  const last = (s.last_ts || '').slice(11, 19)
  const ago = lag == null ? '' : lag < 120 ? `${lag} 秒前` : lag < 7200 ? `${Math.round(lag / 60)} 分鐘前` : `${(lag / 3600).toFixed(1)} 小時前`
  if (lag != null && lag <= 300) return { cls: 'good', icon: '✓', label: '資料正常', detail: `最後一筆 ${last}（${ago}）` }
  if (lag != null && lag <= 1800) return { cls: 'warning', icon: '⚠', label: '資料延遲', detail: `最後一筆 ${last}（${ago}）` }
  return { cls: 'critical', icon: '✕', label: '資料中斷', detail: `最後一筆 ${s.last_ts || '—'}（${ago}）——檢查記錄程式與上傳程式` }
})

// ── 目前循環：每個數字標明是上限、估計、暫定或實測 ──────────────
const fmt = (v, d = 3) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d))
const tiles = computed(() => {
  const c = cur.value
  if (!c || c.error) return []
  const s = c.stoich || {}
  const e = c.estimate
  const ch4Up = s.ch4_frac_upper
  const out = [
    { k: '本循環已進行', v: `${fmt(c.duration_hr, 1)} h`, sub: `起於 ${c.ts_start.slice(5, 16)}`, tag: '實測' },
    {
      k: '反應槽壓力', v: `${fmt(c.p_now, 2)}`, unit: 'kgf/cm²', tag: '實測',
      sub: `補氣時 ${fmt(c.p_start, 2)}；從補氣後 3 分鐘的 ${fmt(s.p_from, 2)} 起算淨降 ${fmt(s.net_drop_kgf, 2)}`,
    },
    {
      k: '曲率篩選 c', v: c.curvature == null ? '—' : fmt(c.curvature, 2),
      sub: c.curvature == null ? (c.why_no_estimate || '') : (c.screened ? '≥ 0.45 通過，可分離物理與生物' : '< 0.45 未通過，太直分不開'),
      tag: '暫定', badge: c.curvature == null ? null : (c.screened ? 'good' : 'warning'),
    },
    {
      k: '生物移除速率 r_b', v: e ? fmt(e.rb, 4) : '—', unit: e ? 'kgf/cm²/h' : '',
      sub: !e ? (c.why_no_estimate || '')
        : kAtEdge(e.k) ? `⚠ k = ${fmt(e.k, 2)} 撞到網格邊界，資料約束不了 k，這個 r_b 不可採信`
        : `弛豫常數 k = ${fmt(e.k, 2)} /h（Algorithm 1，循環未結束）`,
      tag: '暫定',
    },
    {
      k: 'CO2 消耗量（本循環）', v: `≤ ${fmt(s.co2_consumed_upper_kgf, 4)}`, unit: 'kgf/cm²',
      sub: `約 ≤ ${fmt(s.co2_consumed_upper_mmol, 2)} mmol（頭空 ${s.headspace_l ?? '—'} L，僅供量級）`, tag: '上限',
    },
    {
      k: `CO2 消耗速率（近 ${s.recent_hr ?? 3} h）`, v: `≤ ${fmt(s.rate_upper_kgf_hr, 5)}`, unit: 'kgf/cm²/h',
      sub: s.recent_below_quantum ? '⚠ 近 3 小時壓力變化不到 3 個量化階，斜率以雜訊為主'
        : (s.bio_rate_kgf_hr != null ? `其中生物份額估計 ${fmt(s.bio_rate_kgf_hr, 5)}（由 r_b ÷ 4）` : '生物份額要等曲率通過才估得出'),
      tag: '上限',
    },
    {
      k: 'CH4 濃度增量（本循環）',
      v: ch4Up == null ? '—' : `${(ch4Up * RATIO_LO / RATIO_MAX * 100).toFixed(1)}–${(ch4Up * RATIO_HI / RATIO_MAX * 100).toFixed(1)} %`,
      sub: ch4Up == null ? '' : `上限 ${(ch4Up * 100).toFixed(1)} %；範圍依三批排氣對帳的實測比 ${RATIO_LO}–${RATIO_HI}（上限 ${RATIO_MAX}）`,
      tag: '推估',
    },
  ]
  return out
})

// ── 當天的完成循環（同時是圖的表格版） ────────────────────────
const dayCycles = computed(() => {
  const seen = new Set()
  return cycles.value
    .filter(c => (c.ts_start || '').startsWith(day.value))
    .filter(c => (seen.has(c.ts_start) ? false : seen.add(c.ts_start)))
    .sort((a, b) => (a.ts_start < b.ts_start ? -1 : 1))
})

// ── 讀資料 ─────────────────────────────────────────────────────
async function loadDays() {
  days.value = (await api.get('/days')).data
  if (follow.value || !day.value) day.value = latestDay.value
}
async function loadStatus() { status.value = (await api.get('/ingest/status')).data }
async function loadCycles() { cycles.value = (await api.get('/cycles', { params: { limit: 2000 } })).data }
async function loadCurrent() {
  cur.value = isLatest.value ? (await api.get('/cycles/current', { params: { station: station.value } })).data : null
}
async function loadDay() {
  if (!day.value) { records.value = []; render(); return }
  records.value = (await api.get('/records', { params: { date: day.value, points: CHART_POINTS }, timeout: 20000 })).data
  render()
}

async function refresh() {
  if (loading.value) return
  loading.value = true
  err.value = ''
  try {
    await loadStatus()
    await loadDays()
    await Promise.all([loadDay(), loadCycles()])
    await loadCurrent()
    render()                 // 目前循環的起點線要等 loadCurrent 之後才畫得出來
  } catch (e) {
    // 保留上一次的畫面，不清空：後端短暫斷線時圖不該消失
    err.value = `更新失敗（${e.code || e.message}）——畫面保留上一次的資料`
  } finally {
    loading.value = false
  }
}

function onPickDay(e) {
  day.value = e.target.value
  follow.value = day.value === latestDay.value
  refresh()
}
function toggleFollow() {
  follow.value = !follow.value
  if (follow.value) refresh()
}

async function downloadCsv() {
  const rows = (await api.get('/records', { params: { date: day.value }, timeout: 30000 })).data
  const cols = ['timestamp', 'pressure', 'mixer_pressure', 'orp_raw', 'orp', 'ph', 'temp', 'co2_pct', 'ch4_pct', 'is_anomaly']
  const csv = [cols.join(','), ...rows.map(r => cols.map(c => r[c] ?? '').join(','))].join('\n')
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv' }))
  a.download = `BTP_${day.value}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

// ── 圖：三個小圖共用時間軸（不用雙 Y 軸） ───────────────────────
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() }

function render() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value, null, { renderer: 'canvas' })
  const recs = records.value
  const pt = key => recs.filter(r => r[key] != null).map(r => [r.timestamp, r[key]])
  const ink = css('--text-primary'), muted = css('--text-muted'), grid = css('--grid'), axis = css('--axis')
  const s1 = css('--series-1'), s2 = css('--series-2')
  const dayStart = day.value ? `${day.value} 00:00:00` : null
  const dayEnd = day.value ? `${day.value} 23:59:59` : null

  const starts = dayCycles.value.map(c => ({ xAxis: c.ts_start }))
  if (cur.value && !cur.value.error && cur.value.ts_start?.startsWith(day.value)) {
    starts.push({ xAxis: cur.value.ts_start, label: { show: true, formatter: '本循環', color: ink, position: 'end', fontSize: 11 }, lineStyle: { color: ink, width: 1, type: 'solid' } })
  }

  // ⚠ 反應槽與混合槽分開畫。放同一張圖時 Y 軸要同時涵蓋約 1.0 與 3.5，反應槽
  //   0.1~0.2 的下降——整個系統最重要的訊號——被壓成一條平線（實際截圖看過）。
  const PANELS = [
    { title: '反應槽壓力', unit: 'kgf/cm²', h: 150 },
    { title: '混合槽壓力', unit: 'kgf/cm²', h: 70 },
    { title: 'ORP（記錄為絕對值，實際為負）', unit: 'mV', h: 100 },
    { title: 'pH', unit: '', h: 90 },
  ]
  const GAP = 44
  const tops = []
  PANELS.reduce((y, p) => { tops.push(y); return y + p.h + GAP }, 36)
  const last = PANELS.length - 1
  const mkX = i => ({
    type: 'time', gridIndex: i, min: dayStart, max: dayEnd,
    axisLine: { lineStyle: { color: axis } }, axisTick: { show: false },
    axisLabel: { show: i === last, color: muted, formatter: '{HH}:{mm}' },
    splitLine: { show: false },
  })
  const mkY = (i, name) => ({
    type: 'value', gridIndex: i, scale: true,
    axisLabel: { color: muted }, axisLine: { show: false },
    splitLine: { lineStyle: { color: grid, width: 1 } },
  })
  const line = (name, data, color, i, extra = {}) => ({
    name, type: 'line', data, xAxisIndex: i, yAxisIndex: i, showSymbol: false,
    lineStyle: { width: 2, color }, itemStyle: { color }, emphasis: { disabled: true }, ...extra,
  })

  chart.setOption({
    animation: false,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: css('--font') },
    // 每張小圖只有一條線：標題就說明它是什麼，不需要圖例。
    title: PANELS.map((p, i) => ({
      text: p.unit ? `{t|${p.title}}  {u|${p.unit}}` : `{t|${p.title}}`, top: tops[i] - 30, left: 8,
      textStyle: { rich: { t: { color: ink, fontSize: 13, fontWeight: 600 }, u: { color: muted, fontSize: 11 } } },
    })),
    grid: PANELS.map((p, i) => ({ top: tops[i], height: p.h, left: 60, right: 24 })),
    xAxis: PANELS.map((_, i) => mkX(i)),
    yAxis: PANELS.map((p, i) => mkY(i, p.unit)),
    axisPointer: { link: [{ xAxisIndex: 'all' }], lineStyle: { color: muted } },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'line' },
      backgroundColor: css('--surface-2'), borderColor: css('--border'), textStyle: { color: ink },
      valueFormatter: v => (v == null ? '—' : Number(v).toFixed(2)),
    },
    dataZoom: [{ type: 'inside', xAxisIndex: PANELS.map((_, i) => i), filterMode: 'none' }],
    series: [
      line('反應槽壓力', pt('pressure'), s1, 0, { markLine: { silent: true, symbol: 'none', lineStyle: { color: axis, width: 1, type: 'solid' }, label: { show: false }, data: starts } }),
      line('混合槽壓力', pt('mixer_pressure'), s2, 1),
      line('ORP', pt('orp_raw'), s1, 2),
      line('pH', pt('ph'), s1, 3),
    ],
  }, { notMerge: true })
}

watch(dayCycles, () => render())

onMounted(async () => {
  offTheme = onThemeChange(() => render())   // 切主題要重畫：圖的顏色是繪製當下讀的
  await refresh()
  await nextTick()
  ro = new ResizeObserver(() => chart?.resize())
  if (chartEl.value) ro.observe(chartEl.value)
  timer = setInterval(() => {
    if (document.hidden) return
    if (follow.value) refresh()
    else loadStatus().catch(() => {})
  }, POLL_MS)
})
onBeforeUnmount(() => {
  offTheme?.()
  clearInterval(timer)
  ro?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="page">
    <!-- 篩選列：一列，管整頁 -->
    <div class="filters">
      <label class="field">
        <span>日期</span>
        <select :value="day" @change="onPickDay" :disabled="!days.length">
          <option v-for="d in days" :key="d.day" :value="d.day">
            {{ d.day }}（{{ d.n }} 筆，{{ Math.round(d.coverage * 100) }}%）
          </option>
        </select>
      </label>
      <button class="btn" :class="{ on: follow }" @click="toggleFollow" :aria-pressed="follow">
        {{ follow ? '● 跟隨最新（每 30 秒更新）' : '○ 跟隨最新' }}
      </button>
      <button class="btn" @click="downloadCsv" :disabled="!day">下載當日 CSV</button>
      <span class="fresh" :class="fresh.cls" role="status">
        <b>{{ fresh.icon }} {{ fresh.label }}</b>
        <span v-if="fresh.detail" class="detail">{{ fresh.detail }}</span>
      </span>
    </div>
    <p v-if="err" class="msg warn">⚠ {{ err }}</p>
    <p v-if="!days.length && !loading" class="msg">
      尚無資料。監控電腦的上傳程式（edge_backend/monitor_uploader.py）跑起來之後，這裡會自動出現。
    </p>

    <!-- 目前循環 -->
    <section v-if="isLatest && tiles.length" class="card">
      <h2>目前循環 <small>數字會隨時間更新；標「上限」的是化學計量上界，不是實際值</small></h2>
      <div class="tiles">
        <div v-for="t in tiles" :key="t.k" class="tile">
          <div class="tile-k">{{ t.k }} <span class="tag" :class="'tag-' + t.tag">{{ t.tag }}</span></div>
          <div class="tile-v">
            <span v-if="t.badge" class="badge" :class="t.badge">{{ t.badge === 'good' ? '✓' : '⚠' }}</span>
            {{ t.v }} <small v-if="t.unit">{{ t.unit }}</small>
          </div>
          <div class="tile-sub">{{ t.sub }}</div>
        </div>
      </div>
    </section>

    <!-- 圖 -->
    <section class="card" :class="{ dim: loading }">
      <div ref="chartEl" class="chart" role="img"
           :aria-label="`${day} 的反應槽壓力、混合槽壓力、ORP 與 pH 時間序列；逐筆數值可用「下載當日 CSV」取得`"></div>
      <p class="note">
        細直線＝當天已完成循環的起點<span v-if="isLatest">；白線＝目前循環起點</span>。
        滑鼠移到圖上看該時刻的四個值，滾輪縮放時間軸。
        <span v-if="dayInfo">這天收到 {{ dayInfo.n }} 筆（一分鐘一筆的 {{ Math.round(dayInfo.coverage * 100) }}%）。</span>
      </p>
    </section>

    <!-- 當天完成的循環 -->
    <section class="card">
      <h2>{{ day }} 完成的循環 <small>論文 Algorithm 1；曲率 &lt; 0.45 的段不估計</small></h2>
      <div v-if="dayCycles.length" class="table-wrap">
        <table>
          <thead><tr><th>起點</th><th>終點</th><th>時長 h</th><th>落差</th><th>曲率 c</th><th>篩選</th><th>k̂ /h</th><th>r̂_b</th></tr></thead>
          <tbody>
            <tr v-for="c in dayCycles" :key="c.ts_start">
              <td>{{ c.ts_start.slice(11, 16) }}</td>
              <td>{{ c.ts_end.slice(5, 16) }}</td>
              <td>{{ fmt(c.duration_hr, 1) }}</td>
              <td>{{ fmt(c.amplitude, 2) }}</td>
              <td>{{ fmt(c.curvature, 2) }}</td>
              <td>{{ c.screened ? '✓ 通過' : '— 未通過' }}</td>
              <td :class="{ edge: c.screened && kAtEdge(c.k_hat) }">
                {{ c.screened ? fmt(c.k_hat, 2) : '—' }}<span v-if="c.screened && kAtEdge(c.k_hat)"> ⚠</span>
              </td>
              <td :class="{ edge: c.screened && kAtEdge(c.k_hat) }">{{ c.screened ? fmt(c.rb_hat, 4) : '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="dayCycles.some(c => c.screened && kAtEdge(c.k_hat))" class="legend-note">
          ⚠ k̂ 貼在網格邊界（{{ K_LO }} 或 {{ K_HI }}）＝資料約束不了 k，這一段的 r̂_b 吸收了物理項，不可採信（灰字）。
        </p>
      </div>
      <p v-else class="msg">這天還沒有完成的循環（循環要等下一次補氣才算結束）。</p>
    </section>
  </div>
</template>

<style scoped>
.page { padding: 16px; display: flex; flex-direction: column; gap: 16px; max-width: 1400px; margin: 0 auto; }
.filters { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
.field { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 0.88rem; }
select, .btn {
  background: var(--surface-1); color: var(--text-primary); border: 1px solid var(--border);
  border-radius: 6px; padding: 7px 12px; font: inherit; font-size: 0.88rem; cursor: pointer;
}
.btn:hover { background: var(--surface-2); }
.btn.on { box-shadow: inset 0 0 0 1px var(--series-1); }
.btn:disabled { opacity: 0.5; cursor: default; }
.fresh { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; margin-left: auto; font-size: 0.88rem; }
.fresh.good b { color: var(--good); }
.fresh.warning b { color: var(--warning); }
.fresh.critical b { color: var(--critical); }
.fresh.muted b { color: var(--text-muted); }
.detail { color: var(--text-secondary); }
.msg { color: var(--text-secondary); font-size: 0.88rem; }
.msg.warn { color: var(--warning); }

.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.card.dim { opacity: 0.75; }
h2 { font-size: 0.98rem; font-weight: 600; margin-bottom: 12px; color: var(--text-primary); }
h2 small { font-weight: 400; color: var(--text-muted); font-size: 0.78rem; margin-left: 8px; }

.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.tile { background: var(--surface-2); border-radius: 6px; padding: 12px; min-width: 0; }
.tile-k { color: var(--text-secondary); font-size: 0.8rem; display: flex; justify-content: space-between; gap: 6px; }
.tile-v { font-size: 1.35rem; font-weight: 600; margin: 6px 0 4px; overflow-wrap: anywhere; }
.tile-v small { font-size: 0.75rem; font-weight: 400; color: var(--text-secondary); }
.tile-sub { color: var(--text-muted); font-size: 0.76rem; line-height: 1.4; }
.tag { font-size: 0.7rem; padding: 1px 6px; border-radius: 3px; border: 1px solid var(--border); color: var(--text-secondary); white-space: nowrap; }
.tag-上限, .tag-推估 { border-color: var(--warning); color: var(--warning); }
.badge.good { color: var(--good); }
.badge.warning { color: var(--warning); }

.chart { width: 100%; height: 640px; }
td.edge { color: var(--text-muted); }
.legend-note { color: var(--text-muted); font-size: 0.78rem; margin-top: 8px; }
.note { color: var(--text-muted); font-size: 0.78rem; margin-top: 8px; }

.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.84rem; font-variant-numeric: tabular-nums; }
th, td { padding: 6px 10px; text-align: right; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { color: var(--text-muted); font-weight: 500; }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
</style>
