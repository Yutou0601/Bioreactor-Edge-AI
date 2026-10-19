<script setup>
// 實驗排程：Jetson 上研究腳本的佇列（後端 core/research_jobs.py）。
//
// 一次只跑一個；排在後面的可以改參數、調順序、暫緩、取消。已開始的不能改參數
// （改了也不會生效），要改就「複製」一份——複製出來的先暫緩，改好再按恢復。
// ⚠ 只能跑白名單裡的腳本，表單欄位由後端的參數表產生；檢查也在後端做。
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import api from '../services/apiClient'

const tpls = ref([])
const st = ref({ paused: false, active: [], history: [] })
const err = ref('')
const busy = ref(false)
const logJob = ref(null)
const logText = ref('')
const logEl = ref(null)
const followLog = ref(true)

// 表單：新增或編輯（editId 有值＝編輯那一筆）
const form = ref({ template: '', name: '', note: '', hold: false, params: {} })
const editId = ref(null)

const tplMap = computed(() => Object.fromEntries(tpls.value.map(t => [t.id, t])))
const curTpl = computed(() => tplMap.value[form.value.template])
const running = computed(() => st.value.active.find(j => j.status === 'running'))
const queue = computed(() => st.value.active.filter(j => j.status !== 'running'))

const STATUS = { queued: '排隊中', held: '暫緩', running: '執行中', done: '完成', error: '失敗', cancelled: '已取消' }

function defaults(t) {
  return Object.fromEntries(Object.entries(t.params).map(([k, s]) => [k, s.default]))
}
function resetForm(tid) {
  const t = tplMap.value[tid] || tpls.value[0]
  if (!t) return
  editId.value = null
  form.value = { template: t.id, name: '', note: '', hold: false, params: defaults(t) }
}
watch(() => form.value.template, (tid, old) => {
  if (old && tid !== old && !editId.value && tplMap.value[tid]) form.value.params = defaults(tplMap.value[tid])
})

// 只列跟預設不同的參數，表格才看得出這筆跟別筆差在哪
function diffParams(j) {
  const t = tplMap.value[j.template]
  if (!t) return JSON.stringify(j.params)
  const d = Object.entries(j.params).filter(([k, v]) => t.params[k] && v !== t.params[k].default)
  return d.length ? d.map(([k, v]) => `${k}=${v === true ? '是' : v === false ? '否' : v}`).join('  ') : '（全部預設）'
}
function dur(sec) {
  if (sec == null) return '—'
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60
  return h ? `${h} 時 ${m} 分` : m ? `${m} 分 ${s} 秒` : `${s} 秒`
}
function span(j) {
  if (!j.started || !j.finished) return '—'
  return dur(Math.round((new Date(j.finished.replace(' ', 'T')) - new Date(j.started.replace(' ', 'T'))) / 1000))
}
const hhmm = t => (t ? t.slice(5, 16) : '—')
const r2 = v => (v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2))

// NPE 的結果摘要：先驗 A 的 R² 與「每一折都通過校準」
function summaryText(j) {
  const s = j.summary
  if (!s) return ''
  if (s.A && s.passed_all_folds) {
    const a = ['bio', 'leak', 'diss'].map(k => `${k} ${r2(s.A[k]?.r2)}`).join('／')
    const p = Object.entries(s.passed_all_folds).map(([k, v]) => `${k}${v ? '✓' : '✗'}`).join(' ')
    return `R²(A) ${a}　校準 ${p}`
  }
  return JSON.stringify(s).slice(0, 120)
}

async function load() {
  try {
    st.value = (await api.get('/research_jobs')).data
    err.value = ''
  } catch (e) {
    err.value = e.response?.data?.detail || e.message
  }
  if (logJob.value) await loadLog()
}
async function loadLog() {
  try {
    const r = (await api.get(`/research_jobs/${logJob.value}/log`)).data
    logText.value = r.text
    if (followLog.value && logEl.value) requestAnimationFrame(() => { logEl.value.scrollTop = logEl.value.scrollHeight })
  } catch { logText.value = '（讀不到紀錄）' }
}
function showLog(id) { logJob.value = id; followLog.value = true; loadLog() }

async function act(fn) {
  busy.value = true; err.value = ''
  try { await fn(); await load() } catch (e) {
    err.value = e.response?.data?.detail || e.message
  } finally { busy.value = false }
}
const doAction = (j, a) => act(async () => {
  if (a === 'cancel' && !confirm(`取消 #${j.id}「${j.name}」？${j.status === 'running' ? '\n執行中的會被終止，已算的結果不會寫出。' : ''}`)) return
  await api.post(`/research_jobs/${j.id}/${a}`)
})
const doDelete = j => act(async () => {
  if (!confirm(`從清單刪除 #${j.id}「${j.name}」？（紀錄檔與輸出資料夾會留著）`)) return
  await api.delete(`/research_jobs/${j.id}`)
  if (logJob.value === j.id) logJob.value = null
})
const queuePause = p => act(() => api.post(`/research_jobs/queue/${p ? 'pause' : 'resume'}`))

function startEdit(j) {
  editId.value = j.id
  form.value = { template: j.template, name: j.name, note: j.note || '', hold: false, params: { ...j.params } }
  document.getElementById('job-form')?.scrollIntoView({ behavior: 'smooth' })
}
const submit = () => act(async () => {
  const f = form.value
  if (editId.value) {
    await api.patch(`/research_jobs/${editId.value}`, { params: f.params, name: f.name, note: f.note })
  } else {
    await api.post('/research_jobs', { template: f.template, params: f.params, name: f.name, note: f.note, hold: f.hold })
  }
  resetForm(f.template)
})

// 只在頁面看得見時輪詢：分頁切走就停，省監控電腦與 Jetson
let timer = null
function poll() {
  clearInterval(timer); timer = null
  if (document.visibilityState === 'visible') timer = setInterval(load, 5000)
}
onMounted(async () => {
  try { tpls.value = (await api.get('/research_jobs/templates')).data } catch (e) { err.value = e.message }
  resetForm()
  await load()
  if (running.value) showLog(running.value.id)
  poll()
  document.addEventListener('visibilitychange', poll)
})
onBeforeUnmount(() => { clearInterval(timer); document.removeEventListener('visibilitychange', poll) })
</script>

<template>
  <div class="page">
    <div class="card">
      <h2>實驗排程 <small>Jetson 上的研究腳本，依序一次跑一個（GPU）</small></h2>
      <div class="qbar">
        <span :class="['dot', st.paused ? 'warn' : running ? 'run' : 'idle']"></span>
        <span v-if="st.paused">佇列已暫停：執行中的會跑完，但不會再啟動下一個</span>
        <span v-else-if="running">執行中：#{{ running.id }}，後面還有 {{ queue.filter(j => j.status === 'queued').length }} 個排隊</span>
        <span v-else-if="queue.some(j => j.status === 'queued')">即將啟動下一個…</span>
        <span v-else>閒置</span>
        <button class="btn sm" :disabled="busy" @click="queuePause(!st.paused)">{{ st.paused ? '恢復佇列' : '暫停佇列' }}</button>
      </div>
      <p v-if="err" class="msg warn">{{ err }}</p>
    </div>

    <div v-if="running" class="card running">
      <h2>執行中 <small>#{{ running.id }}　{{ running.label }}</small></h2>
      <div class="rgrid">
        <div><span class="k">名稱</span>{{ running.name }}</div>
        <div><span class="k">已跑</span>{{ dur(running.elapsed_sec) }}（{{ hhmm(running.started) }} 開始）</div>
        <div class="wide"><span class="k">進度</span>{{ running.progress || '（腳本還沒回報進度）' }}</div>
        <div class="wide"><span class="k">參數</span><code>{{ diffParams(running) }}</code></div>
        <div v-if="running.out_dir" class="wide"><span class="k">輸出</span><code>{{ running.out_dir }}</code></div>
      </div>
      <div class="actions">
        <button class="btn sm" @click="showLog(running.id)">看紀錄</button>
        <button class="btn sm danger" :disabled="busy" @click="doAction(running, 'cancel')">終止</button>
      </div>
    </div>

    <div class="card">
      <h2>佇列 <small>由上往下跑；暫緩的會被跳過</small></h2>
      <div v-if="!queue.length" class="hint">佇列是空的。用下面的表單加一個。</div>
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>順位</th><th class="l">#</th><th class="l">名稱</th><th class="l">與預設不同的參數</th><th class="l">狀態</th><th class="l">動作</th></tr></thead>
          <tbody>
            <tr v-for="(j, i) in queue" :key="j.id" :class="{ held: j.status === 'held', on: editId === j.id }">
              <td>{{ i + 1 }}</td>
              <td class="l">{{ j.id }}</td>
              <td class="l"><div>{{ j.name }}</div><small v-if="j.note" class="note">{{ j.note }}</small></td>
              <td class="l"><code>{{ diffParams(j) }}</code></td>
              <td :class="['l', j.status]">{{ STATUS[j.status] }}</td>
              <td class="l acts">
                <button class="btn xs" title="移到最前" :disabled="busy || i === 0" @click="doAction(j, 'top')">⤒</button>
                <button class="btn xs" title="往前" :disabled="busy || i === 0" @click="doAction(j, 'up')">↑</button>
                <button class="btn xs" title="往後" :disabled="busy || i === queue.length - 1" @click="doAction(j, 'down')">↓</button>
                <button v-if="j.status === 'queued'" class="btn xs" :disabled="busy" @click="doAction(j, 'hold')">暫緩</button>
                <button v-else class="btn xs" :disabled="busy" @click="doAction(j, 'resume')">恢復</button>
                <button class="btn xs" :disabled="busy" @click="startEdit(j)">編輯</button>
                <button class="btn xs" :disabled="busy" @click="doAction(j, 'clone')">複製</button>
                <button class="btn xs danger" :disabled="busy" @click="doAction(j, 'cancel')">取消</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div id="job-form" class="card">
      <h2>{{ editId ? `編輯 #${editId}` : '新增實驗' }}
        <small v-if="editId">只有還沒開始的能改參數</small></h2>
      <div class="formrow">
        <label>範本
          <select v-model="form.template" :disabled="!!editId">
            <option v-for="t in tpls" :key="t.id" :value="t.id">{{ t.label }}</option>
          </select>
        </label>
        <label>名稱 <input v-model="form.name" type="text" maxlength="80" :placeholder="curTpl?.label" class="wtext" /></label>
      </div>
      <p v-if="curTpl" class="hint">{{ curTpl.doc }}　<code>research/{{ curTpl.script }}</code></p>
      <div v-if="curTpl" class="pgrid">
        <label v-for="(s, k) in curTpl.params" :key="k" class="pf" :title="s.help">
          <span class="pk">{{ k }}<em v-if="form.params[k] !== s.default">＊</em></span>
          <select v-if="s.type === 'choice'" v-model="form.params[k]">
            <option v-for="c in s.choices" :key="c" :value="c">{{ c }}</option>
          </select>
          <input v-else-if="s.type === 'bool'" v-model="form.params[k]" type="checkbox" />
          <input v-else-if="s.type === 'int' || s.type === 'float'" v-model.number="form.params[k]" type="number"
                 :min="s.min" :max="s.max" :step="s.type === 'int' ? 1 : 'any'" />
          <input v-else v-model="form.params[k]" type="text" class="wshort" />
          <small>{{ s.help }}<template v-if="s.min != null">（{{ s.min }}–{{ s.max }}）</template></small>
        </label>
      </div>
      <div class="formrow" style="margin-top: 12px">
        <label class="grow">備註 <input v-model="form.note" type="text" maxlength="500" class="wtext grow" placeholder="為什麼跑這個、要比什麼" /></label>
        <label v-if="!editId"><input v-model="form.hold" type="checkbox" /> 加入後先暫緩</label>
        <button class="btn" :disabled="busy || !form.template" @click="submit">{{ editId ? '儲存修改' : '加入佇列' }}</button>
        <button class="btn" @click="resetForm(form.template)">{{ editId ? '放棄編輯' : '恢復預設' }}</button>
      </div>
      <p class="hint">＊＝與預設值不同。數值範圍後端會再檢查一次，超出會被擋下來並顯示原因。</p>
    </div>

    <div class="card">
      <h2>歷史 <small>最近 100 筆</small></h2>
      <div v-if="!st.history.length" class="hint">還沒有跑完的工作。</div>
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th class="l">#</th><th class="l">名稱</th><th class="l">狀態</th><th>開始</th><th>耗時</th><th class="l">結果／訊息</th><th class="l">動作</th></tr></thead>
          <tbody>
            <tr v-for="j in st.history" :key="j.id" :class="{ on: logJob === j.id }">
              <td class="l">{{ j.id }}</td>
              <td class="l"><div>{{ j.name }}</div><small class="note"><code>{{ diffParams(j) }}</code></small></td>
              <td :class="['l', j.status]">{{ STATUS[j.status] }}</td>
              <td>{{ hhmm(j.started) }}</td>
              <td>{{ span(j) }}</td>
              <td class="l res">{{ summaryText(j) || j.note || '' }}<div v-if="j.out_dir && j.status === 'done'" class="note"><code>{{ j.out_dir }}</code></div></td>
              <td class="l acts">
                <button class="btn xs" @click="showLog(j.id)">紀錄</button>
                <button class="btn xs" :disabled="busy" title="複製一份到佇列（先暫緩）" @click="doAction(j, 'clone')">重跑</button>
                <button class="btn xs" :disabled="busy" @click="doDelete(j)">刪除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="logJob" class="card">
      <h2>紀錄 #{{ logJob }} <small>最後 20 KB，每 5 秒更新</small>
        <label class="follow"><input v-model="followLog" type="checkbox" /> 自動捲到底</label>
        <button class="btn xs" @click="logJob = null">關閉</button></h2>
      <pre ref="logEl" class="log">{{ logText || '（空的）' }}</pre>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 16px; display: flex; flex-direction: column; gap: 16px; max-width: 1400px; margin: 0 auto; }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
h2 { font-size: 0.98rem; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
h2 small { font-weight: 400; color: var(--text-muted); font-size: 0.78rem; }
.qbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 0.88rem; color: var(--text-secondary); }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--text-muted); }
.dot.run { background: var(--good); } .dot.warn { background: var(--warning); }
.running { border-color: var(--series-1); }
.rgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 6px 20px; font-size: 0.86rem; color: var(--text-primary); }
.rgrid .wide { grid-column: 1 / -1; }
.k { color: var(--text-muted); margin-right: 10px; font-size: 0.8rem; }
.actions { display: flex; gap: 8px; margin-top: 12px; }
.formrow { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; font-size: 0.86rem; color: var(--text-secondary); }
.formrow label { display: flex; align-items: center; gap: 6px; }
.grow { flex: 1; min-width: 200px; }
select, input[type=number], input[type=text] { background: var(--surface-2); color: var(--text-primary); border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font: inherit; }
input[type=number] { width: 100px; }
.wtext { width: 260px; max-width: 100%; } .wshort { width: 100px; }
.pgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px 16px; margin-top: 12px; }
.pf { display: flex; flex-direction: column; gap: 4px; font-size: 0.84rem; }
.pf .pk { font-family: Consolas, monospace; color: var(--text-primary); }
.pf .pk em { color: var(--warning); font-style: normal; margin-left: 2px; }
.pf small { color: var(--text-muted); font-size: 0.74rem; line-height: 1.4; }
.pf input[type=checkbox] { align-self: flex-start; }
.btn { background: var(--surface-2); color: var(--text-primary); border: 1px solid var(--border); border-radius: 6px; padding: 7px 16px; font: inherit; cursor: pointer; }
.btn:disabled { opacity: 0.45; cursor: default; }
.btn.sm { padding: 3px 10px; font-size: 0.8rem; }
.btn.xs { padding: 2px 7px; font-size: 0.76rem; }
.btn.danger { color: var(--critical); }
.hint, .note { color: var(--text-muted); font-size: 0.78rem; line-height: 1.5; }
.hint { margin-top: 8px; }
.msg.warn { color: var(--critical); margin-top: 8px; font-size: 0.86rem; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; font-variant-numeric: tabular-nums; }
th, td { padding: 6px 8px; text-align: right; border-bottom: 1px solid var(--grid); vertical-align: top; }
th { color: var(--text-muted); font-weight: 500; white-space: nowrap; }
.l { text-align: left; }
tr.held td { opacity: 0.6; }
tr.on { background: var(--surface-2); }
td.done { color: var(--good); } td.error { color: var(--critical); } td.running, td.queued { color: var(--warning); } td.cancelled, td.held { color: var(--text-muted); }
td.acts { white-space: nowrap; }
td.acts .btn { margin-right: 3px; }
td.res { min-width: 240px; color: var(--text-secondary); }
code { font-family: Consolas, monospace; font-size: 0.78rem; color: var(--text-secondary); word-break: break-all; }
.follow { font-size: 0.78rem; font-weight: 400; color: var(--text-secondary); display: flex; align-items: center; gap: 4px; margin-left: auto; }
.log { background: var(--surface-2); padding: 10px; border-radius: 6px; font-size: 0.75rem; color: var(--text-secondary); overflow: auto; max-height: 420px; white-space: pre-wrap; word-break: break-all; }
</style>
