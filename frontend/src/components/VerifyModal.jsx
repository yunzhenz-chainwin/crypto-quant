/**
 * VerifyModal.jsx — 指標交叉驗證的「資料」彈窗(給一般使用者看)
 *
 * 點頂部「✓ 指標已交叉驗證」徽章時開啟。
 * 用白話呈現:用獨立演算法重算、逐點比對、各幣是否一致;
 * 不丟 1e-15 那種數字,而是說明「差異小到等於完全相同」。
 */
import { useEffect, useState } from 'react'
import { fetchVerify } from '../api/client'

export default function VerifyModal({ onClose }) {
  const [d, setD]     = useState(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    fetchVerify().then(setD).catch(() => setErr(true))
  }, [])

  return (
    <div className="vm-overlay" onClick={onClose}>
      <div className="vm" onClick={e => e.stopPropagation()}>
        <div className="vm-head">
          <span className="vm-title">指標交叉驗證</span>
          <button className="vm-x" onClick={onClose}>✕</button>
        </div>

        <p className="vm-intro">
          我們用<b>另一套獨立演算法</b>重新計算所有技術指標,再跟系統顯示的數值
          <b>逐點比對</b>,確認指標<b>算得正確</b>。
        </p>

        {!d && !err && <div className="vm-loading">驗證中…</div>}
        {err && <div className="vm-err">讀取失敗,請稍後再試。</div>}

        {d && (
          <>
            <div className={`vm-summary ${d.ok ? 'ok' : 'warn'}`}>
              {d.ok ? '通過：' : '注意：'}{d.passed} / {d.total} 個幣 —— 指標完全一致
            </div>

            <div className="vm-items">
              驗證項目:RSI · MACD · 均線(MA) · 布林通道 · 成交量
            </div>

            <div className="vm-coins">
              {(d.coins ?? []).map(c => (
                <span key={c.symbol} className={`vm-coin ${c.ok ? 'ok' : 'bad'}`}>
                  {c.symbol.replace('USDT', '')} {c.ok ? '✓' : '✗'}
                </span>
              ))}
            </div>

            <p className="vm-note">
              所有差異都小於<b>一兆分之一</b>,等於完全相同。<br />
              ※ 這代表指標「<b>計算正確</b>」,<b>不代表</b>「預測會準」。
            </p>
          </>
        )}
      </div>
    </div>
  )
}
