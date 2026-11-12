import hashlib
import pytest
from repolens.retrieval_chunks import chunk_snapshot, split_source, fuse_rankings, CHUNKER_VERSION
from repolens.models import SearchHit


def test_snapshot_chunks_are_stable_and_preserve_original_lines(indexed):
    _,_,snapshot,_,store,_=indexed
    chunks=chunk_snapshot(snapshot.id,store)
    assert chunks==chunk_snapshot(snapshot.id,store)
    assert any(c['parent_symbol']=='Processor.run' for c in chunks)
    assert any(c['source_scope']=='docs' and c['path']=='README.md' for c in chunks)
    assert any(c['path']=='broken.py' for c in chunks)
    for c in chunks:
        evidence=store.read_evidence(snapshot.id,c['path'],c['start_line'],c['end_line'])
        assert c['content_hash']==evidence.content_hash
        assert c['content']==evidence.excerpt and c['chunker_version']==CHUNKER_VERSION
        assert c['snapshot_id']==snapshot.id


def test_long_function_windows_overlap_with_line_and_utf8_bounds():
    text='def long_function():\n'+''.join('    value = "中文字符"\n' for _ in range(300))
    chunks=split_source('long.py',text)
    assert len(chunks)>2
    assert all(c['end_line']-c['start_line']+1<=120 and len(c['content'].encode())<=8000 for c in chunks)
    assert chunks[0]['end_line']>=chunks[1]['start_line']
    assert all(c['parent_symbol']=='long_function' for c in chunks)
    covered={i for c in chunks for i in range(c['start_line'],c['end_line']+1)}
    assert covered==set(range(1,302))


def test_markdown_sections_and_unterminated_line_are_preserved():
    chunks=split_source('README.md','# One\ntext\n## Two\nlast')
    assert [(c['start_line'],c['end_line'],c['parent_symbol']) for c in chunks]==[(1,2,'One'),(3,4,'Two')]
    assert chunks[-1]['content'].endswith('last')


def test_oversize_single_line_is_explicit_error():
    with pytest.raises(ValueError,match='retrieval_line_too_large'):
        split_source('x.txt','中'*3000)


def test_rank_fusion_is_deterministic_and_deduplicates_each_channel():
    a=SearchHit(path='app.py',start_line=1,end_line=3)
    b=SearchHit(path='storage.py',start_line=4,end_line=9)
    one=fuse_rankings({'keyword':[a,a,b],'vector':[b,a]},20)
    two=fuse_rankings({'vector':[b,a],'keyword':[a,a,b]},20)
    assert one==two and len(one)==2
    assert one[0].score>0
    assert fuse_rankings({},20)==[]
