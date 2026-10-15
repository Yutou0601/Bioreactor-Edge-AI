<script setup>
/*
 * 分析模組 —— 泛用頁面。
 *
 * ⚠ 這一頁**刻意不認識任何一個模組**。它問後端要清單、要結果，用
 *   module.json 裡的 title 當標題，再依結果的形狀決定怎麼畫。
 *   所以新增一個分析模組不必改這裡、也不必重新 build 前端。
 *   一旦有人在這裡寫 `if (name === 'covariate')`，那個性質就沒了。
 *
 * ⚠ 三件必須顯示、不能省的事：
 *   1 結果的**計算時刻**。模組是排程跑的，不是即時算的——不標時間的話
 *     看的人會以為畫面上的數字是此刻的狀態。
 *   2 壞掉的模組要列出來並顯示原因。靜默隱藏的話，沒有人會發現某個
 *     分析其實已經幾個月沒更新了。
 *   3 上次執行**失敗**時要講出來。模組失敗時結果表不會更新，畫面上
 *     看起來只是「數字比較舊」，看不出已經壞了。
 */
import { ref, onMounted, computed } from 'vue'
import apiClient from '../services/apiClient'

const loading  = ref(true)
const error    = ref('')
const modules  = ref([])
const scheduler = ref(null)
const results  = ref({})        // name -> /result 的回應
const running  = ref({})        // name -> bool
const runMsg   = ref({})        // name -> 這次手動執行的結果訊息

async function loadList () {
  const { data } = await apiClient.get('/modules')
  modules.value  = data.modules || []
  scheduler.value = data.scheduler || null
}

async function loadResult (name) {
  try {
    const { data } = await apiClient.get(`/modules/${name}/result`)
    results.value = { ...results.value, [name]: data }
  } catch (e) {
    results.value = { ...results.value, [name]: { status: 'error' } }
  }
}

async function refresh () {
  loading.value = true
  error.value = ''
  try {
    await loadList()
    await Promise.all(modules.value.filter(m => m.ok).map(m => loadResult(m.name)))
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

async function runNow (m) {
  running.value = { ...running.value, [m.name]: true }
  runMsg.value  = { ...runMsg.value, [m.name]: '' }
  try {
    // ⚠ 這個端點是**同步**的：它等子行程跑完才回應，最久可到模組宣告的
    //   timeout_s（最慢的模組可達數分鐘）。apiClient 預設 8 秒會在模組還在算的
    //   時候就報逾時，畫面顯示失敗但後端其實跑得好好的。
    const budget = ((m.timeout_s || 300) + 15) * 1000
    const { data } = await apiClient.post(`/modules/${m.name}/run`, null,
                                          { timeout: budget })
    runMsg.value = {
      ...runMsg.value,
      [m.name]: data.ok ? `完成，耗時 ${data.seconds} 秒`
                        : `失敗（exit ${data.exit_code}）`,
    }
    await loadResult(m.name)
    await loadList()
  } catch (e) {
    const detail = e.response?.data?.detail
    runMsg.value = { ...runMsg.value, [m.name]: detail || e.message || String(e) }
  } finally {
    running.value = { ...running.value, [m.name]: false }
  }
}

/* 「多久以前」——絕對時刻看不出新鮮度，而新鮮度正是排程結果最該講的事。 */
function ago (iso) {
  if (!iso) return '—'
  const t = new Date(iso.replace(' ', 'T'))
  if (isNaN(t)) return iso
  const min = Math.floor((Date.now() - t.getTime()) / 60000)
  if (min < 1)   return '剛剛'
  if (min < 60)  return `${min} 分鐘前`
  const hr = Math.floor(min / 60)
  if (hr < 24)   return `${hr} 小時前`
  return `${Math.floor(hr / 24)} 天前`
}

function schedText (m) {
  const t = m.trigger || {}
  if (t.type === 'schedule' && t.every_minutes) {
    const n = t.every_minutes
    return n % 60 === 0 ? `每 ${n / 60} 小時` : `每 ${n} 分鐘`
  }
  return '手動'
}

/* 泛用渲染：把 payload 攤成「欄位 / 值」，巢狀的往下一層再攤。
 * 不猜圖表型別——猜錯比不畫更糟。要看細節的人可以展開原始 JSON。 */
function flatten (obj, prefix = '', out = []) {
  for (const [k, v] of Object.entries(obj || {})) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
      flatten(v, key, out)
    } else if (Array.isArray(v)) {
      out.push([key, v.length <= 6 ? JSON.stringify(v) : `[${v.length} 筆]`])
    } else {
      out.push([key, v === null ? '—' : String(v)])
    }
  }
  return out
}

const rows = computed(() => {
  const m = {}
  for (const [name, r] of Object.entries(results.value)) {
    m[name] = (r && r.status === 'ok') ? flatten(r.result?.payload) : []
  }
  return m
})

function resultOf (name) { return results.value[name] || null }

onMounted(refresh)
</script>

<template>
  <div class="wrap">
    <header class="head">
      <div>
        <h1>分析模組</h1>
        <p class="sub">
          每個模組是一個獨立的短命行程：讀資料、算完、寫回結果、結束。
          它們的相依（pandas、scipy…）不會留在常駐的監控程式裡。
        </p>
      </div>
      <button class="ghost" @click="refresh" :disabled="loading">重新整理</button>
    </header>

    <p v-if="scheduler" class="sched">
      排程 {{ scheduler.running ? '執行中' : '未啟動' }}
      ・每 {{ scheduler.poll_seconds }} 秒檢查
      ・{{ scheduler.n_modules }} 個模組
      <span v-if="scheduler.busy" class="busy">・目前有模組在執行</span>
    </p>

    <p v-if="loading" class="note">載入中…</p>
    <p v-else-if="error" class="err">讀取失敗：{{ error }}</p>
    <p v-else-if="!modules.length" class="note">
      還沒有任何模組。在 <code>edge_backend/modules/</code> 底下建一個資料夾，
      放 <code>module.json</code> 與 <code>run.py</code> 即可——核心與這一頁都不用改。
    </p>

    <section v-for="m in modules" :key="m.name" class="card"
             :class="{ broken: !m.ok }">
      <div class="card-head">
        <div>
          <h2>{{ m.title || m.name }}</h2>
          <p class="meta">
            <code>{{ m.name }}</code> v{{ m.version }}
            ・{{ schedText(m) }}
            <span v-if="m.requires?.length">・需要 {{ m.requires.join('、') }}</span>
          </p>
        </div>
        <button v-if="m.ok" class="run" :disabled="running[m.name]"
                @click="runNow(m)">
          {{ running[m.name] ? '執行中…' : '立即執行' }}
        </button>
      </div>

      <p v-if="m.description" class="desc">{{ m.description }}</p>

      <!-- 壞掉的模組：講清楚壞在哪，不要靜默隱藏 -->
      <p v-if="!m.ok" class="err">⚠ 無法載入：{{ m.error }}</p>

      <template v-else>
        <p v-if="runMsg[m.name]" class="runmsg">{{ runMsg[m.name] }}</p>

        <!-- 上次執行失敗要講出來：結果表不會更新，光看數字只會覺得「比較舊」 -->
        <p v-if="m.last_run && m.last_run.exit_code !== 0" class="err">
          ⚠ 上次執行失敗（exit {{ m.last_run.exit_code }}，{{ ago(m.last_run.finished) }}）。
          下面顯示的是**更早之前**成功那次的結果。
          <span class="log">{{ (m.last_run.log || '').slice(-300) }}</span>
        </p>

        <div v-if="resultOf(m.name)?.status === 'never_run'" class="note">
          尚未跑過。它會依排程自動更新，也可以按「立即執行」。
        </div>
        <div v-else-if="resultOf(m.name)?.status === 'ok'">
          <p class="stamp">
            計算於 {{ resultOf(m.name).result.computed_at }}
            （{{ ago(resultOf(m.name).result.computed_at) }}）
            ・模組版本 {{ resultOf(m.name).result.module_version }}
          </p>
          <table v-if="rows[m.name]?.length">
            <tbody>
              <tr v-for="([k, v]) in rows[m.name]" :key="k">
                <th>{{ k }}</th><td>{{ v }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="note">這次沒有輸出內容。</p>
        </div>
        <div v-else class="note">目前沒有結果可顯示。</div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.wrap { padding: 1.5rem; max-width: 1000px; margin: 0 auto; color: var(--text-primary); }
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
h1 { font-size: 1.1rem; color: var(--text-primary); font-weight: 600; }
.sub { font-size: 0.78rem; color: var(--text-muted); margin-top: 4px; max-width: 62ch; line-height: 1.6; }
.sched { font-size: 0.74rem; color: var(--text-muted); margin: 0.75rem 0 1rem; }
.busy { color: var(--warning); }
.card {
  border: 1px solid var(--border); border-radius: 6px; background: var(--surface-1);
  padding: 1rem 1.1rem; margin-bottom: 0.9rem;
}
.card.broken { border-color: var(--border); }
.card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
h2 { font-size: 0.92rem; color: var(--text-primary); font-weight: 600; }
.meta { font-size: 0.72rem; color: var(--text-muted); margin-top: 3px; }
.desc { font-size: 0.78rem; color: var(--text-secondary); margin-top: 0.5rem; line-height: 1.6; }
.stamp { font-size: 0.72rem; color: var(--text-muted); margin: 0.7rem 0 0.4rem; }
.runmsg { font-size: 0.74rem; color: var(--series-1); margin-top: 0.5rem; }
.note { font-size: 0.78rem; color: var(--text-muted); margin-top: 0.6rem; }
.err { font-size: 0.76rem; color: var(--series-2); margin-top: 0.6rem; line-height: 1.6; }
.log { display: block; color: var(--text-muted); font-size: 0.68rem; margin-top: 4px;
       white-space: pre-wrap; word-break: break-all; }
code { background: var(--surface-2); padding: 1px 5px; border-radius: 3px; font-size: 0.72rem; }
table { width: 100%; border-collapse: collapse; margin-top: 0.3rem; }
th, td { text-align: left; padding: 5px 8px; font-size: 0.76rem;
         border-bottom: 1px solid var(--border); }
th { color: var(--text-muted); font-weight: 400; width: 42%; }
td { color: var(--text-primary); font-variant-numeric: tabular-nums; }
button { font-family: inherit; cursor: pointer; border-radius: 4px;
         font-size: 0.75rem; padding: 5px 12px; transition: all 0.15s; }
.run { background: color-mix(in srgb, var(--series-1) 12%, transparent); color: var(--series-1); border: 1px solid var(--border); }
.run:hover:not(:disabled) { background: color-mix(in srgb, var(--series-1) 20%, transparent); }
.ghost { background: var(--surface-2); color: var(--text-secondary); border: 1px solid var(--border); }
.ghost:hover:not(:disabled) { color: var(--text-secondary); }
button:disabled { opacity: 0.5; cursor: default; }
</style>
