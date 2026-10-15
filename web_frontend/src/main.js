import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/tokens.css'
import './lib/theme'          // 掛載前就套用主題，避免先閃一下錯的配色

const app = createApp(App)
app.use(router)
app.mount('#app')
