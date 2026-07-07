/**
 * useLivePrices — 從 Binance WebSocket 取「即時最新價 + 24h 漲跌」（純前端直連）。
 *
 * K 棒/訊號維持排程更新；這個只讓「最新價」秒級跳動，讓盤面活起來。
 * 失敗（斷線/被擋）自動退避重連；拿不到就回傳空物件，UI 退回排程價，不影響原功能。
 *
 * 用法：const live = useLivePrices(['BTCUSDT','ETHUSDT',...])
 *      live['BTCUSDT'] → { price, changePct }（沒資料時 undefined）
 */
import { useEffect, useRef, useState } from 'react'

export default function useLivePrices(symbols) {
  const [prices, setPrices] = useState({})
  const dataRef = useRef({})
  const symsKey = (symbols || []).join(',')   // 穩定依賴：symbols 內容變了才重連

  useEffect(() => {
    const syms = symsKey ? symsKey.split(',') : []
    if (!syms.length) return

    const streams = syms.map(s => `${s.toLowerCase()}@miniTicker`).join('/')
    const url = `wss://stream.binance.com:9443/stream?streams=${streams}`
    let ws = null, closed = false, retry = 0, dirty = false, reconnectId = null

    const connect = () => {
      ws = new WebSocket(url)
      ws.onopen = () => { retry = 0 }
      ws.onmessage = (ev) => {
        try {
          const m = JSON.parse(ev.data)?.data
          if (!m || m.e !== '24hrMiniTicker') return
          const c = parseFloat(m.c), o = parseFloat(m.o)   // c=最新價、o=24h 前開盤
          if (c > 0) {
            dataRef.current[m.s] = { price: c, changePct: o > 0 ? (c / o - 1) * 100 : null }
            dirty = true
          }
        } catch { /* 忽略單筆解析錯誤 */ }
      }
      ws.onclose = () => {
        if (closed) return
        retry = Math.min(retry + 1, 6)
        reconnectId = setTimeout(connect, 1000 * retry)   // 退避重連
      }
      ws.onerror = () => { try { ws.close() } catch { /* onclose 會接手重連 */ } }
    }
    connect()

    // 每秒把累積的最新價刷進 state（節流 re-render；沒有新資料就不刷）
    const flushId = setInterval(() => {
      if (dirty) { dirty = false; setPrices({ ...dataRef.current }) }
    }, 1000)

    return () => {
      closed = true
      clearInterval(flushId)
      if (reconnectId) clearTimeout(reconnectId)
      try { ws && ws.close() } catch { /* 卸載時關閉 */ }
    }
  }, [symsKey])

  return prices
}
