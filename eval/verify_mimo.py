"""Explicit live smoke test: two bounded requests using synthetic evidence only."""

import json
import urllib.request
from pathlib import Path
from urllib.error import HTTPError

from dotenv import dotenv_values


def main() -> int:
    config = dotenv_values(Path(__file__).resolve().parents[1] / '.env')
    key = config.get('PDA_OPENAI_API_KEY', '')
    if not key or config.get('PDA_OPENAI_BASE_URL') != 'https://api.xiaomimimo.com/v1':
        print('Configuration missing or endpoint differs; no request sent.')
        return 1
    if config.get('PDA_ALLOW_REMOTE_MODELS', '').lower() != 'true':
        print('Remote processing disabled; no request sent.')
        return 1
    cases = [
        ('fact', '合成资料 [demo-uart:1]：演示板 UART 的 PA9 是 TX，波特率为115200。问题：PA9是什么，波特率多少？', ['PA9', '115200', 'demo-uart:1']),
        ('refusal', '合成资料 [demo-uart:1]：PA9是UART TX。问题：这块板的CAN终端电阻是多少？', ['现有资料不足以确定']),
    ]
    success = True
    for name, prompt, expected in cases:
        payload = {
            'model': 'mimo-v2.5-pro',
            'messages': [
                {'role': 'system', 'content': '仅根据提供的合成证据回答，不要补充常识。每个事实句必须以证据ID结束，格式为：事实内容 [证据ID]。证据ID必须逐字复制，包括冒号、连字符和数字，不可省略。例如：结论 [demo-uart:1]。证据不足仅回答：现有资料不足以确定。'},
                {'role': 'user', 'content': prompt},
            ],
            'thinking': {'type': 'disabled'},
            'max_completion_tokens': 512,
            'temperature': 0,
            'stream': False,
        }
        request = urllib.request.Request(
            'https://api.xiaomimimo.com/v1/chat/completions',
            data=json.dumps(payload).encode('utf-8'),
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read())
            answer = body['choices'][0]['message']['content']
            passed = isinstance(answer, str) and all(term in answer for term in expected)
            usage = body.get('usage') or {}
            # Only expose bounded synthetic answers; never headers or raw errors.
            print(json.dumps({'case': name, 'passed': passed,
                              'answer': answer.replace(key, '[REDACTED]')[:1200] if isinstance(answer, str) else None,
                              'missing_terms': [term for term in expected if not isinstance(answer, str) or term not in answer],
                              'finish_reason': body['choices'][0].get('finish_reason'),
                              'tokens': {k: usage.get(k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')}}, ensure_ascii=True))
            success = success and passed
        except HTTPError as exc:
            print(json.dumps({'case': name, 'http_status': exc.code}))
            return 1
        except Exception as exc:
            print(json.dumps({'case': name, 'error_type': type(exc).__name__}))
            return 1
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
