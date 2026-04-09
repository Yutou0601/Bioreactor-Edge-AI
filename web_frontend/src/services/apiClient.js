import axios from 'axios'

// 建立一個專屬的 Axios 實體 (Instance)
const apiClient = axios.create({
  // 統一設定後端 API 的基底網址
  baseURL: 'http://192.168.55.1:8000/api', 
  // 設定超時時間，如果 Jetson 5 秒沒回應就當作斷線
  timeout: 5000, 
  headers: {
    'Content-Type': 'application/json'
  }
})

// 攔截器 (可選)：你可以在這裡統一處理所有 API 的錯誤，例如跳出全域的錯誤通知
apiClient.interceptors.response.use(
  response => response,
  error => {
    console.error('API 請求發生錯誤:', error)
    return Promise.reject(error)
  }
)

export default apiClient