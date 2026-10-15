<script setup>
// 論文檢定：Algorithm 2（簡併偏誤）與 Algorithm 3（純物理虛無），在 Jetson 背景跑。
//
// ⚠ 兩個修正選項都不勾＝論文原樣（research/paper_tests.py --verify 已確認與原腳本
//   逐位元相同）。勾了之後的數字是「修正後」，不是論文報的數字，表格會標出來。
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import echarts from '../lib/echarts'
import api from '../services/apiClient'
import { onThemeChange } from '../lib/theme'

const form = ref({ dataset: 'paper', algo: 'both', exact_time: false, drop_k_edge: false, nrep: 25, draws: 41 })
const runs = ref([])
const sel = ref(null)
const err = ref('')
const busy = ref(false)
const histEl = ref(null)
let chart = null
let offTheme = null
let timer = null

const running = computed(() => runs.value.find(r => r.status === 'running' || r.status === 'queued'))
const isPaper = p => p.dataset === 'paper' && !p.exact_time && !p.drop_k_edge && p.nrep === 25 && p.draws === 41
const fmt = (v, d = 4) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d))
const pct = v => (v == null ? '—' : `${(v * 100).toFixed(0)}%`)

async function loadRuns() {
  runs.value = (await api.get('/paper_tests')).data
  if (sel.value) {
    const fresh = runs.value.find(r => r.id === sel.value.id)
    if (fresh && (fresh.status !== sel.value.status || fresh.progress !== sel.value.progress)) await pick(fresh.id)
  }
}
async function pick(id) {
  sel.value = (await api.get(`/paper_tests/${id}`)).data
  await nextTick()
  renderHist()
}
async function start() {
  busy.value = true; err.value = ''
  try {
    const r = (await api.post('/paper_tests', form.value)).data
    await loadRuns(); await pick(r.id)
  } catch (e) {
    err.value = e.response?.data?.detail || e.message
  } finally { busy.value = false }
}
async function cancel(id) { await api.post(`/paper_tests/${id}/cancel`); await loadRuns() }

// Algorithm 2：每個基準的 ρ 分布（平均 ± 2SD）與實測 ρ 的位置，畫在同一條 0~1 尺上
const a2 = computed(() => sel.value?.result?.algorithm2)
const a3 = computed(() => sel.value?.result?.algorithm3)
const BASE = {
  B0: '真值恆定（r_b 不隨任何東西變）',
  B1: '真值會變，但與 k 無關',
  B2: '真值真的隨 k 上升（實測斜率）',
}
const pos = v => `${Math.max(0, Math.min(1, (v + 0.2) / 1.2)) * 100}%`   // 尺：−0.2 … 1.0
const closest = computed(() => {
  if (!a2.value) return null
  const o = a2.value.rho_observed
  return Object.entries(a2.value.baselines).sort((x, y) => Math.abs(x[1].rho_mean - o) - Math.abs(y[1].rho_mean - o))[0][0]
})

function css(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim() }
function renderHist() {
  if (!histEl.value || !a3.value) { chart?.dispose(); chart = null; return }
  if (!chart) chart = echarts.init(histEl.value)
  const d = a3.value.null_draws, obs = a3.value.observed_median
  const lo = Math.min(...d, 0), hi = Math.max(obs * 1.08, ...d)
  const nb = 30, w = (hi - lo) / nb
  const counts = Array(nb).fill(0)
  d.forEach(v => { counts[Math.min(nb - 1, Math.floor((v - lo) / w))]++ })
  const muted = css('--text-muted')
  chart.setOption({
    animation: false, textStyle: { fontFamily: css('--font') },
    grid: { left: 48, right: 24, top: 24, bottom: 40 },
    tooltip: { trigger: 'axis', backgroundColor: css('--surface-2'), borderColor: css('--border'), textStyle: { color: css('--text-primary') } },
    xAxis: { type: 'value', min: lo, max: hi, axisLabel: { color: muted, formatter: v => v.toFixed(4) }, splitLine: { show: false },
             axisLine: { lineStyle: { color: css('--axis') } }, name: '聚合中位 r̂_b（kgf/cm²/h）', nameLocation: 'middle', nameGap: 26, nameTextStyle: { color: muted } },
    yAxis: { type: 'value', axisLabel: { color: muted }, splitLine: { lineStyle: { color: css('--grid') } }, minInterval: 1 },
    series: [{
      name: '虛無抽樣次數', type: 'bar', barWidth: '90%',
      data: counts.map((c, i) => [lo + (i + 0.5) * w, c]),
      itemStyle: { color: css('--series-1'), borderRadius: [4, 4, 0, 0] },
      markLine: { silent: true, symbol: 'none', data: [{ xAxis: obs }],
        lineStyle: { color: css('--text-primary'), width: 2, type: 'solid' },
        label: { formatter: `實測 ${obs.toFixed(4)}`, color: css('--text-primary'), position: 'insideEndTop' } },
    }],
  }, { notMerge: true })
}
watch(a3, () => nextTick(renderHist))

onMounted(async () => {
  try { await loadRuns() } catch (e) { err.value = e.message }
  if (runs.value.length) await pick(runs.value[0].id)
  offTheme = onThemeChange(() => renderHist())   // 切主題要重畫
  timer = setInterval(() => { if (!document.hidden && running.value) loadRuns().catch(() => {}) }, 3000)
})
onBeforeUnmount(() => { offTheme?.(); clearInterval(timer); chart?.dispose() })
</script>

<template>
  <div class="page">
    <section class="card intro">
      <h2>論文檢定 <small>計算在 Jetson 背景跑；兩個演算法都在回答「Algorithm 1 算出來的 r_b 能不能信」</small></h2>
      <div class="cols">
        <p><b>Algorithm 2　簡併偏誤</b>：用每段循環自己的擬合參數造假資料，只把 r_b 換成已知真值，
          再跑同一個估計器。看「真值固定時，r̂_b 與 k̂ 本來就會相關到多少」，以及聚合中位數回不回得來。</p>
        <p><b>Algorithm 3　純物理虛無</b>：每段改用沒有生物項的模型重造，加同樣的雜訊、量化、篩選、估計。
          如果「完全沒有生物」也能算出接近實測的中位數，實測值就不能當成生物訊號。</p>
      </div>
    </section>

    <section class="card">
      <div class="formrow">
        <label>資料
          <select v-model="form.dataset">
            <option value="paper">論文資料集 C（定稿時的快照）</option>
            <option value="paper_all">資料集 C＋論文之後加入的三批</option>
            <option value="stream">串流資料（Jetson 資料庫）</option>
          </select>
        </label>
        <label>演算法
          <select v-model="form.algo">
            <option value="both">2 和 3</option><option value="2">只跑 2</option><option value="3">只跑 3</option>
          </select>
        </label>
        <label class="chk"><input type="checkbox" v-model="form.exact_time" /> 精確時間軸（修 3 分鐘門檻的浮點邊界）</label>
        <label class="chk"><input type="checkbox" v-model="form.drop_k_edge" /> 排除 k̂ 撞網格邊界的段</label>
        <label>重複 <input type="number" v-model.number="form.nrep" min="2" max="200" /></label>
        <label>抽樣 <input type="number" v-model.number="form.draws" min="2" max="500" /></label>
        <button class="btn" @click="start" :disabled="busy || !!running">{{ running ? '有工作在跑' : '執行' }}</button>
      </div>
      <p class="hint">
        全部不勾、重複 25、抽樣 41＝<b>論文原樣</b>（已逐位元核對原腳本）。論文正文寫 60 次抽樣，但報告的 p = 0.024 是 41 次的結果，以程式為準。
      </p>
      <p v-if="err" class="msg warn">⚠ {{ err }}</p>
      <div v-if="running" class="prog">
        <div class="bar"><span :style="{ width: (running.progress || 0) * 100 + '%' }"></span></div>
        <span>第 {{ running.id }} 號：{{ running.stage }}（{{ pct(running.progress) }}）</span>
        <button class="btn sm" @click="cancel(running.id)">取消</button>
      </div>
    </section>

    <section class="card" v-if="runs.length">
      <h2>執行紀錄 <small>並排看修正前後頭條數字怎麼動；點一列看細節</small></h2>
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>#</th><th>時間</th><th>資料</th><th>設定</th><th>段數</th><th>k̂ 撞邊界</th><th>r̂_b 中位</th><th>負值</th>
            <th>ρ 實測</th><th>B0 ρ</th><th>虛無中位</th><th>p</th><th>耗時</th><th>狀態</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in runs" :key="r.id" :class="{ on: sel?.id === r.id }" @click="pick(r.id)">
              <td>{{ r.id }}</td>
              <td>{{ (r.created || '').slice(5, 16) }}</td>
              <td>{{ { paper: '論文 C', paper_all: 'C＋新批', stream: '串流' }[r.params.dataset] }}</td>
              <td class="l">
                <span v-if="isPaper(r.params)" class="tag paper">論文原樣</span>
                <span v-if="r.params.exact_time" class="tag">精確時間</span>
                <span v-if="r.params.drop_k_edge" class="tag">排除邊界</span>
                <span v-if="r.params.nrep !== 25 || r.params.draws !== 41" class="tag">{{ r.params.nrep }}/{{ r.params.draws }}</span>
              </td>
              <td>{{ r.result?.n_retained ?? '—' }}</td>
              <td>{{ r.result?.n_k_edge ?? '—' }}</td>
              <td>{{ fmt(r.result?.rb_median, 5) }}</td>
              <td>{{ pct(r.result?.frac_negative) }}</td>
              <td>{{ fmt(r.result?.a2?.rho_observed, 3) }}</td>
              <td>{{ fmt(r.result?.a2?.B0, 3) }}</td>
              <td>{{ fmt(r.result?.a3?.null_median, 5) }}</td>
              <td>{{ fmt(r.result?.a3?.p_value, 3) }}</td>
              <td>{{ r.result?.seconds != null ? Math.round(r.result.seconds) + ' 秒' : '—' }}</td>
              <td :class="r.status">{{ { done: '✓ 完成', error: '✕ 錯誤', running: '… 執行中', queued: '… 等待', cancelled: '— 取消' }[r.status] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <template v-if="sel?.result && !sel.result.error">
      <section class="card" v-if="a2">
        <h2>Algorithm 2　簡併偏誤 <small>{{ a2.n }} 段 × {{ a2.nrep }} 次重複</small></h2>
        <p class="lead">實測 ρ(r̂_b, k̂) = <b>{{ fmt(a2.rho_observed, 3) }}</b>，最接近的基準是 <b>{{ closest }}</b>（{{ BASE[closest] }}）。</p>
        <div class="scale">
          <div v-for="(v, key) in a2.baselines" :key="key" class="srow">
            <span class="sk">{{ key }} <small>{{ BASE[key] }}</small></span>
            <span class="track">
              <span class="band" :style="{ left: pos(v.rho_mean - 2 * v.rho_sd), width: `calc(${pos(v.rho_mean + 2 * v.rho_sd)} - ${pos(v.rho_mean - 2 * v.rho_sd)})` }"></span>
              <span class="mean" :style="{ left: pos(v.rho_mean) }"></span>
              <span class="obs" :style="{ left: pos(a2.rho_observed) }"></span>
            </span>
            <span class="sv">ρ {{ fmt(v.rho_mean, 3) }} ± {{ fmt(v.rho_sd, 3) }}</span>
          </div>
          <div class="srow axisrow" aria-hidden="true">
            <span></span>
            <span class="ticks"><span v-for="v in [-0.2, 0, 0.2, 0.4, 0.6, 0.8, 1.0]" :key="v" :style="{ left: pos(v) }">{{ v }}</span></span>
            <span></span>
          </div>
        </div>
        <p class="note">藍帶＝該基準 ρ 的平均 ± 2SD；白線＝實測 ρ。</p>
        <table class="small">
          <thead><tr><th class="l">基準</th><th>投入真值中位</th><th>回收中位（平均）</th><th>偏誤</th></tr></thead>
          <tbody><tr v-for="(v, key) in a2.baselines" :key="key">
            <td class="l">{{ key }}</td><td>{{ fmt(v.truth_median, 5) }}</td><td>{{ fmt(v.median_mean, 5) }}</td><td>{{ v.bias_pct >= 0 ? '+' : '' }}{{ v.bias_pct.toFixed(1) }}%</td>
          </tr></tbody>
        </table>
      </section>

      <section class="card" v-if="a3">
        <h2>Algorithm 3　純物理虛無 <small>{{ a3.n }} 段 × {{ a3.draws }} 次抽樣</small></h2>
        <p class="lead">
          虛無中位 <b>{{ fmt(a3.null_median, 5) }}</b> ± {{ fmt(a3.null_sd, 5) }}（{{ a3.draws }} 次中最大 {{ fmt(a3.null_max, 5) }}），
          實測 <b>{{ fmt(a3.observed_median, 5) }}</b>，置換 p = <b>{{ fmt(a3.p_value, 3) }}</b>。
        </p>
        <div ref="histEl" class="hist" role="img" :aria-label="`純物理虛無下聚合中位數的分布，${a3.draws} 次抽樣；實測值 ${fmt(a3.observed_median, 5)}`"></div>
        <p class="note">p 的下限是 1/(抽樣次數+1) = {{ fmt(1 / (a3.draws + 1), 3) }}：0 次超過實測時就是這個值，再小要多抽。</p>
      </section>
    </template>
    <section v-else-if="sel?.result?.error || sel?.status === 'error'" class="card">
      <p class="msg warn">✕ 第 {{ sel.id }} 號沒有結果：{{ sel.result?.error || sel.stage }}</p>
      <pre v-if="sel.log" class="log">{{ sel.log }}</pre>
    </section>
  </div>
</template>

<style scoped>
.page { padding: 16px; display: flex; flex-direction: column; gap: 16px; max-width: 1400px; margin: 0 auto; }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
h2 { font-size: 0.98rem; font-weight: 600; margin-bottom: 12px; }
h2 small { font-weight: 400; color: var(--text-muted); font-size: 0.78rem; margin-left: 8px; }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
.cols p { color: var(--text-secondary); font-size: 0.86rem; line-height: 1.6; }
.cols b { color: var(--text-primary); }
.formrow { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; font-size: 0.86rem; color: var(--text-secondary); }
.formrow label { display: flex; align-items: center; gap: 6px; }
select, input[type=number] { background: var(--surface-2); color: var(--text-primary); border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font: inherit; }
input[type=number] { width: 72px; }
.btn { background: var(--surface-2); color: var(--text-primary); border: 1px solid var(--border); border-radius: 6px; padding: 7px 16px; font: inherit; cursor: pointer; }
.btn:disabled { opacity: 0.5; cursor: default; }
.btn.sm { padding: 3px 10px; font-size: 0.8rem; }
.hint, .note { color: var(--text-muted); font-size: 0.78rem; margin-top: 10px; line-height: 1.5; }
.msg.warn { color: var(--warning); margin-top: 8px; }
.prog { display: flex; align-items: center; gap: 12px; margin-top: 12px; font-size: 0.84rem; color: var(--text-secondary); flex-wrap: wrap; }
.prog .bar { width: 240px; height: 8px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }
.prog .bar span { display: block; height: 100%; background: var(--series-1); border-radius: 4px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; font-variant-numeric: tabular-nums; }
th, td { padding: 6px 8px; text-align: right; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { color: var(--text-muted); font-weight: 500; }
.l { text-align: left; }
tbody tr { cursor: pointer; }
tbody tr:hover, tbody tr.on { background: var(--surface-2); }
td.done { color: var(--good); } td.error { color: var(--critical); } td.running, td.queued { color: var(--warning); } td.cancelled { color: var(--text-muted); }
.tag { font-size: 0.72rem; padding: 1px 6px; border: 1px solid var(--border); border-radius: 3px; margin-right: 4px; color: var(--text-secondary); }
.tag.paper { border-color: var(--series-1); color: var(--text-primary); }
.lead { color: var(--text-secondary); font-size: 0.88rem; margin-bottom: 14px; }
.lead b { color: var(--text-primary); }
.scale { display: flex; flex-direction: column; gap: 10px; }
.srow { display: grid; grid-template-columns: minmax(150px, 260px) 1fr 140px; align-items: center; gap: 12px; font-size: 0.84rem; }
.sk small { color: var(--text-muted); display: block; font-size: 0.74rem; }
.track { position: relative; height: 14px; background: var(--surface-2); border-radius: 4px; }
.band { position: absolute; top: 3px; height: 8px; background: var(--series-1); opacity: 0.55; border-radius: 4px; }
.mean { position: absolute; top: 0; width: 2px; height: 14px; background: var(--series-1); transform: translateX(-1px); }
.obs { position: absolute; top: -3px; width: 2px; height: 20px; background: var(--text-primary); transform: translateX(-1px); }
.sv { color: var(--text-secondary); text-align: right; font-variant-numeric: tabular-nums; }
.ticks { position: relative; height: 14px; color: var(--text-muted); font-size: 0.72rem; }
.ticks span { position: absolute; transform: translateX(-50%); }
table.small { margin-top: 14px; max-width: 560px; }
.hist { width: 100%; height: 260px; }
.log { background: var(--surface-2); padding: 10px; border-radius: 6px; font-size: 0.75rem; color: var(--text-secondary); overflow-x: auto; max-height: 260px; }
@media (max-width: 640px) { .srow { grid-template-columns: 1fr; } .axisrow { display: none; } }
</style>
