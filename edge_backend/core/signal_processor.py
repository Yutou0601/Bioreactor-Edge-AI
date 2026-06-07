"""
ORP 即時訊號處理器
====================
依據 PDF「基於邊緣運算之生物反應器即時ORP變化分析」實作：

1. 一階差分閾值法 (First-order Difference Threshold)
   Δx_t = x_t - x_{t-1}
   若 Δx_t < θ_drop → 判定為突波，將後續 spike_window 筆資料標記為無效

2. 線性內插重建 (Linear Interpolation)
   x̂(t) = x(t_start) + [x(t_end) - x(t_start)] / [t_end - t_start] * (t - t_start)
   在突波區間結束後，對緩衝區內的資料統一補插值

3. 指數移動平均 EMA (α = 2 / (N+1))
   y_t = α * x_t + (1 - α) * y_{t-1}
   套用在乾淨資料上做即時平滑輸出
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ProcessedPoint:
    timestamp: str
    raw: float
    cleaned: float
    ema: float
    is_anomaly: bool


class ORPSignalProcessor:
    def __init__(
        self,
        ema_window: int = 10,
        spike_threshold: float = -20.0,
        spike_max_minutes: int = 15,
    ):
        """
        Parameters
        ----------
        ema_window       : 滑動視窗大小 N，決定 EMA 平滑因子 α = 2/(N+1)
        spike_threshold  : 一階差分閾值 θ_drop (mV/min)，低於此值判定為突波
        spike_max_minutes: 突波影響區間最大長度（分鐘），超過後強制恢復
        """
        self.alpha = 2.0 / (ema_window + 1)
        self.spike_threshold = spike_threshold
        self.spike_max_minutes = spike_max_minutes

        self._ema: float | None = None
        self._prev_raw: float | None = None
        self._prev_ts: str | None = None

        # 突波緩衝區：儲存突波期間的 (timestamp, raw_orp)
        self._in_spike: bool = False
        self._spike_start_val: float = 0.0
        self._spike_start_ts: str = ""
        self._spike_buffer: list[tuple[str, float]] = []

    # ------------------------------------------------------------------
    # 公開介面
    # ------------------------------------------------------------------

    def process(self, timestamp: str, raw_orp: float) -> list[ProcessedPoint]:
        """
        輸入一筆原始 ORP 資料，回傳可立即儲存的 ProcessedPoint 清單。

        - 正常期間：立即回傳 1 筆
        - 突波期間：緩衝，回傳空清單（等待插值）
        - 突波結束時：回傳緩衝中所有已插值的記錄（一次 flush）
        """
        if self._prev_raw is None:
            # 第一筆：直接初始化
            self._prev_raw = raw_orp
            self._prev_ts = timestamp
            self._ema = raw_orp
            return [ProcessedPoint(timestamp, raw_orp, raw_orp, round(self._ema, 2), False)]

        delta = raw_orp - self._prev_raw

        if not self._in_spike:
            if delta < self.spike_threshold:
                # ── 突波開始 ──
                self._in_spike = True
                self._spike_start_val = self._prev_raw
                self._spike_start_ts = self._prev_ts
                self._spike_buffer = [(timestamp, raw_orp)]
                self._prev_raw = raw_orp
                self._prev_ts = timestamp
                return []  # 開始緩衝，暫不輸出
            else:
                # ── 正常資料 ──
                result = self._update_ema_and_emit(timestamp, raw_orp, cleaned=raw_orp, anomaly=False)
                self._prev_raw = raw_orp
                self._prev_ts = timestamp
                return [result]
        else:
            # ── 突波中 ──
            self._spike_buffer.append((timestamp, raw_orp))
            self._prev_raw = raw_orp
            self._prev_ts = timestamp

            # 判定結束條件：超過最大時間窗 或 ORP 回升超過起始值的 90%
            buf_len = len(self._spike_buffer)
            recovered = (raw_orp >= self._spike_start_val * 0.90 and delta > 0)
            timed_out = buf_len >= self.spike_max_minutes

            if recovered or timed_out:
                return self._flush_spike_buffer(end_val=raw_orp)
            return []

    def flush(self) -> list[ProcessedPoint]:
        """
        強制輸出緩衝區中剩餘的突波資料（用於 CSV 匯入到達檔案結尾時）。
        以最後一筆緩衝值作為插值終點。
        """
        if not self._in_spike or not self._spike_buffer:
            return []
        end_val = self._spike_buffer[-1][1]
        return self._flush_spike_buffer(end_val)

    def reset(self) -> None:
        """重置處理器狀態（重新連接感測器時呼叫）"""
        self._ema = None
        self._prev_raw = None
        self._prev_ts = None
        self._in_spike = False
        self._spike_buffer = []

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    def _update_ema_and_emit(
        self, timestamp: str, raw: float, cleaned: float, anomaly: bool
    ) -> ProcessedPoint:
        if self._ema is None:
            self._ema = cleaned
        else:
            self._ema = self.alpha * cleaned + (1.0 - self.alpha) * self._ema
        return ProcessedPoint(timestamp, raw, cleaned, round(self._ema, 2), anomaly)

    def _flush_spike_buffer(self, end_val: float) -> list[ProcessedPoint]:
        """
        突波結束：對緩衝區所有點做線性內插，再逐點更新 EMA。
        插值公式：
            x̂(t) = x_start + (x_end - x_start) / N_total * i
        """
        n = len(self._spike_buffer)
        x_start = self._spike_start_val
        x_end = end_val
        results: list[ProcessedPoint] = []

        for i, (ts, raw) in enumerate(self._spike_buffer):
            # 線性內插：從 x_start 線性過渡到 x_end
            cleaned = x_start + (x_end - x_start) * (i + 1) / n
            point = self._update_ema_and_emit(ts, raw, cleaned, anomaly=True)
            results.append(point)

        self._in_spike = False
        self._spike_buffer = []
        return results
