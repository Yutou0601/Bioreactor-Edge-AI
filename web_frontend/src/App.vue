<script setup>
import { RouterView, RouterLink } from 'vue-router'
</script>

<template>
  <div class="shell">
    <nav class="page-nav">
      <span class="nav-brand">BTP Edge AI</span>
      <RouterLink to="/">即時監控</RouterLink>
      <RouterLink to="/experiment">實驗批次</RouterLink>
      <RouterLink to="/report">研究分析</RouterLink>
    </nav>
    <RouterView />
  </div>
</template>

<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&display=swap');
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { background: #0d0d0d; color: #e0e0e0; }
</style>

<style scoped>
.shell { min-height: 100vh; font-family: 'Noto Sans TC', sans-serif; }
.page-nav {
  display: flex; align-items: center; gap: 4px;
  background: #111; border-bottom: 1px solid #1e1e1e;
  padding: 0 1.25rem; height: 40px;
}
.nav-brand {
  font-size: 0.8rem; font-weight: 700; color: #333;
  margin-right: 16px; letter-spacing: 0.05em;
}
.page-nav a {
  color: #555; text-decoration: none; font-size: 0.82rem;
  padding: 4px 12px; border-radius: 4px; transition: all 0.15s;
}
.page-nav a:hover { color: #999; background: #1a1a1a; }
.page-nav a.router-link-active {
  color: #3498db; background: rgba(52,152,219,0.1);
}
</style>
