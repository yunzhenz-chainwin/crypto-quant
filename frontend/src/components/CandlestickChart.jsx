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

// ── 前端指標計算 ────────────────────────────────────────────────────────────
// 簡單移動平均：回傳 [{time, value}]
function sma(prices, period) {
  const out = []
  let sum = 0
  const q = []
  for (const p of prices) {
    q.push(p.close); sum += p.close
    if (q.length > period) sum -= q.shift()
    if (q.length === period) out.push({ time: p.date, value: sum / period })
  }
  return out
}

// KDJ（9 日）：RSV → K(快) → D(慢) → J=3K-2D，K/D 起始 50
function kdj(prices, n = 9) {
  const out = []
  let prevK = 50, prevD = 50
  for (let i = 0; i < prices.length; i++) {
    if (i < n - 1) continue
    let hi = -Infinity, lo = Infinity
    for (let j = i - n + 1; j <= i; j++) {
      if (prices[j].high > hi) hi = prices[j].high
      if (prices[j].low  < lo) lo = prices[j].low
    }
    const rsv = hi > lo ? ((prices[i].close - lo) / (hi - lo)) * 100 : 50
    const k = (2 / 3) * prevK + (1 / 3) * rsv
    const d = (2 / 3) * prevD + (1 / 3) * k
    prevK = k; prevD = d
    out.push({ time: prices[i].date, k, d, j: 3 * k - 2 * d })
  }
  return out
}

// DMI（14 期，Wilder 平滑）：+DI/-DI/ADX
function dmi(prices, n = 14) {
  const L = prices.length
  if (L < 2 * n) return []
  const tr = new Array(L).fill(0), pdm = new Array(L).fill(0), mdm = new Array(L).fill(0)
  for (let i = 1; i < L; i++) {
    const h = prices[i].high, l = prices[i].low, pc = prices[i - 1].close, ph = prices[i - 1].high, pl = prices[i - 1].low
    tr[i] = Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc))
    const up = h - ph, dn = pl - l
    pdm[i] = (up > dn && up > 0) ? up : 0
    mdm[i] = (dn > up && dn > 0) ? dn : 0
  }
  let str = 0, spd = 0, smd = 0
  const pdiArr = new Array(L).fill(null), mdiArr = new Array(L).fill(null), dx = new Array(L).fill(null)
  for (let i = 1; i < L; i++) {
    if (i <= n) { str += tr[i]; spd += pdm[i]; smd += mdm[i] }
    else { str = str - str / n + tr[i]; spd = spd - spd / n + pdm[i]; smd = smd - smd / n + mdm[i] }
    if (i >= n && str > 0) {
      const pdi = 100 * spd / str, mdi = 100 * smd / str
      pdiArr[i] = pdi; mdiArr[i] = mdi
      dx[i] = (pdi + mdi) === 0 ? 0 : 100 * Math.abs(pdi - mdi) / (pdi + mdi)
    }
  }
  const adx = new Array(L).fill(null)
  const start = 2 * n - 1
  if (start < L && dx[n] != null) {
    let sum = 0
    for (let i = n; i <= start; i++) sum += (dx[i] || 0)
    adx[start] = sum / n
    for (let i = start + 1; i < L; i++) adx[i] = (adx[i - 1] * (n - 1) + (dx[i] || 0)) / n
  }
  const out = []
  for (let i = 0; i < L; i++) {
    if (pdiArr[i] != null) out.push({ time: prices[i].date, pdi: pdiArr[i], mdi: mdiArr[i], adx: adx[i] })
  }
  return out
}

// BIAS 乖離率：(收盤 − MA) / MA × 100
function bias(prices, period) {
  const out = []
  let sum = 0
  const q = []
  for (const p of prices) {
    q.push(p.close); sum += p.close
    if (q.length > period) sum -= q.shift()
    if (q.length === period) {
      const ma = sum / period
      out.push({ time: p.date, value: ma === 0 ? 0 : (p.close - ma) / ma * 100 })
    }
  }
  return out
}

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

// 可調天數的均線開關（開關 + 數字輸入框）
function MAToggle({ label, period, setPeriod, on, toggle, color }) {
  return (
    <span className="ma-toggle">
      <button
        className={`layer-toggle ${on ? 'on' : ''}`}
        style={{ color: on ? color : '#64748b', borderColor: on ? color : 'var(--border)' }}
        onClick={toggle}
      >
        {on ? '●' : '○'} {label}
      </button>
      <input
        type="number" className="ma-period" value={period} min={2} max={250}
        onChange={e => {
          const v = parseInt(e.target.value, 10)
          if (Number.isFinite(v)) setPeriod(Math.max(2, Math.min(250, v)))
        }}
      />
    </span>
  )
}

const OSC_LIST = ['RSI', 'MACD', 'KDJ', 'DMI', 'BIAS', '無']

export default function CandlestickChart({ prices, indicators, trades }) {
  const containerRef = useRef(null)
  const [fastP,   setFastP]   = useState(5)
  const [slowP,   setSlowP]   = useState(20)
  const [showFast, setShowFast] = useState(true)
  const [showSlow, setShowSlow] = useState(true)
  const [showMA200, setShowMA200] = useState(false)
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
    if (showFast)  addLine(sma(prices, fastP), { color: '#f59e0b', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: `快線MA${fastP}` })
    if (showSlow)  addLine(sma(prices, slowP), { color: '#818cf8', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: `慢線MA${slowP}` })
    if (showMA200) addLine(sma(prices, 200),   { color: '#38bdf8', lineWidth: 1, lineStyle: 1, priceLineVisible: false, lastValueVisible: true, title: 'MA200' })
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
  }, [prices, indicators, trades, fastP, slowP, showFast, showSlow, showMA200, showBB, showVol, showMarkers, osc])

  if (!prices || prices.length === 0) return <div className="chart-empty">載入中…</div>

  return (
    <div style={{ position: 'relative' }}>
      <div className="chart-toolbar">
        <span className="toolbar-lbl">圖層：</span>
        <MAToggle label="快線" period={fastP} setPeriod={setFastP} on={showFast} toggle={() => setShowFast(v => !v)} color="#f59e0b" />
        <MAToggle label="慢線" period={slowP} setPeriod={setSlowP} on={showSlow} toggle={() => setShowSlow(v => !v)} color="#818cf8" />
        <Toggle on={showMA200}   onClick={() => setShowMA200(v => !v)}   color="#38bdf8">MA200</Toggle>
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
