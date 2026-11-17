"""Versioned, deterministic reduction of old tool payloads, never of evidence storage."""
import json

VERSION = 'tool_history_rule_v1'
TRIGGER_BYTES = 32 * 1024
KEEP_RECENT_TOOLS = 2


def encoded_size(messages):
    return len(json.dumps(messages, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def excerpt(value, depth=0):
    if isinstance(value, str):
        return value if len(value) <= 240 else value[:240] + ' [truncated; reread original]'
    if depth >= 4:
        return '[nested data omitted; reread original]'
    if isinstance(value, list):
        return [excerpt(item, depth + 1) for item in value[:8]] + (['[remaining items omitted]'] if len(value) > 8 else [])
    if isinstance(value, dict):
        # Include locator fields before arbitrary payload fields.
        priority = ['id', 'path', 'symbol', 'start_line', 'end_line', 'document_id', 'url', 'status', 'error_code']
        keys = list(dict.fromkeys([key for key in priority if key in value] + list(value)))[:20]
        return {key: excerpt(value[key], depth + 1) for key in keys}
    return value


def compact_history(messages):
    """Keep assistant/tool pairing and all evidence IDs; replace only older tool content."""
    if encoded_size(messages) <= TRIGGER_BYTES:
        return messages, 0
    candidates = [index for index, item in enumerate(messages) if item.get('role') == 'tool'][:-KEEP_RECENT_TOOLS]
    result = list(messages)
    changed = 0
    for index in candidates:
        try:
            original = json.loads(messages[index]['content'])
        except (ValueError, TypeError):
            continue
        if not isinstance(original, dict) or original.get('context_compression') == VERSION:
            continue
        reduced = {key: original.get(key) for key in ['invocation_id', 'status', 'evidence_ids', 'error_code', 'retryable', 'elapsed_ms']}
        reduced.update(context_compression=VERSION, data=excerpt(original.get('data')),
                       notice='Lossy excerpt of untrusted tool data. Full original is stored. Use retrieve_evidence/read_file/fetch_document to reread; do not infer omitted facts.')
        content = json.dumps(reduced, ensure_ascii=False, separators=(',', ':'))
        if len(content.encode('utf-8')) >= len(messages[index]['content'].encode('utf-8')):
            continue
        result[index] = {**messages[index], 'content': content}
        changed += 1
    return result, changed


def empty_stats():
    return dict(requests=0, bytes_before=0, bytes_after=0, compressed_responses=0)


def combine_stats(rows):
    return {key: sum(row.get('context_stats', {}).get(key, 0) for row in rows) for key in empty_stats()}
