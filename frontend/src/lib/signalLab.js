/**
 * signalLab.js — 自訂買賣點實驗室的模擬引擎（純函式，零外部相依）
 *
 * 讓使用者「選指標 + 填數值」→ 立即在載入的 K 線資料上標出買賣點並統計績效。
 * 交易慣例與正式回測（src/backtest.py）一致，數字才有可比性：
 *   - 條件在第 i 天收盤成立 → 第 i+1 天「開盤」成交（不可能用當天收盤價買到當天）
 *   - 費用假設：手續費 0.1%/邊 + 滑價 0.05%（與回測面板預設相同）
 *   - 只做多（現貨）：無持倉時看買入條件、有持倉時看賣出條件
 *
 * 支援的規則（rules 物件；on=false 的規則不參與）：
 *   rsi:     { on, buyBelow, sellAbove } RSI 低於 X 買 / 高於 Y 賣（狀態條件）
 *   macd:    { on }                      MACD 柱由負轉正買（黃金交叉）/ 由正轉負賣（死亡交叉）
 *   ma:      { on, period }              收盤「上穿」均線買 / 「跌破」賣（價格×均線交叉；period: 20|60|200）
 *   maCross: { on, fast, slow }          快均線上穿慢均線買（均線黃金交叉）/ 下穿賣（死亡交叉）
 *   bb:      { on }                      收盤觸及布林下軌買 / 觸及上軌賣
 *   buyMode: 'any' | 'all'               買入條件：任一成立 / 全部成立（賣出恆為任一成立＝出場從嚴）
 */

export const DEFAULT_RULES = {
  rsi:     { on: true,  buyBelow: 30, sellAbove: 70 },
  macd:    { on: false },
  ma:      { on: false, period: 20 },
  maCross: { on: false, fast: 20, slow: 60 },
  bb:      { on: false },
  buyMode: 'any',
}

const FEE  = 0.001    // 手續費 0.1%（單邊）
const SLIP = 0.0005   // 滑價 0.05%

/**
 * 模擬。prices=[{date,open,high,low,close,volume}]（時間升冪）、
 * indicators=[{date,RSI,HIST,MA20,MA60,MA200,BB_UPPER,BB_LOWER,...}]（同 API 格式）。
 * 回傳 { trades, stats, enabledCount } 或 null（資料不足）。
 * trades 內含未平倉部位（exit_date=null），可直接餵給 K 線圖的買賣標記。
 */
export function simulateRules(prices, indicators, rules) {
  if (!prices || prices.length < 3) return null
  const indMap = new Map((indicators ?? []).map(d => [d.date, d]))

  // ── 各規則的當日買/賣條件（i 為 prices 索引；回傳 true/false，資料不足回 null）──
  const conds = []
  if (rules.rsi?.on) {
    conds.push({
      key: 'rsi',
      buy:  (i) => { const v = indMap.get(prices[i].date)?.RSI; return v == null ? null : v < rules.rsi.buyBelow },
      sell: (i) => { const v = indMap.get(prices[i].date)?.RSI; return v == null ? null : v > rules.rsi.sellAbove },
    })
  }
  if (rules.macd?.on) {
    conds.push({
      key: 'macd',
      buy:  (i) => {
        if (i < 1) return null
        const h = indMap.get(prices[i].date)?.HIST, ph = indMap.get(prices[i - 1].date)?.HIST
        return (h == null || ph == null) ? null : (ph < 0 && h >= 0)
      },
      sell: (i) => {
        if (i < 1) return null
        const h = indMap.get(prices[i].date)?.HIST, ph = indMap.get(prices[i - 1].date)?.HIST
        return (h == null || ph == null) ? null : (ph > 0 && h <= 0)
      },
    })
  }
  if (rules.ma?.on) {
    const field = `MA${rules.ma.period}`
    conds.push({
      key: 'ma',
      buy:  (i) => {
        if (i < 1) return null
        const m = indMap.get(prices[i].date)?.[field], pm = indMap.get(prices[i - 1].date)?.[field]
        if (m == null || pm == null) return null
        return prices[i - 1].close <= pm && prices[i].close > m     // 上穿
      },
      sell: (i) => {
        if (i < 1) return null
        const m = indMap.get(prices[i].date)?.[field], pm = indMap.get(prices[i - 1].date)?.[field]
        if (m == null || pm == null) return null
        return prices[i - 1].close >= pm && prices[i].close < m     // 跌破
      },
    })
  }
  if (rules.maCross?.on) {
    const fF = `MA${rules.maCross.fast}`, sF = `MA${rules.maCross.slow}`
    conds.push({
      key: 'maCross',
      buy:  (i) => {                                                  // 均線黃金交叉：快線由下往上穿慢線
        if (i < 1) return null
        const d = indMap.get(prices[i].date), pd = indMap.get(prices[i - 1].date)
        if (d?.[fF] == null || d?.[sF] == null || pd?.[fF] == null || pd?.[sF] == null) return null
        return pd[fF] <= pd[sF] && d[fF] > d[sF]
      },
      sell: (i) => {                                                  // 均線死亡交叉：快線由上往下穿慢線
        if (i < 1) return null
        const d = indMap.get(prices[i].date), pd = indMap.get(prices[i - 1].date)
        if (d?.[fF] == null || d?.[sF] == null || pd?.[fF] == null || pd?.[sF] == null) return null
        return pd[fF] >= pd[sF] && d[fF] < d[sF]
      },
    })
  }
  if (rules.bb?.on) {
    conds.push({
      key: 'bb',
      buy:  (i) => { const d = indMap.get(prices[i].date); return d?.BB_LOWER == null ? null : prices[i].close <= d.BB_LOWER },
      sell: (i) => { const d = indMap.get(prices[i].date); return d?.BB_UPPER == null ? null : prices[i].close >= d.BB_UPPER },
    })
  }
  if (conds.length === 0) return { trades: [], stats: null, enabledCount: 0 }

  // 買入：any=任一成立 / all=全部成立（null=無資料不算成立；all 模式下有 null 即不成立）
  const buyAt = (i) => {
    const vals = conds.map(c => c.buy(i))
    return rules.buyMode === 'all' ? vals.every(v => v === true) : vals.some(v => v === true)
  }
  // 賣出恆為任一成立（出場從嚴：任何一個賣出訊號都先離場）
  const sellAt = (i) => conds.some(c => c.sell(i) === true)

  // ── 逐日走訪：條件成立的「隔天開盤」成交 ─────────────────────────────
  const trades = []
  let pos = null
  for (let i = 0; i < prices.length - 1; i++) {          // 最後一天的訊號沒有隔日可成交
    const next = prices[i + 1]
    if (!pos) {
      if (buyAt(i) && next.open > 0) {
        pos = { entry_date: next.date, entry_price: +(next.open * (1 + SLIP)).toFixed(6), reason: conds.filter(c => c.buy(i) === true).map(c => c.key) }
      }
    } else if (sellAt(i) && next.open > 0) {
      const exitPrice = next.open * (1 - SLIP)
      const ret = (exitPrice * (1 - FEE)) / (pos.entry_price * (1 + FEE)) - 1
      trades.push({
        entry_date: pos.entry_date, exit_date: next.date,
        entry_price: pos.entry_price, exit_price: +exitPrice.toFixed(6),
        return_pct: +(ret * 100).toFixed(2),
        profit: ret > 0,
        hold_days: Math.round((Date.parse(next.date) - Date.parse(pos.entry_date)) / 86400000),
        exit_reason: 'rule_sell', exit_label: '賣出',
      })
      pos = null
    }
  }

  // 未平倉部位：以最後收盤估值（誠實標示為未實現）
  let open = null
  if (pos) {
    const lastClose = prices[prices.length - 1].close
    const unreal = (lastClose * (1 - FEE)) / (pos.entry_price * (1 + FEE)) - 1
    open = {
      entry_date: pos.entry_date, entry_price: pos.entry_price,
      last_close: lastClose, unrealized_pct: +(unreal * 100).toFixed(2),
    }
    // 圖上仍畫進場箭頭（exit_date=null → 只有買入標記）
    trades.push({ entry_date: pos.entry_date, entry_price: pos.entry_price, exit_date: null })
  }

  // ── 統計（只算已平倉交易；買入持有以同區間對照）──────────────────────
  const closed = trades.filter(t => t.exit_date)
  let stats = null
  if (closed.length || open) {
    const wins = closed.filter(t => t.return_pct > 0).length
    const compound = closed.reduce((acc, t) => acc * (1 + t.return_pct / 100), 1)
    const first = prices[0], last = prices[prices.length - 1]
    stats = {
      trades: closed.length,
      wins,
      winRate: closed.length ? +(wins / closed.length * 100).toFixed(1) : null,
      totalReturnPct: +((compound - 1) * 100).toFixed(1),
      buyHoldPct: first.close > 0 ? +((last.close / first.close - 1) * 100).toFixed(1) : null,
      avgHoldDays: closed.length ? +(closed.reduce((s, t) => s + t.hold_days, 0) / closed.length).toFixed(1) : null,
      periodStart: first.date, periodEnd: last.date, bars: prices.length,
    }
  }

  return { trades, open, stats, enabledCount: conds.length }
}
