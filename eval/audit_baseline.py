"""Freeze development evidence without changing application behavior or reading secrets."""
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.logging_config import close_logging
from app.rag.parser import parse_document
from eval.run_eval import PROJECT_ROOT, build_runtime, evaluate, load_questions


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric(rows, field):
    return {'numerator': sum(bool(r[field]) for r in rows), 'denominator': len(rows),
            'failed_ids': [r['id'] for r in rows if not r[field]]}


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = PROJECT_ROOT / 'eval' / 'runs' / stamp
    output.mkdir(parents=True, exist_ok=False)
    fixtures = PROJECT_ROOT / 'tests/fixtures/generated_materials'
    questions = PROJECT_ROOT / 'eval/user_materials_questions.jsonl'
    # Explicit offline selection; never load .env or use ambient remote providers.
    os.environ.update(PDA_LLM_PROVIDER='mock', PDA_EMBEDDING_PROVIDER='mock',
                      PDA_ALLOW_REMOTE_MODELS='false', PDA_EVAL_FIXTURE_DIR=str(fixtures),
                      PDA_EVAL_QUESTIONS_PATH=str(questions), PDA_EVAL_REPORT_PATH=str(output/'legacy.json'))
    files = [*fixtures.glob('*'), questions]
    code = [p for folder in ('app', 'eval') for p in (PROJECT_ROOT/folder).rglob('*.py') if 'runs' not in p.parts]
    manifest = {'dataset': 'development', 'embedding': 'mock:deterministic-hash-v1:96',
                'llm': 'mock:evidence-extractor-v1', 'chunk_chars': 700, 'overlap': 100,
                'vector_top': 10, 'bm25_top': 10, 'answer_top': 5, 'weights': [0.7, 0.3],
                'head': subprocess.check_output(['git','-c',f'safe.directory={PROJECT_ROOT.as_posix()}','rev-parse','HEAD'], cwd=PROJECT_ROOT, text=True).strip(),
                'status': subprocess.check_output(['git','-c',f'safe.directory={PROJECT_ROOT.as_posix()}','status','--short'], cwd=PROJECT_ROOT, text=True),
                'hashes': {str(p.relative_to(PROJECT_ROOT)): digest(p) for p in files+code},
                'real_comparison': 'not_executed'}
    for p in files+code:
        target = output/'snapshot'/p.relative_to(PROJECT_ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p.read_bytes())
    report = evaluate()
    items = load_questions()
    with tempfile.TemporaryDirectory(prefix='pda-audit-') as temp:
        try:
            runtime = build_runtime(Path(temp))
            chunks = runtime.index.list_chunks()
            (output/'chunks.json').write_text(json.dumps([c.model_dump(mode='json') for c in chunks], ensure_ascii=False, indent=2), encoding='utf-8')
            for item, row in zip(items, report['rows'], strict=True):
                row['id'] = item['id']
                row['kind'] = item['kind']
                terms = item['expected_terms']
                ranked = runtime.retriever.search(item['question'], top_k=20)
                row['ranked_candidates'] = [e.model_dump() for e in ranked]
                row['raw_hit_at_5'] = item['expected_source'] in [e.source_file for e in ranked[:5]]
                relevant = [c for c in chunks if c.source_file == item['expected_source']]
                cited = [e for e in ranked if f'[{e.chunk_id}]' in row['answer']]
                row['cited_evidence_term_coverage'] = bool(terms) and all(
                    any(t.casefold() in e.content.casefold() for e in cited) for t in terms)
                row['evidence_supported_proxy'] = row['answer_supported'] and row['cited_evidence_term_coverage']
                if item['kind'] == 'tool':
                    row['diagnosis'] = '日志工具成功与答案正确分开；须人工检查日志引用及排查建议'
                    continue
                if item['kind'] == 'unanswerable':
                    row['diagnosis'] = '通过' if row['refusal_correct'] else '拒答错误'
                    continue
                source = fixtures/item['expected_source']
                parsed = parse_document(source)
                parsed_text = '\n'.join(p.content for p in parsed.pages)
                raw = source.read_text(encoding='utf-8')
                coverage = lambda text: all(t.casefold() in text.casefold() for t in terms)
                row['source_contains_expected_terms'] = coverage(raw)
                row['parsed_contains_expected_terms'] = coverage(parsed_text)
                row['supporting_chunk_ids'] = [c.chunk_id for c in relevant if coverage(c.content)]
                candidates = {e.chunk_id for e in ranked}
                top = {e.chunk_id for e in ranked[:6]}
                support = set(row['supporting_chunk_ids'])
                if not coverage(raw): reason = '评分问题：预期词未逐字出现在原文，需人工判断同义表达'
                elif not coverage(parsed_text): reason = '解析丢失'
                elif not support: reason = '切片断开：所需信息分布于多个切片（跨段题可能正常）'
                elif not support & candidates: reason = '召回遗漏'
                elif not support & top: reason = '排序靠后'
                elif not any(e.chunk_id in support for e in cited): reason = '召回遗漏：回答词法门控剔除或生成截取未覆盖；见排名和引用'
                elif not row['answer_supported']: reason = '生成错误'
                else: reason = '通过'
                row['diagnosis'] = reason
        finally:
            close_logging()
    qa = [r for r in report['rows'] if r['kind'] not in ('tool','unanswerable')]
    refusal = [r for r in report['rows'] if r['kind']=='unanswerable']
    tool = [r for r in report['rows'] if r['kind']=='tool']
    report['counts'] = {field: metric(group, field) for field, group in (
        ('retrieval_hit_at_5',qa), ('raw_hit_at_5',qa), ('citation',qa), ('answer_supported',qa),
        ('evidence_supported_proxy',qa), ('refusal_correct',refusal), ('tool_success',tool))}
    report['scoring_limit'] = '关键词与被引用切片交叉检查仍不是语义蕴含评分；不能识别所有否定或额外编造。原Hit@5等同最终引用命中，raw_hit_at_5才是检索前五文件命中。'
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (output/'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(output), 'counts': report['counts'],
                      'diagnoses': {r['id']: r['diagnosis'] for r in report['rows']}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
