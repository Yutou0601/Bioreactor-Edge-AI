<script setup>
// 系統狀態：資料接收（新）、分析模組（原分析模組頁）、手動匯入（原資料匯入頁＋舊監控頁的手動輸入）。
// 手動匯入保留給補舊資料用；正常資料流由監控電腦的上傳程式自動送進來。
import { computed, defineAsyncComponent, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const ImportView = defineAsyncComponent(() => import('./ImportView.vue'))
const ManualEntry = defineAsyncComponent(() => import('../components/ManualEntry.vue'))
const ImportTab = { name: 'ImportTab', render: () => h('div', [h(ImportView), h('div', { style: 'padding:0 16px 16px;max-width:1400px;margin:0 auto' }, [h(ManualEntry)])]) }

const TABS = [
  { key: 'ingest',  label: '資料接收', comp: defineAsyncComponent(() => import('../components/IngestPanel.vue')) },
  { key: 'modules', label: '分析模組', comp: defineAsyncComponent(() => import('./ModulesView.vue')) },
  { key: 'import',  label: '手動匯入', comp: ImportTab },
]
const route = useRoute()
const router = useRouter()
const active = computed(() => TABS.find(t => t.key === route.query.tab) || TABS[0])
const pick = key => router.replace({ query: { ...route.query, tab: key } })
</script>

<template>
  <div>
    <div class="tabs" role="tablist">
      <button v-for="t in TABS" :key="t.key" role="tab" :aria-selected="active.key === t.key"
              :class="{ on: active.key === t.key }" @click="pick(t.key)">{{ t.label }}</button>
    </div>
    <KeepAlive><component :is="active.comp" :key="active.key" /></KeepAlive>
  </div>
</template>

<style scoped>
.tabs { display: flex; flex-wrap: wrap; gap: 4px; padding: 12px 16px 0; border-bottom: 1px solid var(--border); }
.tabs button {
  background: none; border: none; color: var(--text-secondary); font: inherit; font-size: 0.88rem;
  padding: 8px 14px; cursor: pointer; border-radius: 6px 6px 0 0;
}
.tabs button:hover { color: var(--text-primary); background: var(--surface-1); }
.tabs button.on { color: var(--text-primary); background: var(--surface-1); box-shadow: inset 0 -2px 0 var(--series-1); }
</style>
