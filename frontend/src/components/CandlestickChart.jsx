/**
 * CandlestickChart.jsx — 蠟燭圖 + 成交量 + 買賣標記
 * 使用 lightweight-charts v5 API（chart.addSeries + createSeriesMarkers）
 */
import { useEffect, useRef } from 'react'
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  CrosshairMode,
  createSeriesMarkers,
} from 'lightweight-charts'

export default function CandlestickChart({ prices, trades }) {
  const containerRef = useRef(null)

  useEffect(() => {
    if (!containerRef.current || !prices || prices.length === 0) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
        secondsVisible: false,
      },
      width: containerRef.current.clientWidth,
      height: 360,
    })

    // ── 蠟燭圖（v5：chart.addSeries(CandlestickSeries, options)）────────
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })
    candleSeries.setData(
      prices.map(p => ({
        time:  p.date,
        open:  p.open,
        high:  p.high,
        low:   p.low,
        close: p.close,
      }))
    )

    // ── 成交量（獨立 Y 軸，佔下方 15%）──────────────────────────────────
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat:  { type: 'volume' },
      priceScaleId: 'vol',
    })
    chart.priceScale('vol').applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    })
    volumeSeries.setData(
      prices.map(p => ({
        time:  p.date,
        value: p.volume,
        color: p.close >= p.open
          ? 'rgba(34,197,94,0.3)'
          : 'rgba(239,68,68,0.3)',
      }))
    )

    // ── 回測買賣標記（v5：createSeriesMarkers）───────────────────────────
    if (trades && trades.length > 0) {
      const markers = []
      trades.forEach(t => {
        if (t.entry_date) markers.push({
          time:     t.entry_date,
          position: 'belowBar',
          color:    '#22c55e',
          shape:    'arrowUp',
          text:     `買入 $${Number(t.entry_price).toFixed(0)}`,
        })
        if (t.exit_date) markers.push({
          time:     t.exit_date,
          position: 'aboveBar',
          color:    t.profit ? '#60a5fa' : '#ef4444',
          shape:    'arrowDown',
          text:     `${t.profit ? '獲利' : '停損'} ${t.return_pct > 0 ? '+' : ''}${t.return_pct}%`,
        })
      })
      markers.sort((a, b) => a.time.localeCompare(b.time))
      createSeriesMarkers(candleSeries, markers)
    }

    chart.timeScale().scrollToPosition(-5, false)

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth })
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [prices, trades])

  if (!prices || prices.length === 0) {
    return <div className="chart-empty">載入中…</div>
  }

  return <div ref={containerRef} className="candlestick-wrap" />
}
