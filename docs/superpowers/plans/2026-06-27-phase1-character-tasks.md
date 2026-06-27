# Phase 1 主播形象加工 — 详细任务清单

- 日期：2026-06-27
- 依赖 spec：`docs/superpowers/specs/2026-06-27-ai-tuanbo-canvas-design.md`（§7 阶段一、§9 API、§12 Phase 1）
- 目标：接入 gpt-image-2 真实调用，实现阶段一"主播形象加工"——参考图 + 发型/妆容/服装 → 背透 PNG，替换 Phase 0 的 mock。通过 6 条验收。
- 构建顺序：自底向上 config → gpt_image client → orchestrator → main → index.html → 验收

## 对 spec 的一处微调（需知会）

**spec §11 写"pillow 留到 Phase 2"，但 Phase 1 必须提前引入 pillow。**

原因：gpt-image-2 的 `images.edit` 接口传参考图时，**若参考图是 RGBA 透明 PNG 会报错**（OpenAI 已确认的行为）。运营上传的主播原图可能是带 alpha 的 PNG，必须先用 pillow 预处理成 RGB 白底再传给 API。因此 pillow 从 Phase 2 提前到 Phase 1。不影响架构，只是依赖前移。

## gpt-image-2 API 关键事实（已通过官方文档核实）

| 项 | 值 / 说明 |
|---|---|
| 端点 | `POST /v1/images/edits`（传参考图走 edit 接口，非 generations） |
| 认证 | `Authorization: Bearer $KEY`，第三方中转只改 `base_url`，其余 OpenAI 兼容 |
| 参考图 | `image` 参数，file-like，最多 10 张；**RGBA 会报错，需预处理成 RGB** |
| 响应 | 默认 `b64_json`（URL 仅 1 小时过期）→ 解码后存 storage |
| 透明背景 | `background="transparent"` → 输出带 alpha 的 PNG（正是阶段一要的背透） |
| 锁五官 | `thinking="medium"`（off/low/medium/high，high 太慢，medium 平衡） |
| 成本/速度生死线 | `quality` + `size`：`high`+大 size 可慢到 200 秒；`medium`+`1024x1024` 约 15-40 秒 |
| HTTP timeout | 必须 ≥ 360 秒（thinking + high 会很久） |
| SDK | `openai>=1.50.0` 原生支持 gpt-image-2；用 `AsyncOpenAI` |

## T0 — 配置与依赖

- [ ] `requirements.txt` 追加：`openai>=1.50.0`、`pillow`、`python-dotenv`
- [ ] 新建 `config.py`：从环境变量读配置，`python-dotenv` 加载 `.env`
  ```python
  import os
  from dotenv import load_dotenv
  load_dotenv()

  OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
  OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")  # 第三方中转改这里
  GPT_IMAGE_MODEL = os.getenv("GPT_IMAGE_MODEL", "gpt-image-2")
  GPT_IMAGE_QUALITY = os.getenv("GPT_IMAGE_QUALITY", "medium")   # low/medium/high/auto
  GPT_IMAGE_THINKING = os.getenv("GPT_IMAGE_THINKING", "medium") # off/low/medium/high
  GPT_IMAGE_SIZE = os.getenv("GPT_IMAGE_SIZE", "1024x1024")
  GPT_IMAGE_TIMEOUT = float(os.getenv("GPT_IMAGE_TIMEOUT", "360"))
  ```
- [ ] `.gitignore` 追加 `.env`（防密钥泄漏）
- [ ] 新建 `.env.example`（入库模板，不含真实密钥）：
  ```
  OPENAI_API_KEY=sk-your-key-here
  OPENAI_BASE_URL=https://api.openai.com/v1
  GPT_IMAGE_MODEL=gpt-image-2
  GPT_IMAGE_QUALITY=medium
  GPT_IMAGE_THINKING=medium
  GPT_IMAGE_SIZE=1024x1024
  GPT_IMAGE_TIMEOUT=360
  ```
- [ ] 用户需自行创建 `.env` 填真实 key 与中转 base_url（不入库）

## T1 — clients/gpt_image.py：gpt-image-2 适配层

> **实现调整（基于中转文档核实）**：改用 httpx 直接调 multipart（非 openai SDK），model 用 `gpt-image-2-all`，base_url=`https://llm-api.net/v1`；`_ensure_rgb` 强制先 `convert("RGBA")` 免疫 P/LA 模式（采纳边界防御微调）；中转文档未列 `thinking` 参数，默认不传。

- [ ] **httpx 直接调** `POST {base_url}/images/edits`（multipart），`base_url`/`api_key`/`timeout` 从 config 读
- [ ] `async def generate_character(reference_image_bytes: bytes, hair: str, makeup: str, clothing: str) -> bytes`
  - 返回值：背透 PNG 的 bytes（已 base64 解码，可直接 `storage.save`）
- [ ] 内部流程：
  1. `_ensure_rgb(reference_image_bytes)` — pillow 预处理：RGBA→RGB 白底合成，非 RGB 也转 RGB
  2. 拼装 prompt（模板见下）
  3. `await client.images.edit(model=..., image=BytesIO(rgb_bytes), prompt=..., size=..., quality=..., thinking=..., background="transparent", response_format="b64_json")`
  4. 取 `resp.data[0].b64_json` → `base64.b64decode` → 返回 bytes
- [ ] `_ensure_rgb(image_bytes) -> bytes` 辅助函数：
  ```python
  from PIL import Image
  from io import BytesIO

  def _ensure_rgb(image_bytes: bytes) -> bytes:
      img = Image.open(BytesIO(image_bytes))
      if img.mode == "RGBA":
          bg = Image.new("RGB", img.size, (255, 255, 255))
          bg.paste(img, mask=img.split()[3])
          img = bg
      elif img.mode != "RGB":
          img = img.convert("RGB")
      out = BytesIO()
      img.save(out, format="PNG")
      return out.getvalue()
  ```
- [ ] prompt 模板（中文，gpt-image-2 原生支持 CJK）：
  ```
  保持人物五官与参考图完全一致（必须是同一个人）。
  换装要求：发型={hair}，妆容={makeup}，服装={clothing}。
  半身/全身站立姿态，自然光线，质感细腻。
  纯透明背景（用于后续海报合成）。
  高质量，画面中不要出现任何文字与水印。
  ```
- [ ] 错误处理：捕获 `openai.APIError` 等，抛出带原始 message 的 `RuntimeError`，让 orchestrator 记到 `task.error`
- [ ] 自测：`generate_character(open("test.jpg","rb").read(), "短发", "淡妆", "白衬衫")` 返回合法 PNG bytes

## T2 — orchestrator.py：加 execute_character

- [ ] `async def execute_character(task_id: str, params: dict) -> None`
  - params 字段：`{ reference_image_url, hair, makeup, clothing }`
- [ ] 流程（节点式推进 progress，API 调用期间会有一段停滞属正常）：
  1. `registry.update(task_id, progress=5)` — 开始
  2. `ref_bytes = await storage.download(params["reference_image_url"])` — 拉参考图
     - `registry.update(task_id, progress=15)`
  3. `png_bytes = await gpt_image.generate_character(ref_bytes, hair, makeup, clothing)` — 调 API（耗时大头，15-200s）
     - 调用前 `registry.update(task_id, progress=25)`，调用期间不再推进（真实）
  4. `url = await storage.save(png_bytes, "png")` — 落盘
     - `registry.update(task_id, progress=90)`
  5. 更新 `assets.character_png = url`（复用 execute_mock 第 102-107 行的 assets 更新模式）
     - `registry.update(task_id, progress=100)`
  - 注：`_run` 在 executor 返回后自动设 `status="success"`，executor 内不设 success
- [ ] 注册：`_STAGE_EXECUTORS["character"] = execute_character`
- [ ] 保留 `_STAGE_EXECUTORS["mock"]`（回归测试用，不删）

## T3 — main.py：加阶段一路由

- [ ] Pydantic 模型：
  ```python
  class CharacterRunRequest(BaseModel):
      workflow_id: str
      reference_image_url: str
      hair: str
      makeup: str
      clothing: str
  ```
- [ ] 路由 `POST /api/stages/character/run`：
  ```python
  @app.post("/api/stages/character/run")
  async def character_run(req: CharacterRunRequest):
      task_id = orchestrator.create_task(req.workflow_id, "character", {
          "reference_image_url": req.reference_image_url,
          "hair": req.hair,
          "makeup": req.makeup,
          "clothing": req.clothing,
      })
      return {"task_id": task_id}
  ```
- [ ] `app.title` 改为 `"AI 团播资产画布 — Phase 1"`

## T4 — index.html：卡片加阶段一交互

- [ ] 每张卡片增加「形象加工」区块（在 mock 按钮上方或下方，mock 保留折叠）：
  - 上传主播原图：`<input type="file" accept="image/*">` → 调 `/api/assets/upload` → 存 `wf.reference_image_url`
  - 三个文本输入：发型 / 妆容 / 服装（`<input type="text">`）
  - 「运行形象加工」按钮 → 调 `runCharacter(wfId)`
- [ ] `runCharacter(wfId)`：POST `/api/stages/character/run` body `{workflow_id, reference_image_url, hair, makeup, clothing}` → 存 `wf.character_tid` → `pollTask(wfId, tid, "character")`
- [ ] `pollTask` 复用现有轮询逻辑（每 1500ms GET 状态），success/failed 时 `clearInterval`
- [ ] 成功后卡片显示 `character_png` 缩略图（`<img>` + 点击可放大/新窗打开）
- [ ] 失败时卡片显示 `error` 文本（红色）
- [ ] 进度条区分阶段：mock 用灰色，character 用主题色（视觉区分阶段）

## T5 — 验收（6 条）

- [ ] 验收1（配置）：`.env` 填好 key + 中转 base_url，`uvicorn main:app --reload --port 8000` 正常启动无报错
- [ ] 验收2（真实生图）：上传一张主播原图 → 填发型/妆容/服装 → 点「运行形象加工」→ 任务 pending→running→success，progress 在 25% 处会停留一段（API 生成中，正常）
- [ ] 验收3（背透产出）：成功后 `character_png` URL 在浏览器打开，是**带透明背景的人物 PNG**（棋盘格背景可见），人物五官与参考图一致（thinking 锁五官生效）
- [ ] 验收4（并发闸）：同时触发 3 张阶段一，最多 3 running；第 4 张 pending，前 3 个完成一个放行一个
- [ ] 验收5（错误反馈）：故意填错 key → 卡片显示 `failed` + error 文本（如 401/invalid api key），不影响其他卡片
- [ ] 验收6（回归未破坏）：mock 阶段仍可运行，5 条 Phase 0 验收不退化

## 依赖关系

T0（config + 依赖）→ T1（gpt_image client 依赖 config）→ T2（orchestrator 依赖 gpt_image + storage）→ T3（main 依赖 orchestrator）→ T4（前端依赖 T3 接口）→ T5

## 不在 Phase 1 做

- Fabric.js 画布实际功能（Phase 2）
- 阶段二海报拼装（Phase 2）
- clients/auth.py、clients/seedance.py（Phase 3）
- 视频生成（Phase 3）
- 「应用到画布」按钮的真实功能（Phase 2 接入，Phase 1 仅占位）

## 成本提示

- 默认 `quality=medium` + `size=1024x1024` + `thinking=medium`，单张约 15-40 秒、成本可控
- 若改 `quality=high` + `thinking=high`，单张可慢至 200 秒、成本 4-5×，谨慎
- 并发闸 `Semaphore(3)` 仍生效，最多 3 张同时调用，防账单失控
