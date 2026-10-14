// 只載入用得到的 ECharts 部件。
//
// ⚠ 前端跑在 4 GB 的監控電腦上。`import * as echarts from 'echarts'` 會把所有圖種
//   與元件打包進來（實測壓縮後 1035 kB 單一檔），而全站只用到折線與長條。
//   要加新圖種時在這裡註冊，不要回頭改成整包 import。
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
  DataZoomComponent, MarkLineComponent, MarkAreaComponent, AxisPointerComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart, BarChart,
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
  DataZoomComponent, MarkLineComponent, MarkAreaComponent, AxisPointerComponent,
  CanvasRenderer,
])

export default echarts
export * from 'echarts/core'
