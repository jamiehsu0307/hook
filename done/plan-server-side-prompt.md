# Handoff — 把 Prompt/Schema 組裝搬到後端（關閉 `/query` 繞過）

> 交接對象：Claude Code
> 目的：修掉現行架構中「使用者可以繞過前端、直接打 `/query` 竄改 guardrails」的問題。
> 本文件是實作規格，執行前請完整讀過，尤其 Risks 與 Phase 排序的理由。

---

## 0. Context（為什麼要做這個）

`task.md` 定義的釣魚演練郵件產生器，guardrails（`red_flags` 必填、`{{TRACKING_URL}}` 佔位符、`*.example.com` 示意網域、mechanism 相依欄位規則、四個分類欄位值域）目前**完全由前端保證**：`api/index.html` 組出 system prompt、user prompt、JSON guided-decoding schema 後，才送到後端 `POST /query`。

問題在於 `POST /query`（`api/main.py:281-320`）是純被動轉發：直接 `await request.json()`，只碰 `payload["model"]`（thinking 能力檢查）跟 `payload["options"]`（補預設值），`messages`/`format` 完全不驗證、原封轉給 Ollama。**任何人只要繞過 `index.html`、直接 curl `/query` 帶自組 payload，就能跳過所有 guardrails**——這不是理論風險，是現行程式碼的必然結果。

目標：讓 guardrails 的執行權收回後端，client 只能從驗證過的參數集合裡選，不能自己組 `messages`/`format`。

**明確不在範圍**：`context` 欄位仍是自由文字、會被串進 prompt，本次不處理透過它做 prompt injection 的風險（跟「API 參數竄改」是不同類的風險，只在此標註，不修）。

---

## 1. 現況架構（改之前，先搞懂資料怎麼流的）

```
使用者選參數（scenario/mechanism/lever/action/difficulty/context/model）
  → index.html: buildSchema() + buildUserPrompt(p)
      - SYSTEM_PROMPT ← GET /system-prompt（讀 api/system_prompt.md）
      - EXAMPLES ← GET /examples（讀 api/examples.json，依 mechanism 挑一筆當 few-shot）
      - 分類資料（SCENARIOS/MECHANISMS/LEVERS/ACTIONS/DIFFICULTIES/MECH_RULES）
        目前寫死在 index.html:94-179
  → 組出 { model, messages, stream, format, options }
  → POST /query（main.py:281-320，零驗證，純轉發）
  → Ollama /api/chat
```

**驗證過的事實**（不是推測）：
- `/query` 目前只有 `index.html` 一個呼叫端，repo 裡沒有任何測試框架、也沒有其他程式碼呼叫它。
- `main.py` 目前完全沒有任何 Pydantic `BaseModel`，全部是 `await request.json()` 或 `UploadFile`；`requirements.txt` 沒鎖版本，Pydantic 是透過 FastAPI 帶進來的 v2，寫驗證要用 `field_validator`（v2 API），不是舊版 `validator`。
- `index.html` 的分類資料（`MECH_RULES`/`SCENARIO_LABELS`/dropdown 選單）**改完之後前端仍然需要**——它們不只是拿去組 prompt，也拿去渲染卡片跟填下拉選單，不能整批刪掉。

---

## 2. 目標架構（改之後）

```
使用者選參數
  → index.html: 只收集 { model, scenario, mechanism, lever, action, difficulty, context }
    （分類資料改成 fetch classification.json 來 populate 下拉選單/渲染卡片，不再拿去組 prompt）
  → POST /generate（新端點，main.py）
      - Pydantic GenerateRequest 驗證所有欄位，非法值 422，連 prompt 都不會組
      - 後端讀 system_prompt.md / examples.json / classification.json
      - 後端版 build_schema() / build_user_prompt() 組出 messages/format
      - 呼叫共用 streaming helper（從現行 /query 抽出來的 thinking 檢查 + SSE 轉發）
  → Ollama /api/chat
```

`/query` 最終**整條刪除**——這是唯一真正關閉繞過管道的動作，其他步驟都只是鋪墊。

---

## 3. Implementation Phases

排序刻意讓 `/generate` 先上線、驗證過、才刪 `/query`，全程保留可用的 fallback，避免 restart 時間差造成前後端對不上的破窗。

### Phase 1 — 抽出 `api/classification.json`（純資料搬遷，行為不變）

把 `index.html:94-179` 的 `SCENARIOS`/`MECHANISMS`/`LEVERS`/`ACTIONS`/`DIFFICULTIES`/`MECH_RULES` 搬成一份 JSON，模式比照既有的 `api/examples.json`。

- **為什麼現在做、不 defer**：前端渲染/下拉選單、後端驗證/schema enum 兩邊都真的要用到這份資料。如果各自留一份手抄（JS 一份、Python 再手刻一份），就是重新製造出「UI 能選的值 ≠ 後端接受的值」這個 bug 類型——正是這次重構要消滅的東西。而且目前 `buildUserPrompt()` 裡的 `<enums>` 文字區塊本來就已經是這些陣列的手抄複本，不現在做的話，手抄複本只會從 2 份變 3 份。
- Dependencies：無。
- Risk：Low。

### Phase 2 — 新增 `POST /generate`（`/query` 先保留）

1. **`GenerateRequest` Pydantic model**：`model: str`、`scenario/mechanism/lever/action: str`（用 `field_validator` 對照 `classification.json` 載入的合法 key 集合，或用動態 `Enum` 當欄位型別換取自動 422 + OpenAPI docs）、`difficulty: Literal[1,2,3]`、`context: str = ""`、`options: dict | None = None`。
2. **移植 `buildSchema()`/`buildUserPrompt()` 到 Python**：import 時讀 `system_prompt.md`、`examples.json`、`classification.json`，逐字重現現行 system/user prompt 與 JSON Schema，包含：
   - 依 `delivery_mechanism` 挑出唯一匹配範例的邏輯
   - `SCENARIO_LABELS` 標籤回填
   - `red_flags` 的 `minItems: 1`
   - `difficulty` 宣告為 integer enum `[1,2,3]`
3. **抽出共用 streaming helper**：把現行 `/query` 的 thinking 能力檢查（`main.py:284-295`）與 `event_generator`（`:297-320`）搬進一個內部 function，`/generate` 呼叫它。SSE wire format（`data: <ollama json>\n\n`）維持不變，前端 read loop 不用動。
4. **`options` 白名單**：只認 `num_predict` 並夾上限，不要開放整個自由 dict——這不是 guardrail 竄改，但可以拿來塞誇張參數搞資源濫用。

- 這個階段刻意**不動** `/query`/`/system-prompt`/`/examples`：restart 後新舊端點並存，`index.html` 還沒改，仍然正常運作。
- Dependencies：Phase 1。需要 restart container 生效。
- Risk：**High**（逐字移植 prompt/schema 的保真度——JS→Python 稍有出入，生成結果就會偏移現行行為，且不容易察覺。建議以現行 `index.html` 產物為基準逐字比對）。

### Phase 3 — `index.html` 改打 `/generate`（live，不用 restart）

- 刪除：`SYSTEM_PROMPT`、`loadSystemPrompt()`、`EXAMPLES`、`loadExamples()`、`buildUserPrompt()`、`buildSchema()`。
- `streamQuery()` 改成 POST `{ model, scenario, mechanism, lever, action, difficulty, context, options? }` 到 `/generate`。
- **保留**：`MECH_RULES`、`SCENARIO_LABELS`、dropdown 資料——改成 fetch `classification.json` 取得，因為卡片渲染跟隨機按鈕仍然需要。
- SSE 解析（`stripJsonFence`/`classifyParseFailure`/串流讀取迴圈）不變。
- `count > 1` 的逐封 sequential 生成、單封獨立重試邏輯不變——`count` 從來沒送到後端，`/generate` 維持「一次一封」，前端照舊呼叫 N 次。
- 更新 `__selfTest()`：移除針對已刪函式的斷言（例如 `buildSchema().required.length === 14`），`MECH_RULES` 相關斷言保留。
- `index.html` 是 live 直接讀檔，改完立刻可以 end-to-end 驗證；此時 `/query` 仍在，出問題可以直接改回舊呼叫應急。
- Dependencies：Phase 2 已 restart 上線。
- Risk：Medium。

### Phase 4 — 刪除 `/query`（真正達成目標的一步）

確認 `index.html` 全面走 `/generate` 且驗證通過後，把 `/query` 路由整條刪掉、restart。**繞過管道到此才真正關閉**——前面三個 Phase 都只是鋪墊，這步才是本次重構唯一實質達成安全目標的動作，且可回滾（重新加回即恢復）。

可選一併清理：移除 `GET /system-prompt`、`GET /examples`（前端不再需要，後端已直接讀檔）。這兩個是唯讀 GET，本身無害，只是減少攻擊面；風險是若有外部書籤/工具打到會變 404。

- Dependencies：Phase 3 端到端驗證通過。需要 restart。
- Risk：Low–Medium。

### Phase 5 — 文件與測試

- 更新 `README.md:40`、`CLAUDE.md`、`task.md` §3.1 裡對 `/query`/`/system-prompt`/`/examples` 的敘述，改指向 `/generate`。
- 補一支最小 `pytest`（目前全 repo 沒有測試框架，這是第一支）：
  - 非法 `scenario`/`mechanism`/`lever`/`action`/`difficulty` 回 422
  - schema 帶 `red_flags.minItems === 1`
  - 依 `delivery_mechanism` 挑選範例的邏輯正確
  - `messages`/`format` 由 server 端組出、client 傳進來的同名欄位（如果有）不會被採用

---

## 4. Risks 總表

| 風險 | 等級 | 說明 / 緩解 |
|---|---|---|
| Prompt/Schema 保真度漂移 | **High** | JS→Python 逐字移植稍有出入，生成結果會偏離現行行為且不易察覺。以現行 `index.html` 產物為基準逐字比對，補 Phase 5 測試對照輸出。 |
| 忘記做 Phase 4 | **High** | 沒刪 `/query` 等於整個重構沒有實質效果。獨立成最後一個可追蹤的階段，完成後 `grep` 確認無 `/query` 路由殘留。 |
| Restart / 部署時間差 | Medium | `index.html` live、`main.py` 需 restart。目前的 Phase 排序（先加 `/generate` 保留 `/query` → 改前端 live 驗證 → 最後才刪 `/query`）刻意消除破窗，全程有可用 fallback。 |
| `options` 仍是自由 dict | Medium | 不能繞過內容 guardrails（schema/system prompt 已 server 端組裝），但可送誇張 `num_predict` 造成資源濫用。白名單只認 `num_predict` 並夾上限。 |
| `classification.json` 新增失敗面 | Medium | 檔案缺失/格式錯誤會讓 import 期無法建模型/驗證。Import 時載入、fail fast、錯誤訊息明確。 |
| Pydantic enum 值域來自 runtime JSON | Medium | 無法用 static `Literal`。改用 `field_validator` 對照載入的 key 集合，或動態 `Enum` 欄位型別。 |
| 422 在 UI 顯示為「連線失敗」 | Low | `streamQuery` 把非 2xx 一律當 `connection` 錯誤。正常操作下不會觸發 422，只有竄改/邊界情況才會遇到，對威脅模型無妨。 |
| `__selfTest()` 斷言失聯 | Low | 刪 `buildSchema()` 後相關斷言會壞，Phase 3 一併更新。 |
| 移除 `/system-prompt`/`/examples` 造成外部 404 | Low | 只有 `index.html` 用過，影響面極小。 |
| 既有 stream 中 `raise HTTPException` 行為 | Low | `main.py:305-309` 在 headers 已送出後 raise 只會斷流、非乾淨 500，是既有行為；移植進 helper 時原樣保留，不順手修。 |

---

## 5. Estimated Complexity

整體 **Medium**。

- `main.py`：新增約 60–90 行（`GenerateRequest` + Python 版 `build_schema`/`build_user_prompt` + streaming helper + `/generate`），Phase 4 再淨刪 `/query`（及可選的兩個 GET）。
- `index.html`：淨簡化（刪 `buildSchema`/`buildUserPrompt`/`SYSTEM_PROMPT`/`EXAMPLES` 及其 loader 約 -80 行；新增 `classification.json` fetch 與少量渲染改接）。
- `classification.json`：一次性資料抽取。
- 主要風險與工時集中在 **Phase 2 的逐字移植**跟 **Phase 5 的驗證測試**，不在行數多寡。

---

## 6. 涉及檔案

- `api/main.py`：`/query`（`:281-320`，最終刪除）、`/system-prompt`（`:232-237`，可選刪除）、`/examples`（`:242-247`，可選刪除）、新增 `/generate`
- `api/index.html`：分類常數（`:94-179`，搬出）、`buildSchema`/`buildUserPrompt`（`:280-357`，刪除）、`streamQuery`（`:374-424`，改呼叫方式）、`retryCard`/count 迴圈（`:552-607`，不變）、`__selfTest`（`:615-623`，更新斷言）
- `api/system_prompt.md`、`api/examples.json`：改由後端直接讀取，用途不變
- 新增：`api/classification.json`
- 待更新文件：`README.md:40`、`CLAUDE.md`、`task.md` §3.1
