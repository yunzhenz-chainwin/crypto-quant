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
import { useState, useEffect, useCallback, useRef, lazy, Suspense } from 'react'
import {
  fetchSymbols, fetchAllSignals, fetchOHLC, fetchStatus, fetchIntervals,
  fetchIndicators, fetchBacktest, fetchBacktestSummary, fetchFearGreed,   // fetchCorrelation 暫停（幣種相關性分析）
} from './api/client'
import StatusBar        from './components/StatusBar'
import CandlestickChart from './components/CandlestickChart'
import HeroSignal        from './components/HeroSignal'
import IndicatorCards   from './components/IndicatorCards'
import RecommendationCard from './components/RecommendationCard'
import MarketOverview   from './components/MarketOverview'
// import MacroPanel    from './components/MacroPanel'   // 2026-07-07 先隱藏（價值待議；程式碼＋/api/macro 保留，未來或改「以 BTC 為主的相關性溫度計」版）
import MarketSummary    from './components/MarketSummary'
// import BotWidget     from './components/BotWidget'   // 2026-07-06 暫時下架：使用者確定為主管/老闆，聊天小幫手先隱藏（要恢復連同底部掛載一起取消註解）
// import OnboardingTour   from './components/OnboardingTour' // 2026-07-06 暫停新手導覽
import GlossaryModal    from './components/GlossaryModal'
import useLivePrices    from './lib/useLivePrices'
import { coinName }     from './constants/coins'

// 折疊面板動態載入（code splitting #29）：首屏不下載 recharts 等重依賴，
// 進入詳細頁/展開面板時才抓對應 chunk（Suspense 顯示輕量載入字樣）。
// const CorrelationHeatmap = lazy(() => import('./components/CorrelationHeatmap'))  // 2026-07-06 暫停幣種相關性分析
const SentimentPanel     = lazy(() => import('./components/SentimentPanel'))
const StrategyPanel      = lazy(() => import('./components/StrategyPanel'))   // 詳細資訊彈窗用（計分明細＋回測表格＋實驗室）
// const AIAnalystPanel     = lazy(() => import('./components/AIAnalystPanel')) // 2026-07-06 暫停 AI 智能分析
const panelFallback = <div className="chart-empty">面板載入中…</div>
// 詳細資訊彈窗的載入骨架（比純文字「載入中」順，不會空白跳一下）
const detailFallback = (
  <div className="detail-skeleton" aria-label="載入中">
    <div className="skeleton" style={{ height: 44, borderRadius: 8 }} />
    <div className="skeleton" style={{ height: 220, borderRadius: 8 }} />
    <div className="skeleton" style={{ height: 150, borderRadius: 8 }} />
  </div>
)

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

// 詳細頁可自由開關的區塊（預設全開；偏好存 localStorage，取代固定塞滿的版面）
const PANELS = [
  { key: 'sentiment', label: '市場情緒/新聞' },
  // { key: 'correlation', label: '幣種相關性' },  // 2026-07-06 暫停幣種相關性分析
]

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
  const [btSummary,   setBtSummary]   = useState([])       // 各幣回測績效摘要（市場總覽第二評估標準）
  const [fearGreed,   setFearGreed]   = useState(null)
  const [lastUpdated, setLastUpdated] = useState(0)
  const [refreshing,  setRefreshing]  = useState(false)
  const [ohlc,        setOhlc]        = useState([])
  const [indicators,  setIndicators]  = useState([])
  const [backtest,    setBacktest]    = useState(null)
  // 停損/停利參數（可在「詳細資訊」彈窗調整；供回測、右欄綜合建議、圖上箭頭用）
  const [btParams, setBtParams] = useState({ stopLoss: -0.06, takeProfit: 0.20, feeRate: 0.001, slippage: 0.0005 })
  const [btLoading,   setBtLoading]   = useState(false)
  // const [correlation, setCorrelation] = useState(null)                  // 2026-07-06 暫停幣種相關性分析
  const [dataVersion, setDataVersion] = useState('')        // 後端資料版本（變了=有新資料）
  // const [showCorrelation, setShowCorrelation] = useState(false)         // 2026-07-06 暫停幣種相關性分析
  const [showSentiment,   setShowSentiment]   = useState(true)   // 市場情緒/新聞（預設展開，讓它一眼可見）
  const [chartZoom,       setChartZoom]       = useState(false)  // 蠟燭圖「放大」全螢幕彈窗
  const [detailView,      setDetailView]      = useState(null)   // 「詳細資訊」彈窗內容：null / 'score' / 'indicators' / 'backtest'
  // const [showAI,          setShowAI]          = useState(true) // 2026-07-06 暫停 AI 智能分析
  // 詳細頁「顯示哪些區塊」偏好（預設全開，使用者可關掉不看的；存 localStorage）
  const [panelPrefs,      setPanelPrefs]      = useState(() => {
    try { return JSON.parse(localStorage.getItem('cq_panels') || '{}') } catch { return {} }
  })
  useEffect(() => { localStorage.setItem('cq_panels', JSON.stringify(panelPrefs)) }, [panelPrefs])
  const [labTrades,       setLabTrades]       = useState(null)   // 自訂訊號實驗室的交易（null=未啟用，圖上顯示正式回測標記）
  // 首次造訪自動開新手導覽；Header「導覽」可重看
  // const [showTour, setShowTour] = useState(() => !localStorage.getItem('cq_tour_done')) // 2026-07-06 暫停新手導覽
  const [showGlossary, setShowGlossary] = useState(false)
  const [apiError, setApiError] = useState(false)   // API 失敗橫幅（輕量版 #22）
  const versionRef = useRef('')

  // 這顆幣有沒有時線資料（目前只開 BTC/ETH）
  const hasHourly = (intervals['1h'] ?? []).includes(active)
  // Binance WS 即時最新價（{SYM:{price,changePct}}）——讓最新價/漲跌秒級跳動
  const livePrices = useLivePrices(symbols)

  // 刷新市場摘要資料（訊號 + 恐懼貪婪）
  const refreshMarket = useCallback(async (showSpinner = true) => {
    if (showSpinner) setRefreshing(true)
    try {
      const [sigs, fg, bts] = await Promise.all([
        fetchAllSignals(),
        fetchFearGreed(1),
        fetchBacktestSummary().catch(() => []),   // 回測摘要失敗不該擋住訊號載入 → 降級空陣列
      ])
      setSignals(sigs)
      setFearGreed(fg?.[0] ?? null)
      setBtSummary(Array.isArray(bts) ? bts : [])
      setLastUpdated(Date.now())
      setApiError(false)
    } catch {
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
    } catch {
      setApiError(true)
    }
  }, [active, interval, days, hourDays, startDate, endDate, dateMode])

  // 頁面載入：初始化所有資料
  useEffect(() => {
    fetchSymbols().then(setSymbols).catch(() => {})
    fetchIntervals().then(setIntervals).catch(() => {})
    // fetchCorrelation().then(setCorrelation).catch(() => {})   // 2026-07-06 暫停幣種相關性分析
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
      } catch { /* 略過本次輪詢錯誤，下輪再試 */ }
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

  // 任一彈窗（放大圖 / 詳細資訊）開啟時：Esc 關閉
  useEffect(() => {
    if (!chartZoom && !detailView) return
    const onKey = (e) => { if (e.key === 'Escape') { setChartZoom(false); setDetailView(null) } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [chartZoom, detailView])

  const handleSelectCoin = (symbol) => {
    setActive(symbol)
    setView('detail')
    // 新幣種沒有時線資料時自動退回日線
    if (!(intervals['1h'] ?? []).includes(symbol)) setKInterval('1d')
  }

  const handleBackToOverview = () => {
    setView('overview')
    setLabTrades(null)
  }

  const activeSignal = signals.find(s => s.symbol === active)
  const rangeOptions = interval === '1h' ? HOUR_OPTIONS : DAY_OPTIONS
  const panelOn = (key) => panelPrefs[key] !== false                       // 預設開，明確設 false 才隱藏
  const togglePanel = (key) => setPanelPrefs(p => ({ ...p, [key]: !(p[key] !== false) }))

  return (
    <div className="app">

      {/* ── Header ────────────────────────────────────────────────────── */}
      <header className="header">
        <span className="logo">Crypto Quant</span>
        <nav className="header-nav">
          {view === 'detail' && (
            <button
              className="nav-btn nav-back-btn"
              onClick={handleBackToOverview}
              aria-label="返回市場總覽"
              title="返回市場總覽"
            >
              ←
            </button>
          )}
          <button
            className={`nav-btn ${view === 'overview' ? 'active' : ''}`}
            onClick={handleBackToOverview}
          >
            市場總覽
          </button>
          <button className="nav-btn" onClick={() => setShowGlossary(true)} title="名詞小辭典">
            辭典
          </button>
          {/* 2026-07-06 暫停新手導覽
          <button className="nav-btn" onClick={() => setShowTour(true)} title="重看新手導覽">
            導覽
          </button>
          */}
        </nav>
        <StatusBar />
      </header>

      {/* ── 新手導覽（首次造訪自動開啟）／名詞辭典 ─────────────────────── */}
      {/* 2026-07-06 暫停新手導覽
      {showTour && <OnboardingTour onClose={() => setShowTour(false)} />}
      */}
      {showGlossary && <GlossaryModal onClose={() => setShowGlossary(false)} />}

      {/* ── API 失敗橫幅（取代永遠的「載入中…」）───────────────────────── */}
      {apiError && (
        <div className="api-error-banner">
          注意：資料載入失敗（網路或伺服器暫時無回應）
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
          {/* <MacroPanel /> 先隱藏——見上方 import 註解，程式碼保留 */}
          <MarketOverview signals={signals} backtests={btSummary} livePrices={livePrices} onSelect={handleSelectCoin} />
        </div>
      )}

      {/* ── 幣種詳細模式 ────────────────────────────────────────────────── */}
      {view === 'detail' && (
        <div className="app-layout">
          <main className="main-content">
            {/* 詳細頁頂列：幣種下拉選擇 + 區塊顯示開關（取代左側整排幣種清單，版面更簡潔）*/}
            <div className="detail-topbar">
              <label className="coin-picker-wrap">
                <span className="coin-picker-lbl">幣種</span>
                <select className="coin-picker" value={active}
                        onChange={e => handleSelectCoin(e.target.value)}>
                  {symbols.map(s => <option key={s} value={s}>{coinName(s)}</option>)}
                </select>
              </label>
              <div className="panel-prefs">
                <span className="panel-prefs-lbl">顯示區塊</span>
                {PANELS.map(p => (
                  <label key={p.key} className={`panel-pref ${panelOn(p.key) ? 'on' : ''}`}>
                    <input type="checkbox" checked={panelOn(p.key)} onChange={() => togglePanel(p.key)} />
                    {p.label}
                  </label>
                ))}
              </div>
            </div>

            <HeroSignal signal={activeSignal} symbol={active} live={livePrices[active]} slim />

            {/* 儀表板主區：左＝蠟燭圖（縮小、點🔍放大看大圖），右＝分數＋指標即時解讀 */}
            <div className="detail-main">
            <section className="chart-section detail-chart-col">
              <div className="chart-section-header">
                <span className="chart-section-title">{coinName(active)} 蠟燭圖</span>
                <button className="chart-zoom-btn" onClick={() => setChartZoom(true)} title="放大看大圖">🔍 放大</button>

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
                        自訂
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
                trades={interval === '1d' ? (labTrades ?? backtest?.recent_trades ?? []) : []}
                interval={interval}
                compact
              />
            </section>

            {/* 右欄：買賣策略結論 + 信心分數 + 指標即時解讀（並排在圖旁，第一眼就看到決策）。
                每一塊都可「點下去看詳細」→ 開啟計分明細表、回測表格與建議的彈窗。 */}
            <aside className="detail-side-col">
              {/* 綜合建議（已併入信心分數量表；卡內兩個連結各開「計分明細」/「回測驗證」）*/}
              <RecommendationCard
                signal={activeSignal}
                backtest={backtest}
                params={btParams}
                onDetail={setDetailView}
              />

              {/* 指標即時解讀 → 點看「每個指標的詳解」 */}
              {activeSignal?.factors && (
                <div className="side-block side-clickable" role="button" tabIndex={0}
                     onClick={() => setDetailView('indicators')}
                     onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && setDetailView('indicators')}
                     title="點看每個指標的讀數、對分數的加減與怎麼看">
                  <div className="side-block-title">指標即時解讀<span className="side-more-inline">指標詳解 →</span></div>
                  <IndicatorCards factors={activeSignal.factors} rsi={activeSignal.rsi} />
                </div>
              )}
            </aside>
            </div>

            {/* 策略明細面板已依需求移除（買賣策略結論已放上方右欄；停損停利固定用預設值） */}

            {/* 2026-07-06 暫停 AI 智能分析
            <section className="collapsible-section">
              <button className="collapse-toggle" onClick={() => setShowAI(v => !v)}>
                <span>AI 智能分析（規則引擎 + GPT）</span>
                <span className="collapse-arrow">{showAI ? '▲' : '▼'}</span>
              </button>
              {showAI && <Suspense fallback={panelFallback}><AIAnalystPanel symbol={active} refreshKey={dataVersion} /></Suspense>}
            </section>
            */}

            {/* 市場情緒 / 新聞：依需求移到最後面 */}
            {panelOn('sentiment') && (
            <section className="collapsible-section">
              <button className="collapse-toggle" onClick={() => setShowSentiment(v => !v)}>
                <span>市場情緒 / 新聞</span>
                <span className="collapse-arrow">{showSentiment ? '▲' : '▼'}</span>
              </button>
              {showSentiment && <Suspense fallback={panelFallback}><SentimentPanel symbol={active} /></Suspense>}
            </section>
            )}

            {/* 2026-07-06 暫停「幣種相關性分析」（依需求先註解；要恢復把此段 + 頂部 CorrelationHeatmap import、correlation/showCorrelation state、fetchCorrelation 呼叫一起取消註解）
            {panelOn('correlation') && (
            <section className="collapsible-section">
              <button className="collapse-toggle" onClick={() => setShowCorrelation(v => !v)}>
                <span>幣種相關性分析</span>
                <span className="collapse-arrow">{showCorrelation ? '▲' : '▼'}</span>
              </button>
              {showCorrelation && (
                <div className="correlation-body">
                  <Suspense fallback={panelFallback}><CorrelationHeatmap data={correlation} /></Suspense>
                </div>
              )}
            </section>
            )}
            */}

            {/* 蠟燭圖「放大」全螢幕彈窗（點背景 / ✕ / Esc 關閉；用完整尺寸非 compact） */}
            {chartZoom && (
              <div className="chart-modal-backdrop" onClick={() => setChartZoom(false)}>
                <div className="chart-modal" onClick={e => e.stopPropagation()}>
                  <div className="chart-modal-bar">
                    <span className="chart-modal-title">{coinName(active)} 蠟燭圖</span>
                    <button className="chart-modal-close" onClick={() => setChartZoom(false)} aria-label="關閉放大">✕</button>
                  </div>
                  <CandlestickChart
                    prices={ohlc}
                    indicators={indicators}
                    trades={interval === '1d' ? (labTrades ?? backtest?.recent_trades ?? []) : []}
                    interval={interval}
                  />
                </div>
              </div>
            )}

            {/* 「詳細資訊」彈窗：點右欄哪一塊就顯示對應詳細（計分明細 / 指標詳解 / 回測驗證）*/}
            {detailView && (
              <div className="chart-modal-backdrop" onClick={() => setDetailView(null)}>
                <div className="detail-modal" onClick={e => e.stopPropagation()}>
                  <div className="chart-modal-bar">
                    <span className="chart-modal-title">
                      {coinName(active)}｜{{ all: '計分明細 · 回測驗證', score: '計分明細與進出場規則', indicators: '指標詳解', backtest: '回測驗證明細' }[detailView]}
                    </span>
                    <button className="chart-modal-close" onClick={() => setDetailView(null)} aria-label="關閉詳細">✕</button>
                  </div>
                  <Suspense fallback={detailFallback}>
                    <StrategyPanel
                      view={detailView}
                      signal={activeSignal}
                      backtest={backtest}
                      btLoading={btLoading}
                      params={btParams}
                      onParamsChange={patch => setBtParams(p => ({ ...p, ...patch }))}
                    />
                  </Suspense>
                </div>
              </div>
            )}
          </main>
        </div>
      )}

      {/* ── 全站漂浮 AI 小幫手「小Q」（右下角）──────────────────────────
          詳細頁＝跟隨當前幣；總覽頁＝全市場模式（不綁定任何幣）
          2026-07-06 暫時下架（使用者為主管/老闆）；要恢復把下行與頂部 import 取消註解即可。
      <BotWidget defaultSymbol={view === 'detail' ? active : null} />
      */}

    </div>
  )
}
