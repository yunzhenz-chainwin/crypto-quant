/**
 * App.jsx — 應用程式根元件
 *
 * 兩種模式：
 *   'overview'  市場總覽：卡片網格 + 頂部摘要列
 *   'detail'    幣種詳細：蠟燭圖、回測、情緒、指標
 *
 * 自動刷新：每 5 分鐘重新拉 signals + fearGreed
 */
import { useState, useEffect, useCallback } from 'react'
import {
  fetchSymbols, fetchAllSignals, fetchOHLC,
  fetchIndicators, fetchCorrelation, fetchBacktest, fetchFearGreed,
} from './api/client'
import StatusBar        from './components/StatusBar'
import CandlestickChart from './components/CandlestickChart'
import IndicatorChart   from './components/IndicatorChart'
import CorrelationHeatmap from './components/CorrelationHeatmap'
import BacktestPanel    from './components/BacktestPanel'
import CoinSidebar      from './components/CoinSidebar'
import HeroSignal       from './components/HeroSignal'
import SentimentPanel   from './components/SentimentPanel'
import MarketOverview   from './components/MarketOverview'
import MarketSummary    from './components/MarketSummary'
import { coinName }     from './constants/coins'

const DAY_OPTIONS = [
  { label: '1M', value: 30  },
  { label: '3M', value: 90  },
  { label: '6M', value: 180 },
  { label: '1Y', value: 365 },
  { label: '全部', value: 1825 },
]
const REFRESH_INTERVAL = 5 * 60 * 1000  // 5 分鐘

// 工具：日期物件 → "YYYY-MM-DD"
function toDateStr(d) {
  return d.toISOString().slice(0, 10)
}
const TODAY = toDateStr(new Date())

export default function App() {
  const [symbols,     setSymbols]     = useState([])
  const [view,        setView]        = useState('overview')
  const [active,      setActive]      = useState('BTCUSDT')
  const [days,        setDays]        = useState(180)
  const [dateMode,    setDateMode]    = useState('preset')   // 'preset' | 'custom'
  const [startDate,   setStartDate]   = useState('')
  const [endDate,     setEndDate]     = useState(TODAY)
  const [pendingStart, setPendingStart] = useState('')
  const [pendingEnd,   setPendingEnd]   = useState(TODAY)
  const [signals,     setSignals]     = useState([])
  const [fearGreed,   setFearGreed]   = useState(null)
  const [lastUpdated, setLastUpdated] = useState(0)
  const [refreshing,  setRefreshing]  = useState(false)
  const [ohlc,        setOhlc]        = useState([])
  const [indicators,  setIndicators]  = useState([])
  const [backtest,    setBacktest]    = useState(null)
  const [correlation, setCorrelation] = useState(null)
  const [showIndicators,  setShowIndicators]  = useState(false)
  const [showCorrelation, setShowCorrelation] = useState(false)

  // 刷新市場摘要資料（訊號 + 恐懼貪婪）
  const refreshMarket = useCallback(async (showSpinner = true) => {
    if (showSpinner) setRefreshing(true)
    try {
      const [sigs, fg] = await Promise.all([
        fetchAllSignals(),
        fetchFearGreed(1),
      ])
      setSignals(sigs)
      setFearGreed(fg?.[0] ?? null)
      setLastUpdated(Date.now())
    } catch (_) {}
    if (showSpinner) setRefreshing(false)
  }, [])

  // 頁面載入：初始化所有資料
  useEffect(() => {
    fetchSymbols().then(setSymbols).catch(() => {})
    fetchCorrelation().then(setCorrelation).catch(() => {})
    refreshMarket(false)
  }, [refreshMarket])

  // 每 5 分鐘自動刷新市場摘要
  useEffect(() => {
    const id = setInterval(() => refreshMarket(false), REFRESH_INTERVAL)
    return () => clearInterval(id)
  }, [refreshMarket])

  // 切換幣種 / 天數 / 日期範圍 → 載入詳細頁資料
  useEffect(() => {
    if (view !== 'detail') return
    setOhlc([])
    setIndicators([])
    const opts = dateMode === 'custom' && startDate && endDate
      ? { start: startDate, end: endDate }
      : { days }
    fetchOHLC(active, opts).then(setOhlc).catch(() => {})
    fetchIndicators(active, opts).then(setIndicators).catch(() => {})
    fetchBacktest(active).then(setBacktest).catch(() => {})
  }, [active, days, startDate, endDate, dateMode, view])

  const handleSelectCoin = (symbol) => {
    setActive(symbol)
    setView('detail')
  }

  const activeSignal = signals.find(s => s.symbol === active)

  return (
    <div className="app">

      {/* ── Header ────────────────────────────────────────────────────── */}
      <header className="header">
        <span className="logo">📈 Crypto Quant</span>
        <nav className="header-nav">
          <button
            className={`nav-btn ${view === 'overview' ? 'active' : ''}`}
            onClick={() => setView('overview')}
          >
            市場總覽
          </button>
          <button
            className={`nav-btn ${view === 'detail' ? 'active' : ''}`}
            onClick={() => setView('detail')}
          >
            {coinName(active)}
          </button>
        </nav>
        <StatusBar />
      </header>

      {/* ── 市場摘要列（兩個模式都顯示）────────────────────────────────── */}
      <MarketSummary
        signals={signals}
        fearGreed={fearGreed}
        lastUpdated={lastUpdated}
        onRefresh={() => refreshMarket(true)}
        refreshing={refreshing}
      />

      {/* ── 市場總覽模式 ────────────────────────────────────────────────── */}
      {view === 'overview' && (
        <div className="overview-layout">
          <MarketOverview signals={signals} onSelect={handleSelectCoin} />
        </div>
      )}

      {/* ── 幣種詳細模式 ────────────────────────────────────────────────── */}
      {view === 'detail' && (
        <div className="app-layout">
          <CoinSidebar
            symbols={symbols}
            signals={signals}
            active={active}
            onSelect={handleSelectCoin}
          />

          <main className="main-content">
            <HeroSignal signal={activeSignal} symbol={active} />

            <section className="chart-section">
              <div className="chart-section-header">
                <span className="chart-section-title">{coinName(active)} 蠟燭圖</span>

                <div className="range-controls">
                  {/* 快速預設按鈕 */}
                  <div className="day-tabs">
                    {DAY_OPTIONS.map(opt => (
                      <button
                        key={opt.value}
                        className={`day-tab ${dateMode === 'preset' && days === opt.value ? 'active' : ''}`}
                        onClick={() => { setDays(opt.value); setDateMode('preset') }}
                      >
                        {opt.label}
                      </button>
                    ))}
                    {/* 自訂日期切換 */}
                    <button
                      className={`day-tab ${dateMode === 'custom' ? 'active' : ''}`}
                      onClick={() => {
                        setDateMode(m => m === 'custom' ? 'preset' : 'custom')
                        if (!pendingStart) {
                          const d = new Date(); d.setMonth(d.getMonth() - 6)
                          setPendingStart(toDateStr(d))
                        }
                      }}
                    >
                      📅 自訂
                    </button>
                  </div>

                  {/* 自訂日期面板 */}
                  {dateMode === 'custom' && (
                    <div className="date-range-panel">
                      <label className="dr-label">從</label>
                      <input
                        type="date"
                        className="dr-input"
                        value={pendingStart}
                        min="2021-01-01"
                        max={pendingEnd || TODAY}
                        onChange={e => setPendingStart(e.target.value)}
                      />
                      <label className="dr-label">到</label>
                      <input
                        type="date"
                        className="dr-input"
                        value={pendingEnd}
                        min={pendingStart || "2021-01-01"}
                        max={TODAY}
                        onChange={e => setPendingEnd(e.target.value)}
                      />
                      <button
                        className="dr-apply"
                        disabled={!pendingStart || !pendingEnd}
                        onClick={() => { setStartDate(pendingStart); setEndDate(pendingEnd) }}
                      >
                        套用
                      </button>
                    </div>
                  )}
                </div>
              </div>
              <CandlestickChart
                prices={ohlc}
                indicators={indicators}
                trades={backtest?.recent_trades ?? []}
              />
            </section>

            <SentimentPanel symbol={active} />
            <BacktestPanel symbol={active} />

            <section className="collapsible-section">
              <button className="collapse-toggle" onClick={() => setShowIndicators(v => !v)}>
                <span>技術指標細節（RSI / MACD）</span>
                <span className="collapse-arrow">{showIndicators ? '▲' : '▼'}</span>
              </button>
              {showIndicators && <IndicatorChart data={indicators} symbol={active} />}
            </section>

            <section className="collapsible-section">
              <button className="collapse-toggle" onClick={() => setShowCorrelation(v => !v)}>
                <span>幣種相關性分析</span>
                <span className="collapse-arrow">{showCorrelation ? '▲' : '▼'}</span>
              </button>
              {showCorrelation && (
                <div className="correlation-body">
                  <CorrelationHeatmap data={correlation} />
                </div>
              )}
            </section>
          </main>
        </div>
      )}

    </div>
  )
}
