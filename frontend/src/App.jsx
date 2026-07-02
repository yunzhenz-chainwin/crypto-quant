/**
 * App.jsx — 應用程式根元件
 *
 * 兩種模式：
 *   'overview'  市場總覽：卡片網格 + 頂部摘要列
 *   'detail'    幣種詳細：蠟燭圖（日線/時線）、AI 分析、回測、情緒、指標
 *
 * 自動更新（不用手動重整）：
 *   每 60 秒輪詢 /api/status 的 data_version（各週期最新 K 棒時間戳），
 *   有變化才重拉 訊號/恐懼貪婪/當前圖表資料/AI 分析；分頁切回前景時也立即檢查。
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  fetchSymbols, fetchAllSignals, fetchOHLC, fetchStatus, fetchIntervals,
  fetchIndicators, fetchCorrelation, fetchBacktest, fetchFearGreed,
} from './api/client'
import StatusBar        from './components/StatusBar'
import CandlestickChart from './components/CandlestickChart'
import CorrelationHeatmap from './components/CorrelationHeatmap'
import BacktestPanel    from './components/BacktestPanel'
import CoinSidebar      from './components/CoinSidebar'
import HeroSignal       from './components/HeroSignal'
import SentimentPanel   from './components/SentimentPanel'
import MarketOverview   from './components/MarketOverview'
import MarketSummary    from './components/MarketSummary'
import AIAnalystPanel   from './components/AIAnalystPanel'
import BotWidget        from './components/BotWidget'
import OnboardingTour   from './components/OnboardingTour'
import GlossaryModal    from './components/GlossaryModal'
import { coinName }     from './constants/coins'

// 日線的區間預設（單位：天）
const DAY_OPTIONS = [
  { label: '1M', value: 30  },
  { label: '3M', value: 90  },
  { label: '6M', value: 180 },
  { label: '1Y', value: 365 },
  { label: '全部', value: 1825 },
]
// 時線的區間預設（單位：天；後端會換算成 24 根/天）
const HOUR_OPTIONS = [
  { label: '24H', value: 1  },
  { label: '3D',  value: 3  },
  { label: '7D',  value: 7  },
  { label: '1M',  value: 30 },
  { label: '3M',  value: 90 },
]
const POLL_INTERVAL = 60 * 1000  // 資料版本輪詢：每 60 秒

// 工具：日期物件 → "YYYY-MM-DD"
function toDateStr(d) {
  return d.toISOString().slice(0, 10)
}
const TODAY = toDateStr(new Date())

export default function App() {
  const [symbols,     setSymbols]     = useState([])
  const [intervals,   setIntervals]   = useState({})        // {'1d': [...], '1h': [...]}
  const [view,        setView]        = useState('overview')
  const [active,      setActive]      = useState('BTCUSDT')
  const [interval,    setKInterval]   = useState('1d')      // K 線週期：1d 日線 / 1h 時線
  const [days,        setDays]        = useState(180)
  const [hourDays,    setHourDays]    = useState(7)         // 時線用的區間（天）
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
  const [btParams,    setBtParams]    = useState({ stopLoss: -0.06, takeProfit: 0.20, feeRate: 0.001, slippage: 0.0005 })
  const [btLoading,   setBtLoading]   = useState(false)
  const [correlation, setCorrelation] = useState(null)
  const [dataVersion, setDataVersion] = useState('')        // 後端資料版本（變了=有新資料）
  const [showCorrelation, setShowCorrelation] = useState(false)
  const [showSentiment,   setShowSentiment]   = useState(false)
  const [showBacktest,    setShowBacktest]    = useState(false)
  const [showAI,          setShowAI]          = useState(true)
  // 首次造訪自動開新手導覽；Header「❓ 導覽」可重看
  const [showTour, setShowTour] = useState(() => !localStorage.getItem('cq_tour_done'))
  const [showGlossary, setShowGlossary] = useState(false)
  const [apiError, setApiError] = useState(false)   // API 失敗橫幅（輕量版 #22）
  const versionRef = useRef('')

  // 這顆幣有沒有時線資料（目前只開 BTC/ETH）
  const hasHourly = (intervals['1h'] ?? []).includes(active)

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
      setApiError(false)
    } catch (_) {
      setApiError(true)      // 顯示錯誤橫幅（取代永遠的「載入中…」）
    }
    if (showSpinner) setRefreshing(false)
  }, [])

  // 載入詳細頁圖表資料。clear=false 用於背景自動更新：不清空舊圖、避免閃爍
  const loadDetail = useCallback(async (clear = true) => {
    if (clear) { setOhlc([]); setIndicators([]) }
    const opts = interval === '1h'
      ? { days: hourDays, interval: '1h' }
      : (dateMode === 'custom' && startDate && endDate
          ? { start: startDate, end: endDate }
          : { days })
    try {
      const [p, ind] = await Promise.all([
        fetchOHLC(active, opts),
        fetchIndicators(active, opts),
      ])
      setOhlc(p); setIndicators(ind)
      setApiError(false)
    } catch (_) {
      setApiError(true)
    }
  }, [active, interval, days, hourDays, startDate, endDate, dateMode])

  // 頁面載入：初始化所有資料
  useEffect(() => {
    fetchSymbols().then(setSymbols).catch(() => {})
    fetchIntervals().then(setIntervals).catch(() => {})
    fetchCorrelation().then(setCorrelation).catch(() => {})
    refreshMarket(false)
  }, [refreshMarket])

  // ── 自動更新核心：輪詢資料版本，有變化才重拉（不用手動重整）────────────────
  useEffect(() => {
    let stopped = false
    const check = async () => {
      try {
        const st = await fetchStatus()
        const ver = JSON.stringify(st.data_version ?? st.last_updated ?? {})
        if (!stopped && ver && versionRef.current && ver !== versionRef.current) {
          // 有新資料進來（每小時 K 棒 / 每日更新 / 新增幣種後）→ 全面刷新
          refreshMarket(false)
          fetchIntervals().then(setIntervals).catch(() => {})
          setDataVersion(ver)          // 傳給 AI 面板 & 觸發詳細頁重拉
        }
        if (ver) versionRef.current = ver
      } catch (_) {}
    }
    check()                                              // 啟動先記下目前版本
    const id = setInterval(check, POLL_INTERVAL)
    const onVisible = () => { if (!document.hidden) check() }
    document.addEventListener('visibilitychange', onVisible)
    return () => { stopped = true; clearInterval(id); document.removeEventListener('visibilitychange', onVisible) }
  }, [refreshMarket])

  // 資料版本變化 → 詳細頁背景更新圖表（不清空、不閃爍）。
  // 用 ref 持有最新的 loadDetail，避免它變身份時這個 effect 重複觸發多抓一次。
  const loadDetailRef = useRef(loadDetail)
  useEffect(() => { loadDetailRef.current = loadDetail }, [loadDetail])
  useEffect(() => {
    if (view === 'detail' && dataVersion) loadDetailRef.current(false)
  }, [dataVersion, view])

  // 保險絲：就算版本比對失敗，每 5 分鐘仍全量刷新一次摘要
  useEffect(() => {
    const id = setInterval(() => refreshMarket(false), 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [refreshMarket])

  // 切換幣種 / 週期 / 天數 / 日期範圍 → 重新載入詳細頁資料
  useEffect(() => {
    if (view !== 'detail') return
    loadDetail(true)
  }, [view, loadDetail])

  // 回測只與幣種 + 回測參數有關（與日期範圍無關），獨立抓一次；
  // K 線買賣標記與回測面板共用這一份，改參數時箭頭跟著變（消除原本各抓一次的雙抓）
  useEffect(() => {
    if (view !== 'detail' || !active) return
    let alive = true
    setBtLoading(true)
    setBacktest(null)
    fetchBacktest(active, btParams.stopLoss, btParams.takeProfit, btParams.feeRate, btParams.slippage)
      .then(r => { if (alive) setBacktest(r) })
      .catch(() => { if (alive) setBacktest(null) })
      .finally(() => { if (alive) setBtLoading(false) })
    return () => { alive = false }
  }, [active, btParams, view])

  const handleSelectCoin = (symbol) => {
    setActive(symbol)
    setView('detail')
    // 新幣種沒有時線資料時自動退回日線
    if (!(intervals['1h'] ?? []).includes(symbol)) setKInterval('1d')
  }

  const activeSignal = signals.find(s => s.symbol === active)
  const rangeOptions = interval === '1h' ? HOUR_OPTIONS : DAY_OPTIONS

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
          <button className="nav-btn" onClick={() => setShowGlossary(true)} title="名詞小辭典">
            📖 辭典
          </button>
          <button className="nav-btn" onClick={() => setShowTour(true)} title="重看新手導覽">
            ❓ 導覽
          </button>
        </nav>
        <StatusBar />
      </header>

      {/* ── 新手導覽（首次造訪自動開啟）／名詞辭典 ─────────────────────── */}
      {showTour && <OnboardingTour onClose={() => setShowTour(false)} />}
      {showGlossary && <GlossaryModal onClose={() => setShowGlossary(false)} />}

      {/* ── API 失敗橫幅（取代永遠的「載入中…」）───────────────────────── */}
      {apiError && (
        <div className="api-error-banner">
          ⚠️ 資料載入失敗（網路或伺服器暫時無回應）
          <button onClick={() => { refreshMarket(true); if (view === 'detail') loadDetail(true) }}>
            重試
          </button>
        </div>
      )}

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
                  {/* 週期切換（有時線資料的幣才顯示；目前 BTC/ETH） */}
                  {hasHourly && (
                    <div className="day-tabs interval-tabs">
                      <button
                        className={`day-tab ${interval === '1d' ? 'active' : ''}`}
                        onClick={() => setKInterval('1d')}
                        title="每根 K 棒 = 一天"
                      >
                        日線
                      </button>
                      <button
                        className={`day-tab ${interval === '1h' ? 'active' : ''}`}
                        onClick={() => { setKInterval('1h'); setDateMode('preset') }}
                        title="每根 K 棒 = 一小時（短線視角）"
                      >
                        時線
                      </button>
                    </div>
                  )}

                  {/* 快速預設按鈕 */}
                  <div className="day-tabs">
                    {rangeOptions.map(opt => (
                      <button
                        key={opt.label}
                        className={`day-tab ${dateMode === 'preset' && (interval === '1h' ? hourDays : days) === opt.value ? 'active' : ''}`}
                        onClick={() => {
                          if (interval === '1h') setHourDays(opt.value)
                          else setDays(opt.value)
                          setDateMode('preset')
                        }}
                      >
                        {opt.label}
                      </button>
                    ))}
                    {/* 自訂日期切換（時線資料量大，只開放日線用） */}
                    {interval === '1d' && (
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
                    )}
                  </div>

                  {/* 自訂日期面板 */}
                  {interval === '1d' && dateMode === 'custom' && (
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
                trades={interval === '1d' ? (backtest?.recent_trades ?? []) : []}
                interval={interval}
              />
            </section>

            <section className="collapsible-section">
              <button className="collapse-toggle" onClick={() => setShowAI(v => !v)}>
                <span>🤖 AI 智能分析（規則引擎 + GPT）</span>
                <span className="collapse-arrow">{showAI ? '▲' : '▼'}</span>
              </button>
              {showAI && <AIAnalystPanel symbol={active} refreshKey={dataVersion} />}
            </section>

            <section className="collapsible-section">
              <button className="collapse-toggle" onClick={() => setShowSentiment(v => !v)}>
                <span>市場情緒 / 新聞</span>
                <span className="collapse-arrow">{showSentiment ? '▲' : '▼'}</span>
              </button>
              {showSentiment && <SentimentPanel symbol={active} />}
            </section>

            <section className="collapsible-section">
              <button className="collapse-toggle" onClick={() => setShowBacktest(v => !v)}>
                <span>策略回測</span>
                <span className="collapse-arrow">{showBacktest ? '▲' : '▼'}</span>
              </button>
              {showBacktest && (
                <BacktestPanel
                  signal={activeSignal}
                  data={backtest}
                  loading={btLoading}
                  params={btParams}
                  onParamsChange={patch => setBtParams(p => ({ ...p, ...patch }))}
                />
              )}
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

      {/* ── 全站漂浮 AI 小幫手「小Q」（右下角）──────────────────────────
          詳細頁＝跟隨當前幣；總覽頁＝全市場模式（不綁定任何幣） */}
      <BotWidget defaultSymbol={view === 'detail' ? active : null} />

    </div>
  )
}
