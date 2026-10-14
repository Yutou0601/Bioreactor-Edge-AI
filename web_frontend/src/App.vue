<script setup>
import { RouterView, RouterLink } from 'vue-router'
</script>

<template>
  <div class="shell">
    <nav class="page-nav">
      <span class="nav-brand">BTP 監測系統</span>
      <RouterLink to="/">即時監控</RouterLink>
      <RouterLink to="/cycles">循環分析</RouterLink>
      <RouterLink to="/experiment">實驗批次</RouterLink>
      <RouterLink to="/system">系統狀態</RouterLink>
    </nav>
    <RouterView />
  </div>
</template>

<style scoped>
.shell { min-height: 100vh; }
.page-nav {
  display: flex; align-items: center; gap: 4px; flex-wrap: wrap;
  background: var(--surface-1); border-bottom: 1px solid var(--border);
  padding: 0 16px; min-height: 44px;
}
.nav-brand {
  font-size: 0.82rem; font-weight: 700; color: var(--text-muted);
  margin-right: 16px; letter-spacing: 0.05em;
}
.page-nav a {
  color: var(--text-secondary); text-decoration: none; font-size: 0.88rem;
  padding: 6px 14px; border-radius: 4px;
}
.page-nav a:hover { color: var(--text-primary); background: var(--surface-2); }
.page-nav a.router-link-exact-active,
.page-nav a.router-link-active:not([href="/"]) {
  color: var(--text-primary); background: var(--surface-2);
  box-shadow: inset 0 -2px 0 var(--series-1);
}
</style>
