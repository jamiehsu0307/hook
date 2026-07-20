# Handoff — Phishing Simulation Content Generator (MVP)

> 交接對象：Claude Code
> 目的：實作一個「釣魚演練郵件內容產生器」的互動式網頁 artifact。
> 本文件即為實作規格，請完整遵循「Guardrails」與「Out of Scope」兩節。

---

## 0. Context（給 Claude Code 的背景）

這是一個**經授權的內部資安意識演練工具**。使用者是團隊決策者，用途為員工釣魚郵件的教育訓練（非考核、非懲處）。本 MVP **只做「內容生成」，不做寄送 / 追蹤 / 憑證擷取**。生成的每一封演練信都必須內嵌「可教學的破綻（red flags）」，讓它是一份訓練教材，而不是一個實戰攻擊工具。

---

## 1. Scope

**In scope（本次要做）**
- 互動式單頁網頁（點選參數 → 生成 → 預覽）。
- 透過既有後端 `api/main.py` 的 `POST /generate` 呼叫本機 Ollama，生成**繁體中文**演練郵件（見 §3 Backend 整合契約）。
- 每封信輸出結構化 JSON，含內嵌 red flags。
- 可複製 / 下載 JSON。

**Out of scope（本次明確不做，勿自行擴充）**
- 郵件寄送、投遞、SMTP 整合。
- 點擊追蹤、landing page、憑證擷取頁。
- 針對「真實特定個人」客製化的高擬真攻擊內容。
- 使用真實品牌的真實登入網域。

---

## 2. Guardrails（不可協商的設計約束）

1. **模擬定位**：System prompt 必須框定「內部演練用途」，並要求產出**刻意可辨識的破綻**。
2. **teachable red flags**：每封信的 JSON 一定要有 `red_flags` 陣列，且內容需與 `body` 一致（body 裡真的埋了那些破綻）。
3. **佔位追蹤網址**：連結一律輸出 `{{TRACKING_URL}}` 佔位符，**不得**生成真實可運作的釣魚網址或憑證頁。
4. **示意網域**：寄件網域、連結網域一律使用 `*.example.com` 或明顯 lookalike 示意網域（如 `micros0ft-support.example.com`），**不得**使用真實品牌的真實網域。
5. **可見標記**：UI 上需有明顯的「演練用 / SIMULATION」橫幅；預覽卡的 metadata 面板亦建議顯示 `X-Simulation: true` 標頭欄位（僅示意，非真的寄送）。**此欄位由前端自行附加顯示，不是 §5 schema 的一部分，不要求模型輸出。**
6. **語言**：生成內容為**繁體中文（zh-TW，台灣用語）**。

---

## 3. Tech Stack

- **Frontend**：單頁應用，直接**取代** `api/index.html`（現有的情緒分析頁），沿用該檔已有的暗色設計系統（Cormorant Garamond / Syne / JetBrains Mono）與 dialog、SSE streaming 的既有寫法，不必從零套 `frontend-design` skill。由既有的 FastAPI 後端（`api/main.py`）在 `GET /` 直接served，**同源**，不需要另外起 dev server 或處理跨網域。
- **LLM 後端**：不直接打 Ollama。所有 LLM 呼叫一律經由既有的 `api/main.py` 代理（見下方 §3.1「Backend 整合契約」），它已經處理 SSE streaming、CORS、與 Ollama 溝通的細節。
- **Model**：**不寫死**，UI 加一個 `model` 下拉選單（見 §4），資料來源 `GET /tags`，讓使用者依這台 Ollama 實際有的 model 現場選（原規格寫死 `gemma3:27b`/`gemma4:26b`，但這兩個 tag 是否存在會因環境而異，不應硬編）。`main.py` 的 `LLM_FAMILIES` 白名單已補上 `"gemma3"`（為未來相容），實際能選到什麼 model 以當下 `GET /tags` 回傳為準。

### 3.1 Backend 整合契約

不要在前端組 prompt、schema 或處理 CORS——一律打既有的 `POST /generate`。guardrails（system prompt、user prompt、guided-decoding JSON Schema）全部由後端組裝，前端只送分類參數，無法透過自組 `messages`/`format` 繞過（詳見 `plan-server-side-prompt.md`）。

**Request**（`POST /generate`，同源、相對路徑即可）：
```json
{
  "model": "<使用者於 §4 model 下拉選單選取的值>",
  "scenario": "<§7-A key>",
  "mechanism": "<§7-B key>",
  "lever": "<§6.2 enums 六選一>",
  "action": "<§6.2 enums 擇一>",
  "difficulty": 1,
  "context": "",
  "options": { "num_predict": 3000 }
}
```
- **值域由後端驗證**：`scenario`/`mechanism`/`lever`/`action`/`difficulty` 皆由 `main.py` 的 Pydantic model 對照 `api/classification.json` 驗證，非法值直接回 422，連 prompt 都不會組。
- `options` 只認 `num_predict`，且會被夾在 `main.py` 的 `MAX_NUM_PREDICT` 上限內；其餘欄位一律忽略。
- 模型下拉選單資料來源：`GET /tags`（回傳格式與篩選邏輯見 `main.py` 的 `LLM_FAMILIES` 白名單）。
- **要打 `GET /classification`**：§7 的 `scenario`/`delivery_mechanism` 兩表、§6.2 enums、§5.1 mechanism 相依欄位規則統一存放於 `api/classification.json`，前端於頁面載入時 fetch 這支端點來 populate 下拉選單與卡片渲染邏輯，後端 `/generate` 驗證與 guided-decoding schema 的 enum 也讀同一份檔案——不要在 `index.html` 裡另外寫死一份，避免前後端值域漂移不同步。
- §6.1 system prompt（`api/system_prompt.md`）與 §6.2 few-shot 範例（`api/examples.json`）現在由後端在 import 時讀入、內部組裝進 prompt；前端不再需要、也不再打 `GET /system-prompt`、`GET /examples`（這兩支路由已隨 `POST /query` 一起移除，見 CLAUDE.md）。

**Response**：`text/event-stream`，每行格式為 `data: <ollama json>`；持續累積 `chunk.message.content` 直到 `chunk.done === true`，再對累積字串 `JSON.parse`（解析前先去除可能的 ```json 圍欄）。**Thinking 模型會先在 `message.thinking` 吐出大量內容、`message.content` 長時間為空**（實測已確認），這段期間不是卡住，UI 需維持生成中狀態；只累積 `message.content`，`thinking` 不計入最終 JSON（見 §4 動作）。

**已知後端預設值**：非 thinking 模型時，`main.py` 會補 `options.num_predict=1500`、`options.repeat_penalty=1.3`。difficulty=3、破綻較多時可能被截斷導致 JSON.parse 失敗，前端可在 request 裡自帶 `options.num_predict` 覆蓋（重試時調高，見 §4 動作的失敗分類；會被夾在 `MAX_NUM_PREDICT` 上限內）。

**模型選擇提醒**：`GET /tags` 列出的部分模型（如較保守的一般用途模型）可能會拒絕生成釣魚郵件內容，回傳散文而非 JSON。這是預期內會發生的情況，不是 bug；前端需能辨識並提示換模型（見 §4 動作）。

---

## 4. Functional Requirements

**輸入（UI 控制項）** — 分類維度皆為**輸入**（由使用者指定，模型照做），非事後貼標。
- `model`：下拉選單，資料來源 `GET /tags`（見 §3.1），不寫死特定 model。
- `scenario`：下拉選單（情境/藉口，見 §7-A）。
- `delivery_mechanism`：下拉選單（傳遞手法，見 §7-B）。
- `social_engineering_lever`：下拉選單（社交工程槓桿，見 §6.2 enums）。
- `desired_action`：下拉選單（誘導行動，見 §6.2 enums）。
- `difficulty`：1–3（見 §8 難度分級）。
- `context`：可編輯欄位 — 組織名稱、團隊常用系統（如 M365 / Slack / 內部 ERP）、部門名稱。
- `count`：一次生成幾封變體（預設 1，上限 5）。

> 註：`scenario`（故事）與 `delivery_mechanism`（機制）是**正交**的兩軸，務必拆成兩個獨立欄位，不要合併成一個清單。

**動作**
- 「生成」按鈕 → 送出使用者選取的分類參數 → 呼叫 `POST /generate`（見 §3.1，prompt/schema 組裝已搬到後端）→ 解析 JSON → 渲染。
- 需有 loading 狀態與錯誤處理，區分三種失敗模式，不可整頁崩潰：
  1. **連線失敗**（`/generate` fetch 失敗或非 2xx，含分類參數非法時的 422）→ 提示連線錯誤，可重試。
  2. **JSON 截斷**（stream 正常結束但內容 `JSON.parse` 失敗，且內容看起來像被腰斬的 JSON）→ 多半是 `main.py` 預設的 `num_predict=1500` 不夠（見 §3.1）。重試時應**調高** `options.num_predict`（如 3000）再送，而非原樣重送，否則會重複截斷。
  3. **模型拒答**（stream 正常結束但內容是散文、完全不像 JSON，例如「我不能協助...」）→ 這是不同於截斷的失敗模式，提示「此模型可能拒絕生成演練內容，請換一個 model 再試」，不要用調高 `num_predict` 的方式重試。
- **`count > 1` 的批次失敗處理**：逐封呼叫是彼此獨立的，其中一封失敗（無論哪種失敗模式）**不影響其餘信件繼續生成**；該封在自己的卡片位置顯示失敗狀態與對應錯誤提示、並可單獨重試，不中止整批。「下載全部 JSON」只匯出成功的信件。
- **Thinking model 的 loading 狀態**：streaming 過程中若 `message.content` 持續為空、但 `message.thinking` 有內容且尚未 `done`，代表模型正在思考，UI 應維持「生成中」提示，不可誤判為卡住或空白結果；最終寫入預覽卡與 JSON 輸出的只有累積後的 `message.content`，`thinking` 內容不使用。

**輸出（畫面）**
- 郵件預覽卡：`subject` / `sender_display_name <sender_address>` / `body`（保留換行）/ metadata 面板顯示 `X-Simulation: true`（前端自帶，非模型輸出，見 §2）。
- 依 `delivery_mechanism` 條件渲染相依欄位（見 §5.1）：有值才顯示對應 UI 元素，空字串則不渲染該區塊。
  - `link_text` 有值 → 顯示為連結（實際指向 `{{TRACKING_URL}}`）。
  - `callback_number` 有值 → 顯示為「回撥電話」列。
  - `oauth_app_name` 有值 → 顯示為「請求授權的 App」列。
- red flags 面板：條列 `red_flags`（這是給教學頁用的重點）。
- 標籤：`difficulty`、`scenario`。
- `count > 1` 時，多封信垂直堆疊多張獨立預覽卡，各自有自己的 red flags 面板與標籤（逐封呼叫產生，見 §6 說明；可邊完成邊插入卡片，不必等全部生成完）。
- 動作：每張卡「複製 JSON」（複製該封物件）；另有一顆「下載全部 JSON」，輸出所有已生成信件組成的**陣列** `[{...}, …]`（`count==1` 時陣列長度為 1），檔名 `phishing_sim_<timestamp>.json`。

---

## 5. Data Contract（每封信的 JSON schema）

LLM 必須**只回傳 JSON**（無 markdown、無前後贅字）；前端解析前先去除可能的 ```json 圍欄。

```json
{
  "scenario": "saas_login_alert",
  "delivery_mechanism": "link",
  "social_engineering_lever": "urgency",
  "desired_action": "enter_credentials",
  "difficulty": 2,
  "lever_manifestation": "string  // 一句話說明 body 中如何體現指定槓桿（驗證用＋教學用）",
  "subject": "string",
  "sender_display_name": "string",
  "sender_address": "string  // 示意/lookalike 網域",
  "body": "string  // 繁中內文，依 mechanism 相依欄位的規則決定是否含 {{TRACKING_URL}} 佔位",
  "link_text": "string  // 見下方 mechanism 對應表，不適用時填空字串 \"\"",
  "callback_number": "string  // 見下方 mechanism 對應表，不適用時填空字串 \"\"",
  "oauth_app_name": "string  // 見下方 mechanism 對應表，不適用時填空字串 \"\"",
  "red_flags": [
    "string  // 這封信刻意內嵌的破綻，需與 body 對得上"
  ]
}
```

> 四個分類欄位（`scenario` / `delivery_mechanism` / `social_engineering_lever` / `desired_action`）為**輸入回填**：模型直接回填指定值，不做分類判斷。模型真正要「產生」的是 `lever_manifestation` 與 `red_flags`。
>
> 這份 schema 由後端 `build_schema()`（`api/main.py`）組成標準 JSON Schema（`type`/`properties`/`required`），透過 §3.1 的 `POST /generate` 內部帶給 Ollama 的 `format` 欄位做 guided decoding——前端不再自己組這份 schema，也不是前端事後驗證用的；`difficulty` 宣告為 integer enum `[1,2,3]`，四個分類欄位各自帶對應值域的 enum 約束（值域見 §6.2 `<enums>` 與 §7，實際存放於 `api/classification.json`）；`red_flags` 加 `"minItems": 1`，否則 guided decoding 在合法範圍內可以回傳空陣列 `[]`，直接違反 §2 guardrail 2。

### 5.1 `delivery_mechanism` 相依欄位對應表

六種 `delivery_mechanism` 並非都有連結，單一固定 schema 會逼模型硬塞不合理的欄位。相依欄位一律宣告為必填字串、但**不適用時填空字串 `""`**（不要用 `null`，維持型別單純）：

| `delivery_mechanism` | `link_text` | `{{TRACKING_URL}}` 出現在 body？ | `callback_number` | `oauth_app_name` |
|---|---|---|---|---|
| `link` | 填 | 是 | `""` | `""` |
| `attachment` | 填（附件檔名/連結文字） | 是 | `""` | `""` |
| `qr_code` | 填 | 是（描述於 body 文字中；MVP **不產生真的 QR 圖**，前端只顯示「QR code（演練佔位）」文字標記） | `""` | `""` |
| `oauth_consent` | 填（導向授權頁的連結文字） | 是 | `""` | 填（示意第三方 App 名稱） |
| `bec_no_payload` | `""` | 否 | `""` | `""` |
| `callback` | `""` | 否 | 填（示意電話，如 `0800-000-000`） | `""` |

---

## 6. Prompt Design

### 6.1 System Prompt（請原樣植入，可微調語氣）

```
你是一個「內部資安演練」的釣魚郵件範本產生器，服務對象是經授權的企業資安團隊，
用途僅限員工釣魚郵件「意識訓練」，不用於真實攻擊。

輸出規則：
1. 產出的每一封演練信都必須刻意內嵌可被辨識的破綻（red flags），
   並在 red_flags 欄位如實列出，且破綻必須真的出現在 body 中。
2. 所有連結一律使用佔位符 {{TRACKING_URL}}，不得產生任何真實可運作的網址。
3. 寄件與連結網域一律使用示意網域（*.example.com 或明顯 lookalike），
   不得使用任何真實品牌的真實登入網域。
4. 內容使用繁體中文（台灣用語）。
5. 依指定的 difficulty 調整破綻的明顯程度，但無論多難，至少保留一個可教學的破綻。
6. scenario / delivery_mechanism / social_engineering_lever / desired_action 皆為使用者「指定的輸入」，
   請直接回填，不要自行分類或更改；並額外產生 lever_manifestation 說明 body 如何體現指定槓桿。
7. link_text / callback_number / oauth_app_name 為 delivery_mechanism 相依欄位，只填該 mechanism 實際用得到的欄位，
   其餘一律填空字串 ""，不得無中生有塞入不相關的連結、電話或 App 名稱。
8. 只輸出符合指定 schema 的 JSON，不要有任何額外文字或 markdown 圍欄。
```

### 6.2 User Prompt Template（結構化，含分類 enum）

```
<task>依下列規格產生 1 封繁體中文演練釣魚信。</task>

<spec>
scenario: {scenario}
delivery_mechanism: {delivery_mechanism}
social_engineering_lever: {lever}        # 指定值，body 必須以此槓桿為主軸
desired_action: {action}                 # 指定值，信件要誘導的目標行為
difficulty: {difficulty}                 # 1-3
context: {context}
</spec>

<enums>
social_engineering_lever（六選一）：
  urgency=製造時間壓力 / authority=假冒有權者或官方 / fear=觸發損失或懲罰恐懼 /
  curiosity=引發好奇 / greed=以獎金退款利誘 / trust=冒用熟悉的人或品牌
desired_action（擇一）：
  click_link / enter_credentials / open_attachment / scan_qr / reply / call_number / approve_oauth
delivery_mechanism（擇一）：
  link / attachment / qr_code / bec_no_payload / callback / oauth_consent
（scenario 見 §7-A）
</enums>

<constraints>
1. body 必須真正體現指定的 lever 並誘導指定的 action，不可名實不符。
2. 依 difficulty 調整破綻明顯度，至少保留 1 個可教學破綻。
3. 連結一律用 {{TRACKING_URL}}；寄件與連結網域用示意網域（*.example.com 或 lookalike）。
4. 【衝突處理－簡單版】若 delivery_mechanism 與 desired_action 矛盾，以 delivery_mechanism 為準，
   自動調整 action 並在 red_flags 之外不另報錯。範例：
   - bec_no_payload（無連結無附件）→ action 收斂為 reply 或 call_number，不得用 click_link。
   - qr_code → action 對應 scan_qr。
   - oauth_consent → action 對應 approve_oauth。
5. 【mechanism 相依欄位】link_text / callback_number / oauth_app_name 依 §5.1 對應表填寫，
   不適用的欄位填空字串 ""；bec_no_payload 與 callback 不得在 body 中出現 {{TRACKING_URL}}。
</constraints>

<output_format>
只輸出 JSON，不要 markdown 圍欄，欄位依 §5 schema。四個分類欄位回填指定值，
lever_manifestation 用一句話說明 body 如何體現該槓桿。mechanism 相依欄位依 §5.1 填寫或留空。
</output_format>

<example>
下列 5 個範例覆蓋不同的 mechanism / lever / difficulty 組合，示範 §5.1 mechanism 相依欄位在各情境下如何對齊（尤其 `bec_no_payload`/`callback` 無連結、`oauth_consent` 帶 App 名稱這幾種較容易出錯的情況）。**實際維護位置是 `api/examples.json`（見 §3.1，後端 import 時讀入，前端不再直接存取）**，下方僅為文件用途的展示副本，供理解設計意圖；實際送入單次 prompt 的只有其中 mechanism 匹配的那一筆，不是全部 5 筆一起送：

| # | scenario | mechanism | lever | action | difficulty |
|---|---|---|---|---|---|
| 1 | `saas_login_alert` | `link` | `urgency` | `enter_credentials` | 1 |
| 2 | `collab_mention` | `oauth_consent` | `authority` | `approve_oauth` | 2 |
| 3 | `account_suspension` | `callback` | `fear` | `call_number` | 2 |
| 4 | `ceo_urgent_request` | `bec_no_payload` | `trust` | `reply` | 3 |
| 5 | `delivery_issue` | `qr_code` | `curiosity` | `scan_qr` | 1 |

[
  {
    "scenario": "saas_login_alert",
    "delivery_mechanism": "link",
    "social_engineering_lever": "urgency",
    "desired_action": "enter_credentials",
    "difficulty": 1,
    "lever_manifestation": "全篇以「24 小時內未完成驗證即永久停權」反覆製造急迫感，逼使用者不加思索立即點擊連結。",
    "subject": "【重要】偵測到異常登入，請於24小時內完成身分驗證！！",
    "sender_display_name": "Microsoft 帳戶安全中心",
    "sender_address": "security-alert@micros0ft-support.example.com",
    "body": "親愛的用戶，\n\n您的帳戶於今日凌晨在不明地點被偵測到異常登入嘗試。為保護您的帳戶安全，請立即點擊下方連結完成身分驗證。\n\n若未於24小時內完成驗證，您的帳戶將被永久停權，所有資料將無法復原！！\n\n{{TRACKING_URL}}\n\nMicrosoft 帳戶安全團隊 敬上",
    "link_text": "立即驗證帳戶",
    "callback_number": "",
    "oauth_app_name": "",
    "red_flags": [
      "寄件網域為 micros0ft-support.example.com（0 取代 o 的 lookalike），非官方 microsoft.com 網域",
      "使用「親愛的用戶」等通用稱呼，未指名道姓",
      "以「24 小時內未驗證即永久停權」製造強烈時間壓力",
      "結尾使用「！！」等誇張標點，語氣不符官方通知慣例",
      "要求直接點擊連結輸入帳密驗證身分，官方通知不會如此要求"
    ]
  },
  {
    "scenario": "collab_mention",
    "delivery_mechanism": "oauth_consent",
    "social_engineering_lever": "authority",
    "desired_action": "approve_oauth",
    "difficulty": 2,
    "lever_manifestation": "假冒 IT 資訊安全處以官方政策口吻要求員工立即授權第三方應用程式存取帳號，利用職權施壓、不容質疑。",
    "subject": "「IT 資訊安全處」通知：Slack 協作工具權限升級驗證",
    "sender_display_name": "IT 資訊安全處",
    "sender_address": "it-security@corp-workspace.example.com",
    "body": "您好，\n\n因應公司資安政策更新，所有 Slack 使用者須於本週內完成第三方應用程式「WorkSync Connector」的權限授權，以維持協作工具正常運作。\n\n請點擊下方連結完成授權：\n{{TRACKING_URL}}\n\n如未於期限內完成，您的協作工具帳號權限將受影響。\n\nIT 資訊安全處",
    "link_text": "前往授權頁面",
    "callback_number": "",
    "oauth_app_name": "WorkSync Connector",
    "red_flags": [
      "寄件網域為示意 lookalike（corp-workspace.example.com），非公司真實網域",
      "僅以部門名稱「IT 資訊安全處」署名，無具體聯絡窗口或人員",
      "要求授權一個來源不明的第三方 App「WorkSync Connector」存取帳號",
      "以「不完成將影響帳號權限」施加權威壓力，且未提供人工查證管道"
    ]
  },
  {
    "scenario": "account_suspension",
    "delivery_mechanism": "callback",
    "social_engineering_lever": "fear",
    "desired_action": "call_number",
    "difficulty": 2,
    "lever_manifestation": "以帳號遭系統偵測到違規使用、即將停權為由，觸發使用者對權益受損的恐懼，促使立即回撥電話「確認身份」。",
    "subject": "帳號異常使用警示：如未處理將於 48 小時後停權",
    "sender_display_name": "企業帳戶服務中心",
    "sender_address": "account-service@corp-portal.example.com",
    "body": "您好，\n\n系統偵測到您的帳號有異常使用情形，為保障您的權益，請於 48 小時內回撥 0800-123-456 與客服人員確認身份。\n\n逾期未處理，您的帳號將依規定暫停使用，需另行申請復原。\n\n企業帳戶服務中心",
    "link_text": "",
    "callback_number": "0800-123-456",
    "oauth_app_name": "",
    "red_flags": [
      "官方帳戶服務不會僅以電話回撥方式要求確認身份",
      "未指名具體違規內容，僅籠統稱「異常使用情形」",
      "以停權作為要脅施加恐懼與壓力，且期限刻意壓縮至 48 小時",
      "寄件網域為示意網域（corp-portal.example.com），非公司內部網域",
      "未提供任何官方替代管道（如公司內部系統）供員工自行查證"
    ]
  },
  {
    "scenario": "ceo_urgent_request",
    "delivery_mechanism": "bec_no_payload",
    "social_engineering_lever": "trust",
    "desired_action": "reply",
    "difficulty": 3,
    "lever_manifestation": "假借與員工熟識的執行長口吻，以簡短、個人化、看似出差中匆忙撰寫的語氣建立信任感，誘導對方直接回信協助處理事項，全程不使用連結或附件以降低戒心。",
    "subject": "Re: 這件事先別讓其他人知道",
    "sender_display_name": "David Chen",
    "sender_address": "david.chen@corp-holdings.example.com",
    "body": "我現在在機場趕飛機，方便的話先回信給我，這件事先別讓其他人知道，我等等落地再詳細說明，謝謝。",
    "link_text": "",
    "callback_number": "",
    "oauth_app_name": "",
    "red_flags": [
      "寄件網域為示意 lookalike（corp-holdings.example.com），與正常內部網域不完全一致",
      "以「先別讓其他人知道」刻意阻斷員工向他人求證或通報的機會",
      "全程未提供任何可供查證的具體事項，僅以匆忙語氣要求員工直接回信配合"
    ]
  },
  {
    "scenario": "delivery_issue",
    "delivery_mechanism": "qr_code",
    "social_engineering_lever": "curiosity",
    "desired_action": "scan_qr",
    "difficulty": 1,
    "lever_manifestation": "以「包裹地址有誤、內含商品待確認」引發好奇心，誘導使用者掃描 QR code 一探究竟並重新確認個資。",
    "subject": "您的包裹因地址問題無法配送，內含商品待確認",
    "sender_display_name": "快遞包裹通知中心",
    "sender_address": "notice@express-delivery.example.com",
    "body": "您好，\n\n您的包裹因收件地址資訊有誤，目前無法完成配送。請掃描下方 QR Code（連結：{{TRACKING_URL}}）確認並更新收件地址，逾期未處理包裹將退回原廠。\n\n[QR Code（演練佔位）]\n\n快遞包裹通知中心",
    "link_text": "掃描 QR Code 確認地址",
    "callback_number": "",
    "oauth_app_name": "",
    "red_flags": [
      "寄件網域為示意網域（express-delivery.example.com），非任何真實物流業者官方網域",
      "未提供包裹追蹤編號等可供查證的具體資訊",
      "以模糊的「地址問題」搭配「逾期將退回」製造急迫感與好奇心",
      "要求透過來路不明的 QR Code 重新確認個資，而非官方 App 或官網查詢"
    ]
  }
]
</example>
```

（`count > 1` 時採逐封呼叫，已在 §4/§5.1 定案，不要求模型一次回傳 JSON 陣列；陣列是前端收集每次呼叫結果後自行組出來的，見 §4 輸出。）

---

## 7. Classification Library（兩軸）

分類拆成正交兩軸：**§7-A `scenario`（情境/故事）** 與 **§7-B `delivery_mechanism`（傳遞手法/機制）**。兩者各自獨立選擇。

### 7-A. `scenario`（情境庫，依假冒對象分組）

**帳號 / IT 安全**
| key | 說明 |
|-----|------|
| `password_reset` | 密碼即將到期，需重設 |
| `saas_login_alert` | 偵測到異常/陌生裝置登入 |
| `mfa_reenroll` | MFA 需重新設定/驗證 |
| `mailbox_quota` | 信箱容量已滿，需清理否則停用 |
| `account_suspension` | 帳號違規將被停用 |
| `security_policy_update` | 資安政策更新，需重新登入確認 |

**HR / 人資**
| key | 說明 |
|-----|------|
| `hr_benefit` | 福利/年終/獎金相關確認 |
| `payroll_update` | 薪資帳戶資料需確認/更新 |
| `performance_review` | 績效考核表單需填寫 |
| `policy_ack` | 新規範/員工手冊需簽署確認 |
| `org_survey` | 員工問卷/滿意度調查 |

**財務 / 供應商**
| key | 說明 |
|-----|------|
| `invoice_payment` | 逾期發票/待付款 |
| `vendor_bank_change` | 供應商變更收款帳號（典型 BEC） |
| `expense_reimburse` | 費用報銷/退款 |
| `purchase_order` | 採購訂單確認 |
| `tax_document` | 稅務文件/扣繳憑單 |

**主管 / BEC**
| key | 說明 |
|-----|------|
| `ceo_urgent_request` | 假冒主管緊急交辦（轉帳/機密） |
| `confidential_project` | 機密專案/併購，要求保密勿聲張 |
| `gift_card_request` | 主管要求代購禮品卡 |

**外部服務 / 品牌**
| key | 說明 |
|-----|------|
| `cloud_doc_share` | 有人分享文件給你（SharePoint/Drive/DocuSign） |
| `collab_mention` | 協作工具通知（被 @ 或指派任務） |
| `subscription_renew` | 訂閱到期/付款失敗 |
| `delivery_issue` | 包裹配送地址有誤 |
| `calendar_invite` | 會議邀請需接受/加入 |

**內部營運 / 一般**
| key | 說明 |
|-----|------|
| `it_helpdesk` | IT 服務台通知 |
| `internal_announce` | 內部系統上線/一般公告 |
| `voicemail_notification` | 語音留言通知 |
| `printer_scan` | 掃描件已送達（多功能事務機） |

### 7-B. `delivery_mechanism`（傳遞手法）

| key | 說明 |
|-----|------|
| `link` | 惡意連結導向假登入頁（最常見） |
| `attachment` | 惡意附件（帶巨集檔案 / HTML smuggling） |
| `qr_code` | QR code 釣魚（quishing，繞過 URL 掃描） |
| `bec_no_payload` | 純文字社交，無連結無附件（最難偵測） |
| `callback` | 要求回撥假客服電話（TOAD） |
| `oauth_consent` | 誘導授權第三方 App（繞過 MFA） |

Claude Code 可將兩表分別做成前端兩個下拉選單的資料來源。

> **組合策略提醒**：`scenario × mechanism × lever × action` 全笛卡兒積上千種，勿窮舉。以 `scenario` 為主軸，其餘維度採「每種至少覆蓋一次」的代表性測試矩陣即可。mechanism 與 action 的衝突交由 §6.2 `<constraints>` 第 4 點（簡單版）自動收斂。

---

## 8. Difficulty Rubric

- **L1（明顯）**：錯誤網域、通用稱呼（「親愛的用戶」）、強烈急迫威脅、明顯錯字。破綻多且直白。
- **L2（中等）**：lookalike 網域、情境合理、急迫感較收斂、稱呼較貼近真實。破綻需稍微留意才看得出。
- **L3（細膩）**：模擬對話串/轉寄口吻、看似個人化、破綻最少 — 但**仍須保留至少一個可教學的破綻**（例如寄件位址與顯示名稱不一致）。

---

## 9. UI/UX Notes

- 版面頂部固定「⚠️ 演練用 / SIMULATION ONLY」橫幅，全程可見。
- 單頁、左側參數、右側預覽即可，保持簡潔。
- 達到品質底線：RWD 到手機、鍵盤 focus 可見、尊重 reduced-motion。
- 文案用使用者語言（例：按鈕寫「生成演練信」而非「Submit」）。
- 沿用 `api/index.html` 既有的設計系統與 streaming/dialog 寫法（見 §3），不必重新套 `frontend-design` skill。
- **API 呼叫用相對路徑**（或 `location.origin`），因為頁面就是由 `main.py` 同源 served。不要沿用舊 `index.html` 裡 `` `http://${location.hostname}:7000` `` 這種寫死 port 的寫法（該 port 目前也已經是舊資訊，實際 host port 由部署時決定）。
- **日夜模式切換**（本次追加，原規格未列）：標題列右上角圓形按鈕（☾/☀）切換 `<html data-theme>`，色彩皆走既有 CSS variables，故只需在 `:root[data-theme="light"]` 覆寫一組淺色值即可，不需另寫元件樣式。預設值取 `localStorage.theme`，沒有則 fallback 到 `prefers-color-scheme`；選擇後寫回 `localStorage` 記住偏好。
- **「隨機組合」按鈕**（本次追加，原規格未列）：一鍵隨機帶入 `scenario` / `delivery_mechanism` / `social_engineering_lever` / `desired_action` 四個下拉選單，方便快速試跑不同組合；不動 `difficulty`、`count`、`context`、`model`。

---

## 10. Acceptance Criteria

1. 任一 `scenario` × `delivery_mechanism` × `lever` × `action` × `difficulty` 組合都能生成**合法 JSON** 的繁中演練信。
2. 四個分類欄位正確回填指定的輸入值；`lever_manifestation` 有內容且與 body 一致。
3. `red_flags` 有內容，且與 `body` 內實際埋設的破綻一致。
4. mechanism 與 action 衝突時，依 §6.2 第 4 點自動收斂（如 `bec_no_payload` 不出現 `click_link`）。
5. 連結一律為 `{{TRACKING_URL}}` 佔位符；無任何真實可運作網址；`bec_no_payload`/`callback` 的 body 不含 `{{TRACKING_URL}}`（見 §5.1）。
6. 寄件/連結網域皆為示意網域，無真實品牌真實網域。
7. UI 有明顯「演練用」橫幅。
8. 可複製單封 JSON；`count > 1` 時可下載所有已生成信件組成的 JSON 陣列（見 §4 輸出）。
9. 三種失敗模式皆有對應處理、不整頁崩潰（見 §4 動作）：連線失敗可直接重試；JSON 截斷重試時會調高 `num_predict`；模型拒答時提示換模型而非無限重試。
10. `model` 下拉選單資料即時來自 `GET /tags`（不寫死特定 model 名稱），選單有值即可生成。
11. Thinking 模型生成期間（`message.content` 空但未 done）UI 顯示生成中狀態，不會被誤判為當掉或空結果。
12. `count > 1` 時若其中一封失敗，其餘信件不受影響、照常生成完畢；失敗的那封可單獨重試，「下載全部 JSON」只包含成功的信件。

---

## 11. 後續（本次不做，先記著）

- 生成內容 → 匯入演練平台（Microsoft Attack Simulation Training 第三方 payload / GoPhish）。
- landing page 教學頁（顯示該封信的 red_flags）。
- 指標蒐集（點擊率、憑證輸入率、**通報率**）與匿名化報表。