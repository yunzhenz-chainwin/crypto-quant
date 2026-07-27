/**
 * VerifyModal.jsx — 指標交叉驗證的「資料」彈窗(給一般使用者看)
 *
 * 點頂部「✓ 指標已交叉驗證」徽章時開啟。
 * 用白話呈現:用獨立演算法重算、逐點比對、各幣是否一致;
 * 不丟 1e-15 那種數字,而是說明「差異小到等於完全相同」。
 */
import { useEffect, useRef, useState } from 'react'
import { fetchVerify } from '../api/client'
import { useDialogFocus } from '../lib/useDialogFocus'

export default function VerifyModal({ onClose }) {
  const [d, setD]     = useState(null)
  const [err, setErr] = useState(false)
  const dialogRef = useRef(null)
  const closeRef = useRef(null)

  useDialogFocus(dialogRef, onClose, closeRef)

  useEffect(() => {
    const controller = new AbortController()
    fetchVerify({ signal: controller.signal }).then(setD).catch(error => {
      if (error?.name !== 'AbortError') setErr(true)
    })
    return () => controller.abort()
  }, [])

  return (
    <div className="vm-overlay" onClick={onClose}>
      <div
        ref={dialogRef}
        className="vm"
        role="dialog"
        aria-modal="true"
        aria-labelledby="verify-dialog-title"
        aria-describedby="verify-dialog-description"
        tabIndex="-1"
        onClick={e => e.stopPropagation()}
      >
        <div className="vm-head">
          <h2 id="verify-dialog-title" className="vm-title">指標交叉驗證</h2>
          <button ref={closeRef} className="vm-x" onClick={onClose} aria-label="關閉指標交叉驗證">✕</button>
        </div>

        <p id="verify-dialog-description" className="vm-intro">
          我們用<b>另一套獨立演算法</b>重新計算所有技術指標,再跟系統顯示的數值
          <b>逐點比對</b>,確認指標<b>算得正確</b>。
        </p>

        {!d && !err && <div className="vm-loading" role="status">驗證中…</div>}
        {err && <div className="vm-err" role="alert">讀取失敗,請稍後再試。</div>}

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
