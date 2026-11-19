import json
import math

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.mcp_server import GUIDE_RESOURCE_URI, build_mcp_http_app, mcp
from app.services.embedding_service import embedding_service
from tests.conftest import make_pdf_bytes
from tests.test_knowledge_and_query import _wait_for_done


@pytest.mark.asyncio
async def test_mcp_has_list_and_query_tools_and_guide_resource(clean_db: None):
    """Memastikan MCP server memiliki 2 tool (list_knowledges & query_knowledge) dan deskripsinya merujuk ke resource panduan."""
    tools = await mcp.list_tools()
    assert len(tools) == 2

    tool_map = {t.name: t for t in tools}
    assert set(tool_map.keys()) == {"list_knowledges", "query_knowledge"}

    list_tool = tool_map["list_knowledges"]
    assert "knowledge_ids" in (list_tool.description or "")
    assert GUIDE_RESOURCE_URI in (list_tool.description or "")

    query_tool = tool_map["query_knowledge"]
    assert GUIDE_RESOURCE_URI in (query_tool.description or "")
    assert "list_knowledges" in (query_tool.description or "")
    assert "resource" in (query_tool.description or "").lower()

    # Pastikan skema input memiliki parameter lengkap dan merujuk ke resource panduan
    props = query_tool.input_schema.get("properties", {})
    expected_params = {
        "query",
        "knowledge_ids",
        "top_k",
        "score_threshold",
        "search_mode",
        "use_rerank",
        "use_query_expansion",
        "use_graph",
        "use_hyde",
        "expand_context",
    }
    assert expected_params.issubset(set(props.keys()))
    assert GUIDE_RESOURCE_URI in props["search_mode"]["description"]
    assert "list_knowledges" in props["knowledge_ids"]["description"]

    # Pastikan resource panduan query terdaftar dan dapat dibaca
    resources = await mcp.list_resources()
    assert len(resources) == 1
    assert str(resources[0].uri) == GUIDE_RESOURCE_URI
    assert resources[0].mime_type == "text/markdown"

    contents = await mcp.read_resource(GUIDE_RESOURCE_URI)
    assert len(contents) == 1
    guide_text = contents[0].content
    assert "Panduan Lengkap Metode & Parameter Query MiiRAG" in guide_text
    assert '"hybrid"' in guide_text
    assert '"dense"' in guide_text
    assert '"keyword"' in guide_text
    assert "`use_rerank`" in guide_text
    assert "`use_query_expansion`" in guide_text
    assert "`use_graph`" in guide_text
    assert "`use_hyde`" in guide_text
    assert "`expand_context`" in guide_text


@pytest.mark.asyncio
async def test_mcp_query_tool_execution_and_active_knowledge_in_resource(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Memastikan tool query_knowledge pada MCP berjalan end-to-end dan resource panduan menampilkan knowledge aktif."""
    dim = settings.EMBEDDING_DIMENSIONS

    def _topic_vec(text: str) -> list[float]:
        vec = [0.0] * dim
        low = text.lower()
        if "espresso" in low or "barista" in low or "sop-cafe-01" in low or "sanitasi" in low:
            vec[0] = 1.0
        else:
            vec[1] = 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec]

    async def fake_embed_documents(texts: list[str], title: str | None = None) -> list[list[float]]:
        return [_topic_vec(t) for t in texts]

    async def fake_embed_query(query: str) -> list[float]:
        return _topic_vec(query)

    monkeypatch.setattr(embedding_service, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(embedding_service, "embed_query", fake_embed_query)

    pdf_bytes = make_pdf_bytes(
        [
            (
                "Prosedur Sanitasi Mesin Espresso SOP-CAFE-01\n"
                "Setiap Head Barista wajib melakukan backflush mesin espresso setiap malam pukul 21.00 WIB "
                "menggunakan bubuk pembersih food-grade agar kualitas ekstraksi kopi tetap terjaga."
            )
        ]
    )

    create_resp = await client.post(
        "/api/v1/knowledges",
        data={
            "name": "MCP Cafe Knowledge",
            "description": "Panduan SOP Barista Cafe",
            "process_now": "true",
        },
        files=[("files", ("SOP_Barista.pdf", pdf_bytes, "application/pdf"))],
    )
    assert create_resp.status_code == 201
    knowledge_id = create_resp.json()["id"]
    await _wait_for_done(client, knowledge_id)

    # 1. Panggil tool list_knowledges melalui MCPServer
    list_call = await mcp.call_tool("list_knowledges", {"status": "done"})
    assert not list_call.is_error
    list_data = json.loads(list_call.content[0].text)
    assert list_data["total"] == 1
    assert list_data["items"][0]["id"] == knowledge_id
    assert list_data["items"][0]["name"] == "MCP Cafe Knowledge"
    assert len(list_data["items"][0]["documents"]) == 1
    assert list_data["items"][0]["documents"][0]["filename"] == "SOP_Barista.pdf"

    # 2. Baca resource panduan dan pastikan knowledge yang baru berstatus done muncul di tabel panduan
    contents = await mcp.read_resource(GUIDE_RESOURCE_URI)
    guide_text = contents[0].content
    assert "MCP Cafe Knowledge" in guide_text
    assert knowledge_id in guide_text

    # 3. Panggil tool query_knowledge melalui MCPServer menggunakan ID dari list_knowledges
    call_result = await mcp.call_tool(
        "query_knowledge",
        {
            "query": "Bagaimana prosedur sanitasi backflush mesin espresso SOP-CAFE-01?",
            "knowledge_ids": [knowledge_id],
            "top_k": 3,
            "score_threshold": 0.15,
            "search_mode": "hybrid",
            "use_rerank": False,
            "use_query_expansion": True,
            "use_graph": True,
        },
    )
    assert not call_result.is_error
    assert len(call_result.content) >= 1

    payload = json.loads(call_result.content[0].text)
    assert payload["total_results"] >= 1
    assert payload["results"][0]["filename"] == "SOP_Barista.pdf"
    assert "SOP-CAFE-01" in payload["results"][0]["content"]


@pytest.mark.asyncio
async def test_mcp_http_app_health_and_env_config():
    """Memastikan aplikasi HTTP/SSE MCP membaca konfigurasi .env (port, path, transport) dan menyediakan endpoint /health."""
    from httpx import ASGITransport

    mcp_http_app = build_mcp_http_app()
    async with AsyncClient(transport=ASGITransport(app=mcp_http_app), base_url="http://mcp-test") as ac:
        resp = await ac.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["name"] == settings.MCP_SERVER_NAME
        assert str(settings.MCP_PORT) in data["endpoints"]["streamable_http"]
        assert settings.MCP_PATH in data["endpoints"]["streamable_http"]
        assert settings.MCP_SSE_PATH in data["endpoints"]["sse"]
        assert data["tools"] == ["list_knowledges", "query_knowledge"]
        assert data["resources"] == [GUIDE_RESOURCE_URI]
