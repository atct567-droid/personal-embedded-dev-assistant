# Spec: 个人嵌入式研发知识与故障排查助手

## Objective

本项目是一个单用户、本地运行的嵌入式研发知识与故障排查助手，项目根目录为
`E:\\codex_project\\AI\\personal-dev-assistant`。它面向需要整理协议说明、驱动代码、编译日志和串口日志的嵌入式开发者，提供两条可离线验证的路径：

1. 完整 RAG 知识库：导入 Markdown、TXT、文本型 PDF 以及经过筛选的 C/H、编译日志和串口日志，完成解析、清洗、切片、Embedding、向量检索、BM25、混合重排、带引用回答和离线评测。
2. 轻量故障排查 Agent：基于最多四步的受控计划调用知识检索、日志搜索、清单生成，并在用户明确确认后才保存笔记。

成功标准不是“回答看起来合理”，而是每个结论都能追溯到检索证据；证据不足时必须返回“现有资料不足以确定”，并且所有写操作、路径访问和工具调用都受到显式策略约束。

## Assumptions

- 这是本地单用户工具，不实现账号、云端高可用或多租户隔离。
- 当前工作区已有用户授权，可在项目根目录创建源代码、测试、合成演示资料和被 `.gitignore` 忽略的运行数据。
- 默认测试不访问网络、不调用真实模型、不连接硬件、不烧录设备。
- Python 3.12 是目标版本；当前 Codex 工作区若没有全局 `python` 命令，使用工作区提供的 Python 3.12 可执行文件验证。
- 真实 LLM、真实 Embedding 和 Chroma 属于可替换适配层，不作为离线 MVP 测试的前置条件。MVP 默认使用确定性 Mock Embedding、Mock LLM 和 SQLite 持久化向量索引，以保证可复现。
- 远程模型默认关闭；只有全局 `PDA_ALLOW_REMOTE_MODELS=true` 与每次请求的 `allow_external_processing=true` 同时满足时，明确允许外发的证据才可发送。
- `tests/fixtures` 中只放合成、不敏感的演示资料；真实个人资料、模型文件、日志、数据库和密钥不得提交。

## Tech Stack

- Python 3.12
- FastAPI + Pydantic：HTTP API 和输入/输出契约
- Uvicorn：本地 API 服务
- Streamlit：简单本地界面
- PyMuPDF：文本型 PDF 解析；缺少依赖时返回明确的依赖错误
- SQLite：文档元数据、切片、向量、会话和 trace 的本地持久化
- Python 标准库：确定性 Mock Embedding、BM25、路径边界检查、日志脱敏和安全文件写入
- 可选真实模型：OpenAI-compatible HTTP provider；只从环境变量读取配置，不打印或持久化密钥
- 依赖复现：`requirements.lock` 固定当前已验证的直接和传递依赖版本
- LangChain、Chroma、CrossEncoder 不作为核心业务依赖；如以后接入，只能通过现有接口适配并单独验证，不得隐藏核心业务逻辑

## Commands

在已安装 Python 3.12 的 Windows PowerShell 中：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest -q
uvicorn app.api:app --reload --port 8000
streamlit run app/ui.py --server.port 8501
python -m eval.run_eval
```

当前 Codex 工作区若没有全局 `python`，可以用工作区解释器替代第一行及后续命令的 `python`：

```powershell
& 'C:\Users\19175\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv .venv
```

命令只有在最终环境中实际验证后，才能在交付报告中标为“已验证”。

## Project Structure

```text
app/
├─ api.py                 # FastAPI 应用和稳定错误响应
├─ config.py              # 环境变量、目录和大小限制
├─ runtime.py             # 服务组合根，统一创建依赖
├─ ui.py                  # Streamlit 本地界面
├─ domain/
│  ├─ models.py           # Pydantic 请求、响应和领域模型
│  └─ errors.py           # 可公开的稳定错误结构
├─ llm/
│  ├─ gateway.py          # 模型接口和回答编排
│  └─ providers.py        # Mock 与 OpenAI-compatible provider
├─ embeddings/
│  ├─ gateway.py          # Embedding 接口
│  └─ providers.py        # 确定性 Mock 与可选真实 provider
├─ rag/
│  ├─ parser.py           # Markdown/TXT/PDF/C/H/日志解析和脱敏
│  ├─ chunker.py          # 保留页码、标题和重叠的切片
│  ├─ indexer.py          # 哈希增量导入和 SQLite 向量索引
│  ├─ retriever.py        # 向量、BM25 和混合检索
│  ├─ reranker.py         # 可解释的加权基础重排
│  └─ answer.py           # 证据门控、引用和拒答
├─ agent/
│  ├─ state.py            # Agent 状态和计划
│  ├─ workflow.py         # 最多四步的受控工作流
│  ├─ policy.py           # 工具白名单、重试和步数策略
│  └─ tools.py            # 四个允许工具
└─ storage/
   ├─ metadata.py         # 文档、切片和索引的 SQLite 存储
   └─ sessions.py         # 会话、短期上下文和 trace
```

## Data Contracts

每个切片至少包含：

```text
chunk_id, project_id, source_file, relative_path, document_type,
page_number, section_title, chunk_index, content, file_hash, updated_at
```

RAG 响应包含：

```json
{
  "answer": "回答正文",
  "confidence": "high|medium|low",
  "citations": [
    {
      "source_file": "example.md",
      "section": "UART初始化",
      "page": null,
      "chunk_id": "chunk-001",
      "score": 0.82
    }
  ],
  "trace_id": "trace-..."
}
```

Agent 状态至少包含 `session_id`、`trace_id`、`user_goal`、`current_plan`、`completed_steps`、`tool_results`、`retrieved_evidence`、`pending_confirmation`、`error` 和 `final_answer`。

公开 API：

```text
GET  /health
POST /v1/documents/ingest
POST /v1/documents/scan
POST /v1/rag/query
POST /v1/agent/run
POST /v1/agent/confirm
GET  /v1/sessions/{session_id}
GET  /v1/traces/{trace_id}
```

## Retrieval and Answering

- 查询先做向量 Top 10 和 BM25 Top 10。
- 结果按 `chunk_id` 去重，保存原始向量分数和 BM25 分数。
- 基础重排公式为 `0.7 × vector_score + 0.3 × bm25_score`，两个分数都在进入公式前归一化。
- 最终只把 Top 4～6 证据交给回答层。
- Prompt/回答层把知识库内容视为数据而不是系统指令；回答只能引用检索证据。
- 没有词法重叠、没有有效检索结果或低于证据门槛时拒答，不把 Mock 结果或常识补写成项目事实。
- 每个关键结论带来源文件、章节、页码（若有）和 chunk ID。
- 文档索引 fingerprint 包含 provider、模型、向量维度、解析器版本、切片大小和重叠；fingerprint 变化时必须重建。

## Code Style

使用类型标注、短函数和显式依赖传递；业务逻辑不隐藏在框架魔法中。例如：

```python
def combine_scores(vector_score: float, bm25_score: float) -> float:
    """Return the explainable baseline hybrid score."""
    return round(0.7 * vector_score + 0.3 * bm25_score, 6)
```

命名使用 `snake_case`，领域类型使用 `PascalCase`，公开函数写简短 docstring。安全检查先于文件读取和工具执行；异常转换为项目错误后再返回 API，不泄露绝对路径、密钥、系统提示词或内部 traceback。

## Testing Strategy

- `pytest` 是唯一默认测试入口；测试不得依赖网络、真实模型、真实硬件或用户资料。
- 单元测试覆盖路径穿越、文件类型/大小、哈希增量、解析和切片、BM25/混合重排、证据门控、文件名清洗、工具参数、未确认保存和 Agent 步数。
- 集成测试通过合成 fixture 验证导入→检索→引用回答、允许工具调用、非允许工具拒绝、有限重试和 API 契约。
- `eval/run_eval.py` 默认运行22道离线题；通过 `PDA_EVAL_QUESTIONS_PATH` 和 `PDA_EVAL_FIXTURE_DIR` 可运行24道资料开发集。评测使用 `expected_terms` 独立判断答案是否支持，并区分检索失败、生成失败、拒答失败和工具失败；报告保留题目 ID、精确分子/分母及失败 ID。
- API 集成测试使用 `httpx.ASGITransport`，不依赖已弃用的 TestClient 路径。
- 绿色测试必须以进程退出码 `0` 为准，不以测试框架最后一行文字代替退出码证据。

## Security Boundaries

Always：

- 所有文件路径先 `resolve()`，再校验是否位于配置的允许目录内。
- 限制扩展名和最大文件大小；日志输出和检索结果对 token、密码、Authorization 等字段脱敏，包括结构化 JSON 键。
- 工具默认只读；Agent 最多四步，读工具使用 cooperative deadline，写工具不自动重试。
- 笔记使用安全文件名和独占创建，不覆盖已存在文件；只有确认接口才允许保存。
- `.env`、运行数据库、索引、日志、真实资料和模型文件加入 `.gitignore`。

Ask first：

- 新增外部付费模型或网络服务、系统级安装、访问新的用户目录、真实硬件/串口/烧录操作、修改既有用户文件。

Never：

- 任意 Shell/PowerShell/CMD/Python 代码执行、任意命令工具、自动烧录、自动修改源代码、自动删除/覆盖文件、收集或打印密钥、向外部模型发送敏感资料。

## Success Criteria

- 项目结构、规格、计划、任务清单和 README 完整。
- FastAPI 可以启动，`/health` 返回稳定 JSON；Streamlit 可以启动，或明确记录具体阻塞。
- 合成示例文档可以导入，哈希相同的文档不会重复写入。
- RAG 查询返回回答、置信度、引用和 trace ID；对无依据问题明确拒答。
- 向量检索、BM25、混合重排和引用均有测试。
- Agent 只能调用白名单工具，最多四步，工具失败不会无限重试。
- 未经确认不会写笔记；确认写入不会覆盖已有文件。
- 默认22道和资料24道离线评测均可重复运行，并输出 Hit@5、引用正确率、支持率、拒答率、工具成功率、精确分子/分母、失败 ID、平均延迟和 Bad Case。
- 自动化测试进程退出码为 0；README 中的命令经过实际验证或标注为未验证。
- 最终报告清楚区分已测试代码、Mock 验证、真实模型验证和外部边界未验证项。

## Open Questions

第一版没有阻塞性开放问题。真实 Embedding/LLM 的 provider 只实现接口和安全配置读取，是否接入具体服务留到后续并需单独确认网络、费用和敏感资料边界。
