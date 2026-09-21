# 个人嵌入式研发知识与故障排查助手

这是一个单用户、本地运行的嵌入式研发资料助手 MVP。它把 Markdown、TXT、文本型 PDF、C/H 文件和日志导入本地索引，通过确定性 Mock Embedding + SQLite 向量索引 + BM25 混合检索返回带引用的回答；没有证据时明确拒答。

它还提供一个受控的故障排查 Agent：最多四步，只能调用知识检索、日志搜索、清单生成和确认后的笔记保存工具。没有用户确认时，Agent 不会写笔记。

## 面向 AI 应用研发岗位的项目定位

这个项目按照 AI 应用研发岗位常见的能力要求设计：不止完成一个聊天界面，而是把后端服务、大模型接口、Prompt/Context Engineering、RAG、Tool Calling、Agent 工作流、权限控制、日志观测、成本边界和离线评测串成一个可运行的闭环。

图片中的岗位要求与本项目的对应关系如下：

| 岗位要求 | 项目中的实际落地 | 当前验证边界 |
|---|---|---|
| Python 后端开发，理解 TS/Node.js 服务形态 | 使用 FastAPI、Pydantic、SQLite 和服务组合根实现导入、检索、Agent、会话和 trace API | 本仓库主要使用 Python；没有把未实现的 TS/Node.js 代码包装成已掌握证据 |
| 大模型 API、Prompt 和 Context Engineering | 抽象 LLM/Embedding provider；支持 OpenAI-compatible 协议；将聊天历史、检索上下文和结构化证据分开，并要求回答保留引用 | Mock LLM 和本地 fake transport 已验证；真实远程模型质量未验证 |
| RAG 全流程 | 完成资料导入、Markdown/TXT/PDF/C/H/日志解析、脱敏、切片、Embedding、SQLite 向量索引、BM25、混合重排、证据门控、引用和拒答 | Mock Embedding 已验证；真实 Embedding 语义效果仍未验证 |
| Tool Calling 与 Agent 工作流 | Agent 只允许 `search_knowledge`、`search_log`、`generate_checklist`、`save_note` 四类工具，最多四步；日志结果转换为带行号和引用 ID 的结构化证据 | 工具调用在本地合成日志上验证；不等同于生产级多 Agent 或高并发调度 |
| Agent/RAG 与模型服务封装 | `app/runtime.py` 统一组装 provider、索引、检索、回答、会话和 Agent；API 与 Streamlit 共用业务服务 | 已验证本地 Mock 和协议边界；未验证真实外部服务稳定性 |
| 权限、日志和安全边界 | 路径、扩展名、文件大小、工具白名单、确认保存、远程双重授权、敏感字段脱敏、trace ID 和 JSONL 结构化日志 | 已验证本地安全策略；尚未进行生产身份认证、多租户或合规审计 |
| 成本控制与运行可观测性 | 默认关闭远程模型；远程调用需要全局开关和单次授权；记录 provider/model、延迟、评测结果和失败阶段，避免默认把资料发送到外部 | 当前没有真实账单、Token 计费和线上预算告警；成本控制处于应用边界级别 |
| AI 工程化落地与持续迭代 | 使用规格、架构、任务清单、锁定依赖、可复现评测、失败题分析和 Git 提交保存演进过程；测试器输出分子、分母和失败题号 | 当前定位是本地单用户 MVP，不宣称已经完成生产部署和线上 SLA |
| 智能助手/内部提效工具经验 | 面向嵌入式研发资料和故障日志，支持知识问答、串口日志分析、排查清单生成和确认后笔记沉淀 | 使用脱敏合成资料和本地资料开发集验证，真实团队数据效果需单独验收 |

### 核心数据流

```text
资料/日志
   │
   ├─ 路径与大小校验 → 解析与脱敏 → 切片与 fingerprint
   │                                  │
   │                         Mock/可替换 Embedding
   │                                  │
   └────────────────────── SQLite 向量索引 + BM25
                                      │
                              混合检索与证据门控
                                      │
                         LLM 回答 + 引用 / 安全拒答

用户故障目标 → Agent 计划 → 知识/日志工具 → 结构化证据
                                      │
                              排查清单与最终回答
                                      │
                         用户确认后才保存笔记
```

### 这个项目体现的工程能力

- 能把岗位需求拆成可验证的服务边界，而不是只依赖模型“自由发挥”：检索结果、日志行、清单步骤和笔记内容都有结构化来源。
- 能处理模型应用中的失败路径：证据不足时拒答，远程处理未授权时拒绝，工具失败时保留已成功结果，写笔记时使用确认和幂等保护。
- 能把安全与工程质量前置到数据流：导入前检查文件，索引变化时按 provider/model/维度/解析器/切片参数重建，日志和 API 错误带 trace 但不泄露密钥或正文。
- 能用评测和回归测试定位问题：默认22题离线评测、24题资料开发集、8题留出题、47项自动化测试，以及逐题失败分类，区分解析、切片、检索、排序、生成、拒答和评分问题。

### 可用于简历或面试的项目概述

> 设计并实现一个面向嵌入式研发资料与串口日志的本地 AI 助手，使用 Python/FastAPI 构建统一服务层，通过可替换的 LLM/Embedding provider、SQLite 向量索引、BM25 混合检索和证据门控实现带引用问答；进一步实现受控 Tool Calling Agent，完成知识检索、日志分析、排查清单和确认保存笔记的闭环。项目重点覆盖 Prompt/Context Engineering、RAG 全流程、Agent 工具边界、权限与脱敏、trace 日志、增量索引和离线评测，并明确区分 Mock 验证与真实模型、生产部署之间的边界。

这段描述对应的是当前仓库中已经存在的代码、测试和文档；真实 Embedding 质量、真实 MiMo 回答质量、生产并发、硬件串口和云端 E2E 仍需独立验证，详细审计见 [`eval/EMBEDDING_AUDIT.md`](eval/EMBEDDING_AUDIT.md)。

## 目录

```text
app/                  后端、RAG、Agent、存储和 Streamlit
data/inbox/           待导入资料（本地运行数据，不提交）
data/index/           索引运行数据（不提交）
data/logs/            允许搜索的日志目录（不提交）
data/notes/           用户确认后写入的笔记（不提交）
eval/                 默认22题评测、24题开发集和评测工具
tests/                单元、集成和合成 fixture
docs/                 规格、架构和演示脚本
tasks/                实施计划和任务清单
```

## 安装（Windows PowerShell）

在项目根目录 `E:\\codex_project\\AI\\personal-dev-assistant` 执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

当前 Codex 工作区没有全局 `python` 命令时，使用工作区 Python 3.12 创建虚拟环境：

```powershell
& 'C:\Users\19175\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv .venv
```

后续命令仍使用 `.venv\\Scripts\\python.exe`，不修改系统 Python。

## 测试和离线评测

```powershell
.\.venv\Scripts\Activate.ps1
pytest -q
python -m eval.run_eval
python -m pip check
```

评测只复制 `tests/fixtures` 中的合成资料到临时目录，使用 Mock provider，报告写入被 Git 忽略的 `data/eval_report.json`。当前包含 22 题：13 个有答案问题、4 个拒答问题和 5 个 Agent/日志任务；`expected_terms` 会独立检查答案支持度。它不是线上效果，也不是真实模型效果。

根据本地教程资料整理的脱敏合成测试集位于 `tests/fixtures/generated_materials`，对应问题集为 `eval/user_materials_questions.jsonl`，共24题。这是独立开发集，不替代默认22题评测，也不代表真实资料或线上效果。它覆盖 STM32/MPU6050、ESP32-C3、DHT11/机智云、Python 爬虫、Python 基础和 SQL/JSON 数据。使用下面命令运行；命令结束后可以清除三个环境变量。

```powershell
$env:PDA_EVAL_QUESTIONS_PATH = (Resolve-Path .\eval\user_materials_questions.jsonl).Path
$env:PDA_EVAL_FIXTURE_DIR = (Resolve-Path .\tests\fixtures\generated_materials).Path
$env:PDA_EVAL_REPORT_PATH = (Join-Path $env:TEMP 'personal-dev-assistant-user-materials.json')
python -m eval.run_eval
```

报告中的 `metric_details` 保存每项指标的分子、分母和失败题号。该资料评测用于暴露 Mock Embedding 的召回边界，不把结果当作真实模型质量；当前合成集的低分题应在接入真实 Embedding 后重新比较。

也可以使用已验证的锁文件重建环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
```

如需将评测报告写到当前环境允许的目录，可设置 `PDA_EVAL_REPORT_PATH`；默认仍写入被 Git 忽略的 `data/eval_report.json`。

## 启动后端

```powershell
uvicorn app.api:app --reload --port 8000
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

把待导入资料放到 `data/inbox` 后，可以调用：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/documents/ingest `
  -ContentType 'application/json' `
  -Body '{"source_path":"uart.md","project_id":"default","allow_external_processing":false}'

Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/documents/scan `
  -ContentType 'application/json' `
  -Body '{"project_id":"default","recursive":true}'

Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/rag/query `
  -ContentType 'application/json' `
  -Body '{"question":"PA9 在 UART 中承担什么角色？","project_id":"default"}'
```

路径只能指向配置允许的 `data/inbox` 或 `data/logs`，不接受路径穿越；相同文件哈希且 provider/model/维度/切片 fingerprint 相同时才会返回 `unchanged`。远程模型还需要全局 `PDA_ALLOW_REMOTE_MODELS=true` 和请求中的 `allow_external_processing=true` 双重授权。

## 启动界面

```powershell
streamlit run app/ui.py --server.port 8501
```

界面支持资料上传、知识库查询、引用展示、Agent 计划和“确认保存/不保存”分支。上传保存使用独占创建，不会覆盖同名文件。

## API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 查看服务和 provider 模式 |
| POST | `/v1/documents/ingest` | 导入允许目录中的单个文件 |
| POST | `/v1/documents/scan` | 递归扫描 `data/inbox` 并增量导入 |
| POST | `/v1/rag/query` | 混合检索、证据门控和引用回答 |
| POST | `/v1/agent/run` | 运行最多四步的排查计划 |
| POST | `/v1/agent/confirm` | 确认或拒绝保存笔记 |
| GET | `/v1/sessions/{session_id}` | 查看 Agent 状态和短期结果 |
| GET | `/v1/traces/{trace_id}` | 查看结构化 trace 事件 |

## Provider 和验证边界

- 已验证：SQLite schema 迁移、索引 fingerprint、确定性 Mock Embedding、Mock LLM、BM25、0.7/0.3 基础重排、证据门控、引用、拒答、目录扫描、项目隔离上下文、Agent 白名单、日志证据、日志脱敏、确认保存、稳定错误、trace、默认22题离线评测和24题资料开发集评测。
- 已实现并用本地假传输验证协议边界、但未验证真实效果：OpenAI-compatible LLM provider 和 Embedding provider 接口。默认不启用，也没有发送真实资料或真实密钥。
- MiMo 按量 API 的合成资料验证脚本：`python -m eval.verify_mimo`；完整本地 pipeline 验证：`python -m eval.verify_mimo_pipeline`。这两个命令会读取本机 `.env`，不会打印 API Key；只应使用合成资料。
- 未验证：真实 embedding 语义质量、真实模型回答质量、外部服务费用/网络稳定性、生产并发、真实硬件、串口、烧录和云端 E2E。

不要把 `.env`、API Key、密码、证书、真实日志、真实项目源码或模型文件放入仓库。知识库文档中的命令只作为数据展示，Agent 不会执行它们。

## 进一步说明

- 完整范围与验收标准见 [`docs/spec.md`](docs/spec.md)。
- 组件边界与数据流见 [`docs/architecture.md`](docs/architecture.md)。
- 可复制演示流程见 [`docs/demo-script.md`](docs/demo-script.md)。
- 当前增量进度见 [`tasks/todo.md`](tasks/todo.md)。
