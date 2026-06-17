/**
 * CandlestickChart.jsx — 蠟燭圖 + MA均線 + BB布林帶 + 成交量 + 買賣標記
 * 使用 lightweight-charts v5 API
 *
 * Props：
 *   prices      OHLCV 陣列（含 volume）
 *   indicators  技術指標陣列（含 MA20/MA60/MA200/BB_UPPER/BB_LOWER）
 *   trades      回測交易明細
 */
import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  CrosshairMode,
  createSeriesMarkers,
} from 'lightweight-charts'

export default function CandlestickChart({ prices, indicators, trades }) {
  const containerRef = useRef(null)
  const [showBB,   setShowBB]   = useState(true)
  const [showMA200, setShowMA200] = useState(true)

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
      height: 420,
    })

    // ── 蠟燭圖 ────────────────────────────────────────────────────────
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor:       '#22c55e',
      downColor:     '#ef4444',
      borderVisible: false,
      wickUpColor:   '#22c55e',
      wickDownColor: '#ef4444',
    })
    candleSeries.setData(
      prices.map(p => ({
        time: p.date, open: p.open, high: p.high, low: p.low, close: p.close,
      }))
    )

    // ── 指標疊層 ─────────────────────────────────────────────────────
    if (indicators && indicators.length > 0) {
      const get = (key) =>
        indicators.filter(d => d[key] != null).map(d => ({ time: d.date, value: d[key] }))

      // MA20（橙）
      const ma20d = get('MA20')
      if (ma20d.length) {
        chart.addSeries(LineSeries, {
          color: '#f59e0b', lineWidth: 1, priceLineVisible: false,
          lastValueVisible: true, title: 'MA20',
        }).setData(ma20d)
      }

      // MA60（紫）
      const ma60d = get('MA60')
      if (ma60d.length) {
        chart.addSeries(LineSeries, {
          color: '#818cf8', lineWidth: 1, priceLineVisible: false,
          lastValueVisible: true, title: 'MA60',
        }).setData(ma60d)
      }

      // MA200（藍，可切換顯示）
      if (showMA200) {
        const ma200d = get('MA200')
        if (ma200d.length) {
          chart.addSeries(LineSeries, {
            color: '#38bdf8', lineWidth: 1, lineStyle: 1,  // dashed
            priceLineVisible: false, lastValueVisible: true, title: 'MA200',
          }).setData(ma200d)
        }
      }

      // 布林帶 BB Upper / Lower（可切換顯示）
      if (showBB) {
        const bbUpd = get('BB_UPPER')
        const bbLwd = get('BB_LOWER')
        if (bbUpd.length) {
          chart.addSeries(LineSeries, {
            color: 'rgba(248,113,113,0.55)', lineWidth: 1, lineStyle: 2,  // dotted
            priceLineVisible: false, lastValueVisible: false, title: 'BB+',
          }).setData(bbUpd)
        }
        if (bbLwd.length) {
          chart.addSeries(LineSeries, {
            color: 'rgba(74,222,128,0.55)', lineWidth: 1, lineStyle: 2,
            priceLineVisible: false, lastValueVisible: false, title: 'BB-',
          }).setData(bbLwd)
        }
      }
    }

    // ── 成交量（獨立 Y 軸，佔下方 15%）──────────────────────────────
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat:  { type: 'volume' },
      priceScaleId: 'vol',
    })
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } })
    volumeSeries.setData(
      prices.map(p => ({
        time:  p.date,
        value: p.volume,
        color: p.close >= p.open ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)',
      }))
    )

    // ── 回測買賣標記 ─────────────────────────────────────────────────
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
      if (containerRef.current)
        chart.applyOptions({ width: containerRef.current.clientWidth })
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [prices, indicators, trades, showBB, showMA200])

  if (!prices || prices.length === 0)
    return <div className="chart-empty">載入中…</div>

  return (
    <div style={{ position: 'relative' }}>
      <div ref={containerRef} className="candlestick-wrap" />

      {/* 圖層切換 + 圖例 */}
      <div className="chart-legend">
        <span className="legend-candle-up">■</span> 收漲
        <span className="legend-candle-dn">■</span> 收跌
        <span className="legend-ma20">─</span> MA20
        <span className="legend-ma60">─</span> MA60

        {/* 可切換開關 */}
        <button
          className={`legend-toggle ${showMA200 ? 'on' : ''}`}
          style={{ color: '#38bdf8' }}
          onClick={() => setShowMA200(v => !v)}
        >
          {showMA200 ? '─' : '·'} MA200
        </button>
        <button
          className={`legend-toggle ${showBB ? 'on' : ''}`}
          style={{ color: 'rgba(248,113,113,0.9)' }}
          onClick={() => setShowBB(v => !v)}
        >
          {showBB ? '──' : '··'} 布林帶
        </button>
      </div>
    </div>
  )
}
