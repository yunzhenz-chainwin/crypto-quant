/**
 * CandlestickChart.jsx — 蠟燭圖 + 買賣標記
 *
 * 使用 TradingView lightweight-charts，繪製：
 *   - 蠟燭圖（OHLC）
 *   - 成交量長條圖（下方）
 *   - 回測買入▲（綠色）/ 賣出▼（紅色）標記
 *
 * Props：
 *   prices  來自 /api/prices/{symbol} 的 OHLC 陣列
 *   trades  來自 /api/backtest/{symbol} 的交易明細（可選）
 */
import { useEffect, useRef } from 'react'
import { createChart, CrosshairMode } from 'lightweight-charts'

export default function CandlestickChart({ prices, trades }) {
  const containerRef = useRef(null)
  const chartRef     = useRef(null)

  useEffect(() => {
    if (!containerRef.current || !prices || prices.length === 0) return

    // 建立圖表，深色主題配色
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#0f172a' },
        textColor:  '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: {
        borderColor:     '#334155',
        timeVisible:     true,
        secondsVisible:  false,
      },
      width:  containerRef.current.clientWidth,
      height: 320,
    })
    chartRef.current = chart

    // ── 蠟燭圖 ───────────────────────────────────────────────────────────
    const candleSeries = chart.addCandlestickSeries({
      upColor:       '#22c55e',  // 收漲：綠
      downColor:     '#ef4444',  // 收跌：紅
      borderVisible: false,
      wickUpColor:   '#22c55e',
      wickDownColor: '#ef4444',
    })

    const candleData = prices.map(p => ({
      time:  p.date,
      open:  p.open,
      high:  p.high,
      low:   p.low,
      close: p.close,
    }))
    candleSeries.setData(candleData)

    // ── 成交量 ────────────────────────────────────────────────────────────
    const volumeSeries = chart.addHistogramSeries({
      priceFormat:    { type: 'volume' },
      priceScaleId:   'vol',          // 獨立 Y 軸，不跟蠟燭共用
      color:          '#334155',
    })
    chart.priceScale('vol').applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },  // 成交量只佔下方 15%
    })
    volumeSeries.setData(prices.map(p => ({
      time:  p.date,
      value: p.volume,
      color: p.close >= p.open ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)',
    })))

    // ── 回測買賣標記 ──────────────────────────────────────────────────────
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
      // lightweight-charts 要求 markers 依時間排序
      markers.sort((a, b) => a.time.localeCompare(b.time))
      candleSeries.setMarkers(markers)
    }

    // 自動縮放到最新 120 根蠟燭
    chart.timeScale().scrollToPosition(-5, false)

    // 視窗大小改變時自適應寬度
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
