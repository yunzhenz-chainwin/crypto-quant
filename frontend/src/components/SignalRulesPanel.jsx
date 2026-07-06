/**
 * SignalRulesPanel.jsx — 買賣判斷依據面板（2026-07-06 依主管需求新增）
 *
 * 兩個區塊：
 *  A. 系統訊號的買賣依據：把 6 因子計分規則（src/scoring.py）完整攤開，
 *     並用「當前幣的即時因子得分」對照，讓決策者知道每個買賣標記怎麼來的。
 *  B. 自訂買賣點實驗室：自選指標 + 自填門檻值 → 立即在上方 K 線圖標出
 *     買賣點（綠↑買 / ↓賣），並回測這組規則在目前圖表區間的歷史績效，
 *     用數字對照哪組指標/數值在這顆幣「過去」有效（≠未來保證）。
 *
 * Props：
 *   signal     當前幣的即時訊號（含 score / factors，來自 /api/signals）
 *   prices     目前圖表載入的 OHLCV（模擬區間 = 圖表顯示區間）
 *   indicators 同區間的指標資料（RSI/MACD/MA/BB…）
 *   interval   '1d' | '1h'（實驗室僅日線開放，與回測慣例一致）
 *   onTrades   回傳自訂規則的交易清單給父層 → 疊到 K 線圖（null=關閉、還原回測標記）
 */
import { useState, useMemo, useEffect, useRef } from 'react'
import { simulateRules, DEFAULT_RULES } from '../lib/signalLab'

// ── 6 因子完整計分表（與 src/scoring.py 一字一句對齊；改規則時兩邊同步）──
const SCORING_TABLE = [
  { factor: 'RSI 動量', weight: '±20', rules: '＜30 跌深超賣 +20｜30~35 +12｜35~45 +5｜55~65 −5｜65~70 −12｜＞70 漲多超買 −20' },
  { factor: 'MACD',     weight: '±18', rules: '黃金交叉（柱由負轉正）+18｜動能增強 +10｜動能減弱 −10｜死亡交叉（柱由正轉負）−18' },
  { factor: '均線排列', weight: '±15', rules: '多頭排列（價＞MA20＞MA60）+15｜站上 MA20 +5｜跌破 MA20 −5｜空頭排列 −15' },
  { factor: '長期趨勢 MA200', weight: '±10', rules: '站上 MA200 +10｜跌破 MA200 −10' },
  { factor: '成交量',   weight: '±7',  rules: '放量＞1.5x 均量 +7｜量增＞1.1x +4｜量縮＜0.9x −4｜大縮量＜0.6x −7' },
  { factor: '布林位置', weight: '±12', rules: '跌破下軌 +12｜近下軌(<20%) +7｜下半段 +3｜上半段 −3｜近上軌(>80%) −7｜突破上軌 −12' },
]
const FACTOR_ORDER = ['RSI', 'MACD', 'MA', 'MA200', 'Volume', 'BB']

const fmtSigned = (v) => (v > 0 ? `+${v}` : `${v}`)
const scoreColor = (v) => (v > 0 ? '#22c55e' : v < 0 ? '#ef4444' : '#64748b')

export default function SignalRulesPanel({ signal, prices, indicators, interval, onTrades }) {
  const [showFullTable, setShowFullTable] = useState(false)
  const [labOn, setLabOn]   = useState(false)
  const [rules, setRules]   = useState(DEFAULT_RULES)

  // ── 實驗室模擬（純前端、即時；區間 = 目前圖表載入的資料）────────────
  const result = useMemo(
    () => (labOn && interval === '1d' && prices?.length ? simulateRules(prices, indicators, rules) : null),
    [labOn, rules, prices, indicators, interval],
  )

  // 把交易回傳給父層疊到 K 線圖。onTrades 用 ref 持有，避免父層每次 render 觸發
  const onTradesRef = useRef(onTrades)
  useEffect(() => { onTradesRef.current = onTrades }, [onTrades])
  useEffect(() => {
    // 開啟：有結果給結果、沒交易給 []（圖上清空=讓使用者看見「這組規則沒訊號」）
    // 關閉：給 null → 圖表還原成正式回測的買賣標記
    onTradesRef.current(labOn && interval === '1d' ? (result?.trades ?? []) : null)
  }, [result, labOn, interval])
  useEffect(() => () => onTradesRef.current(null), [])   // 卸載（收合/切頁）時還原

  const patch = (key, sub) => setRules(r => ({ ...r, [key]: { ...r[key], ...sub } }))

  const score   = signal?.score
  const factors = signal?.factors ?? {}
  const factorSum = FACTOR_ORDER.reduce((s, k) => s + (factors[k]?.score ?? 0), 0)
  const stanceZh  = { BULL: '偏多', BEAR: '偏空', NEUTRAL: '中立' }[signal?.signal] ?? '—'

  return (
    <section className="rules-panel">

      {/* ═══ A. 系統訊號的買賣依據 ═══════════════════════════════════ */}
      <div className="rules-block">
        <div className="rules-block-title">系統訊號怎麼判斷買進賣出（回測與圖上箭頭的依據）</div>

        <div className="rules-steps">
          <div className="rules-step">
            <span className="rules-step-num">1</span>
            <div><b>每天收盤後算「信心分數」</b>（0~100，基準 50）：6 個技術因子加減分，
            規則全部公開在下表——分數不是黑箱，每一分都能對出來。</div>
          </div>
          <div className="rules-step">
            <span className="rules-step-num">2</span>
            <div><b>買進點</b>：分數<b style={{ color: '#22c55e' }}> ≥65 首次轉「偏多」</b>的
            <b>隔天開盤</b>買入（收盤才知道分數，不可能用當天價格買到，這是誠實回測的基本假設）。</div>
          </div>
          <div className="rules-step">
            <span className="rules-step-num">3</span>
            <div><b>賣出點</b>（三擇一、先到先出）：① 觸及<b>停損</b>價（預設 −6%）
            ② 觸及<b>停利</b>價（預設 +20%）③ 分數<b style={{ color: '#ef4444' }}> ≤35 轉「偏空」</b>的隔天開盤。
            停損停利可在下方「策略回測」面板調整，圖上箭頭會同步變。</div>
          </div>
        </div>

        {/* 交叉點的使用說明（哪些交叉有進評分、哪些只在圖上） */}
        <div className="rules-cross-note">
          <b>交叉點怎麼用？</b>系統評分中的交叉指標是 <b>MACD 黃金／死亡交叉</b>（MACD 線穿越訊號線
          ＝柱狀圖由負轉正／由正轉負），權重 <b>±18 為六因子中次高</b>，每天都會評估；
          均線因子採「排列狀態」（價＞MA20＞MA60）而非交叉事件、KDJ／DMI 的交叉只顯示在圖表供參考（不進評分）。
          想驗證「均線黃金交叉」這類經典交叉策略 → 用下方實驗室的「均線交叉」規則，直接在圖上看買賣點與績效。
        </div>

        {/* 當前幣的即時計分對照 */}
        {score != null && (
          <div className="rules-live">
            <div className="rules-live-head">
              目前這顆幣的計分：基準 50
              {FACTOR_ORDER.filter(k => factors[k]?.score).map(k => (
                <span key={k} style={{ color: scoreColor(factors[k].score) }}> {fmtSigned(factors[k].score)}</span>
              ))}
              　=　<b className="rules-live-score">{score} 分（{stanceZh}）</b>
              {50 + factorSum !== score && <span className="rules-live-clip">（超界夾回 0~100）</span>}
            </div>
            <table className="mini-table rules-factor-table">
              <thead><tr><th>因子</th><th>目前狀態</th><th>得分</th></tr></thead>
              <tbody>
                {FACTOR_ORDER.filter(k => factors[k]).map(k => (
                  <tr key={k}>
                    <td>{factors[k].label}</td>
                    <td>{factors[k].note}</td>
                    <td style={{ color: scoreColor(factors[k].score), fontWeight: 600 }}>
                      {fmtSigned(factors[k].score)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <button className="rules-table-toggle" onClick={() => setShowFullTable(v => !v)}>
          {showFullTable ? '▲ 收起完整計分規則表' : '▼ 展開完整計分規則表（6 因子加減分明細）'}
        </button>
        {showFullTable && (
          <table className="mini-table rules-scoring-table">
            <thead><tr><th>因子</th><th>權重</th><th>計分規則（滿足哪條加減幾分）</th></tr></thead>
            <tbody>
              {SCORING_TABLE.map(r => (
                <tr key={r.factor}>
                  <td>{r.factor}</td>
                  <td>{r.weight}</td>
                  <td className="rules-scoring-detail">{r.rules}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ═══ B. 自訂買賣點實驗室 ════════════════════════════════════ */}
      <div className="rules-block">
        <div className="rules-block-title lab-title-row">
          <span>自訂買賣點實驗室——選指標、填數值，馬上看買賣點與歷史績效</span>
          {interval === '1d' ? (
            <button className={`lab-switch ${labOn ? 'on' : ''}`} onClick={() => setLabOn(v => !v)}>
              {labOn ? '● 已啟用（圖上顯示自訂買賣點）' : '○ 點我啟用'}
            </button>
          ) : (
            <span className="lab-hint-off">（僅日線提供；請先切回日線）</span>
          )}
        </div>

        {labOn && interval === '1d' && (
          <>
            {/* 規則設定列 */}
            <div className="lab-rules">
              <label className={`lab-rule ${rules.rsi.on ? 'on' : ''}`}>
                <input type="checkbox" checked={rules.rsi.on} onChange={e => patch('rsi', { on: e.target.checked })} />
                <span className="lab-rule-name">RSI</span>
                <span className="lab-rule-desc">
                  低於 <input type="number" className="lab-num" value={rules.rsi.buyBelow} min={5} max={50}
                              onChange={e => patch('rsi', { buyBelow: +e.target.value })} /> 買入、
                  高於 <input type="number" className="lab-num" value={rules.rsi.sellAbove} min={50} max={95}
                              onChange={e => patch('rsi', { sellAbove: +e.target.value })} /> 賣出
                </span>
              </label>
              <label className={`lab-rule ${rules.macd.on ? 'on' : ''}`}>
                <input type="checkbox" checked={rules.macd.on} onChange={e => patch('macd', { on: e.target.checked })} />
                <span className="lab-rule-name">MACD</span>
                <span className="lab-rule-desc">黃金交叉（柱由負轉正）買入、死亡交叉賣出</span>
              </label>
              <label className={`lab-rule ${rules.ma.on ? 'on' : ''}`}>
                <input type="checkbox" checked={rules.ma.on} onChange={e => patch('ma', { on: e.target.checked })} />
                <span className="lab-rule-name">價穿均線</span>
                <span className="lab-rule-desc">
                  收盤上穿
                  <select className="lab-select" value={rules.ma.period} onChange={e => patch('ma', { period: +e.target.value })}>
                    <option value={20}>MA20（月線）</option>
                    <option value={60}>MA60（季線）</option>
                    <option value={200}>MA200（年線）</option>
                  </select>
                  買入、跌破賣出
                </span>
              </label>
              <label className={`lab-rule ${rules.maCross.on ? 'on' : ''}`}>
                <input type="checkbox" checked={rules.maCross.on} onChange={e => patch('maCross', { on: e.target.checked })} />
                <span className="lab-rule-name">均線交叉</span>
                <span className="lab-rule-desc">
                  <select
                    className="lab-select"
                    value={`${rules.maCross.fast}-${rules.maCross.slow}`}
                    onChange={e => {
                      const [fast, slow] = e.target.value.split('-').map(Number)
                      patch('maCross', { fast, slow })
                    }}
                  >
                    <option value="20-60">MA20 × MA60（月穿季）</option>
                    <option value="20-200">MA20 × MA200（月穿年）</option>
                    <option value="60-200">MA60 × MA200（季穿年）</option>
                  </select>
                  黃金交叉（快線上穿）買入、死亡交叉賣出
                </span>
              </label>
              <label className={`lab-rule ${rules.bb.on ? 'on' : ''}`}>
                <input type="checkbox" checked={rules.bb.on} onChange={e => patch('bb', { on: e.target.checked })} />
                <span className="lab-rule-name">布林</span>
                <span className="lab-rule-desc">收盤觸及下軌買入、觸及上軌賣出</span>
              </label>
              <div className="lab-mode">
                買入條件組合：
                <button className={`lab-mode-btn ${rules.buyMode === 'any' ? 'active' : ''}`}
                        onClick={() => setRules(r => ({ ...r, buyMode: 'any' }))}
                        title="訊號多而雜：勾選的條件任何一個成立就買">任一成立</button>
                <button className={`lab-mode-btn ${rules.buyMode === 'all' ? 'active' : ''}`}
                        onClick={() => setRules(r => ({ ...r, buyMode: 'all' }))}
                        title="訊號少而精：勾選的條件同時成立才買">全部成立</button>
                <span className="lab-mode-note">（賣出恆為「任一成立」＝出場從嚴）</span>
              </div>
            </div>

            {/* 結果統計 */}
            {result?.stats ? (
              <>
                <div className="lab-stats">
                  <div className="lab-stat">
                    <span className="lab-stat-lbl">交易次數</span>
                    <span className="lab-stat-val">{result.stats.trades} 筆</span>
                  </div>
                  <div className="lab-stat">
                    <span className="lab-stat-lbl">勝率</span>
                    <span className="lab-stat-val" style={{ color: result.stats.winRate >= 50 ? '#22c55e' : '#f59e0b' }}>
                      {result.stats.winRate != null ? `${result.stats.winRate}%` : '—'}
                    </span>
                  </div>
                  <div className="lab-stat">
                    <span className="lab-stat-lbl">規則總報酬</span>
                    <span className="lab-stat-val" style={{ color: result.stats.totalReturnPct >= 0 ? '#22c55e' : '#ef4444' }}>
                      {result.stats.totalReturnPct >= 0 ? '+' : ''}{result.stats.totalReturnPct}%
                    </span>
                  </div>
                  <div className="lab-stat">
                    <span className="lab-stat-lbl">同期買入持有</span>
                    <span className="lab-stat-val" style={{ color: result.stats.buyHoldPct >= 0 ? '#22c55e' : '#ef4444' }}>
                      {result.stats.buyHoldPct >= 0 ? '+' : ''}{result.stats.buyHoldPct}%
                    </span>
                  </div>
                  <div className="lab-stat">
                    <span className="lab-stat-lbl">平均持倉</span>
                    <span className="lab-stat-val">{result.stats.avgHoldDays ?? '—'} 天</span>
                  </div>
                </div>
                {result.open && (
                  <div className="lab-open-pos">
                    ⏳ 目前持有中（未平倉）：{result.open.entry_date} 進場 ${result.open.entry_price.toLocaleString()}
                    → 最新收盤 ${result.open.last_close.toLocaleString()}
                    （未實現 <b style={{ color: result.open.unrealized_pct >= 0 ? '#22c55e' : '#ef4444' }}>
                      {result.open.unrealized_pct >= 0 ? '+' : ''}{result.open.unrealized_pct}%</b>）
                  </div>
                )}
                <div className="lab-note">
                  ✅ 買賣點已標在上方 K 線圖（綠↑買入、↓賣出）。模擬區間＝圖表目前顯示的
                  {result.stats.periodStart} ~ {result.stats.periodEnd}（{result.stats.bars} 根日 K；
                  切換上方 1M/3M/6M/1Y 會跟著重算）。已含手續費 0.1%/邊＋滑價 0.05%，訊號隔日開盤成交。
                </div>
              </>
            ) : (
              <div className="lab-note lab-empty">
                {result?.enabledCount === 0
                  ? '請至少勾選一個指標條件。'
                  : '這組條件在目前區間沒有產生任何完整交易——可放寬門檻值（例如 RSI 35/65）、改「任一成立」、或把上方區間拉長（6M/1Y）再試。'}
              </div>
            )}

            {/* 怎麼選才有依據 */}
            <div className="lab-guide">
              <div className="lab-guide-title">💡 怎麼選指標與數值才「正確」？</div>
              <ul>
                <li><b>沒有萬用的正確答案，但有經典起點</b>：RSI 30/70（震盪市有效、單邊趨勢會鈍化）；
                    MACD 交叉（趨勢市有效、盤整假訊號多）；均線 MA20 抓波段、MA60/200 抓大趨勢；布林軌道抓極端價。</li>
                <li><b>用上面的數字說話</b>：調整條件後直接對照「規則總報酬 vs 同期買入持有」與勝率——
                    在這顆幣的歷史上贏過買入持有的組合，才算有依據的參數。</li>
                <li><b>訊號太多＝雜訊、太少＝錯過</b>：「全部成立」訊號少而精，「任一成立」多而雜；
                    交易次數 5~20 筆通常較有統計參考性。</li>
                <li><b>過去有效 ≠ 未來保證</b>：這是歷史驗證工具，換個區間（1M↔1Y）看結論是否穩定，比單一區間的漂亮數字更重要。</li>
              </ul>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
