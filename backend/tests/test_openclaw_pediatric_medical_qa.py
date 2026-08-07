from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.routers.conversations import _normalize_workflow_type  # noqa: E402
from app.services.openclaw_gateway import build_pediatric_medical_qa_input  # noqa: E402


def test_pediatric_medical_qa_workflow_is_accepted():
    assert _normalize_workflow_type("pediatric_medical_qa") == "pediatric_medical_qa"
    assert _normalize_workflow_type("pediatric-medical-qa") == "pediatric_medical_qa"


def test_pediatric_medical_qa_input_stays_agent_skill_driven():
    text = build_pediatric_medical_qa_input(
        content="孩子发烧38.5度怎么办？",
        history_messages=[{"role": "assistant", "content": "请补充年龄。"}],
    )

    assert "少儿问诊智能体" in text
    assert "孩子发烧38.5度怎么办？" in text
    assert "请补充年龄" in text
    assert "pediatric-medical-qa" in text
    assert "document_render_docx" not in text
    assert "synthesize_speech" not in text



def test_direct_pediatric_qa_accepts_non_stream_response(monkeypatch):
    from app.services import openclaw_gateway

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return '{"choices":[{"message":{"role":"assistant","content":"建议观察体温。"},"finish_reason":"stop"}]}'.encode("utf-8")

        def __iter__(self):
            return iter(())

    def fake_urlopen(req, timeout):
        captured["payload"] = req.data.decode("utf-8")
        return FakeResponse()

    monkeypatch.setattr(openclaw_gateway.request, "urlopen", fake_urlopen)

    chunks = list(openclaw_gateway.iter_direct_pediatric_qa_events("孩子发烧怎么办？", []))

    assert chunks == ["建议观察体温。"]
    assert '"stream": false' in captured["payload"]
