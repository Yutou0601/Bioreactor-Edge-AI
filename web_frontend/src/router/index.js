import { createRouter, createWebHistory } from 'vue-router'
import MonitorView from '../views/MonitorView.vue'
import ReportView  from '../views/ReportView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/',       component: MonitorView },
    { path: '/report', component: ReportView  },
  ],
})
