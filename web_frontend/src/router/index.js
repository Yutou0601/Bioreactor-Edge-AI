import { createRouter, createWebHistory } from 'vue-router'

// 2026-10-15 改版：七頁精簡成四頁。
//   移除：研究分析（分布圖／熱力圖／突波統計）、ORP 生物相位偵測、CO2／CH4 趨勢圖
//         ——前兩者與論文最後的方法無關；ORP 已證實反映料位與操作而非活性；
//           CO2／CH4 讀數 99.98% 是管路拖尾。
//   合併：生物速率＋下降報表 → 循環分析；分析模組＋資料匯入 → 系統狀態。
// 舊網址一律轉址，書籤與文件裡的連結不會壞。
//
// ⚠ 頁面用動態 import：前端跑在 4 GB 的監控電腦上，沒點開的頁面不該載進來。
const LiveView       = () => import('../views/LiveView.vue')
const CyclesView     = () => import('../views/CyclesView.vue')
const ExperimentView = () => import('../views/ExperimentView.vue')
const SystemView     = () => import('../views/SystemView.vue')
const JobsView       = () => import('../views/JobsView.vue')

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/',           component: LiveView },
    { path: '/cycles',     component: CyclesView },
    { path: '/experiment', component: ExperimentView },
    { path: '/system',     component: SystemView },
    { path: '/jobs',       component: JobsView },
    // 舊網址
    { path: '/rate',    redirect: { path: '/cycles', query: { tab: 'rate' } } },
    { path: '/descent', redirect: { path: '/cycles', query: { tab: 'descent' } } },
    { path: '/modules', redirect: { path: '/system', query: { tab: 'modules' } } },
    { path: '/import',  redirect: { path: '/system', query: { tab: 'import' } } },
    { path: '/report',  redirect: '/' },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
