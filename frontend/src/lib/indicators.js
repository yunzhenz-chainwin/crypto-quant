/**
 * indicators.js — 前端技術指標計算(純函式,抽成獨立模組以便單獨驗證與重用)
 *
 * 由 CandlestickChart 使用;另有 scripts 端的驗證會 import 這裡的函式,
 * 與 pandas_ta(獨立參考)逐點比對,確保計算正確。
 *
 * 輸入 prices：[{ date, open, high, low, close, volume }, ...](已按時間升冪)
 */

// 簡單移動平均 SMA：回傳 [{time, value}]
export function sma(prices, period) {
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

// 指數移動平均 EMA：對近期價格加權更重;以前 period 根的 SMA 當起始值
export function ema(prices, period) {
  const out = []
  const k = 2 / (period + 1)
  let prev = null
  for (let i = 0; i < prices.length; i++) {
    if (i === period - 1) {
      let sum = 0
      for (let j = 0; j < period; j++) sum += prices[j].close
      prev = sum / period
      out.push({ time: prices[i].date, value: prev })
    } else if (i >= period) {
      prev = prices[i].close * k + prev * (1 - k)
      out.push({ time: prices[i].date, value: prev })
    }
  }
  return out
}

// 依類型回傳 SMA 或 EMA
export function movingAvg(prices, period, type) {
  return type === 'EMA' ? ema(prices, period) : sma(prices, period)
}

// KDJ（9 日）：RSV → K(快) → D(慢) → J=3K-2D，K/D 起始 50
export function kdj(prices, n = 9) {
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
export function dmi(prices, n = 14) {
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
export function bias(prices, period) {
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

// ATR 平均真實區間：波動度（不分方向）。TR = max(高低差, |高−前收|, |低−前收|)，
// 首值取前 n 根 TR 平均、之後 Wilder 平滑（與 pandas_ta 預設一致）。回傳 [{time, value}]
export function atr(prices, n = 14) {
  const out = []
  if (prices.length < n + 1) return out
  const tr = new Array(prices.length).fill(0)
  for (let i = 1; i < prices.length; i++) {
    const p = prices[i], prevC = prices[i - 1].close
    tr[i] = Math.max(p.high - p.low, Math.abs(p.high - prevC), Math.abs(p.low - prevC))
  }
  let prev = null
  for (let i = n; i < prices.length; i++) {
    if (i === n) {
      let sum = 0
      for (let j = 1; j <= n; j++) sum += tr[j]
      prev = sum / n
    } else {
      prev = (prev * (n - 1) + tr[i]) / n
    }
    out.push({ time: prices[i].date, value: prev })
  }
  return out
}

// OBV 能量潮：累積成交量（收漲加量、收跌減量、持平不變）；看量價背離。
// 絕對值無意義，只看走勢方向。回傳 [{time, value}]
export function obv(prices) {
  const out = []
  let cum = 0
  for (let i = 0; i < prices.length; i++) {
    const p = prices[i]
    if (i > 0) {
      const prevC = prices[i - 1].close
      if (p.close > prevC) cum += (p.volume || 0)
      else if (p.close < prevC) cum -= (p.volume || 0)
    }
    out.push({ time: p.date, value: cum })
  }
  return out
}
