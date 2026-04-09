import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    // 允許外部裝置 (你的筆電) 連線到 Jetson 的前端伺服器
    host: '0.0.0.0', 
    // 固定前端的 Port 為 5173
    port: 5173,
    // 如果不小心 5173 被佔用，不要自動換 port，直接報錯讓我們知道
    strictPort: true 
  }
})