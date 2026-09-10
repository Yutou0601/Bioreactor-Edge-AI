<script setup>
/**
 * 資料匯入與波形檢視
 * ==================
 * 一次選多個 CSV 匯入，馬上看到波形，以及 Algorithm 1 在上面切出來的循環。
 *
 * ⚠ 波形的降採樣在**後端**做（/api/waveform 的 _envelope），用每桶取
 *   min/max 而不是等距抽樣。這個訊號是鋸齒波，補氣是幾分鐘內的陡升，
 *   等距抽樣會整個跳過那一瞬間，畫出來像平滑下降。
 *
 * ⚠ 這頁顯示的 r_b 是「這批匯入資料」的，不是系統定版值（那個在生物速率
 *   頁，走 cycle 表且已套校準）。段數少時後端會回 rb_usability=unusable，
 *   這時**不顯示數字**——只給一個數字，看的人會當成結果。
 */
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import apiClient from '../services/apiClient'

const files      = ref([])          // 選到的檔案
const importing  = ref(false)
const progress   = ref('')
const result     = ref(null)
const wave       = ref(null)
const signal     = ref('pressure')
const loading    = ref(false)
const err        = ref('')
const fileInput  = ref(null)
const chartRef   = ref(null)
let chart = null

const SIGNALS = [
  { key: 'pressure', label: '反應器壓力', unit: 'kg/cm²', color: '#3a7bd5' },
  { key: 'orp',      label: 'ORP',        unit: 'mV',     color: '#7d5ba6' },
  { key: 'ph',       label: 'pH',         unit: '',       color: '#4caf82' },
]
const meta = computed(() => SIGNALS.find(s => s.key === signal.value))

function pick(e) {
  files.value = Array.from(e.target.files || [])
  result.value = null
}
function clearFiles() {
  files.value = []
  result.value = null
  if (fileInput.value) fileInput.value.value = ''
}
function fmtSize(b) {
  return b < 1024 ? b + ' B'
    : b < 1048576 ? (b / 1024).toFixed(0) + ' KB'
    : (b / 1048576).toFixed(1) + ' MB'
}
const totalSize = computed(() =>
  files.value.reduce((s, f) => s + f.size, 0))

async function doImport() {
  if (!files.value.length) return
  importing.value = true
  err.value = ''
  progress.value = `匯入 ${files.value.length} 個檔案…`
  try {
    const fd = new FormData()
    // ⚠ 欄位名必須是 files（後端 list[UploadFile] = File(...)）
    for (const f of files.value) fd.append('files', f)
    const { data } = await apiClient.post('/import_csv_batch', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,          // 幾十個檔可能要幾分鐘，不要中途斷掉
    })
    result.value = data
    await loadWave()
  } catch (e) {
    err.value = e.response?.data?.detail || e.message || '匯入失敗'
  } finally {
    importing.value = false
    progress.value = ''
  }
}

async function loadWave() {
  loading.value = true
  try {
    const { data } = await apiClient.get('/waveform',
      { params: { signal: signal.value }, timeout: 120000 })
    wave.value = data
    await nextTick()
    draw()
  } catch (e) {
    err.value = e.message || '讀取波形失敗'
  } finally { loading.value = false }
}

function switchSignal(k) { signal.value = k; loadWave() }

function draw() {
  const w = wave.value
  if (!chartRef.value || !w || w.status !== 'ok') return
  if (!chart) chart = echarts.init(chartRef.value, null, { renderer: 'canvas' })

  // 循環邊界疊在波形上：通過預篩的用實線，被篩掉的用淡虛線。
  // 看得出「哪幾段沒被採用」跟看得出速率一樣重要。
  const marks = (w.cycles || []).map(c => ({
    xAxis: c.start,
    lineStyle: {
      color: c.screened ? '#c0392b' : '#bbb',
      width: c.screened ? 1.2 : 1,
      type: c.screened ? 'solid' : 'dashed',
    },
  }))

  chart.setOption({
    grid: { left: 58, right: 20, top: 28, bottom: 58 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: w.series.map(p => p.t),
      axisLabel: { formatter: v => (v || '').slice(5, 16), fontSize: 10 },
    },
    yAxis: {
      type: 'value', scale: true,
      name: meta.value.unit, nameTextStyle: { fontSize: 10 },
      axisLabel: { fontSize: 10 },
    },
    dataZoom: [
      { type: 'inside' },
      { type: 'slider', height: 18, bottom: 14 },
    ],
    series: [{
      type: 'line', showSymbol: false, smooth: false,
      sampling: 'lttb',
      lineStyle: { width: 1.1, color: meta.value.color },
      data: w.series.map(p => p.v),
      markLine: {
        silent: true, symbol: 'none',
        label: { show: false },
        data: marks,
      },
    }],
  }, true)
}

function onResize() { chart && chart.resize() }
onMounted(() => { window.addEventListener('resize', onResize); loadWave() })
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  chart && chart.dispose(); chart = null
})

function fmt(v, d = 4) {
  return (v === null || v === undefined) ? '—' : Number(v).toFixed(d)
}
const USE_META = {
  usable:     { cls: 'u-ok',   tag: '可引用' },
  indicative: { cls: 'u-warn', tag: '僅供參考' },
  unusable:   { cls: 'u-bad',  tag: '不可用' },
}
</script>

<template>
  <div class="page">
    <header class="head">
      <h1>資料匯入 <small>多檔 CSV · 波形與切段檢視</small></h1>
      <p class="sub">一次選多個 CSV 匯入，立刻看到波形與 Algorithm 1 切出的循環。</p>
    </header>

    <!-- ── 選檔 ─────────────────────────────────────── -->
    <section class="panel">
      <div class="picker">
        <input ref="fileInput" type="file" accept=".csv" multiple
               @change="pick" class="file-in" />
        <button class="btn primary" :disabled="!files.length || importing"
                @click="doImport">
          {{ importing ? (progress || '匯入中…') : `匯入 ${files.length} 個檔案` }}
        </button>
        <button v-if="files.length" class="btn ghost" :disabled="importing"
                @click="clearFiles">清除</button>
      </div>

      <div v-if="files.length" class="filelist">
        <div class="fl-head">
          已選 <b>{{ files.length }}</b> 個檔案，共 {{ fmtSize(totalSize) }}
        </div>
        <ul>
          <li v-for="f in files.slice(0, 12)" :key="f.name">
            <span class="fn">{{ f.name }}</span>
            <span class="fs">{{ fmtSize(f.size) }}</span>
          </li>
        </ul>
        <div v-if="files.length > 12" class="more">
          …另外 {{ files.length - 12 }} 個
        </div>
      </div>

      <p v-if="err" class="err">{{ err }}</p>

      <!-- 匯入結果：逐檔列出，失敗的要看得見 -->
      <div v-if="result" class="res">
        <div class="res-top">
          匯入 <b>{{ result.n_ok }}</b> / {{ result.n_files }} 個檔案，
          共 <b>{{ result.imported_total }}</b> 筆
          <span v-if="result.n_failed" class="bad">
            · {{ result.n_failed }} 個失敗
          </span>
        </div>
        <ul class="res-list">
          <li v-for="f in result.files" :key="f.file" :class="{ bad: !f.ok }">
            <span class="fn">{{ f.file }}</span>
            <span v-if="f.ok" class="ok">{{ f.imported }} 筆</span>
            <span v-else class="bad">{{ f.error }}</span>
          </li>
        </ul>
      </div>
    </section>

    <!-- ── 波形 ─────────────────────────────────────── -->
    <section v-if="wave && wave.status === 'ok'" class="panel">
      <div class="wave-head">
        <div class="tabs">
          <button v-for="s in SIGNALS" :key="s.key"
                  class="tab" :class="{ on: signal === s.key }"
                  @click="switchSignal(s.key)">{{ s.label }}</button>
        </div>
        <div class="wave-meta">
          {{ wave.n_records }} 筆 ·
          {{ (wave.from || '').slice(0, 16) }} ~ {{ (wave.to || '').slice(0, 16) }}
          <span v-if="loading" class="dim">· 載入中…</span>
        </div>
      </div>

      <div ref="chartRef" class="chart"></div>

      <p class="legend">
        <span class="k solid"></span> 通過曲率預篩的循環起點
        <span class="k dashed"></span> 被篩掉的循環起點
        <span class="note">
          切段一律依**壓力**（Algorithm 1 的定義），所以三個訊號疊在同一組邊界上。
        </span>
      </p>
    </section>

    <!-- ── 這批資料的速率 ────────────────────────────── -->
    <section v-if="wave && wave.status === 'ok'" class="panel">
      <div class="cards">
        <div class="card">
          <div class="lab">切出循環</div>
          <div class="val">{{ wave.n_cycles }}</div>
          <div class="unit">通過預篩 {{ wave.n_screened }} 段</div>
        </div>
        <div class="card">
          <div class="lab">這批的 r_b 中位數</div>
          <!-- ⚠ 不可用時不顯示數字。給一個數字，看的人就會當成結果。 -->
          <div v-if="wave.rb_usability === 'unusable'" class="val dim">—</div>
          <div v-else class="val">{{ fmt(wave.median_rb_here, 5) }}</div>
          <div class="unit">
            <span v-if="wave.rb_ci">
              {{ fmt(wave.rb_ci[0], 4) }} ~ {{ fmt(wave.rb_ci[1], 4) }}
            </span>
            <span v-else>—</span>
          </div>
        </div>
        <div class="card">
          <div class="lab">精度</div>
          <div class="val" :class="USE_META[wave.rb_usability]?.cls">
            <template v-if="wave.rb_precision_pct != null">
              ±{{ wave.rb_precision_pct }}%
            </template><template v-else>—</template>
          </div>
          <div class="unit">{{ USE_META[wave.rb_usability]?.tag }}</div>
        </div>
      </div>

      <p class="usenote" :class="USE_META[wave.rb_usability]?.cls">
        ⚠ {{ wave.rb_note }}
        這是<b>這批匯入資料</b>的中位數，未套校準，<b>不是系統定版值</b>——
        定版值在「生物速率」頁（走 cycle 表、已校準）。
      </p>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>起</th><th>迄</th><th>時長 hr</th>
              <th>曲率</th><th>預篩</th><th>k̂</th><th>r̂_b</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(c, i) in wave.cycles" :key="i"
                :class="{ dropped: !c.screened }">
              <td class="mono">{{ (c.start || '').slice(5, 16) }}</td>
              <td class="mono">{{ (c.end || '').slice(5, 16) }}</td>
              <td class="mono">{{ c.duration_hr }}</td>
              <td class="mono">{{ c.curvature ?? '—' }}</td>
              <td>
                <span class="badge" :class="c.screened ? 'ok' : 'no'">
                  {{ c.screened ? '通過' : '篩掉' }}
                </span>
              </td>
              <td class="mono">{{ c.k ?? '—' }}</td>
              <td class="mono" :class="{ neg: c.rb != null && c.rb < 0 }">
                {{ c.rb ?? '—' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="tblnote">
        ⚠ <b class="neg">紅色</b>＝這一段算出負的 r_b（物理上不可能）。
        單段近兩成為負是這個估計問題的性質，不是資料壞掉——所以只報中位數，
        而且段數要夠。
      </p>
    </section>

    <section v-else-if="wave" class="panel empty">
      {{ wave.message || '尚無資料' }}
    </section>
  </div>
</template>

<style scoped>
.page { padding: 1.2rem 1.4rem 2.4rem; max-width: 1180px; margin: 0 auto; }
.head h1 { font-size: 1.28rem; margin: 0 0 2px; font-weight: 650; }
.head h1 small { font-size: .74rem; color: #8a8a8a; font-weight: 400; margin-left: 8px; }
.sub { margin: 0 0 1.1rem; font-size: .78rem; color: #777; }

.panel { background: #fff; border: 1px solid #e6e6e6; border-radius: 7px;
         padding: 14px 16px; margin-bottom: 1rem; }

.picker { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.file-in { font-size: .78rem; flex: 1; min-width: 240px; }
.btn { padding: 7px 15px; border-radius: 5px; font-size: .8rem;
       cursor: pointer; border: 1px solid transparent; }
.btn.primary { background: #3a7bd5; color: #fff; }
.btn.primary:disabled { background: #b9c9e2; cursor: not-allowed; }
.btn.ghost { background: #fff; border-color: #d5d5d5; color: #555; }

.filelist { margin-top: 11px; font-size: .74rem; }
.fl-head { color: #666; margin-bottom: 5px; }
.filelist ul { list-style: none; margin: 0; padding: 0;
               max-height: 168px; overflow-y: auto; }
.filelist li { display: flex; justify-content: space-between;
               padding: 2px 6px; border-bottom: 1px solid #f4f4f4; }
.fn { color: #444; font-family: ui-monospace, Consolas, monospace; }
.fs { color: #999; }
.more { color: #999; padding: 4px 6px; }

.err { color: #b23; font-size: .78rem; margin: 8px 0 0; }
.res { margin-top: 12px; padding: 10px 12px; background: #f7faf8;
       border: 1px solid #d9e8df; border-radius: 5px; font-size: .76rem; }
.res-top { margin-bottom: 6px; }
.res-list { list-style: none; margin: 0; padding: 0;
            max-height: 190px; overflow-y: auto; }
.res-list li { display: flex; justify-content: space-between; padding: 2px 0; }
.res-list li.bad { color: #b23; }
.ok { color: #2f6b45; }
.bad { color: #b23; }

.wave-head { display: flex; justify-content: space-between;
             align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.tabs { display: flex; gap: 5px; }
.tab { padding: 5px 13px; border-radius: 4px; border: 1px solid #ddd;
       background: #fff; font-size: .76rem; cursor: pointer; color: #555; }
.tab.on { background: #3a7bd5; border-color: #3a7bd5; color: #fff; }
.wave-meta { font-size: .72rem; color: #888; }
.dim { color: #aaa; }
.chart { width: 100%; height: 320px; }

.legend { font-size: .7rem; color: #777; margin: 6px 0 0;
          display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.k { display: inline-block; width: 16px; height: 0; }
.k.solid  { border-top: 1.5px solid #c0392b; }
.k.dashed { border-top: 1.5px dashed #bbb; }
.legend .note { color: #999; margin-left: 6px; }

.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
         gap: 10px; margin-bottom: 10px; }
.card { border: 1px solid #eee; border-radius: 6px; padding: 10px 12px; }
.lab { font-size: .7rem; color: #888; }
.val { font-size: 1.22rem; font-weight: 620; margin: 2px 0; }
.val.dim { color: #bbb; }
.unit { font-size: .68rem; color: #999; }
.u-ok   { color: #2f6b45; }
.u-warn { color: #86682a; }
.u-bad  { color: #93392f; }

.usenote { font-size: .74rem; line-height: 1.65; padding: 9px 12px;
           border-radius: 5px; margin: 0 0 12px; }
.usenote.u-ok   { background: #eef8f1; border: 1px solid #bfe0c9; }
.usenote.u-warn { background: #fdf6e6; border: 1px solid #e6d29a; }
.usenote.u-bad  { background: #fceceb; border: 1px solid #e5b8b4; }

.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .74rem; }
th { text-align: left; padding: 6px 8px; border-bottom: 2px solid #eee;
     color: #666; font-weight: 600; }
td { padding: 5px 8px; border-bottom: 1px solid #f4f4f4; }
tr.dropped { color: #aaa; background: #fcfcfc; }
.mono { font-family: ui-monospace, Consolas, monospace; }
.neg { color: #c0392b; font-weight: 600; }
.badge { font-size: .66rem; padding: 1px 7px; border-radius: 9px; }
.badge.ok { background: #eef8f1; color: #2f6b45; }
.badge.no { background: #f1f1f1; color: #999; }
.tblnote { font-size: .7rem; color: #777; margin: 8px 0 0; line-height: 1.6; }
.empty { color: #888; font-size: .8rem; text-align: center; padding: 2rem; }
</style>
