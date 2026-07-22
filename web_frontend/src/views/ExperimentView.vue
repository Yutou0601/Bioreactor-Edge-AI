<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import apiClient from '../services/apiClient'

const runs = ref([])
const loading = ref(false)
const error = ref('')
const msg = ref('')
const liveMap = ref({})
const expanded = ref(null)      // 展開顯示每循環明細的 run_id
const cyclesMap = ref({})       // run_id -> cycles[]

// 基準值（洗管線到此標準；2026-07-22 定案）
const baseline = ref({ baseline_ch4: 9.0, baseline_co2: 21.0, baseline_pressure: 1.185 })

// 手動新增批次
const newRun = ref({ run_id: '', n_minutes: 1, scheduled_start: '' })

let pollTimer = null

const STATUS_META = {
  planned: { label: '已規劃', color: '#7f8c8d' },
  running: { label: '進行中', color: '#3498db' },
  done:    { label: '已完成', color: '#2ecc71' },
}

const runningRun = computed(() => runs.value.find(r => r.status === 'running'))

function flash(t) { msg.value = t; setTimeout(() => { if (msg.value === t) msg.value = '' }, 3000) }
function fmt(v, d = 3) { return (v === null || v === undefined) ? '—' : Number(v).toFixed(d) }

async function loadRuns() {
  try {
    const { data } = await apiClient.get('/experiment/runs')
    runs.value = data
    error.value = ''
    for (const r of data.filter(x => x.status === 'running')) {
      try {
        const { data: live } = await apiClient.get(`/experiment/runs/${r.run_id}/live`)
        liveMap.value = { ...liveMap.value, [r.run_id]: live }
      } catch { /* skip */ }
    }
  } catch (e) { error.value = '無法連線後端：' + (e.code || e.message) }
}

async function createPlan() {
  if (runs.value.length && !confirm('已有批次，仍要建立標準計畫嗎？（已存在編號會略過）')) return
  loading.value = true
  try {
    const { data } = await apiClient.post('/experiment/plan', { ...baseline.value })
    flash(`已建立 ${data.created.length} 個批次`)
    await loadRuns()
  } catch (e) { error.value = e.message } finally { loading.value = false }
}

async function addRun() {
  if (!newRun.value.run_id.trim()) { flash('請輸入批次編號'); return }
  try {
    await apiClient.post('/experiment/runs', {
      run_id: newRun.value.run_id.trim(),
      n_minutes: Number(newRun.value.n_minutes),
      scheduled_start: newRun.value.scheduled_start || null,
      ...baseline.value,
    })
    newRun.value.run_id = ''
    await loadRuns()
  } catch (e) { flash(e.response?.status === 409 ? '批次編號已存在' : '新增失敗') }
}

async function startRun(r) {
  if (runningRun.value && runningRun.value.run_id !== r.run_id &&
      !confirm(`批次 ${runningRun.value.run_id} 還在進行中，確定同時開始 ${r.run_id}？`)) return
  // 若有排定開始時間，用該時間；否則現在
  const at = r.scheduled_start || null
  await apiClient.post(`/experiment/runs/${r.run_id}/start`, { at })
  flash(`批次 ${r.run_id} 已開始` + (at ? `（起於 ${at}）` : ''))
  await loadRuns()
}

async function ventRun(r) {
  if (!confirm(`確定批次 ${r.run_id} 現在排氣結束？此刻起計算量測結果。`)) return
  try {
    await apiClient.post(`/experiment/runs/${r.run_id}/vent`)
    flash(`批次 ${r.run_id} 已排氣，量測結果已計算`)
    await loadRuns()
  } catch (e) { flash(e.response?.data?.detail || '排氣失敗') }
}

async function deleteRun(r) {
  if (!confirm(`刪除批次 ${r.run_id}？`)) return
  await apiClient.delete(`/experiment/runs/${r.run_id}`)
  await loadRuns()
}

async function toggleCycles(r) {
  if (expanded.value === r.run_id) { expanded.value = null; return }
  expanded.value = r.run_id
  try {
    const { data } = await apiClient.get(`/experiment/runs/${r.run_id}/cycles`)
    cyclesMap.value = { ...cyclesMap.value, [r.run_id]: data.cycles }
  } catch { cyclesMap.value = { ...cyclesMap.value, [r.run_id]: [] } }
}

async function exportReport(f) {
  try {
    const resp = await apiClient.get(`/experiment/export?fmt=${f}`, { responseType: 'blob', timeout: 15000 })
    const url = URL.createObjectURL(new Blob([resp.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = `experiment_report_${new Date().toISOString().slice(0,16).replace(/[-:T]/g,'')}.${f}`
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
    flash(`已匯出 ${f.toUpperCase()} 報表`)
  } catch (e) { flash('匯出失敗：' + (e.message || '')) }
}

onMounted(() => { loadRuns(); pollTimer = setInterval(loadRuns, 15000) })
onUnmounted(() => clearInterval(pollTimer))
</script>

<template>
  <div class="exp-page">
    <header class="exp-header">
      <div>
        <h1>實驗批次管理</h1>
        <p class="subtitle">洗管線至基準 → 進氣 → 每時循環 n 分鐘 → 自動補氣 → 48hr 後排氣。量測結果自動計算。</p>
      </div>
      <div class="header-actions">
        <button class="btn btn-ghost" @click="exportReport('xlsx')">匯出 Excel</button>
        <button class="btn btn-ghost" @click="exportReport('csv')">匯出 CSV</button>
      </div>
    </header>

    <div v-if="msg" class="toast">{{ msg }}</div>
    <div v-if="error" class="toast err">{{ error }}</div>

    <!-- 進行中批次即時面板 -->
    <div v-if="runningRun && liveMap[runningRun.run_id]" class="live-panel">
      <div class="live-title">
        <span class="dot"></span> 進行中：批次 {{ runningRun.run_id }}
        <span class="live-sub">循環 {{ runningRun.n_minutes }} 分／小時 · 已完成 {{ liveMap[runningRun.run_id].n_cycles_so_far }} 次補氣</span>
      </div>
      <div class="live-grid">
        <div class="live-cell"><span class="lv">{{ fmt(liveMap[runningRun.run_id].current_pressure) }}</span><span class="ll">目前壓力 kg/cm²</span></div>
        <div class="live-cell"><span class="lv">{{ fmt(liveMap[runningRun.run_id].current_orp, 0) }}</span><span class="ll">目前 ORP mV</span></div>
        <div class="live-cell">
          <span class="lv" :class="{ ready: liveMap[runningRun.run_id].remaining_kg <= 0 }">
            {{ liveMap[runningRun.run_id].remaining_kg <= 0 ? '即將補氣' : liveMap[runningRun.run_id].eta_refill_hours + ' hr' }}
          </span>
          <span class="ll">距下次補氣（降到 {{ liveMap[runningRun.run_id].intake_lower }}）</span>
        </div>
        <div class="live-cell">
          <span class="lv">{{ fmt(liveMap[runningRun.run_id].elapsed_hours, 1) }} <small>/ {{ liveMap[runningRun.run_id].target_hours }}</small></span>
          <span class="ll">實驗已跑 / 預計 hr</span>
        </div>
      </div>
    </div>

    <!-- 基準值 + 建立計畫 + 手動新增 -->
    <div class="toolbar">
      <div class="baseline-box">
        <span class="bl-title">基準值（洗管線至此）</span>
        <label>CH4% <input v-model.number="baseline.baseline_ch4" type="number" step="0.1" class="inp inp-sm" /></label>
        <label>CO2% <input v-model.number="baseline.baseline_co2" type="number" step="0.1" class="inp inp-sm" /></label>
        <label>壓力 <input v-model.number="baseline.baseline_pressure" type="number" step="0.005" class="inp inp-sm" /></label>
      </div>
      <div class="add-actions">
        <button class="btn btn-primary" @click="createPlan" :disabled="loading">建立標準計畫（n=1/5/10）</button>
      </div>
    </div>
    <div class="add-form">
      <input v-model="newRun.run_id" placeholder="批次編號 如 1" class="inp" />
      <select v-model="newRun.n_minutes" class="inp">
        <option :value="1">循環 1 分</option>
        <option :value="5">循環 5 分</option>
        <option :value="10">循環 10 分</option>
      </select>
      <label class="sched">排定開始
        <input v-model="newRun.scheduled_start" type="datetime-local" class="inp" />
      </label>
      <button class="btn btn-ghost" @click="addRun">＋ 新增批次</button>
    </div>

    <!-- 批次表 -->
    <div class="table-wrap">
      <table class="exp-table">
        <thead>
          <tr>
            <th></th><th>批次</th><th>循環</th><th>基準<br><small>CH4/CO2/P</small></th>
            <th>補氣band</th><th>狀態</th>
            <th class="grp">總時間<br><small>hr</small></th>
            <th class="grp">補氣<br>循環數</th>
            <th class="grp">下降速率中位<br><small>kg/cm²/hr</small></th>
            <th class="grp cov">進氣前ORP漂移<br><small>菌群共變數</small></th>
            <th class="grp">排氣pH</th>
            <th class="grp">排氣ORP</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="r in runs" :key="r.run_id">
            <tr :class="{ 'row-running': r.status === 'running' }">
              <td class="expand-cell">
                <button class="expander" @click="toggleCycles(r)" :title="'展開每循環明細'">
                  {{ expanded === r.run_id ? '▾' : '▸' }}
                </button>
              </td>
              <td class="mono">{{ r.run_id }}</td>
              <td>{{ r.n_minutes }} 分</td>
              <td class="mono dim">{{ r.baseline_ch4 }}/{{ r.baseline_co2 }}/{{ r.baseline_pressure }}</td>
              <td class="mono dim">{{ r.intake_lower }}→{{ r.intake_upper }}</td>
              <td>
                <span class="badge" :style="{ color: STATUS_META[r.status]?.color, borderColor: STATUS_META[r.status]?.color }">
                  {{ STATUS_META[r.status]?.label || r.status }}
                </span>
                <div v-if="r.status === 'planned' && r.scheduled_start" class="sched-hint">排定 {{ r.scheduled_start.slice(5,16) }}</div>
              </td>
              <td class="mono">{{ fmt(r.results.total_hours, 1) }}</td>
              <td class="mono">{{ r.results.n_cycles || '—' }}</td>
              <td class="mono hl">{{ fmt(r.results.drop_rate_median, 5) }}</td>
              <td class="mono cov">{{ fmt(r.results.culture_drift, 1) }}</td>
              <td class="mono">{{ fmt(r.results.vent_ph, 2) }}</td>
              <td class="mono">{{ fmt(r.results.vent_orp, 0) }}</td>
              <td class="ops">
                <button v-if="r.status === 'planned'" class="op op-start" @click="startRun(r)">開始</button>
                <button v-if="r.status === 'running'" class="op op-vent" @click="ventRun(r)">排氣</button>
                <button class="op op-del" @click="deleteRun(r)">刪</button>
              </td>
            </tr>
            <!-- 每循環明細 -->
            <tr v-if="expanded === r.run_id" class="detail-row">
              <td colspan="13">
                <div class="cycle-detail">
                  <div class="cd-title">每循環特徵（{{ r.run_id }}）— 進氣前 ORP 為菌群成熟度共變數</div>
                  <table v-if="cyclesMap[r.run_id]?.length" class="cycle-table">
                    <thead><tr><th>週期</th><th>起</th><th>時長hr</th><th>P起→P末</th><th>下降速率</th><th>進氣前ORP</th><th>ORP崩落</th></tr></thead>
                    <tbody>
                      <tr v-for="cy in cyclesMap[r.run_id]" :key="cy.cycle">
                        <td>{{ cy.cycle }}</td>
                        <td class="mono dim">{{ cy.start.slice(5) }}</td>
                        <td class="mono">{{ cy.duration_hr }}</td>
                        <td class="mono">{{ cy.pressure_start }}→{{ cy.pressure_end }}</td>
                        <td class="mono hl">{{ fmt(cy.drop_rate, 5) }}</td>
                        <td class="mono cov">{{ cy.pre_injection_orp }}</td>
                        <td class="mono">{{ cy.orp_crash }}</td>
                      </tr>
                    </tbody>
                  </table>
                  <div v-else class="cd-empty">尚無循環（實驗未開始或資料不足）。</div>
                </div>
              </td>
            </tr>
          </template>
          <tr v-if="!runs.length"><td colspan="13" class="empty">尚無批次。點「建立標準計畫」開始。</td></tr>
        </tbody>
      </table>
    </div>

    <p class="footnote">
      量化重點：<b class="hl">下降速率中位數</b>為主要指標（比較 n=1/5/10）。
      <b class="cov">進氣前 ORP 漂移</b>記錄菌群成熟度，用於事後把菌群漂移從 n 效應中扣除（因 n 與實驗天數共線）。
      CH4% 僅參考、不作為證據。
    </p>
  </div>
</template>

<style scoped>
.exp-page { min-height: 100vh; background: #0d0d0d; color: #e0e0e0; padding: 1.25rem; }
.exp-header { display: flex; justify-content: space-between; align-items: flex-start;
  padding-bottom: 1rem; margin-bottom: 1rem; border-bottom: 1px solid #1a1a1a; }
.exp-header h1 { font-size: 1.2rem; font-weight: 700; color: #fff; margin-bottom: 3px; }
.subtitle { font-size: 0.76rem; color: #555; }
.header-actions { display: flex; gap: 8px; }

.btn { font-family: inherit; font-size: 0.82rem; padding: 7px 16px; border-radius: 4px;
  cursor: pointer; border: 1px solid #262626; transition: all 0.15s; }
.btn-primary { background: rgba(52,152,219,0.15); border-color: #2c5a7a; color: #6cb6e8; }
.btn-primary:hover:not(:disabled) { background: rgba(52,152,219,0.28); }
.btn-ghost { background: #161616; color: #aaa; }
.btn-ghost:hover { background: #1e1e1e; color: #ddd; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }

.toast { background: #14261a; border: 1px solid #2ecc71; color: #7fe0a3;
  padding: 8px 14px; border-radius: 4px; font-size: 0.82rem; margin-bottom: 12px; }
.toast.err { background: #2a1414; border-color: #c0392b; color: #e08080; }

.live-panel { background: #101820; border: 1px solid #1c3a52; border-radius: 8px;
  padding: 1rem 1.25rem; margin-bottom: 1.25rem; }
.live-title { font-size: 0.95rem; font-weight: 700; color: #6cb6e8; margin-bottom: 12px;
  display: flex; align-items: center; gap: 8px; }
.live-sub { font-size: 0.75rem; font-weight: 400; color: #557; margin-left: 6px; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: #3498db; animation: pulse 1.6s infinite; }
@keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(52,152,219,0.5)} 70%{box-shadow:0 0 0 8px rgba(52,152,219,0)} 100%{box-shadow:0 0 0 0 rgba(52,152,219,0)} }
.live-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: #1a2a38; border-radius: 6px; overflow: hidden; }
.live-cell { display: flex; flex-direction: column; padding: 12px 16px; background: #0d1620; }
.lv { font-size: 1.5rem; font-weight: 700; font-family: monospace; color: #dfe8f0; }
.lv small { font-size: 0.7rem; color: #557; }
.lv.ready { color: #2ecc71; }
.ll { font-size: 0.68rem; color: #557; margin-top: 4px; }

.toolbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 10px; }
.baseline-box { display: flex; align-items: center; gap: 10px; background: #121212; border: 1px solid #222;
  border-radius: 6px; padding: 8px 14px; }
.bl-title { font-size: 0.76rem; color: #888; font-weight: 600; }
.baseline-box label { font-size: 0.74rem; color: #777; display: flex; align-items: center; gap: 4px; }
.add-form { display: flex; gap: 8px; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; }
.sched { font-size: 0.74rem; color: #777; display: flex; align-items: center; gap: 5px; }
.inp { background: #131313; border: 1px solid #262626; color: #ccc; padding: 6px 10px;
  border-radius: 4px; font-size: 0.8rem; font-family: inherit; }
.inp-sm { width: 64px; }

.table-wrap { overflow-x: auto; border: 1px solid #1a1a1a; border-radius: 8px; }
.exp-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.exp-table th { background: #141414; color: #888; font-weight: 600; padding: 9px 10px;
  text-align: center; border-bottom: 1px solid #222; white-space: nowrap; }
.exp-table th.grp { background: #14201a; color: #6aa583; }
.exp-table th.grp.cov { background: #201a14; color: #c8a06a; }
.exp-table th small, .exp-table td small { font-size: 0.64rem; color: #556; font-weight: 400; }
.exp-table td { padding: 8px 10px; text-align: center; border-bottom: 1px solid #171717; }
.exp-table tbody tr:hover:not(.detail-row) { background: #131313; }
.row-running { background: rgba(52,152,219,0.06); }
.mono { font-family: monospace; color: #cfcfcf; }
.hl { color: #6aa583; font-weight: 700; }
.cov { color: #c8a06a; font-weight: 700; }
.dim { color: #666; }
.empty { color: #555; padding: 2rem; }
.badge { font-size: 0.7rem; padding: 2px 8px; border: 1px solid; border-radius: 10px; }
.sched-hint { font-size: 0.62rem; color: #557; margin-top: 3px; }

.expand-cell { width: 26px; padding: 0 !important; }
.expander { background: none; border: none; color: #667; cursor: pointer; font-size: 0.9rem; }
.expander:hover { color: #aaa; }
.detail-row td { background: #0a0f0c; padding: 0 !important; }
.cycle-detail { padding: 12px 20px; }
.cd-title { font-size: 0.76rem; color: #c8a06a; margin-bottom: 8px; font-weight: 600; }
.cycle-table { width: auto; border-collapse: collapse; font-size: 0.76rem; }
.cycle-table th { background: #12160f; color: #778; padding: 5px 14px; border: 1px solid #1a1a1a; }
.cycle-table td { padding: 5px 14px; border: 1px solid #161616; text-align: center; }
.cd-empty { font-size: 0.76rem; color: #556; padding: 8px 0; }

.ops { display: flex; gap: 4px; justify-content: center; }
.op { font-family: inherit; font-size: 0.7rem; padding: 4px 8px; border-radius: 4px; cursor: pointer;
  border: 1px solid #2a2a2a; background: #161616; color: #999; }
.op-start { border-color: #2c5a7a; color: #6cb6e8; }
.op-vent { border-color: #7a5a2c; color: #e0a860; }
.op-del { border-color: #5a2c2c; color: #c07070; }
.op:hover { filter: brightness(1.3); }

.footnote { font-size: 0.72rem; color: #667; margin-top: 1rem; line-height: 1.7; }

@media (max-width: 760px) { .live-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
