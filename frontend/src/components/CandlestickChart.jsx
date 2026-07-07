/**
 * CandlestickChart.jsx — 整合圖表面板(方案 B:主圖 + 單一擺盪指標槽)
 * 使用 lightweight-charts v5（多面板 pane 共用時間軸/游標/縮放）
 *
 * 主圖疊層(可逐一開關):快線/慢線 MA(天數可調)、MA200、布林帶、成交量、買賣標記
 * 擺盪指標槽(只留一個副面板,用分頁切換):RSI / MACD / KDJ / DMI / BIAS / 無
 *
 * 指標來源:MA(快/慢/200)、KDJ/DMI/BIAS → 前端算;布林帶/RSI/MACD → 後端 indicators。
 *
 * Props：prices（OHLCV）、indicators（含 BB/RSI/MACD…）、trades（回測交易）、
 *        interval（'1d' 日線 / '1h' 時線；時線用 epoch 時間軸並隱藏回測標記）
 */
import { useEffect, useRef, useState } from 'react'
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries,
  CrosshairMode, createSeriesMarkers,
} from 'lightweight-charts'
import { movingAvg, kdj, dmi, bias, atr, obv } from '../lib/indicators'

// 一般圖層開關按鈕
function Toggle({ on, onClick, color, children }) {
  return (
    <button
      className={`layer-toggle ${on ? 'on' : ''}`}
      style={{ color: on ? color : '#64748b', borderColor: on ? color : 'var(--border)' }}
      onClick={onClick}
    >
      {on ? '●' : '○'} {children}
    </button>
  )
}


// 時間欄轉圖表格式：日線 'YYYY-MM-DD' 字串直接用；
// 時線 'YYYY-MM-DD HH:MM:SS'（UTC）→ epoch 秒，並平移到本地時區
// （lightweight-charts 一律以 UTC 顯示數字時間戳，平移後才會顯示成本地時間）。
const TZ_OFFSET_SEC = -new Date().getTimezoneOffset() * 60
function toChartTime(date) {
  if (!date || date.length <= 10) return date
  return Math.floor(Date.parse(date.replace(' ', 'T') + 'Z') / 1000) + TZ_OFFSET_SEC
}

const OSC_LIST = ['RSI', 'MACD', 'KDJ', 'DMI', 'BIAS', 'ATR', 'OBV', '無']

// 擺盪指標的中文名（顯示在按鈕上；與下方「怎麼看」說明用詞一致）
const OSC_NAME = {
  RSI: '相對強弱指標',
  MACD: '指數平滑異同均線',
  KDJ: '隨機指標',
  DMI: '趨向指標',
  BIAS: '乖離率',
  ATR: '平均真實區間',
  OBV: '能量潮',
}

// 各擺盪指標的說明：summary（一句話）＋ sections（按「看詳細」展開的完整教學）
const OSC_DETAIL = {
  RSI: {
    summary: '相對強弱指標（0~100）：衡量漲跌力道，判斷超買超賣與動能。',
    sections: [
      ['是什麼', '衡量近期「上漲力道 vs 下跌力道」的動能指標，數值固定在 0~100 之間。'],
      ['怎麼算', '取 14 天，分別平均上漲日的漲幅與下跌日的跌幅（Wilder 平滑），相對強度 RS ＝ 平均漲幅 ÷ 平均跌幅，RSI ＝ 100 − 100 ÷ (1 + RS)。'],
      ['怎麼看', '>70 ＝ 超買（漲多、隨時可能回檔）；<30 ＝ 超賣（跌多、可能反彈）；50 為多空分界。'],
      ['實戰訊號', '① 由 <30 向上突破 30：偏多參考。② 由 >70 向下跌破 70：偏空 / 減碼參考。③ 背離最重要：價格創新高、RSI 沒創新高 → 動能轉弱（頂背離、警戒回檔）；價創新低、RSI 沒創新低 → 底背離（偏多）。'],
      ['注意', '強勢多頭時 RSI 可長時間停在 70 以上（鈍化），超買不等於馬上跌；盤整時雜訊多。務必搭配趨勢與其他指標，別單獨使用。'],
    ],
  },
  MACD: {
    summary: '指數平滑異同均線：看動能強弱與趨勢轉折（交叉）。',
    sections: [
      ['是什麼', '用兩條不同速度的指數均線之差，捕捉「動能的加速與減速」與趨勢轉折。'],
      ['怎麼算', 'MACD 線 ＝ EMA12 − EMA26（快減慢）；訊號線 ＝ MACD 的 EMA9；柱狀圖 ＝ MACD 線 − 訊號線。'],
      ['怎麼看', 'MACD 線在 0 軸上方偏多、下方偏空；柱狀越長動能越強、縮短代表動能減弱。'],
      ['實戰訊號', '① 黃金交叉：MACD 線由下往上穿訊號線 → 偏多。② 死亡交叉：由上往下穿 → 偏空。③ 柱狀由負轉正 ＝ 動能翻多的早期訊號。④ 價格與 MACD 背離 → 趨勢可能反轉。'],
      ['注意', 'MACD 用均線計算、屬「落後指標」，盤整時常出現假交叉；趨勢明確時最好用。'],
    ],
  },
  KDJ: {
    summary: '隨機指標（0~100）：抓短線超買超賣與轉折，反應快。',
    sections: [
      ['是什麼', '看「收盤價在近期高低區間的相對位置」，對短線轉折反應靈敏。'],
      ['怎麼算', '取 9 天，RSV ＝（收盤 − 最低）÷（最高 − 最低）× 100；K ＝ RSV 的平滑、D ＝ K 的平滑、J ＝ 3K − 2D（最敏感）。'],
      ['怎麼看', '>80 超買、<20 超賣；K、D、J 三線中，J 擺動最大、最領先。'],
      ['實戰訊號', '① K 由下往上穿 D（低檔黃金交叉，尤其 20 以下）→ 偏多。② K 由上往下穿 D（高檔死亡交叉，尤其 80 以上）→ 偏空。③ J 衝破 100 或跌破 0，常是短線過熱 / 過冷的極端。'],
      ['注意', '訊號較「快」也較「雜」，強趨勢中容易鈍化；適合短線、震盪盤，搭配趨勢指標較穩。'],
    ],
  },
  DMI: {
    summary: '趨向指標：判斷「有沒有趨勢、往哪個方向、多強」。',
    sections: [
      ['是什麼', '同時判斷「方向」（多還是空）與「趨勢強度」的指標。'],
      ['怎麼算', '比較每天創新高 / 新低的幅度算出 +DM / −DM，經 14 天 Wilder 平滑得 +DI、−DI；再由兩者差距算出 ADX（趨勢強度）。'],
      ['怎麼看', '+DI（綠）在 −DI（紅）之上 ＝ 多方主導、反之空方；ADX（黃）>25 趨勢明確、<20 盤整。'],
      ['實戰訊號', '① +DI 上穿 −DI 且 ADX 上升 → 多方趨勢成形。② −DI 上穿 +DI → 空方趨勢。③ ADX 由低往上 ＝ 趨勢啟動；ADX 走平 / 下滑 ＝ 趨勢轉弱或進入盤整。'],
      ['注意', 'ADX 只看「強度」不分多空（大跌時 ADX 也很高）；盤整時（ADX<20）方向訊號不可靠。'],
    ],
  },
  BIAS: {
    summary: '乖離率（%）：價格偏離均線多遠，抓過度乖離的回歸。',
    sections: [
      ['是什麼', '衡量目前價格「偏離均線」的百分比，判斷是否漲 / 跌過頭。'],
      ['怎麼算', 'BIAS ＝（收盤 − N 日均線）÷ N 日均線 × 100%。圖上為 6 日與 24 日兩條。'],
      ['怎麼看', '正值 ＝ 價在均線上方（偏強）、負值 ＝ 下方（偏弱）；絕對值越大代表偏離越多。'],
      ['實戰訊號', '① 正乖離過大 → 短線漲多、易拉回均線（偏空回檔）。② 負乖離過大 → 跌深、易反彈回均線（偏多）。③「過大」無絕對值，需看該幣歷史區間相對判斷。'],
      ['注意', '強趨勢中乖離可持續很大，不代表馬上反轉；門檻因幣而異，宜參考該幣過去的乖離區間。'],
    ],
  },
  ATR: {
    summary: '平均真實區間：衡量波動「大小」（不分方向），常用來設停損、判斷行情冷熱。',
    sections: [
      ['是什麼', '衡量每根 K 棒「真實波動幅度」的平均值——只看波動多大，不管漲或跌。'],
      ['怎麼算', '真實區間 TR ＝ max（當根高低差、|最高−前收|、|最低−前收|）；ATR ＝ TR 的 14 期 Wilder 平滑。'],
      ['怎麼看', 'ATR 變大 ＝ 波動加劇（行情轉熱或恐慌）；變小 ＝ 波動收斂（盤整、量縮）。數值大小與該幣價位成正比。'],
      ['實戰訊號', '① 設停損：常用「進場價 − N×ATR」，讓停損隨波動自動放寬或收緊。② ATR 由低檔開始放大，常伴隨突破或變盤。'],
      ['注意', 'ATR 只講波動、不講方向；低價幣數字小、高價幣大，別用絕對值跨幣比較。'],
    ],
  },
  OBV: {
    summary: '能量潮：把成交量依漲跌累加，看「量」有沒有支撐「價」（量價背離）。',
    sections: [
      ['是什麼', '累積型量能指標——收漲把當根量加上去、收跌減掉，觀察資金是流入還是流出。'],
      ['怎麼算', '收盤＞前收 → OBV ＋ 當根量；收盤＜前收 → OBV − 當根量；持平不變。（絕對值無意義，看走勢方向）'],
      ['怎麼看', 'OBV 與價格同步走高 ＝ 上漲有量能支撐；OBV 走平或與價背離 ＝ 上漲缺量、較不健康。'],
      ['實戰訊號', '① 頂背離：價創新高、OBV 沒創新高 → 追高動能不足（警戒）。② 底背離：價創新低、OBV 沒創新低 → 賣壓趨緩（偏多）。'],
      ['注意', 'OBV 是相對趨勢工具，絕對數值不重要；單日爆量可能來自特殊事件，需搭配價格一起判讀。'],
    ],
  },
}

export default function CandlestickChart({ prices, indicators, trades, interval = '1d', compact = false }) {
  const containerRef = useRef(null)
  const tooltipRef   = useRef(null)   // 懸停資訊框（直接操作 DOM，避免高頻 re-render）
  const [maType, setMaType] = useState('EMA')   // 均線類型:SMA / EMA
  // 多條可調均線(天數可改、可逐條開關;顏色對應圖上的線)
  const [mas, setMas] = useState([
    { p: 5,   on: true,  color: '#f59e0b' },
    { p: 10,  on: true,  color: '#22d3ee' },
    { p: 20,  on: true,  color: '#818cf8' },
    { p: 60,  on: false, color: '#38bdf8' },
    { p: 120, on: false, color: '#ec4899' },
  ])
  const [showBB,   setShowBB]   = useState(true)
  const [showVol,  setShowVol]  = useState(true)
  const [showMarkers, setShowMarkers] = useState(true)
  const [osc, setOsc] = useState('RSI')   // 單一擺盪指標槽
  const [oscDetail, setOscDetail] = useState(false)  // 指標詳細說明是否展開


  useEffect(() => {
    if (!containerRef.current || !prices || prices.length === 0) return

    const oscOn = osc !== '無'
    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#0f172a' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155', timeVisible: true, secondsVisible: false },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight || (oscOn ? (compact ? 420 : 560) : (compact ? 300 : 420)),
    })

    // 正規化時間欄：日線維持日期字串、時線轉為本地化 epoch 秒。
    // 之後所有序列（含 lib/indicators 前端計算）都吃這兩份，一致同軸。
    const P   = prices.map(p => ({ ...p, date: toChartTime(p.date) }))
    const IND = (indicators ?? []).map(d => ({ ...d, date: toChartTime(d.date) }))

    // ── 蠟燭圖（主面板）─────────────────────────────────────────────
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e', downColor: '#ef4444', borderVisible: false,
      wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    })
    candleSeries.setData(P.map(p => ({
      time: p.date, open: p.open, high: p.high, low: p.low, close: p.close,
    })))

    const hasInd = IND.length > 0
    const getInd = (key) => hasInd
      ? IND.filter(d => d[key] != null).map(d => ({ time: d.date, value: d[key] }))
      : []
    const addLine = (data, opts) => { if (data.length) chart.addSeries(LineSeries, opts).setData(data) }
    const pin100 = () => ({ priceRange: { minValue: 0, maxValue: 100 } })

    // ── 均線（可調天數）+ 布林帶 + 成交量（主面板）────────────────
    mas.forEach(ma => {
      if (ma.on) addLine(movingAvg(P, ma.p, maType), { color: ma.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: `${maType}${ma.p}` })
    })
    if (showBB) {
      addLine(getInd('BB_UPPER'), { color: 'rgba(248,113,113,0.55)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, title: 'BB+' })
      addLine(getInd('BB_LOWER'), { color: 'rgba(74,222,128,0.55)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, title: 'BB-' })
    }
    if (showVol) {
      const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'vol' })
      chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } })
      vol.setData(P.map(p => ({
        time: p.date, value: p.volume,
        color: p.close >= p.open ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)',
      })))
    }

    // ── 單一擺盪指標副面板（pane 1;由 osc 決定顯示哪一個）──────────
    if (oscOn) {
      const pane = 1
      if (osc === 'RSI') {
        const rsiData = getInd('RSI')
        if (rsiData.length) {
          const rsi = chart.addSeries(LineSeries, { color: '#34d399', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'RSI', autoscaleInfoProvider: pin100 }, pane)
          rsi.setData(rsiData)
          rsi.createPriceLine({ price: 70, color: 'rgba(239,68,68,0.6)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '70' })
          rsi.createPriceLine({ price: 30, color: 'rgba(34,197,94,0.6)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '30' })
        }
      } else if (osc === 'MACD' && hasInd) {
        const histData = IND.filter(d => d.HIST != null).map(d => ({ time: d.date, value: d.HIST, color: d.HIST >= 0 ? 'rgba(34,197,94,0.6)' : 'rgba(239,68,68,0.6)' }))
        if (histData.length) chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false, title: '柱' }, pane).setData(histData)
        const macdData = getInd('MACD')
        if (macdData.length) chart.addSeries(LineSeries, { color: '#60a5fa', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'MACD' }, pane).setData(macdData)
        const signalData = getInd('SIGNAL')
        if (signalData.length) chart.addSeries(LineSeries, { color: '#f97316', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, title: '訊號' }, pane).setData(signalData)
      } else if (osc === 'KDJ') {
        const kd = kdj(P, 9)
        if (kd.length) {
          const kS = chart.addSeries(LineSeries, { color: '#eab308', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'K', autoscaleInfoProvider: pin100 }, pane)
          kS.setData(kd.map(x => ({ time: x.time, value: x.k })))
          kS.createPriceLine({ price: 80, color: 'rgba(239,68,68,0.6)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '80' })
          kS.createPriceLine({ price: 20, color: 'rgba(34,197,94,0.6)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '20' })
          chart.addSeries(LineSeries, { color: '#22d3ee', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'D', autoscaleInfoProvider: pin100 }, pane).setData(kd.map(x => ({ time: x.time, value: x.d })))
          chart.addSeries(LineSeries, { color: '#f472b6', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'J', autoscaleInfoProvider: pin100 }, pane).setData(kd.map(x => ({ time: x.time, value: x.j })))
        }
      } else if (osc === 'DMI') {
        const dm = dmi(P, 14)
        if (dm.length) {
          chart.addSeries(LineSeries, { color: '#22c55e', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: '+DI', autoscaleInfoProvider: pin100 }, pane).setData(dm.map(x => ({ time: x.time, value: x.pdi })))
          chart.addSeries(LineSeries, { color: '#ef4444', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: '-DI', autoscaleInfoProvider: pin100 }, pane).setData(dm.map(x => ({ time: x.time, value: x.mdi })))
          const adxS = chart.addSeries(LineSeries, { color: '#eab308', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true, title: 'ADX', autoscaleInfoProvider: pin100 }, pane)
          adxS.setData(dm.filter(x => x.adx != null).map(x => ({ time: x.time, value: x.adx })))
          adxS.createPriceLine({ price: 25, color: 'rgba(148,163,184,0.6)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '25' })
        }
      } else if (osc === 'BIAS') {
        const b6 = bias(P, 6), b24 = bias(P, 24)
        if (b6.length) {
          const s = chart.addSeries(LineSeries, { color: '#fb923c', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'BIAS6' }, pane)
          s.setData(b6)
          s.createPriceLine({ price: 0, color: 'rgba(148,163,184,0.5)', lineWidth: 1, lineStyle: 2, axisLabelVisible: false })
        }
        if (b24.length) chart.addSeries(LineSeries, { color: '#60a5fa', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'BIAS24' }, pane).setData(b24)
      } else if (osc === 'ATR') {
        const a = atr(P, 14)
        if (a.length) chart.addSeries(LineSeries, { color: '#a78bfa', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true, title: 'ATR' }, pane).setData(a)
      } else if (osc === 'OBV') {
        const o = obv(P)
        if (o.length) chart.addSeries(LineSeries, { color: '#38bdf8', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true, title: 'OBV' }, pane).setData(o)
      }
    }

    // ── 買賣標記（回測是日線策略，僅日線圖顯示；時線時間軸型別也不相容）──
    // t.exit_label 可覆寫出場文字（自訂訊號實驗室用「賣出」而非出場原因）
    let declutterMarkers = null   // 供 rAF / resize / cleanup 引用（無標記時維持 null）
    if (interval === '1d' && showMarkers && trades && trades.length > 0) {
      // 出場標記用「真實出場原因」（停損/停利/訊號出場），與交易明細表一致；
      // 舊版用賺賠推斷成「獲利/停損」——訊號出場也可能賺錢，會標錯原因。
      const EXIT_MARK = { stop_loss: '停損', take_profit: '停利', signal_exit: '訊號出場' }
      // 標記上的價位自適應小數（低價幣不能被 toFixed(0) 捨成 0）
      const fmtPx = (v) => { const n = Number(v); return !(n > 0) ? '' : n < 1 ? n.toFixed(3) : n < 100 ? n.toFixed(1) : n.toFixed(0) }
      // 報酬率精簡：≥10% 取整、其餘 1 位，避免「-6.282%」這種長字串塞爆版面
      const fmtPct = (v) => { const n = Number(v); if (!Number.isFinite(n)) return ''; return `${n > 0 ? '+' : ''}${Math.abs(n) >= 10 ? n.toFixed(0) : n.toFixed(1)}%` }
      const markers = []
      trades.forEach(t => {
        if (t.entry_date) {
          const px = fmtPx(t.entry_price)
          markers.push({ time: t.entry_date, position: 'belowBar', color: '#22c55e', shape: 'arrowUp', text: px ? `買入 $${px}` : '買入' })
        }
        if (t.exit_date) {
          const label = t.exit_label ?? EXIT_MARK[t.exit_reason] ?? (t.profit ? '獲利' : '停損')
          const px = fmtPx(t.exit_price)
          const pct = fmtPct(t.return_pct)
          markers.push({ time: t.exit_date, position: 'aboveBar', color: t.profit ? '#60a5fa' : '#ef4444', shape: 'arrowDown', text: `${label}${px ? ` $${px}` : ''}${pct ? ` ${pct}` : ''}` })
        }
      })
      markers.sort((a, b) => a.time.localeCompare(b.time))

      // 箭頭恆亮；文字依縮放疏密自動取捨——買點(下)、賣點(上)各自成一垂直區，
      // 由左到右貪婪保留互不重疊的標籤，其餘只留箭頭。放大時標籤自然變多、縮到
      // 「全部」時只留稀疏幾個，避免整片文字糊成一團（原本每筆都硬印才會壅擠）。
      const markerApi = createSeriesMarkers(candleSeries, markers)
      const estWidth = (text) => {   // 概估標籤像素寬（CJK/全形字 12px、其餘 7px）
        let w = 12
        for (const ch of text) {
          const c = ch.charCodeAt(0)
          w += (c >= 0x3000 && c <= 0x9fff) || (c >= 0xff00 && c <= 0xffef) ? 12 : 7
        }
        return w
      }
      declutterMarkers = () => {
        const ts = chart.timeScale()
        const W = containerRef.current?.clientWidth ?? 800
        const edge = { aboveBar: -Infinity, belowBar: -Infinity }   // 各區已佔用的最右緣
        markerApi.setMarkers(markers.map(m => {
          const x = ts.timeToCoordinate(m.time)
          if (x == null || x < 0 || x > W) return { ...m, text: '' }   // 畫面外：只留箭頭
          const half = estWidth(m.text) / 2
          if (x - half > edge[m.position] + 8) { edge[m.position] = x + half; return m }
          return { ...m, text: '' }   // 與前一個標籤重疊：退成純箭頭
        }))
      }
      chart.timeScale().subscribeVisibleLogicalRangeChange(declutterMarkers)
    }

    // ── 滑鼠懸停資訊框：游標指到哪根 K 棒，就顯示那根的完整數據 ─────────
    // 查找表 key 與圖表時間一致：日線 'YYYY-MM-DD' 字串 / 時線 epoch 數字。
    const infoMap = new Map()
    prices.forEach((p, i) => {
      infoMap.set(String(toChartTime(p.date)), { p, prev: i > 0 ? prices[i - 1] : null, ind: null, rawDate: p.date })
    })
    ;(indicators ?? []).forEach(d => {
      const e = infoMap.get(String(toChartTime(d.date)))
      if (e) e.ind = d
    })
    // 日線的 crosshair time 回傳 BusinessDay 物件 {year,month,day}，正規化回字串
    const timeKey = (t) => (t && typeof t === 'object')
      ? `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`
      : String(t)
    // 價位自適應小數位（低價幣 DOGE $0.07 不能捨成 0）
    const fp = (v) => v == null ? '—' : v < 1 ? v.toFixed(4) : v < 100 ? v.toFixed(2) : Math.round(v).toLocaleString()
    const fpct = (v) => v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
    // 已開啟的各條均線在每根 K 棒的值 → 懸停框以「線色」標示，一眼對得上圖上哪條線
    // （週期/EMA·SMA/顏色都與主圖那幾條線同源，取代舊的固定 MA20/MA60——那兩條其實沒畫在圖上）
    const maLookup = mas.filter(m => m.on).map(m => ({
      label: `${maType}${m.p}`, color: m.color,
      map: new Map(movingAvg(P, m.p, maType).map(d => [String(d.time), d.value])),
    }))

    chart.subscribeCrosshairMove(param => {
      const tip = tooltipRef.current
      if (!tip) return
      const entry = param.time != null ? infoMap.get(timeKey(param.time)) : null
      if (!entry || !param.point) { tip.style.display = 'none'; return }
      const { p, prev, ind, rawDate } = entry
      const chg = prev?.close ? (p.close - prev.close) / prev.close * 100 : null   // 對前一根收盤的漲跌
      const amp = p.low > 0 ? (p.high - p.low) / p.low * 100 : null                // 當根振幅
      const up  = p.close >= p.open
      const chgUp = chg == null || chg >= 0
      // 標題：日線=日期；時線=本地時間（軸上顯示的也是本地時間，兩者一致）
      let label = rawDate
      if (rawDate.length > 10) {
        const dt = new Date(rawDate.replace(' ', 'T') + 'Z')
        label = `${dt.getFullYear()}/${dt.getMonth() + 1}/${dt.getDate()} ${String(dt.getHours()).padStart(2, '0')}:00`
      }
      const volRatio = (ind?.VOL_MA20 > 0 && p.volume != null) ? p.volume / ind.VOL_MA20 : null
      const bbPct = (ind?.BB_UPPER != null && ind?.BB_LOWER != null && ind.BB_UPPER > ind.BB_LOWER)
        ? (p.close - ind.BB_LOWER) / (ind.BB_UPPER - ind.BB_LOWER) * 100 : null

      const rows = [
        ['開盤', `$${fp(p.open)}`], ['最高', `$${fp(p.high)}`],
        ['最低', `$${fp(p.low)}`],
        ['收盤', `<b style="color:${up ? '#22c55e' : '#ef4444'}">$${fp(p.close)}</b>`],
        ['漲跌', `<b style="color:${chgUp ? '#22c55e' : '#ef4444'}">${fpct(chg)}</b>`],
        ['振幅', fpct(amp).replace('+', '')],
        ['成交量', p.volume != null ? Math.round(p.volume).toLocaleString() + (volRatio ? `（${volRatio.toFixed(1)}x 均量）` : '') : '—'],
      ]
      // 均線各列帶第三元素＝線色，讓標籤與圖上那條線同色
      maLookup.forEach(ma => {
        const v = ma.map.get(timeKey(param.time))
        if (v != null) rows.push([ma.label, `$${fp(v)}`, ma.color])
      })
      if (ind?.RSI != null)  rows.push(['RSI', ind.RSI.toFixed(1), '#34d399'])   // 綠＝RSI 線色
      if (bbPct != null)     rows.push(['布林位置', `${bbPct.toFixed(0)}%（0=下軌 100=上軌）`])

      // 第三元素 color：有線色的列 → 標籤上色＋小色點（像圖例），對得上圖上那條線
      tip.innerHTML = `<div class="ct-date">${label}</div>` +
        rows.map(([k, v, color]) => {
          const key = color
            ? `<span class="ct-k" style="color:${color}"><i class="ct-dot" style="background:${color}"></i>${k}</span>`
            : `<span class="ct-k">${k}</span>`
          return `<div class="ct-row">${key}<span class="ct-v">${v}</span></div>`
        }).join('')
      tip.style.display = 'block'
      // 位置跟著游標；靠右半邊時翻到左側，避免出界
      const w = containerRef.current?.clientWidth ?? 0
      let x = param.point.x + 18
      if (x + tip.offsetWidth > w - 8) x = param.point.x - tip.offsetWidth - 18
      tip.style.left = `${Math.max(4, x)}px`
      tip.style.top  = `${Math.max(4, Math.min(param.point.y - 16, (containerRef.current?.clientHeight ?? 400) - tip.offsetHeight - 8))}px`
    })

    // 擺盪副面板高度(等版面算完再設)
    const raf = requestAnimationFrame(() => {
      try {
        const panes = chart.panes()
        if (oscOn && panes[1]) panes[1].setHeight(160)
      } catch { /* 舊版無 panes API */ }
      if (declutterMarkers) declutterMarkers()   // 首次排版完成後算一次標籤疏密
    })

    chart.timeScale().scrollToPosition(-5, false)

    // 尺寸同步：圖表跟著「容器實際大小」走——容器由 CSS 拉伸(儀表板欄位/彈窗)時，
    // 高度就等於容器高，達成「左圖高度＝右欄高度」；容器沒定高時退回固定高度。
    const fallbackH = oscOn ? (compact ? 420 : 560) : (compact ? 300 : 420)
    const applySize = () => {
      const el = containerRef.current
      if (!el) return
      chart.applyOptions({ width: el.clientWidth, height: el.clientHeight || fallbackH })
      if (declutterMarkers) declutterMarkers()   // 尺寸變了、座標跟著變，重算標籤疏密
    }
    const ro = new ResizeObserver(applySize)
    if (containerRef.current) ro.observe(containerRef.current)
    window.addEventListener('resize', applySize)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      window.removeEventListener('resize', applySize)
      if (declutterMarkers) chart.timeScale().unsubscribeVisibleLogicalRangeChange(declutterMarkers)
      if (tooltipRef.current) tooltipRef.current.style.display = 'none'   // 重建圖表時清掉殘留的資訊框
      chart.remove()
    }
  }, [prices, indicators, trades, maType, mas, showBB, showVol, showMarkers, osc, interval, compact])

  if (!prices || prices.length === 0) {
    return (
      <div className="chart-skeleton">
        <div className="skeleton" style={{ height: 340, borderRadius: 8 }} />
        <div className="skeleton" style={{ height: 90, borderRadius: 8, marginTop: 8 }} />
      </div>
    )
  }

  return (
    <div className="chart-root" style={{ position: 'relative' }}>
            <div className="chart-toolbar">
        <span className="toolbar-lbl">圖層：</span>
        <button className="matype-btn" onClick={() => setMaType(t => t === 'SMA' ? 'EMA' : 'SMA')} title="切換 簡單(SMA)/指數(EMA) 移動平均">均線:{maType}</button>
        {mas.map((ma, i) => (
          <Toggle
            key={i} on={ma.on} color={ma.color}
            onClick={() => setMas(arr => arr.map((m, j) => j === i ? { ...m, on: !m.on } : m))}
          >
            {maType}{ma.p}
          </Toggle>
        ))}
        <Toggle on={showBB}      onClick={() => setShowBB(v => !v)}      color="#f87171">布林帶</Toggle>
        <Toggle on={showVol}     onClick={() => setShowVol(v => !v)}     color="#94a3b8">成交量</Toggle>
        {interval === '1d' && (
          <Toggle on={showMarkers} onClick={() => setShowMarkers(v => !v)} color="#22c55e">買賣標記</Toggle>
        )}
        <span className="osc-selector">
          <span className="osc-lbl">擺盪：</span>
          {OSC_LIST.map(o => (
            <button key={o} className={`osc-tab ${osc === o ? 'active' : ''}`} onClick={() => setOsc(o)}>
              {o}{OSC_NAME[o] ? `(${OSC_NAME[o]})` : ''}
            </button>
          ))}
        </span>
      </div>
      <div ref={containerRef} className="candlestick-wrap">
        {/* 懸停資訊框（subscribeCrosshairMove 直接寫入內容與座標） */}
        <div ref={tooltipRef} className="chart-tooltip" />
      </div>
      {osc !== '無' && OSC_DETAIL[osc] && (
        <div className="osc-help">
          <div className="osc-help-row">
            <span><span className="osc-help-tag">怎麼看 {osc}</span>{OSC_DETAIL[osc].summary}</span>
            <button className="osc-help-more" onClick={() => setOscDetail(v => !v)}>
              {oscDetail ? '收合 ▲' : '看詳細 ▾'}
            </button>
          </div>
          {oscDetail && (
            <div className="osc-help-detail">
              {OSC_DETAIL[osc].sections.map(([label, text]) => (
                <div key={label} className="osc-help-sec">
                  <span className="osc-help-sec-label">{label}</span>
                  <span className="osc-help-sec-text">{text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
