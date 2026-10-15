<script setup>
// Jetson 硬體狀態：溫度、電源軌（電壓／電流／功率）、CPU／GPU、記憶體、風扇。
// 資料：GET /api/jetson/status（快照，每 5 秒）、/api/jetson/history（每 10 秒一筆，留 24 小時）。
//
// ⚠ 溫度燈號的門檻全部來自 Jetson 溫控驅動自己的設定（trip point），不是介面自訂：
//   第一被動降頻點以下＝正常、到主要降頻點之間＝降頻區、超過主要降頻點＝危險、關機點另外列出。
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import echarts from '../lib/echarts'
import api from '../services/apiClient'
import { onThemeChange } from '../lib/theme'

const RANGES = [[15, '15 分'], [60, '1 小時'], [360, '6 小時'], [1440, '24 小時']]
const st = ref(null)
const hist = ref(null)
const minutes = ref(60)
const err = ref('')
const chartEl = ref(null)
let chart = null
let offTheme = null, t1 = null, t2 = null, ro = null

const now = computed(() => st.value?.now)
const info = computed(() => st.value?.static || {})
const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d))

const maxTemp = computed(() => {
  const t = now.value?.temps || {}
  const e = Object.entries(t).sort((a, b) => b[1] - a[1])[0]
  return e ? { zone: e[0], c: e[1] } : null
})
const tempLevel = c => {
  const s = info.value
  if (c == null || s.throttle_first_c == null) return { cls: 'muted', icon: '○', label: '無門檻資料' }
  if (c >= s.throttle_main_c) return { cls: 'critical', icon: '✕', label: `已達主要降頻點 ${s.throttle_main_c}°C` }
  if (c >= s.throttle_first_c) return { cls: 'warning', icon: '⚠', label: `進入降頻區（≥ ${s.throttle_first_c}°C）` }
  return { cls: 'good', icon: '✓', label: `正常（降頻點 ${s.throttle_first_c}°C）` }
}

const tiles = computed(() => {
  const n = now.value
  if (!n) return []
  const vin = n.rails?.VDD_IN
  const lv = tempLevel(maxTemp.value?.c)
  return [
    { k: '總功率（VDD_IN）', v: fmt(vin?.w, 2), u: 'W', sub: `${fmt(vin?.v, 2)} V × ${fmt(vin?.a, 3)} A` },
    { k: '最高溫度', v: fmt(maxTemp.value?.c, 1), u: '°C', sub: `${maxTemp.value?.zone || ''}；${lv.label}`, lv },
    { k: 'CPU 平均使用率', v: fmt(n.cpu_util_avg, 0), u: '%', sub: `${Math.min(...n.cpu_mhz)}–${Math.max(...n.cpu_mhz)} MHz · 負載 ${fmt(n.load1, 2)}` },
    { k: 'GPU 使用率', v: fmt(n.gpu_util, 0), u: '%', sub: `${n.gpu_mhz} / ${fmt(info.value.gpu_max_mhz, 0)} MHz` },
    { k: '記憶體', v: `${fmt(n.ram_used_gb, 1)} / ${fmt(n.ram_total_gb, 1)}`, u: 'GB', sub: `swap ${fmt(n.swap_used_gb, 1)} GB` },
    { k: '風扇', v: n.fan_rpm ?? '—', u: 'rpm', sub: `PWM ${n.fan_pct ?? '—'}%` },
    { k: '電源模式', v: info.value.power_mode || '—', u: '', sub: `${info.value.cpu_count || '—'} 核 · 開機 ${fmt(n.uptime_hr, 1)} h` },
    { k: '磁碟（/）', v: `${fmt(n.disk_used_gb, 0)} / ${fmt(n.disk_total_gb, 0)}`, u: 'GB', sub: `${fmt(n.disk_used_gb / n.disk_total_gb * 100, 0)}% 已用` },
  ]
})

const ZONE_ORDER = ['cpu', 'gpu', 'cv0', 'cv1', 'cv2', 'soc0', 'soc1', 'soc2', 'tj']
const sortedTemps = computed(() => Object.entries(now.value?.temps || {})
  .sort((a, b) => (ZONE_ORDER.indexOf(a[0]) + 99 * (ZONE_ORDER.indexOf(a[0]) < 0)) - (ZONE_ORDER.indexOf(b[0]) + 99 * (ZONE_ORDER.indexOf(b[0]) < 0))))
const RAIL_NAME = { VDD_IN: '總輸入', VDD_CPU_GPU_CV: 'CPU／GPU／CV', VDD_SOC: 'SoC' }

async function loadStatus() {
  try { st.value = (await api.get('/jetson/status')).data; err.value = '' } catch (e) { err.value = e.message }
}
async function loadHist() {
  try { hist.value = (await api.get('/jetson/history', { params: { minutes: minutes.value } })).data; render() } catch (e) { err.value = e.message }
}

function css(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim() }
function render() {
  const h = hist.value
  if (!chartEl.value || !h || !h.ts) return
  if (!chart) chart = echarts.init(chartEl.value)
  const ink = css('--text-primary'), muted = css('--text-muted'), grid = css('--grid'), axis = css('--axis')
  const C = [css('--series-1'), css('--series-2'), css('--series-3'), css('--series-4')]
  const P = [
    { t: '溫度', u: '°C', h: 150, s: [['CPU', 'temp_cpu'], ['GPU', 'temp_gpu'], ['CV', 'temp_cv'], ['SoC', 'temp_soc']] },
    { t: '功率', u: 'W', h: 120, s: [['總輸入', 'w_in'], ['CPU／GPU／CV', 'w_cpu_gpu_cv'], ['SoC', 'w_soc']] },
    { t: '使用率', u: '%', h: 110, s: [['CPU 平均', 'cpu'], ['GPU', 'gpu']] },
    { t: '記憶體', u: 'GB', h: 90, s: [['已用', 'ram']] },
  ]
  const GAP = 52, tops = []
  P.reduce((y, p) => { tops.push(y); return y + p.h + GAP }, 40)
  const series = [], legends = []
  P.forEach((p, i) => p.s.forEach(([name, key], j) => {
    const sname = `${p.t}·${name}`
    legends.push({ i, name: sname })
    series.push({
      name: sname, type: 'line', xAxisIndex: i, yAxisIndex: i, showSymbol: false,
      data: h.ts.map((t, k) => [t, h[key][k]]), lineStyle: { width: 2, color: C[j] }, itemStyle: { color: C[j] },
      emphasis: { disabled: true },
      ...(i === 0 && j === 0 && info.value.throttle_first_c ? {
        markLine: { silent: true, symbol: 'none', data: [{ yAxis: info.value.throttle_first_c }],
          lineStyle: { color: muted, width: 1, type: 'solid' },
          label: { formatter: `降頻點 ${info.value.throttle_first_c}°C`, color: muted, position: 'insideEndTop' } },
      } : {}),
    })
  }))
  chart.setOption({
    animation: false, textStyle: { fontFamily: css('--font') },
    title: P.map((p, i) => ({ text: `{t|${p.t}}  {u|${p.u}}`, top: tops[i] - 34, left: 8,
      textStyle: { rich: { t: { color: ink, fontSize: 13, fontWeight: 600 }, u: { color: muted, fontSize: 11 } } } })),
    // 每張小圖自己的圖例（超過一條線才放），放在該圖右上
    legend: P.map((p, i) => ({ show: p.s.length > 1, top: tops[i] - 32, right: 8, icon: 'roundRect', itemWidth: 14, itemHeight: 3,
      textStyle: { color: css('--text-secondary') }, data: legends.filter(l => l.i === i).map(l => l.name),
      formatter: n => n.split('·')[1] })),
    grid: P.map((p, i) => ({ top: tops[i], height: p.h, left: 52, right: 24 })),
    // 時間軸固定為選定的整段範圍：剛重啟時資料只有右端一小截，一看就知道還在累積，
    // 不會把一分鐘拉滿整個寬度、刻度全是同一分鐘。
    xAxis: P.map((_, i) => ({ type: 'time', gridIndex: i, min: Date.now() - minutes.value * 60000, max: Date.now(), axisLine: { lineStyle: { color: axis } }, axisTick: { show: false },
      axisLabel: { show: i === P.length - 1, color: muted, formatter: '{HH}:{mm}' }, splitLine: { show: false } })),
    yAxis: P.map((p, i) => ({ type: 'value', gridIndex: i, scale: p.u !== '%', min: p.u === '%' ? 0 : undefined, max: p.u === '%' ? 100 : undefined,
      axisLabel: { color: muted }, splitLine: { lineStyle: { color: grid } } })),
    axisPointer: { link: [{ xAxisIndex: 'all' }], lineStyle: { color: muted } },
    tooltip: { trigger: 'axis', backgroundColor: css('--surface-2'), borderColor: css('--border'), textStyle: { color: ink },
      valueFormatter: v => (v == null ? '—' : Number(v).toFixed(1)) },
    dataZoom: [{ type: 'inside', xAxisIndex: P.map((_, i) => i), filterMode: 'none' }],
    series,
  }, { notMerge: true })
}
watch(minutes, loadHist)

onMounted(async () => {
  offTheme = onThemeChange(() => render())   // 切主題要重畫：圖的顏色是繪製當下讀的
  await loadStatus(); await loadHist()
  await nextTick()
  ro = new ResizeObserver(() => chart?.resize()); if (chartEl.value) ro.observe(chartEl.value)
  t1 = setInterval(() => { if (!document.hidden) loadStatus() }, 5000)
  t2 = setInterval(() => { if (!document.hidden) loadHist() }, 15000)
})
onBeforeUnmount(() => {
  offTheme?.(); clearInterval(t1); clearInterval(t2); ro?.disconnect(); chart?.dispose(); chart = null })
</script>

<template>
  <div class="wrap">
    <p v-if="err" class="msg warn">⚠ 讀取失敗：{{ err }}</p>
    <p v-if="st && !st.available" class="msg">{{ st.reason }}</p>

    <template v-if="st?.available && now">
      <section class="card">
        <h2>{{ info.model }} <small>{{ (info.l4t || []).join(' ').replace('# ', '') }} · 每 5 秒更新</small></h2>
        <div class="tiles">
          <div v-for="t in tiles" :key="t.k" class="tile">
            <div class="tk">{{ t.k }}</div>
            <div class="tv">
              <span v-if="t.lv" :class="t.lv.cls">{{ t.lv.icon }}</span>
              {{ t.v }} <small>{{ t.u }}</small>
            </div>
            <div class="ts" :class="t.lv?.cls">{{ t.sub }}</div>
          </div>
        </div>
      </section>

      <div class="two">
        <section class="card">
          <h2>CPU 各核 <small>使用率與時脈</small></h2>
          <div v-for="(u, i) in now.cpu_util || []" :key="i" class="core">
            <span class="cn">核心 {{ i }}</span>
            <span class="track"><span class="bar" :style="{ width: Math.min(100, u) + '%' }"></span></span>
            <span class="cv">{{ fmt(u, 0) }}%</span>
            <span class="cm">{{ now.cpu_mhz[i] }} MHz</span>
          </div>
          <p v-if="!now.cpu_util" class="msg">使用率要兩次讀數才算得出來，稍候…</p>
        </section>

        <section class="card">
          <h2>電源軌 <small>INA3221 量測</small></h2>
          <table>
            <thead><tr><th class="l">電源軌</th><th>電壓 V</th><th>電流 A</th><th>功率 W</th></tr></thead>
            <tbody>
              <tr v-for="(r, name) in now.rails" :key="name">
                <td class="l">{{ RAIL_NAME[name] || name }} <span class="muted">{{ name }}</span></td>
                <td>{{ fmt(r.v, 2) }}</td><td>{{ fmt(r.a, 3) }}</td><td>{{ fmt(r.w, 2) }}</td>
              </tr>
            </tbody>
          </table>
          <h2 class="mt">溫度 <small>降頻 {{ info.throttle_first_c }} / {{ info.throttle_main_c }}°C · 關機 {{ info.critical_c }}°C</small></h2>
          <table>
            <thead><tr><th class="l">區域</th><th>溫度 °C</th><th class="l">狀態</th></tr></thead>
            <tbody>
              <tr v-for="[z, c] in sortedTemps" :key="z">
                <td class="l">{{ z }}</td><td>{{ fmt(c, 1) }}</td>
                <td class="l" :class="tempLevel(c).cls">{{ tempLevel(c).icon }} {{ tempLevel(c).cls === 'good' ? '正常' : tempLevel(c).label }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>

      <section class="card">
        <div class="head">
          <h2>趨勢 <small>每 10 秒一筆，保留 24 小時；滑鼠移上去看該時刻數值、滾輪縮放</small></h2>
          <div class="seg" role="group" aria-label="時間範圍">
            <button v-for="[m, l] in RANGES" :key="m" :class="{ on: minutes === m }" @click="minutes = m">{{ l }}</button>
          </div>
        </div>
        <div ref="chartEl" class="chart" role="img" aria-label="Jetson 溫度、功率、使用率、記憶體的時間序列；即時數值見上方表格"></div>
        <p v-if="hist && hist.ts && hist.ts.length < 3" class="msg">後端剛啟動，歷史資料還在累積（每 10 秒一筆）。</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.wrap { padding: 16px; display: flex; flex-direction: column; gap: 16px; max-width: 1400px; margin: 0 auto; }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 16px; min-width: 0; }
h2 { font-size: 0.98rem; font-weight: 600; margin-bottom: 12px; }
h2.mt { margin-top: 18px; }
h2 small { font-weight: 400; color: var(--text-muted); font-size: 0.78rem; margin-left: 8px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
.tile { background: var(--surface-2); border-radius: 6px; padding: 12px; min-width: 0; }
.tk { color: var(--text-secondary); font-size: 0.8rem; }
.tv { font-size: 1.35rem; font-weight: 600; margin: 6px 0 4px; overflow-wrap: anywhere; }
.tv small { font-size: 0.75rem; font-weight: 400; color: var(--text-secondary); }
.ts { color: var(--text-muted); font-size: 0.76rem; }
.good { color: var(--good); } .warning { color: var(--warning); } .critical { color: var(--critical); } .muted { color: var(--text-muted); }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; }
.core { display: grid; grid-template-columns: 64px 1fr 44px 84px; align-items: center; gap: 10px; font-size: 0.82rem; margin-bottom: 6px; font-variant-numeric: tabular-nums; }
.cn { color: var(--text-secondary); }
.track { height: 8px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }
.bar { display: block; height: 100%; background: var(--series-1); border-radius: 4px; }
.cv { text-align: right; } .cm { color: var(--text-muted); text-align: right; }
table { width: 100%; border-collapse: collapse; font-size: 0.84rem; font-variant-numeric: tabular-nums; }
th, td { padding: 5px 8px; text-align: right; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { color: var(--text-muted); font-weight: 500; }
.l { text-align: left; }
.head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 8px; }
.seg { display: flex; gap: 4px; }
.seg button { background: var(--surface-2); color: var(--text-secondary); border: 1px solid var(--border); border-radius: 6px; padding: 4px 10px; font: inherit; font-size: 0.8rem; cursor: pointer; }
.seg button.on { color: var(--text-primary); box-shadow: inset 0 0 0 1px var(--series-1); }
.chart { width: 100%; height: 700px; }
.msg { color: var(--text-secondary); font-size: 0.84rem; }
.msg.warn { color: var(--warning); }
@media (max-width: 420px) { .core { grid-template-columns: 56px 1fr 40px; } .cm { display: none; } }
</style>
