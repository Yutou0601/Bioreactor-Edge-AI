// 日間／夜間／自動 主題切換。
//
// 自動＝跟著系統（prefers-color-scheme），不設 data-theme；日間／夜間＝在 <html> 設 data-theme。
// 色票本身在 styles/tokens.css。
//
// ⚠ 圖表（ECharts canvas）吃不到 CSS 變數，是在繪製當下用 getComputedStyle 讀色值。
//   所以主題一變就發出 window 事件 'themechange'，有畫圖的元件收到就重畫——
//   不然切了主題，圖會停在舊顏色（白底上一塊夜間配色的圖）。
// ⚠ 選擇存在 localStorage，讀寫都包 try/catch：無痕模式或封鎖網站資料時會丟例外，
//   那時就退回自動，不能讓整個前端起不來。
import { ref } from 'vue'

const KEY = 'btp-theme'
const MODES = ['auto', 'light', 'dark']
export const LABEL = { auto: '自動', light: '日間', dark: '夜間' }

function load() {
  try { const v = localStorage.getItem(KEY); return MODES.includes(v) ? v : 'auto' } catch { return 'auto' }
}

export const mode = ref(load())

function apply(m) {
  const el = document.documentElement
  if (m === 'auto') el.removeAttribute('data-theme')
  else el.setAttribute('data-theme', m)
  // 下一個 frame 再通知：讓新的 CSS 變數先生效，元件重畫時才讀得到新值
  requestAnimationFrame(() => window.dispatchEvent(new Event('themechange')))
}

export function setMode(m) {
  mode.value = m
  try { localStorage.setItem(KEY, m) } catch { /* 存不了就只在這次有效 */ }
  apply(m)
}

export function cycleMode() {
  setMode(MODES[(MODES.indexOf(mode.value) + 1) % MODES.length])
}

// 自動模式下，系統切換深淺色時也要讓圖重畫
try {
  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
    if (mode.value === 'auto') window.dispatchEvent(new Event('themechange'))
  })
} catch { /* 舊瀏覽器沒有 addEventListener 版本，就不跟 */ }

apply(mode.value)

/** 元件用：主題變了就呼叫 fn（通常是 render）。回傳解除函式，給 onBeforeUnmount 用。 */
export function onThemeChange(fn) {
  window.addEventListener('themechange', fn)
  return () => window.removeEventListener('themechange', fn)
}
