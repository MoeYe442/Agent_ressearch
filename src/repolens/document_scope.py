from pathlib import PurePosixPath

DOC_SUFFIXES = {".md", ".rst", ".txt"}
DOC_NAMES = {"readme", "license", "copying", "changelog"}


def source_type(path):
    file = PurePosixPath(path.lower())
    return "repository_document" if file.suffix in DOC_SUFFIXES or file.name in DOC_NAMES else "repository_file"


def allows_path(path, scope="all"):
    if scope not in {"all", "code", "docs"}:
        raise ValueError("invalid_source_scope")
    document = source_type(path) == "repository_document"
    return scope == "all" or (document if scope == "docs" else not document)


def scope_sql(scope):
    if scope not in {"all", "code", "docs"}:
        raise ValueError("invalid_source_scope")
    clauses = [f"lower(path) LIKE '%{suffix}'" for suffix in sorted(DOC_SUFFIXES)]
    clauses.extend(f"(lower(path)='{name}' OR lower(path) LIKE '%/{name}')" for name in sorted(DOC_NAMES))
    predicate = "(" + " OR ".join(clauses) + ")"
    return "1=1" if scope == "all" else predicate if scope == "docs" else "NOT " + predicate
