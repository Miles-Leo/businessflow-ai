from copy import deepcopy
from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.ai.rag import load_markdown, split_markdown


def test_load_markdown_preserves_chinese_text_and_source(tmp_path):
    path = tmp_path / "policy.md"
    text = "# 测试政策\n\n## 发货规则\n\n必须经过审核。\n"
    path.write_text(text, encoding="utf-8")
    document = load_markdown(path)
    assert document.page_content == text
    assert document.metadata["source"] == str(path)


def test_load_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_markdown(tmp_path / "missing.md")


def test_split_preserves_source_sections_and_original_document():
    document = Document(
        page_content="# 测试政策\n\n说明内容。\n\n## AS-01\n\n第一条规则。\n\n## AS-02\n\n第二条规则。",
        metadata={"source": "policy.md", "version": "1.0"},
    )
    original = deepcopy(document)
    chunks = split_markdown(document)
    assert len(chunks) == 3
    assert all(chunk.metadata["source"] == "policy.md" for chunk in chunks)
    assert all(chunk.metadata["version"] == "1.0" for chunk in chunks)
    assert all(chunk.metadata["document_title"] == "测试政策" for chunk in chunks)
    assert chunks[1].metadata["section"] == "AS-01"
    assert "第一条规则。" in chunks[1].page_content
    assert chunks[2].metadata["section"] == "AS-02"
    assert "第二条规则。" in chunks[2].page_content
    assert document == original


def test_demo_policy_all_sections_have_sources():
    path = Path(__file__).resolve().parents[1] / "knowledge" / "after_sales_policy.md"
    chunks = split_markdown(load_markdown(path))
    assert len(chunks) == 8
    assert all(chunk.page_content.strip() for chunk in chunks)
    assert all(chunk.metadata["source"] == str(path) for chunk in chunks)
    sections = [chunk.metadata["section"] for chunk in chunks if "section" in chunk.metadata]
    assert len(sections) == 7
    assert {section.split("：")[0] for section in sections} == {
        f"AS-{index:02d}" for index in range(1, 8)
    }
