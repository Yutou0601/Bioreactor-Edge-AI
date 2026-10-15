<script setup>
// 循環分析：原「生物速率」與「下降報表」合併成一頁的兩個分頁。
// 分頁記在網址 ?tab= 裡，舊網址 /rate、/descent 轉址過來時會直接落在對的分頁。
import { computed, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const TABS = [
  { key: 'rate',    label: '逐循環速率（Algorithm 1）', comp: defineAsyncComponent(() => import('./RateView.vue')) },
  { key: 'descent', label: '每段下降報表',               comp: defineAsyncComponent(() => import('./DescentView.vue')) },
  { key: 'tests',   label: '論文檢定（Algorithm 2／3）', comp: defineAsyncComponent(() => import('./PaperTestsView.vue')) },
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
