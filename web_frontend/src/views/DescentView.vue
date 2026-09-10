<script setup>
/*
 * 每段下降報表（2026-09-11 會議需求）
 * 丟 CSV → 每段的總下降、平均速率、斜率 → 化學計量反推 CO2/CH4
 *
 * ⚠ 三件必須顯示、不能省的事（都是會讓人看錯數字的）：
 *
 *   1 **要一次丟整個期間，不要一天一天丟。** 一天一檔，而循環中位長 7 小時、
 *     大多跨過午夜；逐檔處理會把跨日的一段攔腰砍斷，時長與振幅都錯，而且
 *     結果看起來完全正常。選檔案時預設就是多選。
 *
 *   2 **視窗太短時要把「量不到」標出來。** 感測器量化階 0.01 kgf/cm²，
 *     10 分鐘只掉約 0.005——實測六成的 10 分鐘視窗壓力一個數字都沒動。
 *     那種視窗若照常顯示「斜率 0」，看的人會以為反應停了。
 *
 *   3 **物理上不可能的份額不顯示數字，只顯示原因。** 份額 >100% 或負值
 *     代表輸入有誤（CH4 取到管路拖尾而不是排氣尖峰）。先看到數字再看到
 *     警語，人會記住數字——所以不可能的值一律不給數字。
 */
import { ref, computed } from 'vue'
import apiClient from '../services/apiClient'

const files      = ref([])
const folder     = ref('')
const windowMin  = ref(180)
const volumeL    = ref(null)
const loading    = ref(false)
const error      = ref('')
const result     = ref(null)
const openSeg    = ref(null)

function onPick (e) {
  files.value = Array.from(e.target.files || [])
  folder.value = ''
}

async function run () {
  loading.value = true; error.value = ''; result.value = null
  try {
    const params = { window_min: windowMin.value }
    if (volumeL.value) params.volume_l = volumeL.value
    let data
    if (files.value.length) {
      const fd = new FormData()
      for (const f of files.value) fd.append('files', f)
      // ⚠ 整批解析可能數十秒（一次丟一個月的資料），預設 8 秒會誤判逾時
      ;({ data } = await apiClient.post('/descent_report', fd, {
        params, timeout: 180000,
        headers: { 'Content-Type': 'multipart/form-data' },
      }))
    } else if (folder.value) {
      ;({ data } = await apiClient.post('/descent_report', null,
        { params: { ...params, folder: folder.value }, timeout: 180000 }))
    } else {
      throw new Error('請先選 CSV 檔（可多選）或填伺服器上的資料夾路徑')
    }
    result.value = data
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || String(e)
  } finally {
    loading.value = false
  }
}

const verdictBad = computed(() =>
  (result.value?.summary?.window_verdict || '').startsWith('⚠'))

function fmt (v, n = 4) {
  return (v === null || v === undefined) ? '—' : Number(v).toFixed(n)
}
function pct (v) {
  return (v === null || v === undefined) ? '—' : (Number(v) * 100).toFixed(0) + '%'
}
function st (seg) { return seg.stoichiometry || {} }
</script>

<template>
  <div class="wrap">
    <header>
      <h1>每段下降報表</h1>
      <p class="sub">
        丟 CSV → 切出每一段壓力下降 → 總下降、平均速率、斜率；
        有排氣尖峰時再由壓降反推用掉多少 CO2、產生多少 CH4。
      </p>
    </header>

    <section class="panel">
      <div class="row">
        <label>CSV 檔（<b>可多選</b>）</label>
        <input type="file" accept=".csv" multiple @change="onPick" />
        <span class="hint" v-if="files.length">已選 {{ files.length }} 個檔</span>
      </div>
      <p class="warn-inline">
        ⚠ 一次丟<b>整個期間</b>，不要一天一天丟。一天一檔，而循環中位長約 7 小時、
        大多跨過午夜——逐檔處理會把跨日的一段攔腰砍斷，時長與振幅都會錯，
        而且結果看起來完全正常。
      </p>
      <div class="row">
        <label>或伺服器資料夾</label>
        <input v-model="folder" placeholder="C:\…\202607至08最新循環研究"
               :disabled="files.length > 0" />
      </div>
      <div class="row">
        <label>視窗長度</label>
        <select v-model.number="windowMin">
          <option :value="10">10 分（⚠ 低於感測器分辨力）</option>
          <option :value="30">30 分</option>
          <option :value="60">60 分</option>
          <option :value="180">180 分（3 小時，建議）</option>
          <option :value="240">240 分（4 小時）</option>
        </select>
        <label class="ml">頭空體積 L</label>
        <input v-model.number="volumeL" type="number" step="0.01"
               placeholder="留空＝不算絕對莫耳數" />
      </div>
      <p class="hint">
        頭空體積只影響「絕對莫耳數」。生物份額與 CH4/消耗比值<b>不需要體積</b>
        ——分子分母是同一個頭空的分壓，體積自己消掉。
      </p>
      <button class="go" :disabled="loading" @click="run">
        {{ loading ? '分析中…' : '開始分析' }}
      </button>
      <p v-if="error" class="err">{{ error }}</p>
    </section>

    <template v-if="result">
      <section class="panel">
        <h2>總覽</h2>
        <p class="meta">
          {{ result.n_files }} 個檔、{{ result.n_rows }} 列
          （{{ result.ts_first?.slice(0, 16) }} → {{ result.ts_last?.slice(0, 16) }}）
        </p>
        <div class="tiles">
          <div class="tile"><span>下降段數</span><b>{{ result.n_segments }}</b></div>
          <div class="tile"><span>總下降</span><b>{{ fmt(result.summary.total_drop_sum, 3) }}</b><i>kgf/cm²</i></div>
          <div class="tile"><span>每段中位下降</span><b>{{ fmt(result.summary.total_drop_median, 3) }}</b><i>kgf/cm²</i></div>
          <div class="tile"><span>中位速率</span><b>{{ fmt(result.summary.mean_rate_median) }}</b><i>kgf/cm²/hr</i></div>
          <div class="tile"><span>中位時長</span><b>{{ fmt(result.summary.duration_hr_median, 1) }}</b><i>hr</i></div>
        </div>
        <p :class="verdictBad ? 'verdict bad' : 'verdict'">
          {{ result.summary.window_verdict }}
        </p>
      </section>

      <section class="panel" v-if="result.vent_intervals">
        <h2>排氣錨點之間的轉換</h2>
        <p class="hint">
          CH4 濃度只有<b>排氣瞬間</b>可信（其餘時間是管路拖尾）。
          {{ result.vent_intervals.coverage_note }}
        </p>
        <table v-if="result.vent_intervals.intervals.length">
          <thead><tr>
            <th>起</th><th>迄</th><th>時長</th><th>CH4 起→迄</th>
            <th>消耗總計</th><th>CH4/消耗</th><th>生物份額</th>
          </tr></thead>
          <tbody>
            <tr v-for="(iv, i) in result.vent_intervals.intervals" :key="i"
                :class="{ dim: st(iv).status !== 'ok' }">
              <td>{{ iv.ts_start.slice(0, 16) }}</td>
              <td>{{ iv.ts_end.slice(0, 16) }}</td>
              <td>{{ fmt(iv.duration_hr, 1) }} hr</td>
              <td>{{ fmt(iv.ch4_start_pct, 2) }}% → {{ fmt(iv.ch4_end_pct, 2) }}%</td>
              <td>{{ fmt(iv.consumed_kgf_cm2, 3) }}</td>
              <!-- ⚠ 不可能的值不給數字，只給原因 -->
              <td v-if="st(iv).status === 'ok'">{{ fmt(st(iv).ch4_per_consumed) }}
                <i class="cap">/ 0.25</i></td>
              <td v-else class="na">不可用</td>
              <td v-if="st(iv).status === 'ok'"><b>{{ pct(st(iv).bio_share) }}</b></td>
              <td v-else class="na" :title="st(iv).warning">見下方說明</td>
            </tr>
          </tbody>
        </table>
        <p v-for="(iv, i) in result.vent_intervals.intervals" :key="'w' + i"
           v-show="st(iv).warning" class="err small">
          {{ iv.ts_start.slice(0, 16) }}：{{ st(iv).warning }}
        </p>
      </section>

      <section class="panel">
        <h2>每一段</h2>
        <table>
          <thead><tr>
            <th>起</th><th>迄</th><th>時長</th><th>壓力 起→迄</th>
            <th>總下降</th><th>平均速率</th><th>斜率</th><th>R²</th><th>視窗</th>
          </tr></thead>
          <tbody>
            <template v-for="(s, i) in result.segments" :key="i">
              <tr>
                <td>{{ s.ts_start.slice(0, 16) }}</td>
                <td>{{ s.ts_end.slice(0, 16) }}</td>
                <td>{{ fmt(s.duration_hr, 1) }} hr</td>
                <td>{{ fmt(s.p_start, 2) }} → {{ fmt(s.p_end, 2) }}</td>
                <td><b>{{ fmt(s.total_drop, 3) }}</b></td>
                <td>{{ fmt(s.mean_rate) }}</td>
                <td>{{ fmt(s.slope) }}</td>
                <td>{{ fmt(s.r2, 3) }}</td>
                <td><button class="mini"
                    @click="openSeg = openSeg === i ? null : i">
                    {{ s.windows.length }} 個 {{ openSeg === i ? '▲' : '▼' }}
                  </button></td>
              </tr>
              <tr v-if="openSeg === i" class="sub">
                <td colspan="9">
                  <table class="inner">
                    <thead><tr><th>段內時間</th><th>n</th><th>下降</th>
                      <th>速率</th><th>斜率</th><th>R²</th></tr></thead>
                    <tbody>
                      <tr v-for="(w, k) in s.windows" :key="k"
                          :class="{ blind: w.below_quantum }">
                        <td>{{ fmt(w.hour_start, 1) }}–{{ fmt(w.hour_end, 1) }} hr</td>
                        <td>{{ w.n }}</td>
                        <td>{{ fmt(w.drop, 3) }}</td>
                        <td>{{ fmt(w.rate) }}</td>
                        <!-- ⚠ 低於量化階的視窗不顯示斜率：那是雜訊不是速率 -->
                        <td v-if="!w.below_quantum">{{ fmt(w.slope) }}</td>
                        <td v-else class="na" title="變化量低於感測器分辨力">量不到</td>
                        <td>{{ w.below_quantum ? '—' : fmt(w.r2, 3) }}</td>
                      </tr>
                    </tbody>
                  </table>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>

<style scoped>
.wrap { padding: 1.5rem; max-width: 1180px; margin: 0 auto; color: #ccc; }
h1 { font-size: 1.1rem; color: #e8e8e8; font-weight: 600; }
h2 { font-size: 0.9rem; color: #e0e0e0; font-weight: 600; margin-bottom: 0.6rem; }
.sub { font-size: 0.78rem; color: #777; margin-top: 4px; line-height: 1.6; max-width: 66ch; }
.panel { border: 1px solid #1e1e1e; border-radius: 6px; background: #111;
         padding: 1rem 1.1rem; margin-top: 0.9rem; }
.row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.row label { font-size: 0.76rem; color: #888; min-width: 108px; }
.row label.ml { min-width: auto; margin-left: 12px; }
input[type=text], input:not([type]), input[type=number], select {
  background: #161616; border: 1px solid #262626; color: #ddd;
  border-radius: 4px; padding: 5px 8px; font-size: 0.76rem; font-family: inherit;
  min-width: 200px;
}
input[type=file] { font-size: 0.74rem; color: #999; }
.hint { font-size: 0.72rem; color: #6e6e6e; line-height: 1.6; margin-top: 4px; }
.warn-inline { font-size: 0.74rem; color: #c9a227; line-height: 1.65;
               background: rgba(201,162,39,0.07); border-left: 2px solid #6b5615;
               padding: 7px 10px; border-radius: 3px; margin: 4px 0 10px; }
.meta { font-size: 0.74rem; color: #777; margin-bottom: 0.7rem; }
.tiles { display: flex; gap: 10px; flex-wrap: wrap; }
.tile { background: #151515; border: 1px solid #212121; border-radius: 5px;
        padding: 8px 12px; min-width: 118px; }
.tile span { display: block; font-size: 0.68rem; color: #777; }
.tile b { font-size: 1.02rem; color: #e6e6e6; font-variant-numeric: tabular-nums; }
.tile i { font-size: 0.64rem; color: #666; font-style: normal; margin-left: 3px; }
.verdict { margin-top: 0.8rem; font-size: 0.76rem; color: #7d9a68; line-height: 1.6; }
.verdict.bad { color: #d9a441; }
table { width: 100%; border-collapse: collapse; margin-top: 0.4rem; }
th, td { text-align: left; padding: 5px 8px; font-size: 0.74rem;
         border-bottom: 1px solid #191919; white-space: nowrap; }
th { color: #777; font-weight: 400; }
td { color: #d0d0d0; font-variant-numeric: tabular-nums; }
tr.dim td { color: #6a6a6a; }
tr.blind td { color: #5f5f5f; }
.na { color: #8a6a3a; }
.cap { color: #666; font-style: normal; font-size: 0.68rem; }
.sub > td { background: #0d0d0d; padding: 6px 10px 10px; }
table.inner { width: auto; min-width: 460px; }
table.inner th, table.inner td { font-size: 0.71rem; padding: 3px 10px 3px 0; }
button { font-family: inherit; cursor: pointer; border-radius: 4px;
         font-size: 0.76rem; padding: 6px 14px; transition: all 0.15s; }
.go { background: rgba(52,152,219,0.12); color: #3498db; border: 1px solid #23394a;
      margin-top: 6px; }
.go:hover:not(:disabled) { background: rgba(52,152,219,0.2); }
.mini { background: #171717; color: #888; border: 1px solid #242424;
        font-size: 0.7rem; padding: 2px 8px; }
button:disabled { opacity: 0.5; cursor: default; }
.err { font-size: 0.76rem; color: #c0623a; margin-top: 0.6rem; line-height: 1.6;
       white-space: normal; }
.err.small { font-size: 0.72rem; }
</style>
