# Offline Demo Script

以下命令在 `E:\\codex_project\\AI\\personal-dev-assistant` 执行，使用合成 fixture，不需要 API Key、网络、硬件或外部模型。

## 1. Install and test

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest -q
```

预期：测试进程退出码为 `0`。

## 2. Run the offline evaluation

```powershell
python -m eval.run_eval
Get-Content .\data\eval_report.json -Raw
```

预期报告包含 22 道题、Hit@5、引用正确率、独立答案支持率、拒答率、工具成功率、平均延迟、失败阶段和 Bad Case。

## 3. Run the API

```powershell
uvicorn app.api:app --reload --port 8000
```

另开一个 PowerShell：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Copy-Item .\tests\fixtures\uart.md .\data\inbox\uart.md
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/documents/ingest `
  -ContentType 'application/json' `
  -Body '{"source_path":"uart.md"}'
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/documents/scan `
  -ContentType 'application/json' `
  -Body '{"project_id":"default","recursive":true}'
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/rag/query `
  -ContentType 'application/json' `
  -Body '{"question":"PA9 在 UART 中承担什么角色？"}'
```

预期：第二次对同一文件导入返回 `unchanged`；查询响应包含 `answer`、`citations` 和 `trace_id`。

远程模型默认关闭。若明确确认资料允许外发，必须同时设置 `PDA_ALLOW_REMOTE_MODELS=true`，并在请求体中设置 `allow_external_processing=true`。

## 4. Run the Streamlit UI

```powershell
streamlit run app/ui.py --server.port 8501
```

在浏览器中上传 `tests/fixtures/uart.md`，点击导入，再询问 PA9；切换到 Agent 页签运行排查目标，观察“等待确认”，点击“不保存”验证不会生成笔记，再次运行后点击“确认保存”验证 `data/notes` 出现新文件。

## 5. Security demonstration

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/documents/ingest `
  -ContentType 'application/json' `
  -Body '{"source_path":"..\\secret.txt"}'
```

预期：返回 `PATH_NOT_ALLOWED`，不读取工作区外文件；超大上传也会在写盘前拒绝。任何知识库中的命令都只作为文本证据，不会被 Agent 执行。
