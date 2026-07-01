/**
 * CandlestickChart.jsx — 整合圖表面板(方案 B:主圖 + 單一擺盪指標槽)
 * 使用 lightweight-charts v5（多面板 pane 共用時間軸/游標/縮放）
 *
 * 主圖疊層(可逐一開關):快線/慢線 MA(天數可調)、MA200、布林帶、成交量、買賣標記
 * 擺盪指標槽(只留一個副面板,用分頁切換):RSI / MACD / KDJ / DMI / BIAS / 無
 *
 * 指標來源:MA(快/慢/200)、KDJ/DMI/BIAS → 前端算;布林帶/RSI/MACD → 後端 indicators。
 *
 * Props：prices（OHLCV）、indicators（含 BB/RSI/MACD…）、trades（回測交易）
 */
import { useEffect, useRef, useState } from 'react'
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries,
  CrosshairMode, createSeriesMarkers,
} from 'lightweight-charts'
import { movingAvg, kdj, dmi, bias } from '../lib/indicators'

// 一般圖層開關按鈕
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

// 單條可調均線控制（開關點 + 天數輸入框;顏色對應圖上的線）
function MALine({ ma, onToggle, onPeriod }) {
  return (
    <span className="ma-toggle">
      <button
        className={`layer-toggle ${ma.on ? 'on' : ''}`}
        style={{ color: ma.on ? ma.color : '#64748b', borderColor: ma.on ? ma.color : 'var(--border)' }}
        onClick={onToggle}
      >
        {ma.on ? '●' : '○'}
      </button>
      <input
        type="number" className="ma-period" value={ma.p} min={2} max={250}
        onChange={e => {
          const v = parseInt(e.target.value, 10)
          if (Number.isFinite(v)) onPeriod(Math.max(2, Math.min(250, v)))
        }}
      />
    </span>
  )
}

const OSC_LIST = ['RSI', 'MACD', 'KDJ', 'DMI', 'BIAS', '無']

export default function CandlestickChart({ prices, indicators, trades }) {
  const containerRef = useRef(null)
  const [maType, setMaType] = useState('EMA')   // 均線類型:SMA / EMA
  // 多條可調均線(天數可改、可逐條開關;顏色對應圖上的線)
  const [mas, setMas] = useState([
    { p: 5,   on: true,  color: '#f59e0b' },
    { p: 10,  on: true,  color: '#22d3ee' },
    { p: 20,  on: true,  color: '#818cf8' },
    { p: 60,  on: false, color: '#38bdf8' },
    { p: 120, on: false, color: '#ec4899' },
  ])
  const [showBB,   setShowBB]   = useState(true)
  const [showVol,  setShowVol]  = useState(true)
  const [showMarkers, setShowMarkers] = useState(true)
  const [osc, setOsc] = useState('RSI')   // 單一擺盪指標槽

  useEffect(() => {
    if (!containerRef.current || !prices || prices.length === 0) return

    const oscOn = osc !== '無'
    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#0f172a' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155', timeVisible: true, secondsVisible: false },
      width: containerRef.current.clientWidth,
      height: oscOn ? 560 : 420,
    })

    // ── 蠟燭圖（主面板）─────────────────────────────────────────────
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e', downColor: '#ef4444', borderVisible: false,
      wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    })
    candleSeries.setData(prices.map(p => ({
      time: p.date, open: p.open, high: p.high, low: p.low, close: p.close,
    })))

    const hasInd = indicators && indicators.length > 0
    const getInd = (key) => hasInd
      ? indicators.filter(d => d[key] != null).map(d => ({ time: d.date, value: d[key] }))
      : []
    const addLine = (data, opts) => { if (data.length) chart.addSeries(LineSeries, opts).setData(data) }
    const pin100 = () => ({ priceRange: { minValue: 0, maxValue: 100 } })

    // ── 均線（可調天數）+ 布林帶 + 成交量（主面板）────────────────
    mas.forEach(ma => {
      if (ma.on) addLine(movingAvg(prices, ma.p, maType), { color: ma.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: `${maType}${ma.p}` })
    })
    if (showBB) {
      addLine(getInd('BB_UPPER'), { color: 'rgba(248,113,113,0.55)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, title: 'BB+' })
      addLine(getInd('BB_LOWER'), { color: 'rgba(74,222,128,0.55)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, title: 'BB-' })
    }
    if (showVol) {
      const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'vol' })
      chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } })
      vol.setData(prices.map(p => ({
        time: p.date, value: p.volume,
        color: p.close >= p.open ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)',
      })))
    }

    // ── 單一擺盪指標副面板（pane 1;由 osc 決定顯示哪一個）──────────
    if (oscOn) {
      const pane = 1
      if (osc === 'RSI') {
        const rsiData = getInd('RSI')
        if (rsiData.length) {
          const rsi = chart.addSeries(LineSeries, { color: '#34d399', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'RSI', autoscaleInfoProvider: pin100 }, pane)
          rsi.setData(rsiData)
          rsi.createPriceLine({ price: 70, color: 'rgba(239,68,68,0.6)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '70' })
          rsi.createPriceLine({ price: 30, color: 'rgba(34,197,94,0.6)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '30' })
        }
      } else if (osc === 'MACD' && hasInd) {
        const histData = indicators.filter(d => d.HIST != null).map(d => ({ time: d.date, value: d.HIST, color: d.HIST >= 0 ? 'rgba(34,197,94,0.6)' : 'rgba(239,68,68,0.6)' }))
        if (histData.length) chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false, title: '柱' }, pane).setData(histData)
        const macdData = getInd('MACD')
        if (macdData.length) chart.addSeries(LineSeries, { color: '#60a5fa', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'MACD' }, pane).setData(macdData)
        const signalData = getInd('SIGNAL')
        if (signalData.length) chart.addSeries(LineSeries, { color: '#f97316', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, title: '訊號' }, pane).setData(signalData)
      } else if (osc === 'KDJ') {
        const kd = kdj(prices, 9)
        if (kd.length) {
          const kS = chart.addSeries(LineSeries, { color: '#eab308', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'K', autoscaleInfoProvider: pin100 }, pane)
          kS.setData(kd.map(x => ({ time: x.time, value: x.k })))
          kS.createPriceLine({ price: 80, color: 'rgba(239,68,68,0.6)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '80' })
          kS.createPriceLine({ price: 20, color: 'rgba(34,197,94,0.6)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '20' })
          chart.addSeries(LineSeries, { color: '#22d3ee', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'D', autoscaleInfoProvider: pin100 }, pane).setData(kd.map(x => ({ time: x.time, value: x.d })))
          chart.addSeries(LineSeries, { color: '#f472b6', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'J', autoscaleInfoProvider: pin100 }, pane).setData(kd.map(x => ({ time: x.time, value: x.j })))
        }
      } else if (osc === 'DMI') {
        const dm = dmi(prices, 14)
        if (dm.length) {
          chart.addSeries(LineSeries, { color: '#22c55e', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: '+DI', autoscaleInfoProvider: pin100 }, pane).setData(dm.map(x => ({ time: x.time, value: x.pdi })))
          chart.addSeries(LineSeries, { color: '#ef4444', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: '-DI', autoscaleInfoProvider: pin100 }, pane).setData(dm.map(x => ({ time: x.time, value: x.mdi })))
          const adxS = chart.addSeries(LineSeries, { color: '#eab308', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true, title: 'ADX', autoscaleInfoProvider: pin100 }, pane)
          adxS.setData(dm.filter(x => x.adx != null).map(x => ({ time: x.time, value: x.adx })))
          adxS.createPriceLine({ price: 25, color: 'rgba(148,163,184,0.6)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '25' })
        }
      } else if (osc === 'BIAS') {
        const b6 = bias(prices, 6), b24 = bias(prices, 24)
        if (b6.length) {
          const s = chart.addSeries(LineSeries, { color: '#fb923c', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'BIAS6' }, pane)
          s.setData(b6)
          s.createPriceLine({ price: 0, color: 'rgba(148,163,184,0.5)', lineWidth: 1, lineStyle: 2, axisLabelVisible: false })
        }
        if (b24.length) chart.addSeries(LineSeries, { color: '#60a5fa', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'BIAS24' }, pane).setData(b24)
      }
    }

    // ── 買賣標記 ─────────────────────────────────────────────────
    if (showMarkers && trades && trades.length > 0) {
      const markers = []
      trades.forEach(t => {
        if (t.entry_date) markers.push({ time: t.entry_date, position: 'belowBar', color: '#22c55e', shape: 'arrowUp', text: `買入 $${Number(t.entry_price).toFixed(0)}` })
        if (t.exit_date)  markers.push({ time: t.exit_date, position: 'aboveBar', color: t.profit ? '#60a5fa' : '#ef4444', shape: 'arrowDown', text: `${t.profit ? '獲利' : '停損'} ${t.return_pct > 0 ? '+' : ''}${t.return_pct}%` })
      })
      markers.sort((a, b) => a.time.localeCompare(b.time))
      createSeriesMarkers(candleSeries, markers)
    }

    // 擺盪副面板高度(等版面算完再設)
    const raf = requestAnimationFrame(() => {
      try {
        const panes = chart.panes()
        if (oscOn && panes[1]) panes[1].setHeight(160)
      } catch { /* 舊版無 panes API */ }
    })

    chart.timeScale().scrollToPosition(-5, false)

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth })
    }
    window.addEventListener('resize', handleResize)
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', handleResize); chart.remove() }
  }, [prices, indicators, trades, maType, mas, showBB, showVol, showMarkers, osc])

  if (!prices || prices.length === 0) return <div className="chart-empty">載入中…</div>

  return (
    <div style={{ position: 'relative' }}>
      <div className="chart-toolbar">
        <span className="toolbar-lbl">圖層：</span>
        <button className="matype-btn" onClick={() => setMaType(t => t === 'SMA' ? 'EMA' : 'SMA')} title="切換 簡單(SMA)/指數(EMA) 移動平均">均線:{maType}</button>
        {mas.map((ma, i) => (
          <MALine
            key={i} ma={ma}
            onToggle={() => setMas(arr => arr.map((m, j) => j === i ? { ...m, on: !m.on } : m))}
            onPeriod={p => setMas(arr => arr.map((m, j) => j === i ? { ...m, p } : m))}
          />
        ))}
        <Toggle on={showBB}      onClick={() => setShowBB(v => !v)}      color="#f87171">布林帶</Toggle>
        <Toggle on={showVol}     onClick={() => setShowVol(v => !v)}     color="#94a3b8">成交量</Toggle>
        <Toggle on={showMarkers} onClick={() => setShowMarkers(v => !v)} color="#22c55e">買賣標記</Toggle>
        <span className="osc-selector">
          <span className="osc-lbl">擺盪：</span>
          {OSC_LIST.map(o => (
            <button key={o} className={`osc-tab ${osc === o ? 'active' : ''}`} onClick={() => setOsc(o)}>{o}</button>
          ))}
        </span>
      </div>
      <div ref={containerRef} className="candlestick-wrap" />
    </div>
  )
}
