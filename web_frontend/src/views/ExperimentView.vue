<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import apiClient from '../services/apiClient'

const runs = ref([])
const loading = ref(false)
const error = ref('')
const msg = ref('')

// 進行中批次的即時狀態（run_id -> live）
const liveMap = ref({})

// 手動新增批次表單
const newRun = ref({ run_id: '', n_minutes: 5, vent_pressure: 1.0 })

let pollTimer = null

const STATUS_META = {
  planned: { label: '已規劃', color: '#7f8c8d' },
  running: { label: '進行中', color: '#3498db' },
  done:    { label: '已完成', color: '#2ecc71' },
}

const runningRun = computed(() => runs.value.find(r => r.status === 'running'))

function flash(text) { msg.value = text; setTimeout(() => { if (msg.value === text) msg.value = '' }, 3000) }

async function loadRuns() {
  try {
    const { data } = await apiClient.get('/experiment/runs')
    runs.value = data
    error.value = ''
    // 抓進行中批次的即時狀態
    const running = data.filter(r => r.status === 'running')
    for (const r of running) {
      try {
        const { data: live } = await apiClient.get(`/experiment/runs/${r.run_id}/live`)
        liveMap.value = { ...liveMap.value, [r.run_id]: live }
      } catch { /* 忽略單筆失敗 */ }
    }
  } catch (e) {
    error.value = '無法連線後端：' + (e.code || e.message)
  }
}

async function createPlan() {
  if (runs.value.length && !confirm('已有批次，仍要建立標準 9 批次計畫嗎？（已存在的編號會略過）')) return
  loading.value = true
  try {
    const { data } = await apiClient.post('/experiment/plan', {})
    flash(`已建立 ${data.created.length} 個批次` + (data.skipped.length ? `，略過 ${data.skipped.length} 個` : ''))
    await loadRuns()
  } catch (e) { error.value = e.message } finally { loading.value = false }
}

async function addRun() {
  if (!newRun.value.run_id.trim()) { flash('請輸入批次編號'); return }
  try {
    await apiClient.post('/experiment/runs', {
      run_id: newRun.value.run_id.trim(),
      n_minutes: Number(newRun.value.n_minutes),
      vent_pressure: Number(newRun.value.vent_pressure),
    })
    newRun.value.run_id = ''
    await loadRuns()
  } catch (e) {
    flash(e.response?.status === 409 ? '批次編號已存在' : '新增失敗')
  }
}

async function startRun(r) {
  if (runningRun.value && runningRun.value.run_id !== r.run_id) {
    if (!confirm(`批次 ${runningRun.value.run_id} 還在進行中，確定要同時開始 ${r.run_id}？`)) return
  }
  await apiClient.post(`/experiment/runs/${r.run_id}/start`)
  flash(`批次 ${r.run_id} 已開始進氣`)
  await loadRuns()
}

async function ventRun(r) {
  if (!confirm(`確定批次 ${r.run_id} 現在排氣？此刻起結束計時並計算量測結果。`)) return
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

async function exportReport(fmt) {
  try {
    const resp = await apiClient.get(`/experiment/export?fmt=${fmt}`, { responseType: 'blob', timeout: 15000 })
    const blob = new Blob([resp.data])
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '')
    a.href = url
    a.download = `experiment_report_${stamp}.${fmt}`
    document.body.appendChild(a); a.click(); a.remove()
    URL.revokeObjectURL(url)
    flash(`已匯出 ${fmt.toUpperCase()} 報表`)
  } catch (e) { flash('匯出失敗：' + (e.message || '')) }
}

function fmtNum(v, digits = 3) {
  return (v === null || v === undefined) ? '—' : Number(v).toFixed(digits)
}

onMounted(() => { loadRuns(); pollTimer = setInterval(loadRuns, 15000) })
onUnmounted(() => clearInterval(pollTimer))
</script>

<template>
  <div class="exp-page">
    <header class="exp-header">
      <div>
        <h1>實驗批次管理</h1>
        <p class="subtitle">進氣 1.2 → 循環 n 分鐘 → 排氣。每批次量測結果由感測訊號自動計算。</p>
      </div>
      <div class="header-actions">
        <button class="btn btn-ghost" @click="exportReport('xlsx')">匯出 Excel</button>
        <button class="btn btn-ghost" @click="exportReport('csv')">匯出 CSV</button>
      </div>
    </header>

    <div v-if="msg" class="toast">{{ msg }}</div>
    <div v-if="error" class="toast err">{{ error }}</div>

    <!-- 進行中批次的即時面板 -->
    <div v-if="runningRun" class="live-panel">
      <div class="live-title">
        <span class="dot"></span> 進行中：批次 {{ runningRun.run_id }}
        <span class="live-sub">循環 {{ runningRun.n_minutes }} 分／小時</span>
      </div>
      <div class="live-grid" v-if="liveMap[runningRun.run_id]">
        <div class="live-cell">
          <span class="lv">{{ fmtNum(liveMap[runningRun.run_id].current_pressure, 3) }}</span>
          <span class="ll">目前壓力 (kg/cm²)</span>
        </div>
        <div class="live-cell">
          <span class="lv">{{ fmtNum(liveMap[runningRun.run_id].vent_target, 2) }}</span>
          <span class="ll">排氣目標</span>
        </div>
        <div class="live-cell">
          <span class="lv">{{ fmtNum(liveMap[runningRun.run_id].remaining_kg, 3) }}</span>
          <span class="ll">距目標還差 (kg/cm²)</span>
        </div>
        <div class="live-cell">
          <span class="lv" :class="{ ready: liveMap[runningRun.run_id].reached_target }">
            {{ liveMap[runningRun.run_id].reached_target ? '可排氣' : liveMap[runningRun.run_id].eta_hours + ' hr' }}
          </span>
          <span class="ll">預估剩餘（{{ liveMap[runningRun.run_id].rate_is_live ? '即時速率' : '歷史速率' }}）</span>
        </div>
      </div>
      <div v-else class="live-empty">尚無感測資料，請確認資料管線運作中。</div>
    </div>

    <!-- 建立計畫 / 手動新增 -->
    <div class="toolbar">
      <button class="btn btn-primary" @click="createPlan" :disabled="loading">建立標準 9 批次計畫</button>
      <div class="add-form">
        <input v-model="newRun.run_id" placeholder="批次編號 如 1.1" class="inp" />
        <select v-model="newRun.n_minutes" class="inp">
          <option :value="1">循環 1 分</option>
          <option :value="5">循環 5 分</option>
          <option :value="10">循環 10 分</option>
        </select>
        <input v-model.number="newRun.vent_pressure" type="number" step="0.05" class="inp inp-sm" title="排氣目標" />
        <button class="btn btn-ghost" @click="addRun">＋ 新增批次</button>
      </div>
    </div>

    <!-- 批次表 -->
    <div class="table-wrap">
      <table class="exp-table">
        <thead>
          <tr>
            <th>批次</th><th>循環時間</th><th>進氣</th><th>排氣目標</th><th>狀態</th>
            <th class="grp">總時間<br><small>hrs</small></th>
            <th class="grp">下降速率<br><small>kg/cm²/hr</small></th>
            <th class="grp">排氣 pH</th>
            <th class="grp">排氣 ORP</th>
            <th class="grp">CH4%<br><small>參考</small></th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in runs" :key="r.run_id" :class="{ 'row-running': r.status === 'running' }">
            <td class="mono">{{ r.run_id }}</td>
            <td>{{ r.n_minutes }} 分</td>
            <td>{{ r.intake_pressure }}</td>
            <td>{{ r.vent_pressure }}</td>
            <td>
              <span class="badge" :style="{ color: STATUS_META[r.status]?.color, borderColor: STATUS_META[r.status]?.color }">
                {{ STATUS_META[r.status]?.label || r.status }}
              </span>
            </td>
            <td class="mono">{{ fmtNum(r.results.total_hours, 2) }}</td>
            <td class="mono hl">{{ fmtNum(r.results.pressure_drop_rate, 5) }}</td>
            <td class="mono">{{ fmtNum(r.results.vent_ph, 2) }}</td>
            <td class="mono">{{ fmtNum(r.results.vent_orp, 1) }}</td>
            <td class="mono dim">{{ fmtNum(r.results.vent_ch4_peak_ref, 1) }}</td>
            <td class="ops">
              <button v-if="r.status === 'planned'" class="op op-start" @click="startRun(r)">開始進氣</button>
              <button v-if="r.status === 'running'" class="op op-vent" @click="ventRun(r)">排氣</button>
              <button class="op op-del" @click="deleteRun(r)">刪除</button>
            </td>
          </tr>
          <tr v-if="!runs.length">
            <td colspan="11" class="empty">尚無批次。點「建立標準 9 批次計畫」開始。</td>
          </tr>
        </tbody>
      </table>
    </div>

    <p class="footnote">
      量化重點：綠色區塊的「下降壓力速率」為主要指標，用於比較 n=1/5/10 的差異。
      CH4% 僅取排氣峰值當參考，不作為證據（見證據鏈文件）。
    </p>
  </div>
</template>

<style scoped>
.exp-page { min-height: 100vh; background: #0d0d0d; color: #e0e0e0; padding: 1.25rem; }
.exp-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding-bottom: 1rem; margin-bottom: 1rem; border-bottom: 1px solid #1a1a1a;
}
.exp-header h1 { font-size: 1.2rem; font-weight: 700; color: #fff; margin-bottom: 3px; }
.subtitle { font-size: 0.78rem; color: #555; }
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

/* ── 即時面板 ── */
.live-panel { background: #101820; border: 1px solid #1c3a52; border-radius: 8px;
              padding: 1rem 1.25rem; margin-bottom: 1.25rem; }
.live-title { font-size: 0.95rem; font-weight: 700; color: #6cb6e8; margin-bottom: 12px;
              display: flex; align-items: center; gap: 8px; }
.live-sub { font-size: 0.75rem; font-weight: 400; color: #557; margin-left: 6px; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: #3498db;
       box-shadow: 0 0 0 0 rgba(52,152,219,0.6); animation: pulse 1.6s infinite; }
@keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(52,152,219,0.5)} 70%{box-shadow:0 0 0 8px rgba(52,152,219,0)} 100%{box-shadow:0 0 0 0 rgba(52,152,219,0)} }
.live-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: #1a2a38;
             border-radius: 6px; overflow: hidden; }
.live-cell { display: flex; flex-direction: column; padding: 12px 16px; background: #0d1620; }
.lv { font-size: 1.5rem; font-weight: 700; font-family: monospace; color: #dfe8f0; }
.lv.ready { color: #2ecc71; }
.ll { font-size: 0.7rem; color: #557; margin-top: 4px; }
.live-empty { color: #667; font-size: 0.82rem; }

/* ── 工具列 ── */
.toolbar { display: flex; justify-content: space-between; align-items: center;
           flex-wrap: wrap; gap: 12px; margin-bottom: 1rem; }
.add-form { display: flex; gap: 8px; align-items: center; }
.inp { background: #131313; border: 1px solid #262626; color: #ccc; padding: 6px 10px;
       border-radius: 4px; font-size: 0.8rem; font-family: inherit; }
.inp-sm { width: 70px; }

/* ── 表格 ── */
.table-wrap { overflow-x: auto; border: 1px solid #1a1a1a; border-radius: 8px; }
.exp-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
.exp-table th { background: #141414; color: #888; font-weight: 600; padding: 10px 12px;
                text-align: center; border-bottom: 1px solid #222; white-space: nowrap; }
.exp-table th.grp { background: #14201a; color: #6aa583; }
.exp-table th small, .exp-table td small { font-size: 0.65rem; color: #556; font-weight: 400; }
.exp-table td { padding: 9px 12px; text-align: center; border-bottom: 1px solid #171717; }
.exp-table tbody tr:hover { background: #131313; }
.row-running { background: rgba(52,152,219,0.06); }
.mono { font-family: monospace; color: #cfcfcf; }
.hl { color: #6aa583; font-weight: 700; }
.dim { color: #666; }
.empty { color: #555; padding: 2rem; }

.badge { font-size: 0.72rem; padding: 2px 9px; border: 1px solid; border-radius: 10px; }

.ops { display: flex; gap: 5px; justify-content: center; }
.op { font-family: inherit; font-size: 0.72rem; padding: 4px 9px; border-radius: 4px;
      cursor: pointer; border: 1px solid #2a2a2a; background: #161616; color: #999; }
.op-start { border-color: #2c5a7a; color: #6cb6e8; }
.op-vent { border-color: #7a5a2c; color: #e0a860; }
.op-del { border-color: #5a2c2c; color: #c07070; }
.op:hover { filter: brightness(1.3); }

.footnote { font-size: 0.72rem; color: #556; margin-top: 1rem; line-height: 1.6; }

@media (max-width: 760px) {
  .live-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
