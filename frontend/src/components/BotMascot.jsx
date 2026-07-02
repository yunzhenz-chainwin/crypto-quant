/**
 * BotMascot.jsx — 「小Q」吉祥物（純 SVG + CSS 動畫，零外部依賴）
 *
 * 表情狀態（mood）：
 *   idle      待機：輕輕漂浮、眨眼、天線呼吸燈
 *   thinking  思考：眼睛左右掃描、天線快閃、頭上冒思考泡泡
 *   bull      開心（偏多）：瞇瞇眼 ^_^、大微笑、綠色調、蹦跳
 *   bear      擔心（偏空）：垂天線、八字眉、紅色調
 *   neutral   平靜（中性）：淡定表情、黃色調
 *   talk      說話：嘴巴一開一合、小幅搖擺
 *
 * 用法：<BotMascot mood="bull" size={64} />
 * 動畫全部在 index.css 的 .bm-* 區塊；prefers-reduced-motion 時自動關閉。
 */

// 各表情的主色（臉部發光元素用）
const MOOD_COLOR = {
  idle: '#7dd3fc', thinking: '#7dd3fc', neutral: '#fbbf24',
  bull: '#4ade80', bear: '#f87171', talk: '#7dd3fc',
}

export default function BotMascot({ mood = 'idle', size = 64, className = '' }) {
  const c = MOOD_COLOR[mood] ?? MOOD_COLOR.idle

  return (
    <svg
      className={`bot-mascot mood-${mood} ${className}`}
      width={size} height={size * 1.07}
      viewBox="0 0 140 150"
      role="img" aria-label="AI 小幫手 小Q"
    >
      {/* 地面影子（跟著漂浮縮放） */}
      <ellipse className="bm-shadow" cx="70" cy="141" rx="28" ry="5" fill="#000" opacity="0.28" />

      {/* 思考泡泡（thinking 才顯示） */}
      {mood === 'thinking' && (
        <g className="bm-think" fill={c}>
          <circle className="bm-think-1" cx="104" cy="30" r="4" />
          <circle className="bm-think-2" cx="115" cy="20" r="5.5" />
          <circle className="bm-think-3" cx="128" cy="9"  r="7" />
        </g>
      )}

      <g className="bm-float">
        {/* 天線 */}
        <g className="bm-antenna">
          <line x1="70" y1="16" x2="70" y2="32" stroke="#64748b" strokeWidth="4" strokeLinecap="round" />
          <circle className="bm-antenna-tip" cx="70" cy="13" r="6" fill={c} />
        </g>

        {/* 耳朵 */}
        <rect x="24" y="48" width="10" height="20" rx="5" fill="#475569" />
        <rect x="106" y="48" width="10" height="20" rx="5" fill="#475569" />

        {/* 頭 */}
        <rect x="32" y="30" width="76" height="56" rx="18" fill="#334155" stroke="#475569" strokeWidth="2.5" />
        {/* 臉部螢幕 */}
        <rect x="41" y="39" width="58" height="38" rx="11" fill="#0b1220" />

        {/* 眼睛（依表情換形狀） */}
        {mood === 'bull' ? (
          /* 開心瞇瞇眼 ^ ^ */
          <g className="bm-eyes" stroke={c} strokeWidth="4" strokeLinecap="round" fill="none">
            <path d="M48 60 Q55 51 62 60" />
            <path d="M78 60 Q85 51 92 60" />
          </g>
        ) : mood === 'bear' ? (
          /* 擔心的眼睛 + 八字眉 */
          <g className="bm-eyes">
            <path d="M47 47 L60 52" stroke={c} strokeWidth="3.5" strokeLinecap="round" />
            <path d="M93 47 L80 52" stroke={c} strokeWidth="3.5" strokeLinecap="round" />
            <circle cx="55" cy="60" r="5" fill={c} />
            <circle cx="85" cy="60" r="5" fill={c} />
            <circle cx="56.6" cy="58.4" r="1.6" fill="#fff" opacity="0.9" />
            <circle cx="86.6" cy="58.4" r="1.6" fill="#fff" opacity="0.9" />
          </g>
        ) : (
          /* 一般圓眼（idle/thinking/neutral/talk），thinking 時整組左右掃描 */
          <g className="bm-eyes">
            <circle cx="55" cy="58" r="6" fill={c} />
            <circle cx="85" cy="58" r="6" fill={c} />
            <circle cx="57" cy="56" r="2" fill="#fff" opacity="0.9" />
            <circle cx="87" cy="56" r="2" fill="#fff" opacity="0.9" />
          </g>
        )}

        {/* 嘴巴 */}
        {mood === 'bull' ? (
          <path className="bm-mouth" d="M58 66 Q70 78 82 66" stroke={c} strokeWidth="4"
                strokeLinecap="round" fill="none" />
        ) : mood === 'bear' ? (
          <path className="bm-mouth" d="M59 72 Q70 63 81 72" stroke={c} strokeWidth="4"
                strokeLinecap="round" fill="none" />
        ) : mood === 'thinking' ? (
          <circle className="bm-mouth" cx="70" cy="69" r="3.5" fill={c} />
        ) : mood === 'talk' ? (
          <ellipse className="bm-mouth bm-mouth-talk" cx="70" cy="69" rx="7" ry="5" fill={c} />
        ) : (
          <path className="bm-mouth" d="M62 69 H78" stroke={c} strokeWidth="4"
                strokeLinecap="round" fill="none" />
        )}

        {/* 腮紅（開心/說話時比較明顯） */}
        <circle className="bm-blush" cx="46" cy="68" r="4.5" fill="#fb7185"
                opacity={mood === 'bull' || mood === 'talk' ? 0.55 : 0.18} />
        <circle className="bm-blush" cx="94" cy="68" r="4.5" fill="#fb7185"
                opacity={mood === 'bull' || mood === 'talk' ? 0.55 : 0.18} />

        {/* 身體 */}
        <rect x="44" y="88" width="52" height="36" rx="15" fill="#334155" stroke="#475569" strokeWidth="2.5" />
        {/* 胸口指示燈 */}
        <circle className="bm-core" cx="70" cy="106" r="7.5" fill={c} opacity="0.9" />
        <circle cx="70" cy="106" r="11" fill="none" stroke={c} strokeWidth="1.5" opacity="0.35" />

        {/* 手（右手在 bull/talk 會揮手；FAB hover 也會揮） */}
        <g className="bm-arm-l">
          <rect x="28" y="92" width="13" height="24" rx="6.5" fill="#475569" />
        </g>
        <g className="bm-arm-r">
          <rect x="99" y="92" width="13" height="24" rx="6.5" fill="#475569" />
        </g>

        {/* 腳 */}
        <rect x="50" y="122" width="14" height="12" rx="6" fill="#475569" />
        <rect x="76" y="122" width="14" height="12" rx="6" fill="#475569" />
      </g>
    </svg>
  )
}

// 訊號立場 → 表情（AI 面板 / 漂浮小幫手共用）
export function stanceToMood(stance) {
  if (stance === '偏多') return 'bull'
  if (stance === '偏空') return 'bear'
  return 'neutral'
}
