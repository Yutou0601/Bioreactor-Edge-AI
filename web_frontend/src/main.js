import { createApp } from 'vue'
import App from './App.vue'

// 這裡未來如果安裝了 Vue Router (切換頁面) 或 Pinia (狀態管理)，就會在這裡 use()
const app = createApp(App)

// 將 Vue 應用程式掛載到 index.html 裡面 id="app" 的區塊
app.mount('#app')