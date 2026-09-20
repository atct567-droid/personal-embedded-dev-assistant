# Task Checklist: 个人嵌入式研发知识与故障排查助手

> 任务按依赖顺序排列。每完成一个任务，先运行对应验证并记录退出码，再进入下一项。

## Baseline

- [x] 读取并落实用户提供的项目规格
- [x] 将项目根目录切换为 `E:\\codex_project\\AI\\personal-dev-assistant`
- [x] 写入 `docs/spec.md`
- [x] 写入 `tasks/plan.md`
- [x] 写入本任务清单

## Foundation

- [x] Task 1 — 配置、领域模型、错误结构、pyproject 和 pytest 基线
- [x] Task 2 — Mock LLM/Embedding 与 `/health`
- [x] Checkpoint — 基础测试退出码为 0

## Minimal RAG

- [x] Task 3 — 文档解析、脱敏、切片和哈希
- [x] Task 4 — SQLite 索引、增量导入和向量检索
- [x] Task 5 — BM25、混合重排、证据回答和引用
- [x] Checkpoint — 合成资料完成离线 RAG 闭环

## API and UI

- [x] Task 6 — FastAPI 端点、会话、trace 和稳定异常
- [x] Task 7 — Streamlit 本地界面

## Controlled Agent

- [x] Task 8 — 白名单工具、日志搜索和清单生成
- [x] Task 9 — Agent 状态机、重试和确认保存
- [x] Checkpoint — Agent 安全边界与 API 集成通过

## Evaluation and Delivery

- [x] Task 10 — 默认22题与资料24题离线评测和合成演示资料
- [x] Task 11 — README、架构、演示脚本和最终验证
- [x] Final — 区分代码测试、Mock 验证、真实模型验证和外部未验证边界

## Hardening Follow-up

- [x] 索引 schema 迁移、provider/model/chunk fingerprint 和远程双重授权
- [x] 共享导入服务、目录扫描、C/H 函数切片和 UI 文件大小边界
- [x] Agent 日志证据、计划状态、cooperative deadline、幂等笔记和项目隔离上下文
- [x] RAG session、摘要、稳定 404/405、请求 trace、JSONL 轮转日志和健康降级
- [x] 24题资料开发集答案支持审计、留出题冻结和本地 fake provider 验证
- [x] requirements.lock、全新虚拟环境 pip check 和测试验证
