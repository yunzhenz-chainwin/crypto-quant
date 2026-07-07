/**
 * StrategyPanel.jsx — 「詳細資訊」彈窗的內容路由
 *
 *   view='indicators' → 指標詳解：每個指標的讀數/加減/怎麼看（點右欄「指標即時解讀」）
 *   其他（'all' 等）    → 計分明細 ＋ 回測驗證：點「綜合建議」卡就同時顯示這兩個
 *      · 計分明細：進出場規則 + 6 因子計分表 + 停損停利
 *      · 回測驗證：策略報酬/勝率/回撤 + 三基準 + 樣本內外 + 參數掃描 + 資產曲線 + 逐筆
 */
import SignalRulesPanel from './SignalRulesPanel'
import BacktestPanel from './BacktestPanel'
import { IndicatorDetail } from './IndicatorCards'

export default function StrategyPanel({ view = 'all', signal, backtest, btLoading, params, onParamsChange }) {
  // 指標詳解
  if (view === 'indicators') {
    return <div className="strategy-panel"><IndicatorDetail factors={signal?.factors} /></div>
  }

  // 計分明細 ＋ 回測驗證（點「綜合建議」卡 → 這兩個一起顯示）
  return (
    <div className="strategy-panel">
      <SignalRulesPanel part="rules" signal={signal} params={params} onParamsChange={onParamsChange} />
      <BacktestPanel data={backtest} loading={btLoading} params={params} onParamsChange={onParamsChange} hideParams />
    </div>
  )
}
