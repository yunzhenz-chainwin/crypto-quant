/**
 * CandlestickChart.jsx — 單一整合圖表面板：K線 + 所有指標(可逐一開關)
 * 使用 lightweight-charts v5（多面板 pane 共用時間軸／游標／縮放）
 *
 * 上方工具列可獨立開關每個圖層：
 *   MA20 / MA60 / MA200 / 布林帶 / 成交量 / RSI / MACD / 買賣標記
 * 全部預設開啟,使用者自行關掉不想看的。
 *
 * Props：prices（OHLCV）、indicators（含 MA/RSI/MACD/BB…）、trades（回測交易）
 */
import { useEffect, useRef, useState } from 'react'
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries,
  CrosshairMode, createSeriesMarkers,
} from 'lightweight-charts'

// 單一圖層開關按鈕（亮=開、暗=關,顏色對應該指標在圖上的顏色）
function Toggle({ on, onClick, color, children }) {
  return (
    <button
      className={`layer-toggle ${on ? 'on' : ''}`}
      style={{ color: on ? color : '#64748b', borderColor: on ? color : 'var(--border)' }}
      onClick={onClick}
    >
      {on ? '●' : '○'} {children}
    </button>
  )
}

export default function CandlestickChart({ prices, indicators, trades }) {
  const containerRef = useRef(null)
  // 每個圖層一個開關,預設全開
  const [showMA20,    setShowMA20]    = useState(true)
  const [showMA60,    setShowMA60]    = useState(true)
  const [showMA200,   setShowMA200]   = useState(true)
  const [showBB,      setShowBB]      = useState(true)
  const [showVol,     setShowVol]     = useState(true)
  const [showRSI,     setShowRSI]     = useState(true)
  const [showMACD,    setShowMACD]    = useState(true)
  const [showMarkers, setShowMarkers] = useState(true)

  useEffect(() => {
    if (!containerRef.current || !prices || prices.length === 0) return

    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#0f172a' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155', timeVisible: true, secondsVisible: false },
      width: containerRef.current.clientWidth,
      height: 640,
    })

    // ── 蠟燭圖（主面板 pane 0）───────────────────────────────────────
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e', downColor: '#ef4444', borderVisible: false,
      wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    })
    candleSeries.setData(prices.map(p => ({
      time: p.date, open: p.open, high: p.high, low: p.low, close: p.close,
    })))

    const hasInd = indicators && indicators.length > 0
    const get = (key) => hasInd
      ? indicators.filter(d => d[key] != null).map(d => ({ time: d.date, value: d[key] }))
      : []
    const addLine = (data, opts) => { if (data.length) chart.addSeries(LineSeries, opts).setData(data) }

    // ── 均線 / 布林帶（主面板疊層,依開關）──────────────────────────
    if (showMA20)  addLine(get('MA20'),  { color: '#f59e0b', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'MA20' })
    if (showMA60)  addLine(get('MA60'),  { color: '#818cf8', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'MA60' })
    if (showMA200) addLine(get('MA200'), { color: '#38bdf8', lineWidth: 1, lineStyle: 1, priceLineVisible: false, lastValueVisible: true, title: 'MA200' })
    if (showBB) {
      addLine(get('BB_UPPER'), { color: 'rgba(248,113,113,0.55)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, title: 'BB+' })
      addLine(get('BB_LOWER'), { color: 'rgba(74,222,128,0.55)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, title: 'BB-' })
    }

    // ── 成交量（主面板底部 15%,依開關）────────────────────────────
    if (showVol) {
      const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'vol' })
      chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } })
      vol.setData(prices.map(p => ({
        time: p.date, value: p.volume,
        color: p.close >= p.open ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)',
      })))
    }

    // ── RSI / MACD 子面板（共用時間軸;pane 索引動態連續,避免空面板）──
    let nextPane = 1
    if (showRSI) {
      const rsiData = get('RSI')
      if (rsiData.length) {
        const pane = nextPane++
        const rsi = chart.addSeries(LineSeries, {
          color: '#34d399', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'RSI',
          // RSI 依定義為 0~100 → 釘死刻度,不要 autoscale(否則會被壓扁、30/70 線位置飄移)
          autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
        }, pane)
        rsi.setData(rsiData)
        rsi.createPriceLine({ price: 70, color: 'rgba(239,68,68,0.6)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '70' })
        rsi.createPriceLine({ price: 30, color: 'rgba(34,197,94,0.6)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '30' })
      }
    }
    if (showMACD && hasInd) {
      const histData = indicators.filter(d => d.HIST != null).map(d => ({
        time: d.date, value: d.HIST,
        color: d.HIST >= 0 ? 'rgba(34,197,94,0.6)' : 'rgba(239,68,68,0.6)',
      }))
      const macdData = get('MACD')
      if (histData.length || macdData.length) {
        const pane = nextPane++
        if (histData.length) chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false, title: '柱' }, pane).setData(histData)
        if (macdData.length) chart.addSeries(LineSeries, { color: '#60a5fa', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'MACD' }, pane).setData(macdData)
        const signalData = get('SIGNAL')
        if (signalData.length) chart.addSeries(LineSeries, { color: '#f97316', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, title: '訊號' }, pane).setData(signalData)
      }
    }

    // ── 買賣標記（依開關）─────────────────────────────────────────
    if (showMarkers && trades && trades.length > 0) {
      const markers = []
      trades.forEach(t => {
        if (t.entry_date) markers.push({ time: t.entry_date, position: 'belowBar', color: '#22c55e', shape: 'arrowUp', text: `買入 $${Number(t.entry_price).toFixed(0)}` })
        if (t.exit_date)  markers.push({ time: t.exit_date, position: 'aboveBar', color: t.profit ? '#60a5fa' : '#ef4444', shape: 'arrowDown', text: `${t.profit ? '獲利' : '停損'} ${t.return_pct > 0 ? '+' : ''}${t.return_pct}%` })
      })
      markers.sort((a, b) => a.time.localeCompare(b.time))
      createSeriesMarkers(candleSeries, markers)
    }

    // 面板高度需等版面計算完成（此刻 pane 高度仍為 0）→ 延到下一 frame 再設
    const raf = requestAnimationFrame(() => {
      try {
        const panes = chart.panes()
        for (let i = 1; i < nextPane; i++) if (panes[i]) panes[i].setHeight(150)
      } catch { /* 舊版 lightweight-charts 無 panes API */ }
    })

    chart.timeScale().scrollToPosition(-5, false)

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth })
    }
    window.addEventListener('resize', handleResize)
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', handleResize); chart.remove() }
  }, [prices, indicators, trades, showMA20, showMA60, showMA200, showBB, showVol, showRSI, showMACD, showMarkers])

  if (!prices || prices.length === 0) return <div className="chart-empty">載入中…</div>

  return (
    <div style={{ position: 'relative' }}>
      {/* 圖層開關：所有指標一次都在同一面板,點按即開/關 */}
      <div className="chart-toolbar">
        <span className="toolbar-lbl">圖層：</span>
        <Toggle on={showMA20}    onClick={() => setShowMA20(v => !v)}    color="#f59e0b">MA20</Toggle>
        <Toggle on={showMA60}    onClick={() => setShowMA60(v => !v)}    color="#818cf8">MA60</Toggle>
        <Toggle on={showMA200}   onClick={() => setShowMA200(v => !v)}   color="#38bdf8">MA200</Toggle>
        <Toggle on={showBB}      onClick={() => setShowBB(v => !v)}      color="#f87171">布林帶</Toggle>
        <Toggle on={showVol}     onClick={() => setShowVol(v => !v)}     color="#94a3b8">成交量</Toggle>
        <Toggle on={showRSI}     onClick={() => setShowRSI(v => !v)}     color="#34d399">RSI</Toggle>
        <Toggle on={showMACD}    onClick={() => setShowMACD(v => !v)}    color="#60a5fa">MACD</Toggle>
        <Toggle on={showMarkers} onClick={() => setShowMarkers(v => !v)} color="#22c55e">買賣標記</Toggle>
      </div>
      <div ref={containerRef} className="candlestick-wrap" />
    </div>
  )
}
