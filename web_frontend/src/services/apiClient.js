import axios from 'axios'

// 建立一個專屬的 Axios 實體 (Instance)
const apiClient = axios.create({
  // 統一設定後端 API 的基底網址
  // 開發模式（npm run dev）走 .env.development → localhost
  // 正式建置（npm run build）走 .env.production → Jetson 固定 IP
  baseURL: import.meta.env.VITE_API_BASE_URL,
  // timeout 要比 poll 間隔短，避免上一輪請求還掛著下一輪就觸發
  timeout: 3000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 攔截器 (可選)：你可以在這裡統一處理所有 API 的錯誤，例如跳出全域的錯誤通知
apiClient.interceptors.response.use(
  response => response,
  error => {
    // warn 而不是 error，避免後端暫時離線就洗紅色
    console.warn('[API]', error.config?.url, error.code || error.message)
    return Promise.reject(error)
  }
)

export default apiClient