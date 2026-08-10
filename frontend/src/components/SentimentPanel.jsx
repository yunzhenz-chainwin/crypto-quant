/**
 * SentimentPanel.jsx — 市場情緒面板
 *
 * 版面：左側錶盤（恐懼貪婪） + 右側新聞（分類 tab）
 *
 * 子元件說明：
 *   fgConfig()        依指數值回傳顏色、標籤、說明文字
 *   FearGreedGauge    SVG 半圓錶盤，指針用極座標計算位置
 *   FearGreedChart    30 天趨勢面積圖，紅線=25（恐慌），綠線=75（貪婪）
 *   NewsArticles      單純的文章列表，最新 / 歷史模式都共用
 *   NewsFeed          分類 tab 切換 + 日期選擇器（歷史模式）
 *   BackfillPanel     匯入歷史新聞的表單（從 HackerNews 回補）
 *   SentimentPanel    主元件，管理所有狀態並組裝以上子元件
 */
import { useState, useEffect, useId } from 'react'
import {
  ResponsiveContainer, AreaChart, Area,
  XAxis, YAxis, Tooltip, ReferenceLine,
} from 'recharts'
import { fetchFearGreed, fetchNews, fetchNewsHistory, fetchNewsDates, backfillNews, fetchNewsSentiment, fetchNewsSources } from '../api/client'
import { coinZh, coinTicker } from '../constants/coins'

// 依指數值（0~100）回傳對應的顏色、標籤和解說文字
function fgConfig(value) {
  const v = Number(value)
  if (v <= 25) return { color: '#ef4444', label: '極度恐慌', tip: '市場非常悲觀，歷史上常是中長期買入機會' }
  if (v <= 45) return { color: '#f97316', label: '恐慌',     tip: '市場情緒偏悲觀，價格通常偏低' }
  if (v <= 55) return { color: '#f59e0b', label: '中立',     tip: '市場情緒平衡，方向不明' }
  if (v <= 75) return { color: '#84cc16', label: '貪婪',     tip: '市場情緒偏樂觀，注意過熱風險' }
  return              { color: '#22c55e', label: '極度貪婪', tip: '市場過於樂觀，歷史上常是短期高點' }
}

// 半圓錶盤：0 在左、50 在上、100 在右。SVG 的 y 軸向下，所以 y 座標要反向計算。
function FearGreedGauge({ value }) {
  const v   = Math.max(0, Math.min(100, Number(value) || 0))
  const cfg = fgConfig(v)
  const angle = 180 - (v / 100) * 180
  const rad   = (angle * Math.PI) / 180
  const cx = 80, cy = 76, r = 54, arcR = 62
  const arc = `M ${cx - arcR} ${cy} A ${arcR} ${arcR} 0 0 1 ${cx + arcR} ${cy}`
  const nx = cx + r * Math.cos(rad)     // 指針尖端 x
  const ny = cy - r * Math.sin(rad)     // 指針尖端 y
  return (
    <div className="fg-gauge-wrap">
      <svg viewBox="0 0 160 102" className="fg-gauge-svg">
        <path d={arc} fill="none" stroke="#334155" strokeWidth="10" strokeLinecap="round" />
        <defs>
          <linearGradient id="fgGrad" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor="#ef4444" />
            <stop offset="25%"  stopColor="#f97316" />
            <stop offset="50%"  stopColor="#f59e0b" />
            <stop offset="75%"  stopColor="#84cc16" />
            <stop offset="100%" stopColor="#22c55e" />
          </linearGradient>
        </defs>
        <path d={arc} fill="none" stroke="url(#fgGrad)" strokeWidth="10" strokeLinecap="round" opacity="0.35" />
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={cfg.color} strokeWidth="3" strokeLinecap="round" />
        <circle cx={cx} cy={cy} r="4" fill={cfg.color} />
        <text x={cx} y={cy + 18} textAnchor="middle" fill={cfg.color} fontSize="20" fontWeight="bold">{v}</text>
        <text x={cx - arcR} y={cy + 16} textAnchor="middle" fill="#64748b" fontSize="9">0</text>
        <text x={cx + arcR} y={cy + 16} textAnchor="middle" fill="#64748b" fontSize="9">100</text>
      </svg>
      <div className="fg-label" style={{ color: cfg.color }}>{cfg.label}</div>
      <div className="fg-tip">{cfg.tip}</div>
    </div>
  )
}

// 30 天恐懼貪婪趨勢圖；API 回傳資料是倒序（最新在前），先 reverse 再畫
function FearGreedChart({ history }) {
  if (!history || history.length === 0) return null
  // timestamp 是 Unix 秒數，轉換成「月/日」格式顯示在 X 軸
  const data = [...history].reverse().map(d => ({
    date:  d.timestamp ? new Date(Number(d.timestamp) * 1000).toLocaleDateString('zh-TW', { month: 'numeric', day: 'numeric' }) : '',
    value: Number(d.value),
  }))
  return (
    <ResponsiveContainer width="100%" height={80}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
        <defs>
          <linearGradient id="fgArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="#f59e0b" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 9 }} interval="preserveStartEnd" />
        <YAxis domain={[0, 100]} hide />
        <Tooltip
          contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
          formatter={(v) => [v, '指數']}
        />
        <ReferenceLine y={25} stroke="#ef4444" strokeDasharray="3 2" strokeOpacity={0.4} />
        <ReferenceLine y={75} stroke="#22c55e" strokeDasharray="3 2" strokeOpacity={0.4} />
        <Area dataKey="value" stroke="#f59e0b" fill="url(#fgArea)" strokeWidth={1.5} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

// 新聞情緒溫度：近 N 天每日分數（-100 極空 ~ +100 極多）長條 + 今日統計
// 資料來源 /api/sentiment/summary（news_sentiment_daily 彙總表，30 分鐘滾動更新）
function NewsSentimentStrip({ symbol }) {
  const [market, setMarket] = useState(null)   // 全市場
  const [coin,   setCoin]   = useState(null)   // 這顆幣

  useEffect(() => {
    let alive = true
    fetchNewsSentiment('MARKET', 14).then(r => { if (alive) setMarket(r.daily) }).catch(() => {})
    fetchNewsSentiment(coinTicker(symbol), 14).then(r => { if (alive) setCoin(r.daily) }).catch(() => {})
    return () => { alive = false }
  }, [symbol])

  const scoreColor = (s) => (s > 15 ? '#22c55e' : s < -15 ? '#ef4444' : '#f59e0b')

  const Bars = ({ daily, label }) => {
    if (!daily?.length) return null
    const last = daily[daily.length - 1]
    return (
      <div className="ns-row">
        <div className="ns-row-head">
          <span className="ns-label">{label}</span>
          <span className="ns-today" style={{ color: scoreColor(last.score) }}>
            今日 {last.score > 0 ? '+' : ''}{last.score}
            <span className="ns-counts">（{last.n_total} 則：多 {last.n_bull} / 空 {last.n_bear}）</span>
          </span>
        </div>
        <div className="ns-bars" title="近 14 天每日新聞情緒（綠=偏多、紅=偏空、黃=中性）">
          {daily.map(d => (
            <div key={d.date} className="ns-bar-slot"
                 title={`${d.date}：${d.score > 0 ? '+' : ''}${d.score}（${d.n_total} 則）`}>
              <div className="ns-bar" style={{
                background: scoreColor(d.score),
                height: `${Math.max(8, Math.abs(d.score) * 0.9)}%`,
              }} />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (!market?.length && !coin?.length) return null
  return (
    <div className="news-senti-strip">
      <div className="fg-panel-title">新聞情緒溫度 <span className="ns-scale">-100 空 ~ +100 多</span></div>
      <Bars daily={market} label="全市場" />
      <Bars daily={coin}   label={coinZh(symbol)} />
    </div>
  )
}

// 情緒標籤的顯示樣式（看多=綠、看空=紅、中立=灰）
const SENTIMENT_STYLE = {
  bullish: { label: '看多', color: '#22c55e', bg: 'rgba(34,197,94,0.12)' },
  bearish: { label: '看空', color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
  neutral: { label: '中立', color: '#94a3b8', bg: 'rgba(148,163,184,0.1)' },
}

// 新聞文章列表：最新模式和歷史模式都用同一個元件，只差資料來源不同
function NewsArticles({ items }) {
  if (!items || items.length === 0)
    return <div className="chart-empty">此分類暫無新聞</div>
  return (
    <div className="news-list">
      {items.map((item, i) => {
        const s = SENTIMENT_STYLE[item.sentiment] ?? SENTIMENT_STYLE.neutral
        return (
          <a key={i} href={item.url} target="_blank" rel="noreferrer" className="news-item">
            <div className="news-row">
              <span className="news-sentiment-badge" style={{ color: s.color, background: s.bg }}>
                {s.label}
              </span>
              <span className="news-title">{item.title}</span>
            </div>
            <span className="news-meta">{item.domain} · {item.published_at || item.fetched_at?.slice(0, 10)}</span>
          </a>
        )
      })}
    </div>
  )
}

/**
 * 新聞來源標示：讀 /api/sentiment/sources 的實際分布，不寫死清單。
 *
 * 原本這裡寫死「CoinTelegraph · CoinDesk · Decrypt」，但庫裡實際有數百個網域、
 * 最大宗是動區 BlockTempo，那三家合計只佔約四分之一——寫死的清單會讓人誤以為
 * 新聞只來自那三家英文媒體。點開可看實際前幾大來源與則數，能自己核對。
 */
function useNewsSources() {
  const [stats, setStats] = useState(null)
  const [open, setOpen] = useState(false)
  const listId = useId()

  useEffect(() => {
    const controller = new AbortController()
    fetchNewsSources({ signal: controller.signal }).then(setStats).catch(() => {})
    return () => controller.abort()
  }, [])

  if (!stats?.total) {
    return { button: <span className="news-sources">資料來源載入中…</span>, list: null }
  }

  // 刻意回傳兩個節點分開掛：按鈕留在 .news-panel-header（flex 橫列），
  // 展開的清單要掛到 header 外面。若用 Fragment 一起回傳，清單會被攤平成
  // header 的第三個 flex item、橫向擠在按鈕右邊，把標題列撐成一大塊。
  return {
    button: (
      <button
        type="button"
        className="news-sources news-sources-btn"
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
        aria-controls={listId}
        title="點看實際來源分布（依資料庫統計，非固定清單）"
      >
        資料來源：{stats.rss.length} 家 RSS ＋ Google News 聚合 · 共 {stats.domains} 個來源 {open ? '▲' : '▼'}
      </button>
    ),
    list: open ? (
        <div id={listId} className="news-sources-list">
          <div className="news-sources-sum">
            資料庫 {stats.total.toLocaleString()} 則，其中 {stats.aggregated.toLocaleString()} 則經 Google News 聚合
            （來源名稱前綴 <code>GN:</code>）。以下為則數最多的來源：
          </div>
          <div className="news-sources-grid">
            {stats.top.map(t => (
              <span key={t.domain} className="news-sources-chip" data-agg={t.via_aggregator}>
                {t.domain}<b>{t.count.toLocaleString()}</b>
              </span>
            ))}
          </div>
          <div className="news-sources-sum">
            直接訂閱的 RSS：{stats.rss.join('、')}
          </div>
        </div>
    ) : null,
  }
}

/**
 * 新聞面板：分類 tab + 文章列表
 * - isHistory=false：顯示最新 RSS 新聞，依幣種篩選
 * - isHistory=true：顯示歷史新聞，加上日期下拉選單
 * displayData 切換時重設 activeTab 到第一個分類
 */
function NewsFeed({ symbol, news, historyData, isHistory, availableDates, historyDate, onDateChange }) {
  const [activeTab, setActiveTab] = useState(null)

  const displayData = isHistory ? historyData : news
  const categories  = displayData?.categories ?? []

  // 資料切換（換幣種 / 換模式 / 換日期）時，自動選中第一個分類 tab
  useEffect(() => {
    if (categories.length > 0) setActiveTab(categories[0].name)
  }, [displayData])

  const currentItems = categories.find(c => c.name === activeTab)?.items ?? []
  const sources = useNewsSources()

  return (
    <div className="news-panel">
      {/* 標題列 */}
      <div className="news-panel-header">
        <span className="news-panel-title">
          {isHistory ? `歷史新聞 — ${historyDate}` : `最新新聞 ${symbol ? `— ${coinZh(symbol)}` : ''}`}
        </span>
        {sources.button}
      </div>
      {sources.list}

      {/* 歷史日期選擇 */}
      {isHistory && (
        <div className="news-date-row">
          <span className="news-date-label">選擇日期：</span>
          <select
            className="news-date-select"
            value={historyDate}
            onChange={e => onDateChange(e.target.value)}
          >
            {availableDates.map(d => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          {displayData && (
            <span className="news-date-count">共 {displayData.total} 則</span>
          )}
        </div>
      )}

      {/* 分類 Tab */}
      {!displayData
        ? <div className="chart-empty">載入中…</div>
        : categories.length === 0
          ? <div className="chart-empty">
              {isHistory ? '這天還沒有記錄（資料從今天開始累積）' : '暫無新聞'}
            </div>
          : (
            <>
              <div className="news-tabs">
                {categories.map(cat => (
                  <button
                    key={cat.name}
                    className={`news-tab ${activeTab === cat.name ? 'active' : ''}`}
                    onClick={() => setActiveTab(cat.name)}
                  >
                    <span>{cat.name}</span>
                    <span className="news-tab-count">{cat.items.length}</span>
                  </button>
                ))}
              </div>
              <NewsArticles items={currentItems} />
            </>
          )
      }
    </div>
  )
}

/**
 * 歷史回補面板
 * 讓使用者選擇日期範圍，呼叫後端 /api/sentiment/news/backfill
 * 完成後呼叫 onDone()，觸發父元件重新載入日期清單
 *
 * 預設範圍：從今天往前 30 天（一個月）
 */
function BackfillPanel({ onDone }) {
  const today = new Date().toISOString().slice(0, 10)   // 供日期輸入 max=；每次 render 同值

  // 預設起訖用 lazy initializer（只在首次 render 算一次），避免在 render 中呼叫 Date.now() 的不純副作用
  const [fromDate, setFromDate] = useState(() => new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10))
  const [toDate,   setToDate]   = useState(today)
  const [loading,  setLoading]  = useState(false)
  const [result,   setResult]   = useState(null)

  const run = async () => {
    setLoading(true)
    setResult(null)
    try {
      const r = await backfillNews(fromDate, toDate)
      setResult(r)
      if (r.ok) onDone()  // 成功後通知父元件重新整理日期清單
    } catch (e) {
      setResult({ ok: false, error: String(e) })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="backfill-panel">
      <div className="backfill-title">匯入歷史新聞</div>
      <div className="backfill-desc">
        從 HackerNews 免費抓取加密幣相關舊新聞，存入資料庫供日後查詢。
      </div>
      <div className="backfill-row">
        <label>從
          <input type="date" className="backfill-date" value={fromDate}
            max={toDate} onChange={e => setFromDate(e.target.value)} />
        </label>
        <label>到
          <input type="date" className="backfill-date" value={toDate}
            min={fromDate} max={today} onChange={e => setToDate(e.target.value)} />
        </label>
        <button className="backfill-btn" onClick={run} disabled={loading}>
          {loading ? '匯入中…' : '開始匯入'}
        </button>
      </div>
      {loading && <div className="backfill-note">正在從 HackerNews 抓取資料，請稍候…</div>}
      {result && (
        <div className={`backfill-result ${result.ok ? 'ok' : 'err'}`}>
          {result.ok
            ? `匯入完成！新增 ${result.saved} 則，資料庫共 ${result.db_total} 則`
            : `失敗：${result.error}`}
        </div>
      )}
    </div>
  )
}

/**
 * 市場情緒主元件（SentimentPanel）
 *
 * 狀態說明：
 *   fgData         恐懼貪婪指數的 30 天資料陣列
 *   news           最新 RSS 新聞（依幣種篩選）
 *   isHistory      是否處於歷史模式（false=最新，true=歷史）
 *   availableDates 資料庫中有紀錄的日期清單（歷史查詢的下拉選單）
 *   historyDate    歷史模式下選中的日期
 *   historyData    選中日期的新聞資料
 *   dbTotal        資料庫總筆數（顯示在底部統計）
 *   showBackfill   是否展開回補面板
 */
export default function SentimentPanel({ symbol }) {
  const [fgData,         setFgData]         = useState(null)
  const [news,           setNews]           = useState(null)
  const [isHistory,      setIsHistory]      = useState(false)
  const [availableDates, setAvailableDates] = useState([])
  const [historyDate,    setHistoryDate]    = useState('')
  const [historyData,    setHistoryData]    = useState(null)
  const [dbTotal,        setDbTotal]        = useState(0)
  const [showBackfill,   setShowBackfill]   = useState(false)

  // 重新載入日期清單和總筆數（回補完成後也會呼叫）
  const reloadDates = () =>
    fetchNewsDates().then(r => {
      setAvailableDates(r.dates ?? [])
      setDbTotal(r.total ?? 0)
      // 只有還沒選過日期時才自動選第一個，避免覆蓋使用者的選擇
      if (r.dates?.length && !historyDate) setHistoryDate(r.dates[0])
    }).catch(() => {})

  useEffect(() => {
    const controller = new AbortController()
    fetchFearGreed(30, { signal: controller.signal }).then(setFgData).catch(error => {
      if (error?.name !== 'AbortError') setFgData([])
    })
    reloadDates()
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setNews(null)
    fetchNews(symbol, { signal: controller.signal }).then(setNews).catch(error => {
      if (error?.name !== 'AbortError') setNews({ categories: [], error: true })
    })
    return () => controller.abort()
  }, [symbol])

  useEffect(() => {
    if (!isHistory || !historyDate) return
    const controller = new AbortController()
    setHistoryData(null)
    fetchNewsHistory(historyDate, null, { signal: controller.signal }).then(setHistoryData).catch(error => {
      if (error?.name !== 'AbortError') setHistoryData({ categories: [], error: true })
    })
    return () => controller.abort()
  }, [isHistory, historyDate])

  const current = fgData?.[0]

  return (
    <section className="sentiment-section">
      <div className="sentiment-header">
        <h2 className="section-title">市場情緒</h2>
        <span className="section-subtitle">反映現在市場整體的恐慌或樂觀程度</span>
      </div>

      <div className="sentiment-body">
        {/* 左：錶盤 */}
        <div className="fg-panel">
          <div className="fg-panel-title">恐懼貪婪指數<span className="info-tip" tabIndex="0" role="note" aria-label="0 到 100 的市場情緒溫度計；極端值只適合作為反向參考，不是精準擇時工具。" title="0~100 的市場情緒溫度計（綜合波動、動能、社群聲量）：0~25 極度恐慌、75~100 極度貪婪。極端值常被當反向參考——別人恐懼我貪婪，但不是精準擇時工具。">ⓘ</span></div>
          {current
            ? <FearGreedGauge value={current.value} />
            : <div className="chart-empty">載入中…</div>
          }
          <div className="fg-chart-label">近 30 天趨勢</div>
          <FearGreedChart history={fgData} />
          {/* 出處：這個指數不是我們算的，是外部提供的，標清楚才知道數字真不真實 */}
          <div className="fg-source">
            資料來源：
            <a href="https://alternative.me/crypto/fear-and-greed-index/"
               target="_blank" rel="noopener noreferrer"
               title="Crypto Fear &amp; Greed Index，由 alternative.me 提供；本站每日回補歷史值">
              alternative.me
            </a>
            （Crypto Fear &amp; Greed Index，每日更新）
          </div>

          {/* 新聞情緒溫度（全市場 + 這顆幣，來自每日彙總表） */}
          <NewsSentimentStrip symbol={symbol} />

          {/* 資料庫統計 + 回補按鈕 */}
          <div className="db-stat">
            資料庫已儲存 <strong>{dbTotal.toLocaleString()}</strong> 則歷史新聞
          </div>
          <button
            className="backfill-toggle"
            onClick={() => setShowBackfill(v => !v)}
            aria-expanded={showBackfill}
            aria-controls="news-backfill-panel"
          >
            {showBackfill ? '▲ 收起' : '▼ 匯入更多歷史新聞'}
          </button>
          {showBackfill && (
            <div id="news-backfill-panel">
              <BackfillPanel onDone={() => { reloadDates(); setShowBackfill(false) }} />
            </div>
          )}
        </div>

        {/* 右：分類新聞 + 歷史切換 */}
        <div className="fg-news">
          {/* 最新 / 歷史 切換按鈕 */}
          <div className="news-mode-toggle">
            <button
              className={`mode-btn ${!isHistory ? 'active' : ''}`}
              onClick={() => setIsHistory(false)}
              aria-pressed={!isHistory}
            >
              最新新聞
            </button>
            <button
              className={`mode-btn ${isHistory ? 'active' : ''}`}
              onClick={() => setIsHistory(true)}
              aria-pressed={isHistory}
            >
              歷史查詢
            </button>
          </div>

          <NewsFeed
            symbol={symbol}
            news={news}
            historyData={historyData}
            isHistory={isHistory}
            availableDates={availableDates}
            historyDate={historyDate}
            onDateChange={setHistoryDate}
          />
        </div>
      </div>
    </section>
  )
}
