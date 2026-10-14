<script setup>
// 資料接收：上傳程式有沒有在送、每天收齊了沒有。
//
// ⚠ 兩種「延遲」都要看：
//   請求延遲＝多久沒收到上傳程式的請求（上傳程式或 USB 斷了）
//   資料延遲＝最新一筆資料距今多久（上傳程式活著，但記錄程式停了）
//   2026-07-22 記錄靜默中斷 17.5 小時就是後者——只看前者會一直是綠的。
import { ref, onMounted, onBeforeUnmount } from 'vue'
import api from '../services/apiClient'

const st = ref(null)
const days = ref([])
const health = ref(null)
const err = ref('')
let timer = null

const ago = s => (s == null ? '—' : s < 120 ? `${s} 秒` : s < 7200 ? `${Math.round(s / 60)} 分鐘` : `${(s / 3600).toFixed(1)} 小時`)
const level = s => (s == null ? 'muted' : s <= 300 ? 'good' : s <= 1800 ? 'warning' : 'critical')
const icon = { good: '✓', warning: '⚠', critical: '✕', muted: '○' }

async function load() {
  try {
    const [a, b, c] = await Promise.all([api.get('/ingest/status'), api.get('/days'), api.get('/health')])
    st.value = a.data; days.value = b.data; health.value = c.data; err.value = ''
  } catch (e) {
    err.value = `讀取失敗（${e.code || e.message}）`
  }
}
onMounted(() => { load(); timer = setInterval(() => { if (!document.hidden) load() }, 30000) })
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="wrap">
    <p v-if="err" class="msg warn">⚠ {{ err }}</p>

    <section class="card">
      <h2>上傳站台</h2>
      <div v-if="st?.stations?.length" class="table-wrap">
        <table>
          <thead><tr><th>站台</th><th>資料延遲</th><th>請求延遲</th><th>最後一筆</th><th>目前檔案</th><th>累計收到</th><th>新寫入</th></tr></thead>
          <tbody>
            <tr v-for="s in st.stations" :key="s.station">
              <td>{{ s.station }}</td>
              <td :class="level(s.data_lag_sec)">{{ icon[level(s.data_lag_sec)] }} {{ ago(s.data_lag_sec) }}</td>
              <td :class="level(s.lag_sec)">{{ icon[level(s.lag_sec)] }} {{ ago(s.lag_sec) }}</td>
              <td>{{ s.last_ts }}</td>
              <td>{{ s.file }}<span v-if="s.offset != null" class="muted"> @ {{ s.offset.toLocaleString() }} B</span></td>
              <td>{{ s.n_rows?.toLocaleString() }}</td>
              <td>{{ s.n_new?.toLocaleString() }}</td>
            </tr>
          </tbody>
        </table>
        <p class="note">
          資料延遲＝最新一筆距今多久（記錄程式停了會變大）；請求延遲＝多久沒收到上傳程式的請求（上傳程式或 USB 斷了會變大）。
          5 分鐘內 ✓、30 分鐘內 ⚠、超過 ✕。
        </p>
      </div>
      <p v-else class="msg">
        還沒有站台送過資料。在監控電腦的 edge_backend 下執行 <code>python monitor_uploader.py</code>，
        並確認兩台 .env 的 REACTOR_INGEST_TOKEN 相同。
      </p>
    </section>

    <section class="card">
      <h2>每日資料覆蓋率 <small>一分鐘一筆＝每天 1440 筆</small></h2>
      <div v-if="days.length" class="days">
        <div v-for="d in days" :key="d.day" class="day">
          <span class="d">{{ d.day }}</span>
          <span class="track"><span class="bar" :style="{ width: Math.min(100, d.coverage * 100) + '%' }"></span></span>
          <span class="v">{{ Math.round(d.coverage * 100) }}%</span>
          <span class="n muted">{{ d.n }} 筆 · {{ d.first_ts.slice(11, 16) }}–{{ d.last_ts.slice(11, 16) }}</span>
        </div>
      </div>
      <p v-else class="msg">資料庫裡還沒有資料。</p>
    </section>

    <section v-if="health" class="card">
      <h2>後端</h2>
      <p class="kv">已運行 <b>{{ health.uptime_min }}</b> 分鐘 · 記憶體中 <b>{{ health.record_count?.toLocaleString() }}</b> 筆
        <span v-if="health.last_timestamp"> · 最新 {{ health.last_timestamp }}</span></p>
    </section>
  </div>
</template>

<style scoped>
.wrap { padding: 16px; display: flex; flex-direction: column; gap: 16px; max-width: 1400px; margin: 0 auto; }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
h2 { font-size: 0.98rem; font-weight: 600; margin-bottom: 12px; }
h2 small { font-weight: 400; color: var(--text-muted); font-size: 0.78rem; margin-left: 8px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.84rem; font-variant-numeric: tabular-nums; }
th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { color: var(--text-muted); font-weight: 500; }
.good { color: var(--good); } .warning { color: var(--warning); } .critical { color: var(--critical); }
.muted { color: var(--text-muted); }
.note, .msg { color: var(--text-secondary); font-size: 0.8rem; margin-top: 8px; line-height: 1.5; }
.msg.warn { color: var(--warning); }
code { background: var(--surface-2); padding: 1px 5px; border-radius: 3px; }
.days { display: flex; flex-direction: column; gap: 6px; max-height: 420px; overflow-y: auto; }
.day { display: grid; grid-template-columns: 96px minmax(80px, 1fr) 44px auto; align-items: center; gap: 10px; font-size: 0.82rem; font-variant-numeric: tabular-nums; }
.track { height: 8px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }
.bar { display: block; height: 100%; background: var(--series-1); border-radius: 4px; }
.v { text-align: right; }
.kv { color: var(--text-secondary); font-size: 0.86rem; }
@media (max-width: 560px) { .day { grid-template-columns: 88px 1fr 40px; } .day .n { display: none; } }
</style>
