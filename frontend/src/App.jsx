/**
 * App.jsx — 應用程式根元件
 *
 * 版面結構：
 *   header（標題列）
 *   └── app-layout（flex 橫排）
 *       ├── CoinSidebar（左側 200px，15 個幣種清單）
 *       └── main-content（右側主要區域）
 *           ├── HeroSignal    大訊號卡（當前幣的 BULL/BEAR/NEUTRAL）
 *           ├── PriceChart    K 線 / 均線圖 + 時間切換（1M/3M/6M/1Y）
 *           ├── SentimentPanel 恐懼貪婪指數 + 分類新聞
 *           ├── BacktestPanel  回測績效（精簡版）
 *           ├── IndicatorChart RSI / MACD（預設收起）
 *           └── CorrelationHeatmap 相關性熱圖（預設收起）
 *
 * 狀態說明：
 *   symbols     所有可用幣種代號（從後端取得）
 *   active      目前選中的幣種（點 sidebar 切換）
 *   days        K 線顯示天數（1M / 3M / 6M / 1Y）
 *   signals     所有幣種的訊號（陣列，sidebar 顯示小圓點用）
 *   indicators  當前幣種的技術指標資料（換幣或換天數時重新載入）
 *   correlation 所有幣種的相關性矩陣（只載入一次）
 */
import { useState, useEffect } from 'react'
import {
  fetchSymbols, fetchAllSignals,
  fetchIndicators, fetchCorrelation,
} from './api/client'
import StatusBar from './components/StatusBar'
import PriceChart from './components/PriceChart'
import IndicatorChart from './components/IndicatorChart'
import CorrelationHeatmap from './components/CorrelationHeatmap'
import BacktestPanel from './components/BacktestPanel'
import CoinSidebar from './components/CoinSidebar'
import HeroSignal from './components/HeroSignal'
import SentimentPanel from './components/SentimentPanel'
import { coinName } from './constants/coins'

// 時間區間選項（標籤顯示 / 實際天數）
const DAY_OPTIONS = [
  { label: '1M',  value: 30 },
  { label: '3M',  value: 90 },
  { label: '6M',  value: 180 },
  { label: '1Y',  value: 365 },
]

export default function App() {
  const [symbols,     setSymbols]     = useState([])
  const [active,      setActive]      = useState('BTCUSDT')  // 預設顯示比特幣
  const [days,        setDays]        = useState(180)        // 預設 6 個月
  const [signals,     setSignals]     = useState([])
  const [indicators,  setIndicators]  = useState([])
  const [correlation, setCorrelation] = useState(null)
  const [showIndicators,  setShowIndicators]  = useState(false)  // RSI/MACD 預設收起
  const [showCorrelation, setShowCorrelation] = useState(false)  // 相關性圖預設收起

  // 頁面載入時：取幣種清單、所有訊號、相關性矩陣（這三項不隨幣種切換而變）
  useEffect(() => {
    fetchSymbols().then(setSymbols).catch(() => {})
    fetchAllSignals().then(setSignals).catch(() => {})
    fetchCorrelation().then(setCorrelation).catch(() => {})
  }, [])

  // 切換幣種或時間區間時，重新載入技術指標
  useEffect(() => {
    setIndicators([])  // 先清空，讓圖表顯示載入中狀態
    fetchIndicators(active, days).then(setIndicators).catch(() => {})
  }, [active, days])

  // 從 signals 陣列裡找出當前幣種的訊號資料
  const activeSignal = signals.find(s => s.symbol === active)

  return (
    <div className="app">
      <header className="header">
        <span className="logo">📈 Crypto Quant</span>
        <StatusBar />  {/* 顯示資料最後更新時間 */}
      </header>

      <div className="app-layout">
        {/* 左側：15 個幣種清單，每個幣顯示訊號顏色 + 最新價格 */}
        <CoinSidebar
          symbols={symbols}
          signals={signals}
          active={active}
          onSelect={setActive}
        />

        <main className="main-content">

          {/* 大訊號卡：一眼看出當前幣是看多/看空，附上 RSI 說明 */}
          <HeroSignal signal={activeSignal} symbol={active} />

          {/* 價格走勢圖 + 時間區間切換按鈕 */}
          <section className="chart-section">
            <div className="chart-section-header">
              <span className="chart-section-title">{coinName(active)} 價格走勢</span>
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
            <PriceChart data={indicators} />
          </section>

          {/* 市場情緒：恐懼貪婪指數 + 分類新聞 + 歷史回補 */}
          <SentimentPanel symbol={active} />

          {/* 回測績效（精簡版）：只顯示 3 個關鍵數字 */}
          <BacktestPanel symbol={active} />

          {/* 技術指標細節（RSI / MACD）：預設收起，進階使用者才展開 */}
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

          {/* 幣種相關性分析：預設收起，避免畫面太長 */}
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
    </div>
  )
}
