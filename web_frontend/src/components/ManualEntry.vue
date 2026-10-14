<script setup>
// 手動輸入一筆感測資料（從舊的即時監控頁搬來，欄位與 POST /api/records 相同）。
// 主要用途是補記：例如設備方在面板上抄下的讀數。正常資料流不經過這裡。
import { ref } from 'vue'
import api from '../services/apiClient'

const blank = () => ({ timestamp: '', orp: null, pressure: null, ph: null, temp: 30.0,
  mixer_pressure: null, co2_pct: 0, ch4_pct: 0, note: '' })
const form = ref(blank())
const busy = ref(false)
const msg = ref('')
const FIELDS = [
  ['orp', 'ORP', 'mV', 1], ['pressure', '反應槽壓力', 'kgf/cm²', 0.01], ['mixer_pressure', '混合槽壓力', 'kgf/cm²', 0.01],
  ['ph', 'pH', '', 0.01], ['temp', '溫度', '°C', 0.1], ['co2_pct', 'CO2', '%', 0.1], ['ch4_pct', 'CH4', '%', 0.1],
]

async function submit() {
  const f = form.value
  const missing = FIELDS.filter(([k]) => f[k] === null || f[k] === '').map(([, l]) => l)
  if (missing.length) { msg.value = `⚠ 請填：${missing.join('、')}`; return }
  busy.value = true
  try {
    const body = { ...f, orp_raw: f.orp, orp_cleaned: f.orp,
      timestamp: f.timestamp ? f.timestamp.replace('T', ' ') + (f.timestamp.length === 16 ? ':00' : '') : null,
      note: f.note || '手動輸入' }
    const r = await api.post('/records', body)
    msg.value = `✓ 已新增 ${r.data.timestamp}`
    form.value = blank()
  } catch (e) {
    msg.value = `✕ 新增失敗（${e.response?.data?.detail || e.code || e.message}）`
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="card">
    <h2>手動輸入一筆 <small>補記用；正常資料由上傳程式自動送進來</small></h2>
    <div class="grid">
      <label class="fg wide"><span>時間（留空＝現在）</span><input type="datetime-local" step="1" v-model="form.timestamp" /></label>
      <label v-for="[k, label, unit, step] in FIELDS" :key="k" class="fg">
        <span>{{ label }} <i v-if="unit">{{ unit }}</i></span>
        <input type="number" :step="step" v-model.number="form[k]" />
      </label>
      <label class="fg wide"><span>備註</span><input type="text" v-model="form.note" placeholder="事件說明、批次號…" /></label>
    </div>
    <div class="row">
      <button class="btn" @click="submit" :disabled="busy">{{ busy ? '新增中…' : '新增' }}</button>
      <span class="msg">{{ msg }}</span>
    </div>
  </section>
</template>

<style scoped>
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
h2 { font-size: 0.98rem; font-weight: 600; margin-bottom: 12px; }
h2 small { font-weight: 400; color: var(--text-muted); font-size: 0.78rem; margin-left: 8px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.fg { display: flex; flex-direction: column; gap: 4px; font-size: 0.8rem; color: var(--text-secondary); }
.fg i { font-style: normal; color: var(--text-muted); }
.fg.wide { grid-column: span 2; }
input { background: var(--surface-2); color: var(--text-primary); border: 1px solid var(--border); border-radius: 6px; padding: 7px 10px; font: inherit; min-width: 0; }
.row { display: flex; align-items: center; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
.btn { background: var(--surface-2); color: var(--text-primary); border: 1px solid var(--border); border-radius: 6px; padding: 7px 16px; font: inherit; cursor: pointer; }
.btn:disabled { opacity: 0.5; }
.msg { color: var(--text-secondary); font-size: 0.84rem; }
@media (max-width: 420px) { .fg.wide { grid-column: span 1; } }
</style>
