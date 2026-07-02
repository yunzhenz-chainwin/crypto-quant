# -*- coding: utf-8 -*-
"""
canned_qa.py — 小Q 固定問答層（豐富版固定答案，GPT 只做「優化」不做替代）

回答架構（2026-07-02 依營運需求調整）：
  使用者問題
    ↓ ① 比對固定問答庫（本檔 QA_TEMPLATES 54 條 + 幣種知識 5 類意圖）
    │     命中 → 組出「審核過的豐富固定答案」（模板 + 即時數據填空）
    │     ├─ GPT 可用 → 把固定答案當底稿丟給 GPT 潤飾補充（ai_analyst.enhance_answer，
    │     │             鐵則：不得改數據/立場/新增數字）→ 回優化版（source=canned+gpt）
    │     └─ GPT 不可用 → 直接回固定答案（source=canned）
    ↓ ② 沒命中 → GPT 自由回答（被數據錨定）或規則引擎摘要（現行 ask() 流程）

設計原則：
  - 固定答案是骨幹：內容可審核、零幻覺；GPT 只能加值不能推翻
  - 命中規則：所有條目的觸發關鍵詞取「最長命中」者（RSI是什麼→指標教學，不會誤入幣種小檔案）
  - 模板變數（{幣名}{RSI}{風險清單}…）由即時資料庫填入，與前台圖表同一來源
  - 本檔的 QA_TEMPLATES 同時是《AI機器人固定問答範本.docx》的生成來源（單一真相）
"""
import re

from backend.services.coin_facts import get_facts
from backend.services.reader import load_prices
from backend.services.signal_engine import get_signal

DISCLAIM = "\n\n⚠️ 技術面教學分析，不是投資建議，資金請自行控管。"

# ═════════════════════════════════════════════════════════════════════════════
# 固定問答庫（54 條）。欄位：(分類, 問題示例, 觸發關鍵詞｜分隔, 答案模板)
# 模板可用變數見 _build_vars()；渲染時查無資料的變數顯示「—」。
# ═════════════════════════════════════════════════════════════════════════════
QA_TEMPLATES = [
    # ═══ A. 行情判讀（16 條，答案帶即時數據）═══
    ("行情", "現在適合進場嗎？",
     "進場｜買點｜可以買｜適合買｜上車｜入手｜加倉｜佈局",
     "{幣名}目前{立場}（信心分數 {分數}/100）。\n\n**技術快照**\n{技術快照}\n\n💡 {操作參考}" + DISCLAIM),
    ("行情", "現在該賣嗎？要不要獲利了結／逃頂？",
     "該賣｜要不要賣｜賣掉｜出場｜獲利了結｜逃頂｜落袋",
     "{幣名}目前{立場}（信心分數 {分數}）。\n\n**技術快照**\n{技術快照}\n\n賣出決策建議看三件事：\n・當初進場的理由現在還在嗎？\n・有沒有觸及你設定的停利／停損價位？\n・趨勢面：{趨勢說明}\n\n紀律比預測重要：預先設好出場條件，到了就執行。" + DISCLAIM),
    ("行情", "可以抄底嗎？低點到了嗎？",
     "抄底｜接刀｜低點到了｜見底｜落底",
     "沒有人能確認低點，只能看「止跌訊號」出現了沒。{幣名}目前：\n・RSI {RSI}\n・布林位置：{位置說明}\n・動能：{動能說明}\n\n提醒：下跌趨勢中「便宜」常常更便宜——我們回測過，跌深加碼在幣市是**負優勢**策略。想接也建議分批、小倉位、設好停損。" + DISCLAIM),
    ("行情", "停損停利要怎麼設？",
     "停損｜停利｜止損｜止盈｜出場點",
     "常見做法（擇一並堅持執行）：\n・**固定比例**：進場價 -6%～-10% 停損、+15%～+25% 分批停利（平台回測預設 -6%／+20%）\n・**技術位**：跌破 MA20（{幣名}目前 {MA20}）或前低出場\n・**移動停利**：從高點回落固定 % 出場，讓獲利奔跑\n\n重點不是哪個數字最完美，而是**進場前就設好、到了就執行**。" + DISCLAIM),
    ("行情", "主要風險是什麼？",
     "主要風險｜風險是什麼｜風險｜要注意｜危險｜擔心｜地雷｜注意什麼",
     "以目前數據，{幣名}的主要風險提醒：\n{風險清單}\n\n**技術快照**\n{技術快照}"),
    ("行情", "現在趨勢是多頭還是空頭？",
     "趨勢｜多頭｜空頭｜方向｜走勢｜盤勢怎麼看",
     "{幣名}趨勢判讀：\n・{趨勢說明}\n・{動能說明}\n\n綜合立場：**{立場}**（信心分數 {分數}）。"),
    ("行情", "支撐和壓力在哪裡？",
     "支撐｜壓力｜阻力｜關鍵價位",
     "{幣名}參考技術價位（統計參考、非預測；現價 ${價格}）：\n・布林通道上軌 {布林上軌}／下軌 {布林下軌}\n・均線 MA20 {MA20}／MA60 {MA60}／MA200 {MA200}\n\n價格接近這些位置時常有反應，但沒有保證；跌破支撐後支撐會變成壓力（反之亦然）。"),
    ("行情", "會漲到多少？幫我預測目標價",
     "會漲到｜會跌到｜目標價｜預測價｜漲到哪｜跌到哪",
     "老實說：我**不做價格預測**——任何宣稱能精準預測價格的都不可信。\n\n我能給的是現況數據：{幣名}{立場}、RSI {RSI}、技術參考位（布林 {布林下軌}～{布林上軌}）。\n與其猜目標價，不如設好進出場紀律：賺要賺得到、賠要賠得起。"),
    ("行情", "短線（近幾小時）怎麼看？",
     "短線｜小時線｜日內｜今天走勢｜盤中｜現在走",
     "{短線摘要}\n\n日線大方向：{立場}（信心分數 {分數}）。短線與日線同向時勝率較高；相反時寧可觀望。"),
    ("行情", "為什麼漲／為什麼跌？發生什麼事？",
     "為什麼漲｜為什麼跌｜怎麼了｜發生什麼｜出什麼事",
     "單日漲跌通常沒有單一原因，我給你數據面的線索：\n・{幣名}近期：1 日 {漲跌1日}%、7 日 {漲跌7日}%、30 日 {漲跌30日}%\n・動能：{動能說明}\n・量能：{量能說明}\n・近 3 天相關新聞：看多 {本幣看多} / 看空 {本幣看空} 則（「市場情緒／新聞」面板可看標題）\n\n媒體的「因為 XX 所以漲跌」多半是事後歸因；看數據比找理由可靠。"),
    ("行情", "成交量怎麼看？量能如何？",
     "成交量｜量能｜爆量｜縮量｜有沒有量",
     "{幣名}目前量能：{量能說明}\n\n**量價口訣**\n・價漲量增 = 上漲健康　・價漲量縮 = 上攻無力存疑\n・價跌量增 = 賣壓真實　・價跌量縮 = 賣壓趨緩\n\n蠟燭圖下方的成交量柱（綠漲紅跌）可以直接對照。"),
    ("行情", "最近的新聞對它是好是壞？",
     "新聞｜消息面｜利多｜利空｜輿論",
     "近 3 天與{幣名}相關新聞 {本幣新聞數} 則：看多 {本幣看多}、看空 {本幣看空}。\n今日{幣名}新聞情緒分數：**{單幣情緒分}**（-100 極空 ～ +100 極多）。\n\n新聞情緒由審核過的中英詞庫自動判讀（每 30 分鐘更新），詳細標題在「市場情緒／新聞」面板，每則都附原文連結。"),
    ("行情", "整體市場（大盤）現在如何？",
     "大盤｜整體市場｜市場氣氛｜現在市場｜市場情緒",
     "全市場溫度：\n・恐懼貪婪指數 **{恐懼貪婪值}**（{恐懼貪婪標籤}）\n・今日市場新聞情緒 {市場情緒分}（-100～+100）\n\n歷史經驗：極度恐慌常伴隨劇烈波動，也常是中長期布局的討論區間——但沒有必然，倉位控制永遠優先。"),
    ("行情", "這顆幣最近表現如何？",
     "表現如何｜漲多少｜跌多少｜漲跌幅｜最近如何｜近況",
     "{幣名}近期表現（截至 {日期}，現價 ${價格}）：\n・1 日 {漲跌1日}%\n・7 日 {漲跌7日}%\n・30 日 {漲跌30日}%\n\n技術面{立場}（信心分數 {分數}）。{趨勢說明}"),
    ("行情", "波動大嗎？適合新手嗎？",
     "波動大｜穩不穩｜刺激｜新手適合｜適合新手",
     "{幣名} 30 天漲跌 {漲跌30日}%——加密貨幣整體波動遠大於股市，單日 ±5% 是家常便飯。\n\n新手建議：先用小到「賠光也不心痛」的金額練習，熟悉本站的指標、訊號與回測工具後再談加碼；主流幣（BTC/ETH）的波動已經比小幣溫和許多。" + DISCLAIM),
    ("行情", "它和其他幣會一起漲跌嗎？",
     "相關性｜一起漲跌｜連動｜同漲同跌",
     "幣市高度連動：多數山寨幣與 BTC 的相關係數在 0.6～0.9（詳細頁最下方「幣種相關性分析」有完整矩陣與年化波動度）。\n\n兩個意義：\n・BTC 大跌時，山寨幣很難獨善其身\n・在幣圈內「分散買很多幣」的避險效果有限，真正的分散要跨資產"),

    # ═══ B. 投資觀念／風控（8 條）═══
    ("觀念", "我該投多少錢進去？",
     "投多少｜多少錢買｜多少資金｜比例｜倉位",
     "我不能替你決定金額，但通用原則很明確：\n・只用**閒錢**（3～6 個月生活費之外的錢）\n・單一幣別佔總資產有上限（常見 5%～10%）\n・分批進場，不一次全押\n・進場前先想好「賠到多少會出場」\n\n金額大小不影響練習效果——先小額把紀律練起來。"),
    ("觀念", "可以全部身家買進嗎？我想梭哈",
     "梭哈｜全部買｜身家｜全押｜歐印",
     "**強烈不建議。**加密貨幣單日可跌 10%+、單月可腰斬（{幣名} 30 天 {漲跌30日}% 就在眼前）。\n\n梭哈最大的問題不是虧損本身，是**你會在最恐慌的時刻被迫做決定**（急用錢、扛不住），而那通常是最差的賣點。請保留生活費與應急金，分批、有紀律地參與。"),
    ("觀念", "定期定額買幣可以嗎？",
     "定期定額｜定投｜DCA｜每月買",
     "定期定額（DCA）的優點：免擇時、平滑成本、克服追高殺低的人性。適合看好長期、不想盯盤的人。\n\n兩個注意：\n・DCA 攤平的是「波動」不是「歸零風險」——標的要挑（主流幣 vs 小幣風險天差地遠）\n・仍要設總投入上限，別無限加碼" + DISCLAIM),
    ("觀念", "我被套牢了怎麼辦？",
     "套牢｜被套｜虧損中｜賠錢怎麼辦｜攤平",
     "先冷靜回答三個問題：\n1. 當初進場的理由，現在還成立嗎？\n2. 如果今天空手，你會用現在的價格買它嗎？\n3. 這筆錢多久內不用動？\n\n「不甘心」不是持有理由。務必避免**無計畫地不斷攤平**（越攤越重）。可以設定明確計畫：反彈到 X 減碼、跌破 Y 認錯出場。\n\n{幣名}現況參考：{立場}（信心分數 {分數}）、{趨勢說明}" + DISCLAIM),
    ("觀念", "現在追高會不會接在山頂？",
     "追高｜FOMO｜來不及｜怕買在高點｜山頂",
     "FOMO（怕錯過）是散戶虧損的主因之一。先看數據冷靜一下：\n・{幣名} RSI {RSI}\n・布林位置：{位置說明}\n・7 日已漲跌 {漲跌7日}%\n\n若指標已過熱，寧可等回檔或分批小額試單。記住：**錯過不會虧錢，追錯會**——行情永遠有下一班車。"),
    ("觀念", "長期持有好還是做短線好？",
     "長期持有｜短線好嗎｜波段｜存幣｜長抱",
     "這是兩種不同的遊戲：\n・**長期持有**：賭產業趨勢，優點是省心，代價是要能忍受 -50% 級別的回檔不砍在低點\n・**短線／波段**：賭技術優勢，需要紀律與時間，多數人最後輸給手續費與情緒\n\n平台工具對應：長期看「全部」週期＋MA200；波段看日線訊號＋回測驗證。誠實說：多數人適合「核心長期＋小倉位練波段」的混合。" + DISCLAIM),
    ("觀念", "可以開槓桿／玩合約嗎？",
     "槓桿｜合約｜期貨｜開多單｜開空單｜幾倍",
     "本平台只做**現貨**技術分析，不提供合約建議。\n\n你需要知道的事實：槓桿會等倍放大虧損，而且有**強制平倉**機制——保證金不足時倉位直接歸零，連「凹單等反彈」的機會都沒有（新聞常見的「X 億爆倉」就是這個）。新手用槓桿，大概率是把學費一次繳完。"),
    ("觀念", "怎麼分散風險？",
     "分散風險｜資產配置｜避險｜雞蛋",
     "幣圈內的分散效果有限——幣種間高度連動（見相關性面板），BTC 跌大家一起跌。\n\n比較實際的層次：\n1. **跨資產**：加密貨幣只佔總資產一部分，其餘為股、債、現金\n2. **幣圈內**：主流幣為主、小幣小額，留一部分穩定幣等機會\n3. **時間分散**：分批進出，避免單點決策" + DISCLAIM),

    # ═══ C. 指標教學（10 條，靜態）═══
    ("教學", "什麼是 RSI？",
     "什麼是RSI｜RSI是什麼｜RSI怎麼看｜相對強弱",
     "**RSI（相對強弱指標，0~100）**衡量近期漲跌力道。\n・>70 超買（漲多了，隨時可能回檔）\n・<30 超賣（跌多了，可能技術性反彈）\n・50 是多空分界\n\n{幣名}目前 RSI **{RSI}**。\n\n注意：強趨勢中 RSI 會「鈍化」（一直掛在高檔或低檔），不宜單獨使用；K 線圖下方的擺盪指標槽可切換查看，旁邊有「怎麼看」詳細教學。"),
    ("教學", "什麼是 MACD？",
     "什麼是MACD｜MACD是什麼｜MACD怎麼看｜指數平滑",
     "**MACD** 用快慢兩條指數均線的差值看動能與轉折：\n・MACD 線由下往上穿過訊號線＝**黃金交叉**（偏多）\n・由上往下穿＝**死亡交叉**（偏空）\n・柱狀圖放大縮小＝動能增強減弱\n\n{幣名}目前：{動能說明}\n\n注意：MACD 是落後指標，盤整時假交叉多、趨勢明確時最好用。"),
    ("教學", "什麼是 KDJ？",
     "什麼是KDJ｜KDJ是什麼｜隨機指標",
     "**KDJ（隨機指標，0~100）**看收盤價在近期高低區間的相對位置，對短線轉折反應快：\n・>80 超買、<20 超賣\n・K 線由下往上穿 D 線（低檔）→ 偏多；高檔下穿 → 偏空\n・J 線最敏感，衝破 100 或跌破 0 常是短線極端\n\n訊號快但雜訊也多，適合短線與震盪盤，搭配趨勢指標較穩。K 線圖擺盪槽可切換 KDJ。"),
    ("教學", "什麼是 DMI／ADX？",
     "什麼是DMI｜DMI是什麼｜ADX是什麼｜趨向指標",
     "**DMI（趨向指標）**同時判斷「方向」與「強度」：\n・+DI（綠）在 -DI（紅）上方＝多方主導，反之空方\n・**ADX（黃）**是趨勢強度：>25 趨勢明確、<20 盤整\n\n關鍵觀念：ADX 只管趨勢「強不強」、不分多空——大跌時 ADX 也會很高。盤整時（ADX<20）方向訊號不可靠。"),
    ("教學", "什麼是乖離率 BIAS？",
     "乖離率｜BIAS｜偏離均線",
     "**乖離率（BIAS）**＝價格偏離均線的百分比，用來抓「漲跌過頭後的回歸」：\n・正乖離過大 → 短線漲太快，容易拉回均線\n・負乖離過大 → 跌深，容易反彈回均線\n\n「過大」沒有絕對標準，要對照該幣自己的歷史區間；強趨勢中乖離可以持續很大，不代表馬上反轉。"),
    ("教學", "什麼是布林通道？",
     "布林通道｜布林帶｜BB是什麼",
     "**布林通道**＝20 日均線 ±2 個標準差的帶狀區間，統計上價格約 95% 的時間在帶內：\n・碰上軌＝偏熱（短線偏貴）\n・碰下軌＝偏冷（短線偏便宜）\n・**通道收窄（擠壓）**常預告大行情將至——但不預告方向\n\n{幣名}目前：{位置說明}（上軌 {布林上軌}／下軌 {布林下軌}）"),
    ("教學", "均線是什麼？EMA 和 SMA 差在哪？",
     "均線是什麼｜MA是什麼｜EMA｜SMA｜移動平均",
     "**均線（MA）**＝最近 N 根 K 棒收盤價的平均，可以看成「這段期間進場者的平均成本」：\n・**SMA** 簡單平均：每天等權，較平滑\n・**EMA** 指數平均：近期加權，反應較快\n\n常用週期：MA20（月線、短期）、MA60（季線、中期）、MA200（年線、牛熊分界）。{幣名}目前 MA20 {MA20}／MA60 {MA60}／MA200 {MA200}。蠟燭圖工具列可切 SMA/EMA 並開關各條均線。"),
    ("教學", "黃金交叉和死亡交叉是什麼？",
     "黃金交叉｜死亡交叉｜金叉｜死叉",
     "指「快線穿過慢線」的瞬間：\n・**黃金交叉**：短均線由下往上穿過長均線 → 短期動能轉強（偏多訊號）\n・**死亡交叉**：由上往下穿 → 偏空訊號\n\nMACD 的快慢線交叉是同一概念。注意：交叉是**落後**訊號（確認時行情已走一段），盤整時會頻繁假交叉，建議搭配量能與趨勢強度（ADX）過濾。"),
    ("教學", "K 線（蠟燭圖）怎麼看？",
     "K線怎麼看｜蠟燭圖｜紅K｜綠K｜看不懂圖｜影線｜上影線｜下影線｜十字線",
     "一根 K 棒記錄一段時間的四個價位：開盤、收盤、最高、最低。\n・本站**綠漲紅跌**（美式配色）\n・實體（粗的部分）＝開盤到收盤的區間\n・上下影線＝盤中衝到的最高最低\n・**長上影線**＝衝高被賣壓打回（高檔出現要警戒）；**長下影線**＝殺低有人承接（低檔出現偏支撐）\n・**十字線**（幾乎沒實體）＝多空僵持，趨勢末端出現常是轉折前兆\n\n詳細頁可切換：日線（一根＝一天，看波段）／時線（一根＝一小時，看短線；目前 {時線清單} 提供）。"),
    ("教學", "日線和時線差在哪？該看哪個？",
     "日線時線｜週期差別｜看哪個週期｜時線是什麼",
     "差別在一根 K 棒代表的時間長度：\n・**日線**：一根＝一天。雜訊少、適合看波段與大方向\n・**時線**：一根＝一小時。反應快、適合抓短線進出時機，但雜訊多\n\n建議用法：**先用日線定方向，再用時線找時機**（日線偏多時，時線回檔不破支撐＝較好的進場點）。目前時線提供 {時線清單}，蠟燭圖右上角切換。"),
    ("教學", "什麼是背離？（頂背離／底背離）",
     "背離｜頂背離｜底背離｜divergence",
     "**背離**＝價格與指標「走不同方向」，是動能衰竭的專業級警訊：\n・**頂背離**：價格創新高，但 RSI／MACD 沒創新高 → 上漲動能轉弱，警戒回檔\n・**底背離**：價格創新低，但指標沒創新低 → 下跌動能衰竭，留意反彈\n\n在本站怎麼看：K 線圖下方切到 RSI 或 MACD，對照主圖的高低點即可目視判讀。\n\n注意：背離可以持續很久才兌現（背離之後還有背離），適合當**警訊**而不是進出場的單獨依據，務必搭配趨勢與量能。"),
    ("教學", "什麼是 ATR？",
     "ATR｜真實波幅｜平均真實區間",
     "**ATR（平均真實區間）**＝最近 N 天「每日實際波動幅度」的平均，是專業交易者衡量波動、設停損的工具：\n・ATR 大＝行情波動劇烈；ATR 小＝盤整安靜\n・經典用法：**停損距離 = 進場價 ± 1.5~2 倍 ATR**（讓停損跟著波動調整，避免被正常震盪掃出場）\n\n本站圖表目前未內建 ATR；可用**布林通道寬度**近似觀察波動大小（通道越寬波動越大）。若需要 ATR 可回報管理者評估新增。"),
    ("教學", "什麼是 OBV（能量潮）？",
     "OBV｜能量潮",
     "**OBV（能量潮）**＝把每天的成交量按漲跌累加起來的「資金流向計數器」：收漲日加上當日量、收跌日減去當日量。\n・價漲 + OBV 同步創高 → 上漲有量支撐（健康）\n・價漲 + OBV 走平或下降 → **量價背離**，上漲缺乏資金認同（警戒）\n\n本站圖表目前未內建 OBV；可用成交量柱＋20 日均量（VOL_MA20）觀察類似的量價關係。"),
    ("教學", "費波納契回撤是什麼？",
     "費波納契回撤｜斐波那契回撤｜費波納契｜斐波那契｜黃金分割｜fibonacci｜回撤位",
     "**費波納契回撤**＝用黃金比例（38.2%、50%、61.8%）預估「回檔可能停在哪」的畫線工具：\n・一段上漲後回檔，常在漲幅的 38.2%／50%／61.8% 位置遇到支撐\n・跌破 61.8% 通常視為原趨勢轉弱\n\n誠實說：它有「自我實現預言」成分——因為夠多人看，這些位置才有反應。本站圖表目前未提供畫線工具；可自行用波段高低點心算，或搭配本站的均線／布林參考位。"),
    ("教學", "一目均衡表是什麼？",
     "一目均衡表｜ichimoku｜雲帶｜雲圖",
     "**一目均衡表（Ichimoku）**＝日本開發的全能型指標，一張圖同時看趨勢、支撐壓力與動能，特色是「雲帶」：\n・價格在雲上＝多頭、雲下＝空頭、雲中＝盤整\n・雲帶厚度＝支撐壓力的強度\n・轉換線／基準線交叉＝類似均線金死叉\n\n本站圖表目前未內建一目均衡表（元素較多、新手易眼花）；用 MA20/60/200 均線組合可以達到類似的趨勢判讀效果。"),
    ("教學", "VWAP 是什麼？",
     "VWAP｜成交量加權平均價",
     "**VWAP（成交量加權平均價）**＝把成交量納入權重的平均成本線，機構交易員的基準價：\n・價格在 VWAP 之上＝當日買方強勢；之下＝賣方強勢\n・機構常用「優於 VWAP 的價格成交」來評估交易品質\n\n它主要用於**日內交易**；本站以日線波段為主，圖表未內建 VWAP。時線（{時線清單}）搭配均線可做類似的短線成本判讀。"),
    ("教學", "頭肩頂、雙底這些型態怎麼看？",
     "頭肩頂｜頭肩底｜雙頂｜雙底｜M頭｜W底｜三角收斂｜旗形｜型態學",
     "**K 線型態學**＝從價格軌跡的形狀推測多空易手，常見的有：\n・**頭肩頂／M 頭（雙頂）**：高檔反轉訊號，跌破頸線確認\n・**頭肩底／W 底（雙底）**：低檔反轉訊號，突破頸線確認\n・**三角收斂／旗形**：整理型態，突破方向決定行情\n\n兩個專業提醒：\n1. 型態主觀性強，「事後看都很準、當下看都模糊」——確認訊號（頸線突破＋放量）比預測型態重要\n2. 務必搭配量能：突破無量常是假突破\n\n本站蠟燭圖可自由縮放觀察型態，搭配成交量柱驗證。"),
    ("教學", "資金費率、未平倉量是什麼？（鏈上與合約數據）",
     "資金費率｜未平倉量｜持倉量｜MVRV｜鏈上數據｜鏈上指標｜合約數據",
     "這些是**合約市場與鏈上**的專業情緒指標：\n・**資金費率**：合約多空雙方互付的利息。費率高＝多頭擁擠（追高風險）、負費率＝空頭擁擠（軋空潛力）\n・**未平倉量（OI）**：市場上未結算的合約總量。價漲 OI 增＝趨勢有新資金；價漲 OI 減＝空頭回補居多，續航存疑\n・**MVRV**：幣價相對鏈上平均成本的倍數，估「整體市場賺賠狀態」\n\n本站目前未接入這些數據（已列在功能路線圖）；新聞面板常出現「爆倉」「ETF 流入流出」等相關訊息可輔助判讀。"),

    # ═══ D. 名詞教學（8 條）═══
    ("教學", "信心分數是怎麼算的？",
     "信心分數｜分數怎麼算｜幾分代表什麼",
     "**信心分數（0~100，50 中立）**由 6 個技術因子加權合成：RSI、MACD、均線排列、長期趨勢 MA200、成交量、布林位置。≥65 判定偏多、≤35 判定偏空。\n\n{幣名}目前 **{分數} 分（{立場}）**。\n\n誠實提醒：此分數定位是「教學指標」——回測顯示它目前沒有擇時優勢（成績單公開在後台）；正式訊號以動量策略為準。"),
    ("教學", "恐懼貪婪指數是什麼？",
     "恐懼貪婪是什麼｜恐慌指數｜貪婪指數",
     "**恐懼貪婪指數（0~100）**綜合波動、動能、社群聲量等衡量整體市場情緒：\n・0～25 極度恐慌、75～100 極度貪婪\n・目前：**{恐懼貪婪值}（{恐懼貪婪標籤}）**\n\n用法：極端值常被當**反向參考**（「別人恐懼我貪婪」）——歷史上極度恐慌區常是中長期布局討論區，但它不是精準擇時工具，別單獨使用。"),
    ("教學", "回測是什麼？可信嗎？",
     "回測是什麼｜歷史測試｜backtest",
     "**回測**＝把一套買賣規則放到歷史資料上模擬「過去照做會怎樣」，是策略的及格門檻。\n\n詳細頁的回測面板：用本站 6 因子訊號進出場，含手續費 0.1%＋滑價假設，可調停損停利參數對照。\n\n可信度要點：\n・回測好 ≠ 未來好（市場會變）\n・參數調到完美＝「背答案」（過擬合）\n・本站對策：保留樣本外驗證、成績單公開"),
    ("教學", "夏普比率是什麼？",
     "夏普比率｜sharpe｜划算度",
     "**夏普比率**＝報酬相對風險的「划算度」：每承擔一分波動，換到多少超額報酬。\n・<0 賠錢　・0~1 普通　・>1 不錯　・>2 很好\n\n用途：兩個策略報酬率一樣時，選夏普高的——過程波動小、比較抱得住。回測面板有顯示。"),
    ("教學", "最大回撤是什麼？",
     "最大回撤｜回撤是什麼｜最慘賠多少",
     "**最大回撤（MDD）**＝資產從高點到後續低點的最大跌幅，代表「過程中最痛的一段帳面縮水」。\n\n它是心理承受度的量尺：回測報酬 +100% 但 MDD -50%，意味著你得先忍受資產腰斬而不砍單，才吃得到後面的獲利。選策略時 MDD 比報酬率更值得先看。"),
    ("教學", "勝率和獲利因子是什麼？",
     "勝率是什麼｜獲利因子｜贏面",
     "・**勝率**＝賺錢的交易佔比\n・**獲利因子**＝總獲利 ÷ 總虧損，**>1 才是整體賺錢**\n\n關鍵觀念：勝率高 ≠ 賺錢——勝率 80% 但一次大賠可能全吐回去；反之勝率 40% 配上「大賺小賠」也能獲利。兩個數字要一起看（回測面板都有）。"),
    ("教學", "做多和做空是什麼意思？",
     "做多是什麼｜做空是什麼｜多單空單",
     "・**做多**＝先買後賣，賭上漲（現貨買入就是做多）\n・**做空**＝先借來賣、跌了買回還，賭下跌（需要合約或借貸）\n\n本站說的「偏多／偏空」是**技術面立場判讀**：偏空對現貨投資人的意義是「謹慎、減碼、等待」，不是叫你去開空單。"),
    ("教學", "比特幣減半是什麼？ETF 又是什麼？",
     "減半是什麼｜halving｜ETF是什麼｜現貨ETF",
     "・**減半**：比特幣每約 4 年把礦工的新幣獎勵砍半（最近一次 2024 年），供給增速下降。歷史上減半後常有牛市——但樣本只有 4 次，參考別迷信。\n・**現貨 ETF**：讓一般股票帳戶能買進「追蹤幣價的基金」，是傳統資金進場的大門。新聞常報的 inflow／outflow（申購／贖回金流）反映機構資金動向，對市場情緒影響大。"),

    # ═══ E. 平台功能（6 條）═══
    ("平台", "平台支援哪些幣？",
     "哪些幣｜支援什麼幣｜幣種清單｜有哪些幣",
     "目前追蹤 {幣數} 檔主流幣：{支援清單}。\n\n時線（1 小時 K）目前提供 **{時線清單}**。跟我聊天直接講幣名就能切換（例：「以太幣如何？」）；想追蹤新幣可請管理者到後台新增。"),
    ("平台", "圖上的買賣箭頭標記是什麼？",
     "買賣標記｜綠色箭頭｜紅色箭頭｜圖上箭頭｜買入標記｜賣出標記｜箭頭是什麼",
     "那是**回測策略的模擬進出場點**（教學用途）：\n・綠色向上箭頭＝策略模擬「買入」的位置與價格\n・向下箭頭＝出場位置（藍＝獲利了結、紅＝停損）\n\n它們來自「策略回測」面板的規則（6 因子訊號＋停損停利），調整回測參數時箭頭會同步改變——可以用來檢視「如果照訊號操作會在哪買哪賣」。\n\n注意：這是**歷史模擬**，不是即時買賣建議；工具列的「買賣標記」按鈕可開關（僅日線顯示）。"),
    ("平台", "圖表怎麼操作？（開關指標、縮放）",
     "圖表操作｜圖表怎麼｜怎麼操作｜開關圖層｜怎麼縮放｜圖層｜指標怎麼開｜怎麼切指標｜圖表功能",
     "蠟燭圖上方是**圖層工具列**，全部點擊即可開關：\n・「均線:EMA/SMA」切換均線算法；EMA5/10/20/60/120 逐條開關\n・布林帶、成交量、買賣標記\n・「擺盪」列：RSI／MACD／KDJ／DMI／BIAS 切換下方副圖\n\n操作：滑鼠滾輪縮放、按住拖曳平移；右上角切「日線/時線」與時間區間（1M~全部）。\n\n小撇步：選了擺盪指標後，圖表下方會出現該指標的「📖 怎麼看」說明，點「看詳細」有完整教學；看不懂的名詞也可以直接問我。"),
    ("平台", "時線圖要怎麼看？在哪裡切換？",
     "怎麼切時線｜小時圖在哪｜時線在哪",
     "進入 **BTC 或 ETH 的詳細頁**，蠟燭圖右上角有「日線／時線」切換：\n・時線提供 24H／3D／7D／1M／3M 區間\n・所有指標（均線、布林、RSI、MACD、KDJ…）都能在時線上用\n・資料每小時第 6 分鐘自動更新\n\n其他幣目前僅日線。"),
    ("平台", "正式策略訊號是什麼？",
     "正式策略｜動量策略｜策略訊號",
     "那是平台經回測與樣本外驗證的「**防禦型跨幣動量策略**」：\n・BTC 站上 100 日均線（大盤天氣好）才進場\n・持有近 30 天最強勢的 5 檔幣、等權重\n・控制整體波動、定期換倉；天氣不好就抱現金\n\n它與教學用的「信心分數」是兩套東西：策略有驗證過的優勢；分數目前是教學性質（回測無擇時優勢，成績單公開）。"),
    ("平台", "你的分析是怎麼來的？",
     "怎麼分析的｜分析依據｜數據哪來",
     "我是**多引擎**架構：\n1. **固定問答庫**：審核過的模板＋即時數據（現在這則就是）\n2. **規則引擎**：Binance 官方行情算出的 6 因子技術分析\n3. **GPT**：把同一套數據交給 AI 綜合研判（與規則引擎立場不一致會標「觀點分歧」）\n\n行情來自 Binance API、新聞來自 10 家真實媒體 RSS（附原文連結）、指標計算有獨立交叉驗證（首頁徽章可查）。"),
    ("平台", "新聞是從哪裡來的？是真的嗎？",
     "新聞來源｜新聞哪來｜新聞是真的嗎",
     "全部來自真實媒體的官方 RSS：CoinTelegraph、CoinDesk、Decrypt、The Block、CryptoSlate、Blockworks、Bitcoin Magazine、動區、鏈新聞＋Google News 中文聚合。\n\n系統**只搬運、不改寫、不創作**，每則都保留原始網址，點開即可對質原文；情緒標籤（看多/看空）是我們用審核過的詞庫做的自動判讀，屬於分析、不是新聞內容。"),
    ("平台", "可以查以前（歷史）的數據嗎？",
     "歷史數據｜查以前｜過去的數據｜歷史查詢｜以前的指標｜之前的價格｜歷史價格",
     "可以！直接把「日期＋想看的東西」講給我聽就行：\n・**單日快照**：「{幣名} 6月15日的 RSI」「2026-06-01 收盤多少」「昨天的價格」「三天前的數據」\n・**月度回顧**：「{幣名} 上個月漲多少」「6 月表現如何」\n\n我會直接查資料庫的真實歷史（日線約從 2021 年 7 月起），回覆當日開高低收、RSI/MACD、均線與信心分數。\n\n也可以在蠟燭圖用「📅 自訂」選日期區間自己看圖。"),
    ("平台", "資料多久更新一次？",
     "多久更新｜資料更新頻率｜即時嗎",
     "・日線 K 棒：每天 09:00（台北時間）\n・時線（{時線清單}）：每小時第 6 分鐘\n・新聞與情緒：每 30 分鐘\n・恐懼貪婪指數：每天\n\n頁面每分鐘自動檢查新資料、有變化才更新畫面——**不用手動重整**。"),

    # ═══ F. 信任與誠實（3 條）═══
    ("信任", "你的建議可以信嗎？這是投資建議嗎？",
     "可以信嗎｜可靠嗎｜準嗎｜是投資建議嗎｜信得過",
     "老實說：我提供的是「根據即時數據的技術面**教學分析**」，不是投資建議。\n\n更誠實的部分：本站 6 因子分數經回測**目前沒有預測優勢**（成績單公開在後台，沒有藏）；已驗證較有效的是動量策略。我的價值在於幫你把數據看清楚、把風險講明白——決策與風險屬於你自己。"),
    ("信任", "你會不會騙我？資料是真的嗎？",
     "騙我｜假的吧｜資料真的嗎｜造假",
     "我的每個數字都可以被驗證：\n・行情：Binance 官方 API（跟交易所 App 對得上）\n・新聞：附原始連結，點開對質\n・指標：有獨立演算法交叉驗證（首頁「驗證徽章」可點開看逐項結果）\n\n我**不會編造**——資料不足時我會直說「資料不足」；我答不了的問題會交給更合適的引擎，不硬答。"),
    ("信任", "為什麼你的數字跟其他網站不一樣？",
     "數字不一樣｜跟別的網站不同｜價格不對",
     "常見三個原因：\n1. **交易所不同**：本站用 Binance 的 USDT 交易對，各所價格本就有小差異\n2. **時間基準不同**：日線收盤是 UTC 0 點（台北早上 8 點），「今日漲跌」的起算點可能不同\n3. **計價單位**：USDT ≈ 美元但不完全相等\n\n差異通常在 1% 內；若明顯異常，請回報管理者檢查。"),

    # ═══ G. 閒聊導回（3 條）═══
    ("閒聊", "你好／嗨",
     "你好｜哈囉｜嗨｜早安｜午安｜晚安｜hello｜hi",
     "嗨！我是小Q 👋\n\n目前{幣名}{立場}（信心分數 {分數}）。想知道什麼？\n・問行情：「現在適合進場嗎」「主要風險」\n・問知識：「LTC 是什麼」「比特幣的起源」\n・換幣聊：直接講幣名就好，例如「以太幣如何？」"),
    ("閒聊", "謝謝／再見",
     "謝謝｜感謝｜辛苦了｜掰掰｜再見｜bye",
     "不客氣！送你一句：**紀律 > 預測，倉位 > 眼光**。\n有需要隨時點我，我都在右下角 🤖"),
    ("閒聊", "講個笑話／陪我聊天",
     "笑話｜好無聊｜陪我聊｜唱歌",
     "我是量化機器人，笑話庫只有一條：\n「為什麼投資人過馬路都特別小心？——因為他們知道什麼叫**單邊行情**。」😅\n\n好了回來看盤吧！要我幫你分析哪顆幣？"),
]

# 幣種知識類意圖（另用 coin_facts 知識庫組答案；關鍵詞同樣參與「最長命中」競賽）
KNOWLEDGE_INTENTS = [
    ("origin", ["起源", "由來", "誰創", "誰發明", "誰做的", "誰開發", "創辦", "創始",
                "歷史", "背景故事", "哪一年出", "哪年出", "什麼時候出", "何時推出", "來頭", "故事"]),
    ("supply_coin", ["供應量", "供給量", "總量", "發行量", "上限多少", "會不會增發", "增發",
                     "通膨嗎", "通縮嗎", "銷毀", "多少枚", "幾枚"]),
    ("holders", ["多少人買", "購買人數", "持有人數", "多少人持有", "多少人用", "使用人數",
                 "熱門嗎", "很多人買", "有人買嗎", "採用度", "普及嗎"]),
    ("purpose", ["用途", "能幹嘛", "能幹麻", "幹嘛用", "做什麼用", "拿來做什麼", "有什麼用",
                 "應用場景", "特色是什麼", "解決什麼"]),
    ("what_is", ["是什麼", "是甚麼", "什麼幣", "甚麼幣", "介紹一下", "介紹", "認識一下",
                 "科普", "小檔案", "基本資料", "基本資訊", "what is", "什麼來頭"]),
]


# ── 比對：所有條目取「最長命中關鍵詞」者（避免「RSI是什麼」誤入幣種小檔案）──
def _match(question: str):
    """回傳 ('qa', index) 或 ('knowledge', intent) 或 None。"""
    q = (question or "").replace(" ", "")
    ql = q.lower()
    best = None                    # (關鍵詞長度, 型別, key)
    for idx, (_, _, kws, _) in enumerate(QA_TEMPLATES):
        for k in kws.split("｜"):
            if k and (k in q or k.lower() in ql):
                if best is None or len(k) > best[0]:
                    best = (len(k), "qa", idx)
    for intent, kws in KNOWLEDGE_INTENTS:
        for k in kws:
            if k and (k in q or k.lower() in ql):
                # 「是什麼/是甚麼」太泛用（主要風險是什麼、趨勢是什麼…都含它），
                # 競爭時降權成 1：只有在沒有任何具體條目命中時才走幣種小檔案。
                w = 1 if k in ("是什麼", "是甚麼") else len(k)
                if best is None or w > best[0]:
                    best = (w, "knowledge", intent)
    return (best[1], best[2]) if best else None


# ── 模板變數（即時數據填空；與前台圖表同一資料來源）──────────────────────────
def _build_vars(symbol: str) -> dict:
    from backend.services.ai_analyst import build_context, local_analysis, _coin_zh
    from backend.services.news_store import load_sentiment_daily
    from backend.services.app_db import get_coins

    ctx = build_context(symbol)
    loc = local_analysis(ctx)
    tk = symbol.replace("USDT", "")

    def point(tag, fb="資料不足"):
        return next((p["text"] for p in loc["points"] if p["tag"] == tag), fb)

    def fmt(v):
        return f"{v:,.0f}" if isinstance(v, (int, float)) and v else "—"

    def pct(v):
        return f"{v:+.2f}" if isinstance(v, (int, float)) else "—"

    n3 = ctx["sentiment"].get("news_3d") or {}
    fg = ctx["sentiment"].get("fear_greed") or {}
    try:
        coin_s = load_sentiment_daily(tk, 1)
        mkt_s = load_sentiment_daily("MARKET", 1)
    except Exception:
        coin_s = mkt_s = []
    coins = [c for c in get_coins() if c.get("enabled", True)]
    # 時線幣種清單：即時讀 DB（後台加開時線幣後，所有相關答案自動跟著變）
    try:
        from backend.services.reader import available_symbols
        zh_of = {c["symbol"]: f'{c.get("zh", "")} {(c.get("ticker") or c["symbol"].replace("USDT", ""))}'
                 for c in coins}
        hourly_list = "、".join(zh_of.get(s, s.replace("USDT", ""))
                                for s in available_symbols("1h")) or "（尚未開放）"
    except Exception:
        hourly_list = "BTC、ETH"
    rsi = ctx["daily"].get("rsi")
    snapshot = "\n".join(
        f"・{p['emoji']} {p['tag']}：{p['text']}"
        for p in loc["points"] if p["tag"] in ("趨勢", "動能", "量能", "位置"))

    return {
        "{幣名}": ctx.get("name_zh") or tk, "{代號}": tk,
        "{價格}": f'{ctx["price"]:,.2f}' if ctx.get("price") else "—",
        "{日期}": ctx.get("as_of") or "—",
        "{立場}": loc["stance"], "{分數}": str(loc["score"]),
        "{漲跌1日}": pct(ctx["change_pct"].get("1d")),
        "{漲跌7日}": pct(ctx["change_pct"].get("7d")),
        "{漲跌30日}": pct(ctx["change_pct"].get("30d")),
        "{RSI}": f"{rsi:.0f}" if rsi is not None else "—",
        "{MA20}": fmt(ctx["daily"].get("ma20")), "{MA60}": fmt(ctx["daily"].get("ma60")),
        "{MA200}": fmt(ctx["daily"].get("ma200")),
        "{布林上軌}": fmt(ctx["daily"].get("bb_upper")),
        "{布林下軌}": fmt(ctx["daily"].get("bb_lower")),
        "{趨勢說明}": point("趨勢"), "{動能說明}": point("動能"),
        "{量能說明}": point("量能"), "{位置說明}": point("位置"),
        "{技術快照}": snapshot or "資料不足",
        "{風險清單}": "\n".join("・⚠️ " + r for r in loc["risks"]) or "・資料不足",
        "{操作參考}": loc["suggestion"],
        "{短線摘要}": next((f"短線 1h 視角：{p['text']}" for p in loc["points"]
                            if p["tag"] == "短線 1h"),
                           f"此幣目前無時線資料（1 小時 K 目前提供 {hourly_list}）"),
        "{本幣新聞數}": str(n3.get("this_coin_total", 0)),
        "{本幣看多}": str(n3.get("this_coin_bullish", 0)),
        "{本幣看空}": str(n3.get("this_coin_bearish", 0)),
        "{單幣情緒分}": str(coin_s[-1]["score"]) if coin_s else "—",
        "{市場情緒分}": str(mkt_s[-1]["score"]) if mkt_s else "—",
        "{恐懼貪婪值}": str(fg.get("value", "—")),
        "{恐懼貪婪標籤}": fg.get("label", "—"),
        "{幣數}": str(len(coins)),
        "{支援清單}": "、".join(
            f'{c.get("zh", "")} {(c.get("ticker") or c["symbol"].replace("USDT", ""))}'
            for c in coins),
        "{時線清單}": hourly_list,
        "_ctx": ctx, "_loc": loc,     # 給 GPT 優化層當佐證數據
    }


def _render(template: str, vars_: dict) -> str:
    out = template
    for k, v in vars_.items():
        if k.startswith("{"):
            out = out.replace(k, str(v))
    return out


# ── 幣種知識類答案（coin_facts 知識庫）──────────────────────────────────────
def _live_bits(symbol: str) -> dict:
    out = {"price": None, "vol": None, "vol_usdt": None, "stance": None, "score": None}
    try:
        rows = load_prices(symbol, days=2)
        if rows:
            out["price"] = rows[-1]["close"]
            out["vol"] = rows[-1]["volume"]
            if out["vol"] and out["price"]:
                out["vol_usdt"] = out["vol"] * out["price"]
    except Exception:
        pass
    try:
        sig = get_signal(symbol)
        out["stance"] = {"BULL": "偏多", "BEAR": "偏空", "NEUTRAL": "中性"}.get(sig.get("signal"))
        out["score"] = sig.get("score")
    except Exception:
        pass
    return out


def _fmt_usd(v) -> str:
    if not v:
        return "—"
    if v >= 1e8:
        return f"{v / 1e8:,.1f} 億美元"
    if v >= 1e4:
        return f"{v / 1e4:,.0f} 萬美元"
    return f"{v:,.0f} 美元"


def _knowledge_answer(symbol: str, intent: str) -> str | None:
    facts = get_facts(symbol)
    if not facts:
        return None                  # 新幣還沒寫知識檔 → 讓 GPT / 規則引擎接手
    from backend.services.app_db import get_coins
    name = next((c.get("zh") or symbol for c in get_coins() if c["symbol"] == symbol), symbol)
    tk = symbol.replace("USDT", "")
    live = _live_bits(symbol)
    price_line = (f"目前價格 ${live['price']:,.2f}"
                  + (f"，技術面{live['stance']}（信心分數 {live['score']}）" if live["stance"] else "")
                  ) if live["price"] else ""
    tail = f"\n\n想看技術面可以再問我「{name}現在如何？」或「適合進場嗎？」"

    if intent == "what_is":
        return (f"**【{name} {tk} 小檔案】**\n{facts['positioning']}\n\n"
                f"・**起源**：{facts['origin']}\n"
                f"・**用途**：{facts['purpose']}\n"
                f"・**供應**：{facts['supply']}\n"
                f"・**共識機制**：{facts['consensus']}\n"
                f"・**採用概況**：{facts['adoption']}\n"
                + (f"\n{price_line}" if price_line else "")
                + f"\n⚠️ 留意：{facts['risk']}")
    if intent == "origin":
        return (f"**{name} {tk} 的起源**\n{facts['origin']}\n\n"
                f"它的定位：{facts['positioning']}" + tail)
    if intent == "purpose":
        return (f"**{name} {tk} 的用途與特色**\n{facts['purpose']}\n\n"
                f"⚠️ 留意：{facts['risk']}" + tail)
    if intent == "supply_coin":
        return (f"**{name} {tk} 的供應機制**\n{facts['supply']}\n\n"
                f"供應機制影響稀缺性敘事：固定上限（如 BTC）偏「數位黃金」故事，"
                f"溫和通膨（如 DOGE、DOT）則靠需求成長支撐。" + tail)
    # holders：誠實說沒有精確統計，用替代指標
    vol_txt = ""
    if live["vol"]:
        vol_txt = (f"・昨日幣安 USDT 現貨成交約 {live['vol']:,.0f} 枚 {tk}"
                   + (f"（約 {_fmt_usd(live['vol_usdt'])}）" if live["vol_usdt"] else "")
                   + "，這只是全球市場的一部分\n")
    return (f"**{name} {tk} 有多少人買？**\n"
            f"老實說：全球「持有人數」沒有精確統一的統計（同一人可有多個地址、"
            f"交易所帳戶又是多人共用一個地址），所以我不給你假精確的數字。\n\n"
            f"可參考的替代指標：\n{vol_txt}"
            f"・採用概況：{facts['adoption']}\n"
            f"・近期熱度可看「市場情緒／新聞」面板的該幣新聞量" + tail)


# ── 歷史數據查詢（「6月15日比特幣RSI多少」「上個月漲多少」直接查 DB 回答）──────
_ZH_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
           "八": 8, "九": 9, "十": 10}


def _parse_history_query(question: str):
    """
    從問題解析歷史時間點/區間。回傳：
      {"type": "day",   "date": date}                      單日快照
      {"type": "month", "y": int, "m": int}                月度回顧
      None                                                  沒有歷史語意
    支援：YYYY-MM-DD、YYYY年M月D日、M月D日、昨天/前天/大前天、N天前、
          上週（=7天前）、上個月、這個月、X月（今年，未到則視為去年）
    """
    import re as _re
    from datetime import datetime, timezone, timedelta, date
    q = question.replace(" ", "")
    today = datetime.now(timezone.utc).date()

    m = _re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})[日號]?", q)
    if m:
        try:
            return {"type": "day", "date": date(int(m.group(1)), int(m.group(2)), int(m.group(3)))}
        except ValueError:
            return None
    # 帶年份的月份（2024年11月 / 2024-11）→ 該年該月的月度回顧
    m = _re.search(r"(20\d{2})[-/年](\d{1,2})月?(?![\d日號])", q)
    if m and 1 <= int(m.group(2)) <= 12:
        return {"type": "month", "y": int(m.group(1)), "m": int(m.group(2))}
    m = _re.search(r"(?<![\d.])(\d{1,2})月(\d{1,2})[日號]", q)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
            if d > today:
                d = d.replace(year=today.year - 1)
            return {"type": "day", "date": d}
        except ValueError:
            return None
    if "大前天" in q:
        return {"type": "day", "date": today - timedelta(days=3)}
    if "前天" in q:
        return {"type": "day", "date": today - timedelta(days=2)}
    if "昨天" in q or "昨日" in q:
        return {"type": "day", "date": today - timedelta(days=1)}
    m = _re.search(r"([一二三四五六七八九十]|\d+)天前", q)
    if m:
        n = _ZH_NUM.get(m.group(1)) or int(m.group(1))
        return {"type": "day", "date": today - timedelta(days=n)}
    if "上週" in q or "上周" in q or "上禮拜" in q:
        return {"type": "day", "date": today - timedelta(days=7), "approx": "上週約此時（7 天前）"}
    if "上個月" in q or "上月" in q:
        y, mth = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        return {"type": "month", "y": y, "m": mth}
    if "這個月" in q or "本月" in q:
        return {"type": "month", "y": today.year, "m": today.month}
    m = _re.search(r"(?<![\d.月])(\d{1,2})月(?![\d日號])", q)
    if m and ("漲" in q or "跌" in q or "表現" in q or "回顧" in q or "行情" in q
              or "怎麼樣" in q or "怎樣" in q or "如何" in q or "rsi" in q.lower()
              or "價" in q or "數據" in q or "指標" in q):
        mth = int(m.group(1))
        if 1 <= mth <= 12:
            y = today.year if mth <= today.month else today.year - 1
            return {"type": "month", "y": y, "m": mth}
    return None


def has_history_query(question: str) -> bool:
    """問題是否含歷史時間語意（全站模式下需先反問幣種）。"""
    return _parse_history_query(question) is not None


def _rsi_zone(v):
    if v is None:
        return ""
    return ("（跌深超賣）" if v < 30 else "（偏弱）" if v < 45 else "（中性）" if v <= 55
            else "（偏強）" if v <= 70 else "（漲多超買）")


def _history_answer(symbol: str, question: str) -> dict | None:
    """歷史查詢：直接查資料庫的真實數據組答案（零幻覺）。查無資料時誠實說。"""
    hq = _parse_history_query(question)
    if not hq:
        return None
    from backend.services.reader import load_indicators, load_prices, load_signal_history
    from backend.services.app_db import get_coins
    name = next((c.get("zh") or symbol for c in get_coins() if c["symbol"] == symbol), symbol)
    tk = symbol.replace("USDT", "")

    def fp(v):  # 價位自適應
        return "—" if v is None else (f"{v:,.4f}" if v < 1 else f"{v:,.2f}")

    def _out_of_range_reply(asked_txt: str, anchor_iso: str) -> dict:
        """範圍外三層回覆：可查區間 → 最接近的可查快照 → GPT 公開常識補充（標註非本站數據）。
        anchor_iso：請求時間點的 ISO 日期（判斷該取「最早」還是「最新」的鄰近快照）。"""
        from backend.services.reader import data_range
        dmin, dmax = data_range(symbol)
        range_txt = f"{dmin} ～ {dmax}" if dmin else "（此幣尚無資料）"
        near_txt = ""
        if dmin:
            near_d = dmin if anchor_iso < dmin else dmax   # 早於範圍→最早日；晚於/未來→最新日
            nr = load_indicators(symbol, start=near_d, end=near_d)
            if nr:
                n = nr[-1]
                nrsi = n.get("RSI")
                near_txt = (f"\n・最接近的可查日 **{near_d}**：收盤 ${fp(n['close'])}、"
                            f"RSI {f'{nrsi:.1f}' if nrsi is not None else '—'}{_rsi_zone(nrsi)}")
        gpt_txt = ""
        try:
            from backend.services.ai_analyst import gpt_history_fallback
            extra = gpt_history_fallback(question, name, range_txt)
            if extra:
                gpt_txt = f"\n\n{extra}"
        except Exception:
            pass
        tail = ("" if gpt_txt else
                "\n・（設定 GPT 金鑰後，範圍外的年代我還能依公開歷史常識做約略補充，並會明確標註非本站數據）")
        ans = (f"你問的 **{asked_txt}** 超出我能「驗證」的範圍 🙇\n"
               f"・{name} {tk} 可查區間：**{range_txt}**（日線，UTC）{near_txt}{tail}{gpt_txt}\n\n"
               f"想擴充更早的歷史（Binance 最早約 2017 年起）可請管理者調整回補年數。")
        return {"answer": ans, "intent": "history:out_of_range", "ctx": None, "coin_specific": True}

    if hq["type"] == "day":
        d = hq["date"].isoformat()
        rows = load_indicators(symbol, start=d, end=d)
        if not rows:
            return _out_of_range_reply(d, d)
        r = rows[-1]
        sig = load_signal_history(symbol, start=d, end=d)
        sig_txt = (f"\n・當日信心分數 {sig[-1]['score']}"
                   f"（{ {'BULL':'偏多','BEAR':'偏空','NEUTRAL':'中立'}.get(sig[-1]['signal'], '—') }）"
                   if sig else "")
        approx = f"（{hq['approx']}）" if hq.get("approx") else ""
        rsi = r.get("RSI")
        hist = r.get("HIST")
        ans = (f"📅 **{d} {name} {tk}**（日線收盤，UTC）{approx}\n"
               f"・收盤 ${fp(r['close'])}（開 ${fp(r['open'])}／高 ${fp(r['high'])}／低 ${fp(r['low'])}）\n"
               f"・RSI {f'{rsi:.1f}' if rsi is not None else '—'}{_rsi_zone(rsi)}"
               f"｜MACD 柱 {f'{hist:+.4f}' if hist is not None else '—'}\n"
               f"・MA20 ${fp(r.get('MA20'))}／MA60 ${fp(r.get('MA60'))}／MA200 ${fp(r.get('MA200'))}"
               f"{sig_txt}\n\n想對照現在 → 問「{name}現在如何？」")
        return {"answer": ans, "intent": "history:day", "ctx": None, "coin_specific": True}

    # month：月度回顧
    y, mth = hq["y"], hq["m"]
    from calendar import monthrange
    start = f"{y:04d}-{mth:02d}-01"
    end = f"{y:04d}-{mth:02d}-{monthrange(y, mth)[1]:02d}"
    rows = load_prices(symbol, start=start, end=end)
    if not rows:
        return _out_of_range_reply(f"{y} 年 {mth} 月", start)
    first, last = rows[0], rows[-1]
    chg = (last["close"] - first["open"]) / first["open"] * 100 if first["open"] else 0
    hi = max(r["high"] for r in rows)
    lo = min(r["low"] for r in rows)
    ind = load_indicators(symbol, start=end, end=end) or load_indicators(symbol, start=last["date"], end=last["date"])
    rsi = ind[-1].get("RSI") if ind else None
    ans = (f"📅 **{y} 年 {mth} 月 {name} {tk} 月度回顧**（日線，UTC）\n"
           f"・月初開盤 ${fp(first['open'])} → 月末收盤 ${fp(last['close'])}（**{chg:+.1f}%**）\n"
           f"・當月最高 ${fp(hi)}／最低 ${fp(lo)}（振幅 {((hi - lo) / lo * 100) if lo else 0:.1f}%）\n"
           f"・月末 RSI {f'{rsi:.1f}' if rsi is not None else '—'}{_rsi_zone(rsi)}\n"
           f"・資料涵蓋 {len(rows)} 個交易日（{first['date']} ~ {last['date']}）")
    return {"answer": ans, "intent": "history:month", "ctx": None, "coin_specific": True}


# ── 對外入口 ─────────────────────────────────────────────────────────────────
# 模板中「幣種專屬」的變數：全市場模式下若答案用到這些，要註明「以比特幣為例」
_COIN_VARS = ("{幣名}", "{代號}", "{價格}", "{立場}", "{分數}", "{RSI}", "{MA20}",
              "{MA60}", "{MA200}", "{布林上軌}", "{布林下軌}", "{漲跌", "{趨勢說明}",
              "{動能說明}", "{量能說明}", "{位置說明}", "{技術快照}", "{風險清單}",
              "{操作參考}", "{短線摘要}", "{本幣", "{單幣情緒分}")


def match_kind(question: str):
    """公開的命中查詢：('qa', index) / ('knowledge', intent) / None。
    全站（無幣種）模式的路由邏輯用它決定「該答、該反問哪顆幣、還是交棒」。"""
    return _match(question)


def entry_info(hit) -> dict:
    """命中條目的中繼資料：分類 / 問題示例 / 是否幣種專屬（模板用到幣種變數）。"""
    kind, key = hit
    if kind == "knowledge":
        return {"kind": "knowledge", "category": "幣種知識", "example": key,
                "coin_specific": True}
    cat, example, _, template = QA_TEMPLATES[key]
    return {"kind": "qa", "category": cat, "example": example,
            "coin_specific": any(v in template for v in _COIN_VARS)}


def market_greeting() -> str:
    """全站模式的打招呼：講整體市場，不預設任何一顆幣。"""
    fg_txt = ""
    try:
        from backend.services.reader import load_fear_greed_history
        fg = load_fear_greed_history(days=2)
        if fg:
            zh = {"Extreme Fear": "極度恐慌", "Fear": "恐慌", "Neutral": "中性",
                  "Greed": "貪婪", "Extreme Greed": "極度貪婪"}
            fg_txt = f"目前全市場恐懼貪婪指數 {fg[-1]['value']}（{zh.get(fg[-1]['label'], fg[-1]['label'])}）。\n\n"
    except Exception:
        pass
    return (f"嗨！我是小Q，全站的量化小幫手 👋\n\n{fg_txt}"
            "想看哪顆幣直接講名字就好（例：「比特幣現在如何？」「以太幣風險？」），\n"
            "也可以問我教學問題（「RSI 是什麼？」）或大盤狀況（「市場情緒怎麼樣？」）。")


def ask_which_coin(question: str) -> str:
    """行情/知識類問題但沒講幣種時的反問（全站模式用），絕不擅自挑一顆幣回答。"""
    from backend.services.app_db import get_coins
    coins = [c for c in get_coins() if c.get("enabled", True)]
    tks = "、".join((c.get("ticker") or c["symbol"].replace("USDT", "")) for c in coins[:8])
    return (f"這題要看「哪一顆幣」喔！直接把幣名加進問題就行～\n\n"
            f"例如：「**比特幣**{question.strip()[:20]}」「**以太幣**{question.strip()[:20]}」\n\n"
            f"我支援 {len(coins)} 檔：{tks}…（完整清單可問「支援哪些幣」）")


def try_answer(symbol: str, question: str) -> dict | None:
    """
    固定問答入口。命中 → {answer(豐富固定答案), intent, ctx, coin_specific}；
    沒命中 → None。ctx 供 GPT 優化層引用（佐證數據），不外洩給前端。
    """
    # 歷史查詢優先：「6月15日RSI多少」「上個月漲多少」→ 直接查 DB 的真實歷史數據
    # （必須先於一般比對：這類問題常含「漲多少」等關鍵詞，會被「近期表現」搶走）
    hist = _history_answer(symbol, question)
    if hist:
        return hist

    hit = _match(question)
    if not hit:
        return None
    kind, key = hit
    info = entry_info(hit)

    if kind == "knowledge":
        ans = _knowledge_answer(symbol, key)
        if not ans:
            return None
        return {"answer": ans, "intent": f"knowledge:{key}", "ctx": None,
                "coin_specific": True}

    cat, example, _, template = QA_TEMPLATES[key]
    vars_ = _build_vars(symbol)
    return {"answer": _render(template, vars_), "intent": f"{cat}:{example}",
            "ctx": vars_.get("_ctx"), "coin_specific": info["coin_specific"]}
