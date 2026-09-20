"""Opt-in live MiMo pipeline check using temporary synthetic files only."""
import json
import os
import tempfile
from pathlib import Path

from dotenv import dotenv_values

from app.config import Settings
from app.domain.errors import PolicyDeniedError
from app.logging_config import close_logging
from app.runtime import ApplicationRuntime


def main():
    config = dotenv_values(Path(__file__).resolve().parents[1] / '.env')
    if config.get('PDA_OPENAI_BASE_URL') != 'https://api.xiaomimimo.com/v1':
        print('Endpoint mismatch; no request sent.')
        return 1
    for name in ('PDA_OPENAI_API_KEY', 'PDA_OPENAI_BASE_URL', 'PDA_OPENAI_MODEL', 'PDA_ALLOW_REMOTE_MODELS'):
        os.environ[name] = config.get(name) or ''
    os.environ['PDA_LLM_PROVIDER'] = 'openai-compatible'
    os.environ['PDA_EMBEDDING_PROVIDER'] = 'mock'
    results = {}
    with tempfile.TemporaryDirectory(prefix='mimo-pipeline-') as directory:
        try:
            from dataclasses import replace
            settings = replace(Settings.from_root(Path(directory)), allow_remote_models=config.get('PDA_ALLOW_REMOTE_MODELS') == 'true')
            runtime = ApplicationRuntime.from_settings(settings)
            text = '# UART\nPA9 是 TX，波特率115200。UART timeout 应先检查共地和波特率。'
            runtime.imports.save_upload_and_ingest('demo.md', text.encode('utf-8'), allow_external_processing=True)
            results['incremental'] = runtime.imports.ingest_path('demo.md', allow_external_processing=True).status == 'unchanged'
            try:
                runtime.answerer.answer('PA9 UART 波特率是多少？')
                results['authorization'] = False
            except PolicyDeniedError:
                results['authorization'] = True
            response = runtime.conversations.query('PA9 在 UART 中是 TX 还是 RX？波特率是多少？请回答这两项。', project_id='default', top_k=5, trace_id='live-rag', allow_external_processing=True)
            results['rag_fact'] = '115200' in response.answer and 'TX' in response.answer
            results['inline_citation'] = any(c.chunk_id in response.answer for c in response.citations)
            refusal = runtime.answerer.answer('CAN termination resistance?', allow_external_processing=True)
            results['local_refusal'] = not refusal.citations and '不足以确定' in refusal.answer
            (settings.logs_dir / 'device.log').write_text('ERROR UART timeout\n', encoding='utf-8')
            state = runtime.agent.run('检查 UART timeout', allow_external_processing=True)
            results['agent'] = bool(state.log_evidence and state.retrieved_evidence and state.pending_confirmation and not state.error)
            results['no_write_before_confirmation'] = not list(settings.notes_dir.glob('*.md'))
            saved = runtime.agent.confirm(state.session_id, True)
            results['confirmed_note'] = bool(saved.note_path and (settings.notes_dir / saved.note_path).is_file())
        except Exception as exc:
            results['error_type'] = type(exc).__name__
        finally:
            close_logging()
    print(json.dumps({'mode': 'live-mimo/mock-embedding', 'checks': results}))
    return 0 if results and all(value is True for value in results.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
