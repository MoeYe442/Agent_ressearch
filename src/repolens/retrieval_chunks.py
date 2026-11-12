"""Versioned source chunks; original line boundaries remain the citation authority."""
import ast
import hashlib
import json
from repolens.secure_io import physical_lines
from repolens.document_scope import source_type
from repolens.models import SearchHit

CHUNKER_VERSION = "ast-headings-window-v1"


def split_source(path, text):
    lines = physical_lines(text)
    if any(len(line.encode('utf-8')) > 8000 for line in lines):
        raise ValueError('retrieval_line_too_large')
    owners = [''] * len(lines)
    if path.endswith(('.py', '.pyi')):
        try:
            tree = ast.parse(text)
            def walk(node, parents=()):
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        name = '.'.join((*parents, child.name))
                        start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                        for i in range(start-1, child.end_lineno):
                            owners[i] = name
                        walk(child, (*parents, child.name))
                    else:
                        walk(child, parents)
            walk(tree)
        except (SyntaxError, RecursionError):
            owners = [''] * len(lines)
    elif path.lower().endswith('.md'):
        heading = ''
        for i, line in enumerate(lines):
            if line.startswith('#'):
                heading = line.lstrip('# ').strip()
            owners[i] = heading
    segments, start = [], 0
    for i in range(1, len(lines)+1):
        if i == len(lines) or owners[i] != owners[start]:
            segments.append((start, i, owners[start]))
            start = i
    chunks = []
    for first, last, owner in segments:
        start = first
        while start < last:
            end, size = start, 0
            while end < last and end-start < 120 and size+len(lines[end].encode('utf-8')) <= 8000:
                size += len(lines[end].encode('utf-8'))
                end += 1
            content = ''.join(lines[start:end])
            chunks.append({'path': path, 'start_line': start+1, 'end_line': end, 'parent_symbol': owner, 'content': content, 'content_hash': hashlib.sha256(content.encode()).hexdigest(), 'source_scope': 'docs' if source_type(path)=='repository_document' else 'code', 'chunker_version': CHUNKER_VERSION})
            if end == last:
                break
            start = max(start+1, end-20)
    return chunks


def chunk_snapshot(snapshot_id, store):
    snapshot = store.db.get_snapshot(snapshot_id)
    chunks = []
    for path in sorted(snapshot.manifest):
        for chunk in split_source(path, store.file_text(snapshot_id, path)):
            chunk['snapshot_id'] = snapshot_id
            identity = {key: chunk[key] for key in ('snapshot_id','path','start_line','end_line','content_hash','chunker_version')}
            chunk['id'] = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
            chunks.append(chunk)
    return chunks


def fuse_rankings(rankings, limit=20):
    merged = {}
    for channel in sorted(rankings):
        seen = set()
        rank = 0
        for item in rankings[channel]:
            key = (item.path,item.start_line,item.end_line)
            if key in seen:
                continue
            seen.add(key)
            rank += 1
            if key not in merged:
                merged[key] = item.model_copy(update={'score':0.0})
            merged[key].score += 1/(60+rank)
    return sorted(merged.values(),key=lambda item:(-item.score,item.path,item.start_line,item.end_line))[:min(max(limit,1),20)]
