import ast
import re
import sqlite3
from repolens.evidence import EvidenceStore
from repolens.models import SearchHit, IndexSummary
from repolens.secure_io import physical_lines


class RepositoryIndex:
    def __init__(self, db):
        self.db = db
        with db.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS symbols (snapshot_id TEXT, path TEXT, symbol TEXT, start_line INTEGER, end_line INTEGER)")
            try:
                conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS text_chunks USING fts5(snapshot_id UNINDEXED, path UNINDEXED, start_line UNINDEXED, end_line UNINDEXED, content)")
            except sqlite3.OperationalError as exc:
                raise RuntimeError("SQLite FTS5 is required; install a Python build with FTS5 support") from exc

    def search_symbols(self, snapshot_id, query, limit=10):
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self.db.connect() as conn:
            rows = conn.execute("SELECT path,symbol,start_line,end_line FROM symbols WHERE snapshot_id=? AND symbol LIKE ? ESCAPE '\\' ORDER BY (symbol=?) DESC,path,start_line LIMIT ?", (snapshot_id, "%" + escaped + "%", query, min(max(limit, 1), 20))).fetchall()
        return [SearchHit(**dict(row)) for row in rows]

    def search_text(self, snapshot_id, query, limit=10):
        terms = re.findall(r"\w+", query, flags=re.UNICODE)
        if not terms:
            return []
        match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms[:20])
        with self.db.connect() as conn:
            rows = conn.execute("SELECT path,start_line,end_line,bm25(text_chunks) AS rank FROM text_chunks WHERE text_chunks MATCH ? AND snapshot_id=? ORDER BY rank,path,start_line LIMIT ?", (match, snapshot_id, min(max(limit, 1), 20))).fetchall()
        return [SearchHit(path=row["path"], start_line=int(row["start_line"]), end_line=int(row["end_line"]), score=-row["rank"]) for row in rows]


def build_index(snapshot, db):
    RepositoryIndex(db)
    store = EvidenceStore(db)
    summary = IndexSummary()
    with db.connect() as conn:
        conn.execute("DELETE FROM symbols WHERE snapshot_id=?", (snapshot.id,))
        conn.execute("DELETE FROM text_chunks WHERE snapshot_id=?", (snapshot.id,))
        for path in sorted(snapshot.manifest):
            text = store.file_text(snapshot.id, path, allow_importing=True)
            summary.files += 1
            lines = physical_lines(text)
            for start in range(0, len(lines), 60):
                conn.execute("INSERT INTO text_chunks VALUES (?,?,?,?,?)", (snapshot.id, path, start + 1, min(start + 60, len(lines)), "\n".join(lines[start:start + 60])))

            def record(name, start, end):
                conn.execute("INSERT INTO symbols VALUES (?,?,?,?,?)", (snapshot.id, path, name, start, end))
                summary.symbols += 1

            if path.endswith(".py"):
                try:
                    tree = ast.parse(text)
                except SyntaxError as exc:
                    summary.parse_errors[path] = f"SyntaxError at line {exc.lineno}"
                    continue

                def walk(node, parents=()):
                    for child in ast.iter_child_nodes(node):
                        if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                            name = ".".join((*parents, child.name))
                            start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                            record(name, start, child.end_lineno)
                            walk(child, (*parents, child.name))
                        elif isinstance(child, (ast.Import, ast.ImportFrom)):
                            for alias in child.names:
                                record((child.module + "." if isinstance(child, ast.ImportFrom) and child.module else "") + alias.name, child.lineno, child.end_lineno)
                        else:
                            walk(child, parents)
                walk(tree)
            elif path.endswith(".md"):
                for number, line in enumerate(lines, 1):
                    if line.startswith("#"):
                        record(line.lstrip("# "), number, number)
        conn.execute("INSERT OR REPLACE INTO entities VALUES ('indexes',?,?)", (snapshot.id, summary.model_dump_json()))
        snapshot.status = "ready"
        conn.execute("INSERT OR REPLACE INTO entities VALUES ('snapshots',?,?)", (snapshot.id, snapshot.model_dump_json()))
    return summary
