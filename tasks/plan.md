# Implementation Plan: 个人嵌入式研发知识与故障排查助手

## Overview

在 `E:\\codex_project\\AI\\personal-dev-assistant` 中构建一个可实际自用、可用于求职展示的本地 MVP。实现顺序遵循依赖图和纵向切片：先让最小应用可启动，再让合成文档走通导入→检索→引用回答，随后接入完整混合检索、API/UI、受控 Agent、离线评测和交付文档。

## Architecture Decisions

1. **SQLite-backed local index**：SQLite 同时保存文档元数据、切片和确定性向量 JSON，避免 MVP 强依赖下载大型模型或本机原生库；检索接口为以后接入 Chroma 留出边界。
2. **Explicit provider interfaces**：LLM 和 Embedding 都通过协议/网关注入；Mock 默认启用，OpenAI-compatible provider 只在显式配置后启用，任何真实调用都不进入默认测试。
3. **Evidence-gated answers**：回答层必须接收检索证据并生成引用；没有词法/检索证据时返回固定拒答，不允许模型自由补全项目事实。
4. **Service composition root**：`app/runtime.py` 统一创建配置、SQLite 存储、检索、回答、会话和 Agent，API 与 Streamlit 共享同一组业务服务。
5. **Safe path and write policy**：输入路径必须位于 `data/inbox` 或 `data/logs`；笔记只写入 `data/notes`，使用独占创建和安全文件名，确认之前只返回预览。
6. **Small dependency surface**：核心 BM25、Mock Embedding、路径安全和文件写入使用标准库，外部包只承担 FastAPI、Uvicorn、Streamlit、PyMuPDF 和测试。

## Dependency Graph

```text
config/errors/models
        │
        ├── SQLite metadata/session/trace storage
        │             │
        │             ├── parser → chunker → indexer
        │             │                         │
        │             │                         └── vector/BM25/hybrid retrieval
        │             │                                      │
        │             │                                      └── evidence-gated answer
        │             │                                                   │
        │             ├── API contract ──────────────────────────────────┘
        │             └── Agent policy/tools/workflow
        │                                                                  │
        └──────────────────────────────────────────────────────────────────┴── UI/eval/docs
```

## Task List

### Phase 0: Baseline

- [x] Task 0: 保存规格、计划和任务清单
  - Acceptance: 三份文档描述范围、边界、依赖顺序、验收和未验证项。
  - Verify: 检查三个文件存在并可读。
  - Dependencies: None

### Phase 1: Foundation

- [x] Task 1: 工程配置、领域模型、稳定错误和依赖声明
  - Acceptance: 配置能解析项目目录；Pydantic 模型覆盖 API 契约；错误结构不暴露内部信息；pytest 配置可用。
  - Verify: 运行基础单元测试，进程退出码为 0。
  - Dependencies: Task 0

- [x] Task 2: Mock LLM/Embedding 和最小 FastAPI `/health`
  - Acceptance: 不需要 API Key 就能实例化 provider；健康检查有稳定响应和 trace ID。
  - Verify: API 单测和 provider 单测。
  - Dependencies: Task 1

### Checkpoint: Foundation

- [x] 应用模块可以导入。
- [x] 基础测试通过。
- [x] 所有默认行为不访问网络、不接触硬件。

### Phase 2: Minimal RAG Vertical Slice

- [x] Task 3: 文档解析、清洗、脱敏和文本切片
  - Acceptance: Markdown/TXT/C/H/日志可解析；文本型 PDF 使用 PyMuPDF；切片保留标题、页码、哈希和重叠信息。
  - Verify: 解析、PDF 缺依赖边界、切片和脱敏单测。
  - Dependencies: Task 1

- [x] Task 4: SQLite 文档索引、文件哈希和确定性向量检索
  - Acceptance: 示例文档可导入；相同哈希跳过；索引可持久化；查询返回 Top-K 切片元数据。
  - Verify: 索引集成测试和增量导入测试。
  - Dependencies: Tasks 2-3

- [x] Task 5: BM25、混合重排、证据回答和引用
  - Acceptance: 向量/BM25 各取 Top 10，按 0.7/0.3 合并；Top 4～6 进入回答；无依据问题拒答；回答带 citation。
  - Verify: 3 个合成问题有引用，1 个无依据问题拒答。
  - Dependencies: Task 4

### Checkpoint: Core RAG

- [x] 合成文档导入→检索→回答闭环离线运行。
- [x] 检索失败与生成/回答拒答可以区分。
- [x] 运行进程退出码为 0。

### Phase 3: API, Sessions and UI

- [x] Task 6: API 端点、会话、trace 和稳定异常
  - Acceptance: 六类公开接口可用；请求生成 trace；会话保存最近上下文和摘要字段；异常不泄露绝对路径和内部 traceback。
  - Verify: 使用 `httpx.ASGITransport` 的 FastAPI 集成测试。
  - Dependencies: Tasks 1-5

- [x] Task 7: Streamlit 查询/导入/Agent 界面
  - Acceptance: UI 能显示健康状态、导入结果、RAG 回答、引用、Agent 计划和确认按钮；缺少依赖时有友好提示。
  - Verify: Python 编译检查和启动导入检查；真实浏览器交互列为可选手工验证。
  - Dependencies: Task 6

### Phase 4: Controlled Agent

- [x] Task 8: 工具白名单、日志搜索和清单生成
  - Acceptance: `search_knowledge`、`search_log`、`generate_checklist`、`save_note` 具备严格参数；不存在任意命令执行入口。
  - Verify: 工具参数、路径边界、脱敏和非白名单拒绝测试。
  - Dependencies: Tasks 4-6

- [x] Task 9: 最多四步的 Agent 状态机和确认保存
  - Acceptance: Agent 保存完整状态；每工具最多重试一次；运行结束 pending confirmation；未确认不写文件；确认时独占创建笔记。
  - Verify: Agent 集成测试、重试测试和笔记确认测试。
  - Dependencies: Task 8

### Phase 5: Evaluation and Delivery

- [x] Task 10: 默认22题离线评测和24题资料开发集
  - Acceptance: 覆盖事实题、跨章节、流程、拒答和工具题；使用 `expected_terms` 独立检查答案支持度；输出题目 ID、题型、来源、检索、引用、Hit@5、支持率、拒答率、工具成功率、精确分子/分母、失败 ID、延迟和 Bad Case。
  - Verify: 默认 `python -m eval.run_eval` 与环境变量指定的24题资料集均退出码为 0 并生成 JSON 报告。
  - Dependencies: Tasks 5 and 9

- [x] Task 11: README、架构说明、演示脚本和最终验证
  - Acceptance: README 提供复制可用命令和边界说明；架构/演示文档与实现一致；运行数据和秘密被忽略。
  - Verify: 全量 pytest、编译检查、启动检查和 Git 状态检查。
  - Dependencies: Tasks 6-10

### Phase 6: Hardening Follow-up

- [x] Task 12: SQLite schema migration、index fingerprint、远程双重授权和结构化脱敏
- [x] Task 13: Agent 日志证据、计划状态、cooperative deadline、幂等笔记和项目隔离上下文
- [x] Task 14: 共享导入/扫描服务、C/H 函数切片、API trace/日志/稳定错误和 Streamlit 安全边界
- [x] Task 15: 22题默认评测、24题资料开发集、锁定依赖和全新环境验证；Git 收口提交

## Verification Checkpoints

### After Tasks 1-2

- [x] 基础导入和健康检查测试通过。
- [x] Mock provider 可重复运行。

### After Tasks 3-5

- [x] RAG 最小闭环测试通过。
- [x] 引用和拒答行为符合规格。

### After Tasks 6-9

- [x] API 和 Agent 集成测试通过。
- [x] 未确认保存和非法工具调用均被阻断。

### Complete

- [x] 全量测试进程退出码为 0。
- [x] 默认22题和资料24题离线评测可重复运行，且报告保存分子、分母和失败 ID。
- [x] README 命令与当前实现一致。
- [x] 已验证与未验证边界已写入交付报告。

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---:|---|
| 当前环境没有全局 Python 或测试依赖 | Medium | 使用工作区 Python 3.12；依赖装入项目虚拟环境；保留纯标准库核心逻辑。 |
| PyMuPDF/Streamlit 安装失败 | Medium | 先完成文本路径和 Mock 测试；API/UI 启动阻塞单独报告，不伪造 PDF/UI 验证。 |
| Mock 向量不能代表真实语义效果 | High | 仅把它标为确定性测试 embedding；真实模型效果单独标未验证。 |
| 日志包含密钥或绝对路径 | High | 解析、日志和 API 输出统一脱敏；只允许配置目录。 |
| 混合检索对短中文问题不稳定 | Medium | 增加字符/词法 token、BM25 归一化和证据门控测试；记录 Bad Case。 |
| 用户运行数据误提交 Git | High | `.gitignore` 忽略 data/index、数据库、日志、notes、`.env` 和模型文件；提供合成 fixture。 |

## Open Questions

真实模型供应商、具体 embedding 模型和是否采用 Chroma 不阻塞 MVP；这些选择必须在网络、费用和敏感文档边界确认后作为独立增强任务处理。
