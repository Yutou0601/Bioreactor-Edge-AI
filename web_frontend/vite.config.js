import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    // 允許同網段的其他裝置連進開發伺服器（在別台機器上開網頁看畫面）。
    // 僅影響 npm run dev；正式是由後端直接供應 dist/。
    host: '0.0.0.0', 
    // 固定前端的 Port 為 5173
    port: 5173,
    // 如果不小心 5173 被佔用，不要自動換 port，直接報錯讓我們知道
    strictPort: true 
  }
})