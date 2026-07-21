# Plan — LLM 輸出用 OpenCC 轉繁體中文

> 目的：`/generate` 的 system prompt 已要求「繁體中文演練釣魚信」，但 LLM 本身沒有語言保證，模型仍可能吐出簡體字。用 [OpenCC](https://github.com/byvoid/opencc)（官方 PyPI 套件 `opencc`）在後端做保底轉換。

---

## 0. Context

- `build_user_prompt()`（[main.py:497](api/main.py#L497)）已在 `<task>` 明確要求繁體中文，但這只是 prompt-level 的期望，不是保證——模型（尤其非中文優化的 `llama`/`mistral`/`gemma3`/`phi` 等 `LLM_FAMILIES`）仍可能輸出簡體。
- 範圍限定在 **LLM 輸出**（`/generate`）。`/ingest` OCR 走 RapidOCR，不是 LLM，不在範圍內。
- 前端 `streamQuery()`（[index.html:207-223](api/index.html#L207-L223)）只是把每個 SSE chunk 的 `content` 累加成字串，最後才整體 `JSON.parse`——不管後端是逐行轉還是整段轉，前端拿到的結果都一樣，不需要改前端。

## 1. 現況資料流

```
POST /generate
  → build_schema() + build_user_prompt(req)（main.py，已要求輸出繁體中文）
  → stream_ollama_chat(payload)
      → event_generator(): async for line in response.aiter_lines(): yield f"data: {line}\n\n"
  → index.html: 逐行 JSON.parse，累加 content，最後整體 parse
```

`line` 是「SSE envelope 包 guided-JSON schema 字串」的巢狀結構，但 JSON 語法字元（`{`、`"`、`,`）跟英文 key（`content`/`message`...）都不是漢字——OpenCC 只認辭典裡的簡體字，直接對整行做轉換是安全的，已是繁體或非中文的部分等於 no-op。

## 2. 目標架構

```
event_generator() 逐行轉換後才 yield：
  yield f"data: {TRADITIONAL_CONVERTER.convert(line)}\n\n"
```

**轉換時機選逐行、不選整段收完再轉**：
- 保留原本的串流打字效果；整段轉需要先 buffer 完再一次吐出，前端會看起來卡住。
- 代價：OpenCC 片語辭典（如「鼠标」→「滑鼠」需要一次看到完整詞）若詞被切在兩個 chunk 邊界，會退化成單字對應（「鼠標」而非「滑鼠」）。字元層級一定正確，只是少數詞彙不是最道地的台灣用字，可接受。

**設定檔選 `s2twp.json`**（簡體 → 台灣正體＋台灣常用詞彙），對齊專案的台灣繁中脈絡，比 `s2t.json`（純繁體、無地區用詞轉換）更貼近實際需求。

## 3. Implementation Phases

### Phase 1 — 加入依賴

`api/requirements.txt` 新增一行 `opencc`（現有套件皆未 pin 版本，跟隨風格）。

- Risk：Low。Docker image 有 `build-essential`，就算沒有現成 wheel 也能編譯；官方文件稱 Linux x64/arm64 皆有 prebuilt wheel，正常應直接裝起來。

### Phase 2 — 後端轉換

`api/main.py`：
1. `import opencc`
2. 模組層級新增 `TRADITIONAL_CONVERTER = opencc.OpenCC("s2twp.json")`（import 時初始化、fail fast，跟現有 `ENGINE = RapidOCR()` 同模式）
3. `event_generator()` 內把 `yield f"data: {line}\n\n"` 改成 `yield f"data: {TRADITIONAL_CONVERTER.convert(line)}\n\n"`

- Dependencies：Phase 1。需要 restart container 生效（`main.py` 是 import 一次的模組，不像 `index.html` live 讀檔）。
- Risk：Low。純字串轉換，不改變 JSON 結構、不影響現有的 thinking 能力檢查或 SSE forwarding 邏輯。

### Phase 3 — 測試

`api/test_main.py` 加一個一行斷言的測試，驗證 `main.TRADITIONAL_CONVERTER.convert("简体字")` 轉出繁體。不用 mock httpx 串流——轉換邏輯本身是可獨立測的純函式呼叫，不需要牽動 SSE plumbing。

- Dependencies：Phase 2。
- Risk：Low。

---

## 4. Risks 總表

| 風險 | 等級 | 說明 / 緩解 |
|---|---|---|
| 片語辭典被 chunk 邊界切斷 | Low | 退化成單字對應，字元層級仍正確，只是用字不是最道地的台灣詞彙。 |
| `opencc` 套件在 Docker 內編譯失敗 | Low | image 已有 `build-essential`；官方套件本身也提供 Linux x64/arm64 prebuilt wheel。 |
| `main.py` 需要 restart 才生效 | Low | 既有已知行為（README 已載明），非本次新增風險。 |

## 5. Estimated Complexity

**Low**。2 個檔案改動（`requirements.txt` + `main.py`）+ 1 個測試，不動前端。
