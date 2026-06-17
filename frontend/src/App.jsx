/**
 * App.jsx — 應用程式根元件
 *
 * 兩種模式（view state）：
 *   'overview'  市場總覽：顯示所有 15 個幣種的訊號摘要表
 *   'detail'    幣種詳細：顯示單一幣種的蠟燭圖、情緒、回測等
 *
 * 狀態說明：
 *   view        目前顯示模式（'overview' | 'detail'）
 *   active      目前選中的幣種（detail 模式下使用）
 *   days        蠟燭圖顯示天數（1M / 3M / 6M / 1Y）
 *   signals     所有幣種的訊號陣列
 *   ohlc        當前幣種的 OHLC 資料（蠟燭圖用）
 *   indicators  當前幣種的技術指標（均線 / RSI / MACD）
 *   backtest    當前幣種的回測結果（買賣標記用）
 *   correlation 相關性矩陣（只載入一次）
 */
import { useState, useEffect } from 'react'
import {
  fetchSymbols, fetchAllSignals, fetchOHLC,
  fetchIndicators, fetchCorrelation, fetchBacktest,
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
import { coinName }     from './constants/coins'

const DAY_OPTIONS = [
  { label: '1M', value: 30  },
  { label: '3M', value: 90  },
  { label: '6M', value: 180 },
  { label: '1Y', value: 365 },
]

export default function App() {
  const [symbols,     setSymbols]     = useState([])
  const [view,        setView]        = useState('overview')   // 預設先顯示總覽
  const [active,      setActive]      = useState('BTCUSDT')
  const [days,        setDays]        = useState(180)
  const [signals,     setSignals]     = useState([])
  const [ohlc,        setOhlc]        = useState([])
  const [indicators,  setIndicators]  = useState([])
  const [backtest,    setBacktest]    = useState(null)
  const [correlation, setCorrelation] = useState(null)
  const [showIndicators,  setShowIndicators]  = useState(false)
  const [showCorrelation, setShowCorrelation] = useState(false)

  // 頁面載入：取幣種清單、所有訊號、相關性矩陣
  useEffect(() => {
    fetchSymbols().then(setSymbols).catch(() => {})
    fetchAllSignals().then(setSignals).catch(() => {})
    fetchCorrelation().then(setCorrelation).catch(() => {})
  }, [])

  // 切換幣種或天數：重新載入蠟燭圖、技術指標、回測買賣點
  useEffect(() => {
    if (view !== 'detail') return
    setOhlc([])
    setIndicators([])
    fetchOHLC(active, days).then(setOhlc).catch(() => {})
    fetchIndicators(active, days).then(setIndicators).catch(() => {})
    fetchBacktest(active).then(setBacktest).catch(() => {})
  }, [active, days, view])

  // 從總覽點選幣種 → 切換到詳細頁
  const handleSelectCoin = (symbol) => {
    setActive(symbol)
    setView('detail')
  }

  const activeSignal = signals.find(s => s.symbol === active)

  return (
    <div className="app">
      <header className="header">
        <span className="logo">📈 Crypto Quant</span>
        <nav className="header-nav">
          {/* 總覽 / 詳細 切換 */}
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

      {/* ── 市場總覽模式 ─────────────────────────────────────────────────── */}
      {view === 'overview' && (
        <div className="overview-layout">
          <MarketOverview signals={signals} onSelect={handleSelectCoin} />
        </div>
      )}

      {/* ── 幣種詳細模式 ─────────────────────────────────────────────────── */}
      {view === 'detail' && (
        <div className="app-layout">
          <CoinSidebar
            symbols={symbols}
            signals={signals}
            active={active}
            onSelect={handleSelectCoin}
          />

          <main className="main-content">

            {/* 大訊號卡 */}
            <HeroSignal signal={activeSignal} symbol={active} />

            {/* 蠟燭圖 + 時間切換 */}
            <section className="chart-section">
              <div className="chart-section-header">
                <span className="chart-section-title">{coinName(active)} 蠟燭圖</span>
                <div className="day-tabs">
                  {DAY_OPTIONS.map(opt => (
                    <button
                      key={opt.value}
                      className={`day-tab ${days === opt.value ? 'active' : ''}`}
                      onClick={() => setDays(opt.value)}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
              {/* 傳入 OHLC 資料與回測買賣點，蠟燭圖上會顯示標記 */}
              <CandlestickChart
                prices={ohlc}
                trades={backtest?.recent_trades ?? []}
              />
            </section>

            {/* 市場情緒 */}
            <SentimentPanel symbol={active} />

            {/* 回測績效 */}
            <BacktestPanel symbol={active} />

            {/* RSI / MACD（折疊） */}
            <section className="collapsible-section">
              <button
                className="collapse-toggle"
                onClick={() => setShowIndicators(v => !v)}
              >
                <span>技術指標細節（RSI / MACD）</span>
                <span className="collapse-arrow">{showIndicators ? '▲' : '▼'}</span>
              </button>
              {showIndicators && <IndicatorChart data={indicators} symbol={active} />}
            </section>

            {/* 相關性（折疊） */}
            <section className="collapsible-section">
              <button
                className="collapse-toggle"
                onClick={() => setShowCorrelation(v => !v)}
              >
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
