def test_ast_finds_class_method_and_import(indexed):
    from repolens.indexing import RepositoryIndex
    _, db, snapshot, summary, _, _ = indexed
    index = RepositoryIndex(db)
    assert index.search_symbols(snapshot.id, "Processor")[0].path == "app.py"
    assert index.search_symbols(snapshot.id, "Processor.run")[0].start_line == 9
    assert index.search_symbols(snapshot.id, "StateStore")[0].symbol == "StateStore"
    assert any(x.symbol == "storage.StateStore" for x in index.search_symbols(snapshot.id, "storage.StateStore"))
    assert summary.symbols >= 8


def test_syntax_error_keeps_text_search(indexed):
    from repolens.indexing import RepositoryIndex
    _, db, snapshot, summary, _, _ = indexed
    assert "broken.py" in summary.parse_errors
    assert RepositoryIndex(db).search_text(snapshot.id, "searchable_marker")[0].path == "broken.py"
    assert isinstance(RepositoryIndex(db).search_text(snapshot.id, '" OR * :'), list)
