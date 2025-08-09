import pytest

from agent_actions.utils import FieldAnalyzer, FieldChunker
from agent_actions.common.transformers.string_transformer import Tokenizer


@pytest.fixture(autouse=True)
def dummy_tokenizer(monkeypatch):
    def num_tokens_from_string(text, model):
        return len(text.split())

    def split_text_content(text, chunk_size, overlap, **kwargs):
        words = text.split()
        step = max(1, chunk_size - overlap)
        chunks = []
        for i in range(0, len(words), step):
            chunk = " ".join(words[i : i + chunk_size])
            if chunk:
                chunks.append(chunk)
        return chunks

    monkeypatch.setattr(Tokenizer, "num_tokens_from_string", staticmethod(num_tokens_from_string))
    monkeypatch.setattr(Tokenizer, "split_text_content", staticmethod(split_text_content))


def _config():
    return {
        "chunk_size": 3,
        "overlap": 0,
        "tokenizer_model": "dummy",
        "split_method": "dummy",
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content"],
            "preserve_fields": ["title"],
            "chunk_threshold": 1,
        },
    }


def test_analyzer_identifies_fields_to_chunk():
    analyzer = FieldAnalyzer(_config())
    record = {"title": "doc", "content": "word " * 10}
    analysis = analyzer.analyze_record(record)
    assert analysis.fields_to_chunk == ["content"]
    assert analysis.requires_chunking


def test_chunker_splits_field_and_preserves_metadata():
    config = _config()
    analyzer = FieldAnalyzer(config)
    chunker = FieldChunker(config)
    record = {"title": "doc", "content": "word " * 10}
    analysis = analyzer.analyze_record(record)
    chunks = chunker.chunk_record(record, analysis)
    assert len(chunks) > 1
    total = chunks[0]["chunk_info"][0]["total_chunks"]
    assert total == len(chunks)
    for chunk in chunks:
        assert chunk["title"] == "doc"
        info = chunk["chunk_info"][0]
        assert info["source_field"] == "content"

