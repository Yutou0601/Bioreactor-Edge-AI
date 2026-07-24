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
const editRow = ref(null)       // 正在編輯起訖時間的 run_id
const editForm = ref({ start_time: '', end_time: '' })

// 基準值（洗管線到此標準；2026-07-22 定案）
const baseline = ref({ baseline_ch4: 9.0, baseline_co2: 21.0, baseline_pressure: 1.185 })

// 手動新增批次
const newRun = ref({ run_id: '', n_minutes: 1, scheduled_start: '' })

let pollTimer = null

// "YYYY-MM-DD HH:MM:SS" → "YYYY-MM-DDTHH:MM"（datetime-local 顯示用）
function toLocal(ts) { return ts ? ts.replace(' ', 'T').slice(0, 16) : '' }
// 當下時間的 datetime-local 字串
function nowLocal() {
  const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

const STATUS_META = {
  planned: { label: '已規劃', color: '#7f8c8d' },
  running: { label: '進行中', color: '#3498db' },
  done:    { label: '已完成', color: '#2ecc71' },
}

const runningRun = computed(() => runs.value.find(r => r.status === 'running'))
const live = computed(() => runningRun.value ? liveMap.value[runningRun.value.run_id] : null)

function flash(t) { msg.value = t; setTimeout(() => { if (msg.value === t) msg.value = '' }, 3000) }
function fmt(v, d = 3) { return (v === null || v === undefined) ? '—' : Number(v).toFixed(d) }

// 本循環即時壓力小圖：把 cycle_series 轉成 SVG polyline，並標出補氣下限參考線。
// 無外部繪圖庫（維持後端/前端輕量、CSP 安全），純算座標。
const W = 460, H = 96, PAD = 6
const liveChart = computed(() => {
  const s = live.value?.cycle_series
  if (!s || s.length < 2) return null
  const ps = s.map(d => d.p)
  const lower = live.value.intake_lower
  const base = live.value.baseline_pressure
  let lo = Math.min(...ps, lower), hi = Math.max(...ps, base ?? -Infinity)
  if (hi - lo < 0.02) hi = lo + 0.02                       // 避免平線時擠成一條
  const x = i => PAD + (W - 2 * PAD) * i / (s.length - 1)
  const y = p => PAD + (H - 2 * PAD) * (1 - (p - lo) / (hi - lo))
  return {
    line: ps.map((p, i) => `${x(i).toFixed(1)},${y(p).toFixed(1)}`).join(' '),
    lowerY: y(lower).toFixed(1),
    baseY: base != null ? y(base).toFixed(1) : null,
    t0: s[0].t, t1: s[s.length - 1].t,
  }
})

// CH4 峰值即時預測。目標訊號（CH4）本身只有排氣瞬間有效、樣本又少，
// 故一律連同 n_train / cv_rmse / 可靠度一起顯示，狀態非 ok 時不顯示數字。
const ch4 = ref(null)
const PHASE_META = {
  1: { label: 'Phase 1 底物利用期', color: '#e74c3c' },
  2: { label: 'Phase 2 產甲烷活躍期', color: '#2ecc71' },
  3: { label: 'Phase 3 底物耗盡期', color: '#e67e22' },
}
// 特徵的中文說明，讓重要度圖不必看程式碼也讀得懂
const FEATURE_LABEL = {
  cycle_length_min:      '週期長度',
  phase2_duration_min:   'Phase2 時長',
  phase2_fraction:       'Phase2 佔比',
  phase1_mean_slope:     'Phase1 平均 ORP 斜率',
  phase2_orp_mean:       'Phase2 ORP 均值',
  phase2_orp_std:        'Phase2 ORP 標準差',
  phase2_macd_mean:      'Phase2 MACD 均值',
  orp_drop_magnitude:    'ORP 崩落幅度',
  phase3_onset_fraction: 'Phase3 起始位置',
  pressure_mean:         '壓力均值',
  ph_mean:               'pH 均值',
}
async function loadCh4() {
  try {
    const { data } = await apiClient.get('/ch4_prediction')
    ch4.value = data
  } catch { ch4.value = null }
}

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

// 排氣：開啟時間編輯列（預設當下，可人工改成實際排氣時刻或往後抓峰值）
function openVent(r) {
  editRow.value = r.run_id
  editForm.value = { start_time: toLocal(r.start_time), end_time: nowLocal(), _vent: true }
}
async function confirmVent(r) {
  try {
    // 若同時改了起始時間，先存起來
    if (editForm.value.start_time && editForm.value.start_time !== toLocal(r.start_time)) {
      await apiClient.patch(`/experiment/runs/${r.run_id}`, { start_time: editForm.value.start_time })
    }
    await apiClient.post(`/experiment/runs/${r.run_id}/vent`, { at: editForm.value.end_time || null })
    editRow.value = null
    flash(`批次 ${r.run_id} 已排氣（結束時間 ${editForm.value.end_time.replace('T',' ')}），量測結果已計算`)
    await loadRuns()
  } catch (e) { flash(e.response?.data?.detail || '排氣失敗') }
}

// 編輯起訖時間（事後修正，可對齊 CSV 時間）
function openEdit(r) {
  editRow.value = r.run_id
  editForm.value = { start_time: toLocal(r.start_time), end_time: toLocal(r.end_time), _vent: false }
}
async function saveEdit(r) {
  try {
    await apiClient.patch(`/experiment/runs/${r.run_id}`, {
      start_time: editForm.value.start_time || null,
      end_time: editForm.value.end_time || null,
    })
    editRow.value = null
    flash(`批次 ${r.run_id} 時間已更新，量測結果已重算`)
    await loadRuns()
  } catch (e) { flash(e.response?.data?.detail || '更新失敗') }
}
function cancelEdit() { editRow.value = null }

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

// level: 'runs'（批次彙整）或 'cycles'（每循環特徵，餵模型用）
async function exportReport(f, level = 'runs') {
  const path = level === 'cycles' ? '/experiment/export/cycles' : '/experiment/export'
  const name = level === 'cycles' ? 'experiment_cycles' : 'experiment_report'
  try {
    const resp = await apiClient.get(`${path}?fmt=${f}`, { responseType: 'blob', timeout: 15000 })
    const url = URL.createObjectURL(new Blob([resp.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = `${name}_${new Date().toISOString().slice(0,16).replace(/[-:T]/g,'')}.${f}`
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
    flash(`已匯出 ${level === 'cycles' ? '每循環' : '批次'} ${f.toUpperCase()}`)
  } catch (e) { flash('匯出失敗：' + (e.message || '')) }
}

onMounted(() => {
  loadRuns(); loadCh4()
  pollTimer = setInterval(() => { loadRuns(); loadCh4() }, 15000)
})
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
        <div class="exp-group">
          <span class="eg-label">批次彙整</span>
          <button class="btn btn-ghost" @click="exportReport('xlsx','runs')">Excel</button>
          <button class="btn btn-ghost" @click="exportReport('csv','runs')">CSV</button>
        </div>
        <div class="exp-group">
          <span class="eg-label">每循環（餵模型）</span>
          <button class="btn btn-ghost" @click="exportReport('xlsx','cycles')">Excel</button>
          <button class="btn btn-ghost" @click="exportReport('csv','cycles')">CSV</button>
        </div>
      </div>
    </header>

    <div v-if="msg" class="toast">{{ msg }}</div>
    <div v-if="error" class="toast err">{{ error }}</div>

    <!-- 進行中批次即時面板 -->
    <div v-if="live" class="live-panel" :class="{ 'panel-stale': live.stale }">
      <div class="live-title">
        <span class="dot" :class="{ dead: live.stale }"></span> 進行中：批次 {{ runningRun.run_id }}
        <span class="live-sub">循環 {{ runningRun.n_minutes }} 分／小時 · 已完成 {{ live.n_cycles_so_far }} 次補氣</span>
      </div>

      <!-- 記錄健康度：昨天記錄死掉 17.5hr 無告警，此列即為防呆 -->
      <div class="rec-health" :class="live.stale ? 'rh-bad' : (live.n_gaps ? 'rh-warn' : 'rh-ok')">
        <template v-if="live.stale">
          ⛔ 記錄可能已中斷：最後一筆在 <b>{{ live.staleness_min }}</b> 分鐘前（{{ live.last_timestamp?.slice(5,16) }}）。反應器仍在運轉，請檢查記錄程式。
        </template>
        <template v-else>
          ✓ 記錄正常，最後一筆 {{ live.staleness_min }} 分前
        </template>
        <span v-if="live.n_gaps" class="rh-gap">· 本批次已中斷 {{ live.n_gaps }} 次／{{ live.gap_hours }}hr</span>
        <span v-if="live.clock_skew" class="rh-gap">· ⚠ 記錄端時鐘與本機不同步</span>
      </div>

      <div class="live-grid">
        <div class="live-cell">
          <span class="lv">{{ fmt(live.current_pressure) }}</span>
          <span class="ll">目前壓力 kg/cm²
            <b v-if="live.pressure_vs_base != null" class="ref">基準{{ live.pressure_vs_base >= 0 ? '+' : '' }}{{ fmt(live.pressure_vs_base) }}</b>
          </span>
        </div>
        <div class="live-cell">
          <span class="lv">{{ fmt(live.current_orp, 0) }}</span>
          <span class="ll">目前 ORP mV
            <b v-if="live.orp_vs_pre != null" class="ref">進氣前{{ live.orp_vs_pre >= 0 ? '+' : '' }}{{ fmt(live.orp_vs_pre, 0) }}</b>
          </span>
        </div>
        <div class="live-cell">
          <span class="lv" :class="{ ready: live.remaining_kg <= 0 }">
            {{ live.remaining_kg <= 0 ? '即將補氣' : live.eta_refill_hours + ' hr' }}
          </span>
          <span class="ll">距下次補氣（降到 {{ live.intake_lower }}）
            <b class="ref">{{ live.rate_is_live ? '實測速率' : '預估速率' }}</b>
          </span>
        </div>
        <div class="live-cell">
          <span class="lv">{{ fmt(live.elapsed_hours, 1) }} <small>/ {{ live.target_hours }}</small></span>
          <span class="ll">實驗已跑 / 預計 hr</span>
        </div>
      </div>

      <!-- 本循環即時壓力曲線 + 臨時平緩化（觀測用，未結束不進建模）-->
      <div class="live-chart" v-if="liveChart">
        <div class="lc-head">
          <span>本循環壓力曲線</span>
          <span class="lc-slopes">
            早段 {{ fmt(live.cycle_slope_early, 4) }} · 晚段 {{ fmt(live.cycle_slope_late, 4) }} ·
            <b class="flat" :class="{ 'flat-pos': live.cycle_flattening > 0.0005 }">
              平緩化 {{ fmt(live.cycle_flattening, 4) }}
            </b>
            <span class="lc-prov">（進行中·臨時值）</span>
          </span>
        </div>
        <svg :viewBox="`0 0 ${W} ${H}`" class="lc-svg" preserveAspectRatio="none">
          <line v-if="liveChart.baseY" x1="0" :y1="liveChart.baseY" :x2="W" :y2="liveChart.baseY" class="lc-base" />
          <line x1="0" :y1="liveChart.lowerY" :x2="W" :y2="liveChart.lowerY" class="lc-lower" />
          <polyline :points="liveChart.line" class="lc-line" />
        </svg>
        <div class="lc-axis"><span>{{ liveChart.t0 }}</span><span class="lc-lbl">— 下限補氣線 ·· 基準線</span><span>{{ liveChart.t1 }}</span></div>
      </div>
    </div>

    <!-- CH4 峰值即時預測 -->
    <div v-if="ch4" class="ch4-panel">
      <div class="ch4-head">
        <span class="ch4-title">CH4 排氣峰值 · 即時預測</span>
        <span v-if="ch4.current_phase" class="phase-tag"
              :style="{ color: PHASE_META[ch4.current_phase]?.color, borderColor: PHASE_META[ch4.current_phase]?.color }">
          {{ PHASE_META[ch4.current_phase]?.label }}
        </span>
      </div>

      <div class="ch4-body">
        <!-- 只有 status=ok 才顯示數字。其餘狀態一律顯示原因，不顯示可能誤導的值 -->
        <div class="ch4-main">
          <template v-if="ch4.status === 'ok'">
            <span class="ch4-val">{{ fmt(ch4.predicted_peak, 1) }}<small>%</small></span>
            <span class="ch4-sub">預測峰值 · ±{{ fmt(ch4.cv_rmse, 1) }} (LOO-CV RMSE)</span>
          </template>
          <template v-else>
            <span class="ch4-na">—</span>
            <span class="ch4-sub">尚不提供預測值</span>
          </template>
        </div>

        <div class="ch4-meta">
          <div><b>{{ ch4.n_train }}</b> 個已完成排氣週期（訓練樣本）</div>
          <div v-if="ch4.cycle_progress !== null">
            本週期進度 <b>{{ (ch4.cycle_progress * 100).toFixed(0) }}%</b>
          </div>
          <div class="ch4-why" :class="ch4.status === 'ok' ? 'w-warn' : 'w-block'">
            {{ ch4.reliability }}
          </div>
        </div>
      </div>

      <!-- GA 特徵選擇 + Ridge 特徵重要度（即時計算）-->
      <div v-if="ch4.feature_selection && !ch4.feature_selection.error" class="fi-block">
        <div class="fi-head">
          <span class="fi-title">特徵重要度</span>
          <span class="fi-meta">
            GA 自 {{ ch4.feature_selection.n_total }} 個特徵選出
            <b>{{ ch4.feature_selection.n_selected }}</b> 個 ·
            LOO-CV RMSE <b>{{ ch4.feature_selection.rmse_selected }}</b>
            <span class="fi-base">（全特徵 {{ ch4.feature_selection.rmse_all }}）</span>
          </span>
          <!-- ≥2 序列必須有圖例；顏色不單獨承載意義，數值另以正負號標示 -->
          <span class="fi-legend">
            <i class="sw sw-pos"></i>正向
            <i class="sw sw-neg"></i>負向
          </span>
        </div>

        <div class="fi-rows">
          <div v-for="f in ch4.feature_selection.importances" :key="f.feature" class="fi-row"
               :title="`${FEATURE_LABEL[f.feature] || f.feature}：權重 ${(f.weight*100).toFixed(1)}%，標準化係數 ${f.coef}`">
            <span class="fi-label">{{ FEATURE_LABEL[f.feature] || f.feature }}</span>
            <span class="fi-track">
              <span class="fi-bar" :class="f.coef >= 0 ? 'bar-pos' : 'bar-neg'"
                    :style="{ width: Math.max(f.weight * 100, 1.5) + '%' }"></span>
            </span>
            <span class="fi-val">
              {{ (f.weight * 100).toFixed(1) }}%
              <span class="fi-coef">{{ f.coef >= 0 ? '+' : '' }}{{ f.coef }}</span>
            </span>
          </div>
        </div>
        <div class="fi-note">
          權重＝|標準化 Ridge 係數| 佔比；符號表示該特徵推高（+）或壓低（−）CH4 峰值。
          <b>樣本 {{ ch4.n_train }} 週期下，特徵選擇本身即有選擇偏差，排序僅供探索。</b>
        </div>
      </div>

      <div v-if="ch4.history?.length" class="ch4-hist">
        <span class="hist-label">歷次排氣（實際 → 樣本內配適）</span>
        <span v-for="h in ch4.history.slice(-6)" :key="h.vent_time" class="hist-item">
          {{ h.vent_time.slice(5, 10) }}
          <b>{{ h.actual_peak }}</b><span class="hist-fit">/{{ h.fitted }}</span>
        </span>
      </div>

      <div class="ch4-caveat">⚠ {{ ch4.caveat }}</div>
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
      <label class="sched">開始時間（可填過去，抓既有資料）
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
            <th class="grp">離散度<br><small>IQR·範圍</small></th>
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
              <td class="mono">
                <template v-if="r.results.n_cycles">{{ r.results.n_cycles_complete }}/{{ r.results.n_cycles }}</template>
                <template v-else>—</template>
                <div v-if="r.results.n_gaps" class="gap-warn" :title="`記錄中斷 ${r.results.n_gaps} 次，合計 ${r.results.gap_hours} 小時。反應器仍在運轉，僅資料未記錄。`">
                  ⚠ 中斷 {{ r.results.n_gaps }} 次／{{ r.results.gap_hours }}hr
                </div>
              </td>
              <td class="mono hl">{{ fmt(r.results.drop_rate_median, 5) }}</td>
              <td class="mono dim sm">
                <template v-if="r.results.drop_rate_iqr != null">IQR {{ fmt(r.results.drop_rate_iqr, 4) }}<br>{{ fmt(r.results.drop_rate_min, 4) }}–{{ fmt(r.results.drop_rate_max, 4) }}</template>
                <template v-else-if="r.results.drop_rate_min != null">n=1</template>
                <template v-else>—</template>
              </td>
              <td class="mono cov">{{ fmt(r.results.culture_drift, 1) }}</td>
              <td class="mono">{{ fmt(r.results.vent_ph, 2) }}</td>
              <td class="mono">{{ fmt(r.results.vent_orp, 0) }}</td>
              <td class="ops">
                <button v-if="r.status === 'planned'" class="op op-start" @click="startRun(r)">開始</button>
                <button v-if="r.status === 'running'" class="op op-vent" @click="openVent(r)">排氣</button>
                <button v-if="r.status !== 'planned'" class="op op-edit" @click="openEdit(r)" title="編輯起訖時間">編輯</button>
                <button class="op op-del" @click="deleteRun(r)">刪</button>
              </td>
            </tr>
            <!-- 排氣 / 編輯時間列（人工輸入，可修改） -->
            <tr v-if="editRow === r.run_id" class="detail-row">
              <td colspan="14">
                <div class="time-edit">
                  <span class="te-title">{{ editForm._vent ? '排氣時間（可改成實際排氣時刻，往後幾分鐘可抓 CH4 峰值）' : '編輯起訖時間（可對齊 CSV）' }}</span>
                  <label>開始 <input v-model="editForm.start_time" type="datetime-local" class="inp" /></label>
                  <label>結束 <input v-model="editForm.end_time" type="datetime-local" class="inp" /></label>
                  <button v-if="editForm._vent" class="btn-sm ok" @click="confirmVent(r)">確定排氣</button>
                  <button v-else class="btn-sm ok" @click="saveEdit(r)">儲存</button>
                  <button class="btn-sm cancel" @click="cancelEdit">取消</button>
                </div>
              </td>
            </tr>
            <!-- 每循環明細 -->
            <tr v-if="expanded === r.run_id" class="detail-row">
              <td colspan="14">
                <div class="cycle-detail">
                  <div class="cd-title">每循環特徵（{{ r.run_id }}）— 進氣前 ORP 為菌群成熟度共變數</div>
                  <table v-if="cyclesMap[r.run_id]?.length" class="cycle-table">
                    <thead><tr><th>週期</th><th>起</th><th>時長hr</th><th>P起→P末</th><th>下降速率</th><th>早段</th><th>晚段</th><th>平緩化</th><th>進氣前ORP</th><th>ORP崩落</th><th>完整性</th></tr></thead>
                    <tbody>
                      <tr v-for="cy in cyclesMap[r.run_id]" :key="cy.cycle" :class="{ 'row-partial': !cy.complete }">
                        <td>{{ cy.cycle }}</td>
                        <td class="mono dim">{{ cy.start.slice(5) }}</td>
                        <td class="mono">{{ cy.duration_hr }}</td>
                        <td class="mono">{{ cy.pressure_start }}→{{ cy.pressure_end }}</td>
                        <td class="mono hl">{{ fmt(cy.drop_rate, 5) }}</td>
                        <td class="mono dim">{{ fmt(cy.slope_early, 4) }}</td>
                        <td class="mono dim">{{ fmt(cy.slope_late, 4) }}</td>
                        <td class="mono flat">{{ fmt(cy.flattening, 4) }}</td>
                        <td class="mono cov">{{ fmt(cy.pre_injection_orp, 1) }}</td>
                        <td class="mono">{{ fmt(cy.orp_crash, 1) }}</td>
                        <td><span class="q-tag" :class="cy.complete ? 'q-ok' : 'q-bad'">{{ cy.quality }}</span></td>
                      </tr>
                    </tbody>
                  </table>
                  <div v-else class="cd-empty">尚無循環（實驗未開始或資料不足）。</div>
                </div>
              </td>
            </tr>
          </template>
          <tr v-if="!runs.length"><td colspan="14" class="empty">尚無批次。點「建立標準計畫」開始。</td></tr>
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
.header-actions { display: flex; gap: 16px; align-items: flex-end; }
.exp-group { display: flex; align-items: center; gap: 5px; }
.exp-group .btn { padding: 5px 12px; }
.eg-label { font-size: 0.68rem; color: #556; margin-right: 2px; }

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
.ll .ref { color: #7a90a4; font-weight: 700; margin-left: 4px; }

/* 記錄健康度告警列 */
.panel-stale { border-color: #7a2a2a; background: #1a1012; }
.dot.dead { background: #e05a5a; animation: none; }
.rec-health { font-size: 0.76rem; padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; line-height: 1.5; }
.rh-ok { color: #6aa88a; background: #0d1a14; }
.rh-warn { color: #d0a24a; background: #1c1710; }
.rh-bad { color: #f0a0a0; background: #241012; border: 1px solid #7a2a2a; font-weight: 600; }
.rh-gap { color: #b0763a; margin-left: 4px; }

/* 本循環即時壓力曲線 */
.live-chart { margin-top: 12px; background: #0b131c; border: 1px solid #16242f; border-radius: 6px; padding: 10px 12px; }
.lc-head { display: flex; justify-content: space-between; align-items: baseline; font-size: 0.72rem; color: #6a8296; margin-bottom: 6px; flex-wrap: wrap; gap: 4px; }
.lc-slopes { font-family: monospace; color: #7a90a4; }
.lc-slopes .flat { color: #9b8ad4; }
.lc-slopes .flat.flat-pos { color: #b89ae8; }
.lc-prov { color: #4a5a68; font-family: inherit; }
.lc-svg { width: 100%; height: 96px; display: block; }
.lc-line { fill: none; stroke: #4fa8e8; stroke-width: 1.6; vector-effect: non-scaling-stroke; }
.lc-lower { stroke: #c85a5a; stroke-width: 1; stroke-dasharray: 5 3; vector-effect: non-scaling-stroke; }
.lc-base { stroke: #4a6a4a; stroke-width: 1; stroke-dasharray: 2 3; vector-effect: non-scaling-stroke; }
.lc-axis { display: flex; justify-content: space-between; font-size: 0.62rem; color: #4a5a68; margin-top: 3px; font-family: monospace; }
.lc-axis .lc-lbl { font-family: inherit; }
.sm { font-size: 0.68rem; line-height: 1.3; }

/* CH4 峰值即時預測 */
.ch4-panel { background: #16121c; border: 1px solid #2e2440; border-radius: 8px;
  padding: 1rem 1.25rem; margin-bottom: 1.25rem; }
.ch4-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.ch4-title { font-size: 0.95rem; font-weight: 700; color: #b89ae8; }
.phase-tag { font-size: 0.68rem; padding: 2px 8px; border: 1px solid; border-radius: 10px; }
.ch4-body { display: flex; gap: 1.5rem; align-items: flex-start; flex-wrap: wrap; }
.ch4-main { display: flex; flex-direction: column; min-width: 190px; }
/* hero 數字用比例字：等寬數字在大字級下會顯得鬆散（見 dataviz anti-patterns）。
   下方 .fi-val 則保留等寬，因為那些數字是逐列垂直對齊的表格值 */
.ch4-val { font-size: 2rem; font-weight: 700; color: #d8c8f0; line-height: 1.1;
  font-variant-numeric: proportional-nums; }
.ch4-val small { font-size: 0.9rem; color: #7a6a94; margin-left: 2px; }
.ch4-na { font-size: 2rem; font-weight: 700; color: #4a4458; line-height: 1.1; }
.ch4-sub { font-size: 0.66rem; color: #6a5f80; margin-top: 4px; }
.ch4-meta { flex: 1; min-width: 240px; font-size: 0.72rem; color: #8a7fa0; line-height: 1.7; }
.ch4-meta b { color: #c8b8e0; }
.ch4-why { margin-top: 4px; padding: 5px 9px; border-radius: 5px; line-height: 1.5; }
.w-warn { background: #1e1810; color: #d0a24a; }
.w-block { background: #241820; color: #c88aa8; }
.ch4-hist { margin-top: 10px; padding-top: 9px; border-top: 1px solid #241c30;
  font-size: 0.68rem; color: #6a5f80; display: flex; gap: 10px; flex-wrap: wrap; align-items: baseline; }
.hist-label { color: #55495f; }
.hist-item { font-family: monospace; }
.hist-item b { color: #b8a8d0; }
.hist-fit { color: #55495f; }
.ch4-caveat { margin-top: 8px; font-size: 0.64rem; color: #6a5a5a; line-height: 1.5; }

/* 特徵重要度：發散配色（正/負），已用 dataviz validator 對本面板底色 #16121c
   驗過 CVD ΔE 23.6 / normal 31.9 / 對比 ≥3:1，全數通過 */
.fi-block { margin-top: 12px; padding-top: 10px; border-top: 1px solid #241c30; }
.fi-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.fi-title { font-size: 0.78rem; font-weight: 700; color: #b8a8d0; }
.fi-meta { font-size: 0.68rem; color: #7a6f8c; }
.fi-meta b { color: #c8b8e0; }
.fi-base { color: #55495f; }
.fi-legend { margin-left: auto; font-size: 0.66rem; color: #7a6f8c; display: flex;
  align-items: center; gap: 5px; }
.sw { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
.sw-pos { background: #3987e5; }
.sw-neg { background: #e34948; margin-left: 6px; }

.fi-rows { display: flex; flex-direction: column; gap: 2px; }   /* 2px 條間留白 */
.fi-row { display: flex; align-items: center; gap: 9px; padding: 1px 0; }
.fi-row:hover { background: #1b1622; }
.fi-label { flex: 0 0 150px; font-size: 0.68rem; color: #9a8fb0; text-align: right; }
.fi-track { flex: 1; height: 13px; background: #201a2a; border-radius: 2px; overflow: hidden; }
.fi-bar { display: block; height: 100%; border-radius: 0 4px 4px 0; }  /* 資料端圓角 4px */
.bar-pos { background: #3987e5; }
.bar-neg { background: #e34948; }
.fi-val { flex: 0 0 110px; font-size: 0.68rem; font-family: monospace; color: #c8b8e0; }
.fi-coef { color: #6a5f80; margin-left: 4px; }
.fi-note { margin-top: 7px; font-size: 0.63rem; color: #6a5f80; line-height: 1.55; }
.fi-note b { color: #a08a70; }

@media (max-width: 700px) {
  .fi-label { flex-basis: 96px; }
  .fi-val { flex-basis: 84px; }
}

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
.flat { color: #9b8ad4; font-weight: 700; }
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

/* 資料完整性：非完整週期不進入統計與建模，需一眼看得出來 */
.gap-warn { font-size: 0.62rem; color: #e08c4a; margin-top: 3px; white-space: nowrap; cursor: help; }
.row-partial { background: rgba(224,140,74,0.05); }
.q-tag { font-size: 0.64rem; padding: 2px 6px; border: 1px solid; border-radius: 8px; white-space: nowrap; }
.q-ok { color: #4caf82; border-color: #2d5f49; }
.q-bad { color: #e08c4a; border-color: #6b4526; }

.ops { display: flex; gap: 4px; justify-content: center; }
.op { font-family: inherit; font-size: 0.7rem; padding: 4px 8px; border-radius: 4px; cursor: pointer;
  border: 1px solid #2a2a2a; background: #161616; color: #999; }
.op-start { border-color: #2c5a7a; color: #6cb6e8; }
.op-vent { border-color: #7a5a2c; color: #e0a860; }
.op-edit { border-color: #3a3a3a; color: #999; }
.op-del { border-color: #5a2c2c; color: #c07070; }
.op:hover { filter: brightness(1.3); }

/* 時間編輯列 */
.time-edit { padding: 12px 20px; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; background: #0a0f14; }
.te-title { font-size: 0.78rem; color: #e0a860; font-weight: 600; }
.time-edit label { font-size: 0.76rem; color: #778; display: flex; align-items: center; gap: 5px; }
.btn-sm { font-family: inherit; font-size: 0.76rem; padding: 5px 14px; border-radius: 4px; cursor: pointer; border: 1px solid; }
.btn-sm.ok { background: rgba(46,204,113,0.12); border-color: #2c7a4a; color: #7fe0a3; }
.btn-sm.cancel { background: #161616; border-color: #333; color: #888; }
.btn-sm:hover { filter: brightness(1.25); }

.footnote { font-size: 0.72rem; color: #667; margin-top: 1rem; line-height: 1.7; }

@media (max-width: 760px) { .live-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
