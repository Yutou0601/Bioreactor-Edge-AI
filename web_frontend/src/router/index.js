import { createRouter, createWebHistory } from 'vue-router'
import MonitorView from '../views/MonitorView.vue'
import ReportView  from '../views/ReportView.vue'
import ExperimentView from '../views/ExperimentView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/',           component: MonitorView },
    { path: '/experiment', component: ExperimentView },
    { path: '/report',     component: ReportView  },
  ],
})
