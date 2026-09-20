# 个人嵌入式研发知识与故障排查助手

这是一个单用户、本地运行的嵌入式研发资料助手 MVP。它把 Markdown、TXT、文本型 PDF、C/H 文件和日志导入本地索引，通过确定性 Mock Embedding + SQLite 向量索引 + BM25 混合检索返回带引用的回答；没有证据时明确拒答。

它还提供一个受控的故障排查 Agent：最多四步，只能调用知识检索、日志搜索、清单生成和确认后的笔记保存工具。没有用户确认时，Agent 不会写笔记。

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
