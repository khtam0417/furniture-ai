"""The runtime model is gpt-6-luna through Portkey, for BOTH agents, verified on the actual outbound requests.

The real OpenAI-SDK/PydanticAI client is built (no TestModel); a capturing httpx2 transport stands in for the
network, so nothing leaves the machine. The API key is a fake test value and is never printed.
"""

import json

import httpx2
import pytest
from fastapi.testclient import TestClient

from furnishai import config
from furnishai.app import create_app
from furnishai.config import Settings

from conftest import make_image

FAKE_KEY = "test-key-not-a-real-credential"
DECOY = "unauthorized-model"


class Gateway:
    """Records each outbound request and answers like the Responses API with a schema-valid tool call."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append({"url": str(request.url), "method": request.method, "headers": dict(request.headers), "body": body})
        args = self.answers.pop(0)
        tools = [t for t in body.get("tools", []) if t.get("type") == "function"]
        if tools:
            output = [{"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": tools[0]["name"],
                       "arguments": json.dumps(args), "status": "completed"}]
        else:
            output = [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": json.dumps(args), "annotations": []}]}]
        return httpx2.Response(200, json={
            "id": f"resp_test_{len(self.requests)}", "object": "response", "created_at": 1761350400, "status": "completed",
            "model": body.get("model"), "output": output, "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
            "usage": {"input_tokens": 1200, "input_tokens_details": {"cached_tokens": 200}, "output_tokens": 80,
                      "output_tokens_details": {"reasoning_tokens": 10}, "total_tokens": 1280}})


@pytest.fixture
def decoy_env(monkeypatch):
    # Every plausible override knob points at an unauthorized model; none may take effect.
    for var in ("MODEL", "MODEL_NAME", "OPENAI_MODEL", "FURNISHAI_MODEL", "PYDANTIC_AI_MODEL", "PORTKEY_MODEL"):
        monkeypatch.setenv(var, DECOY)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")


def test_photo_and_preference_agents_send_gpt_6_luna_to_portkey(tmp_path, decoy_env):
    gateway = Gateway([{"room_type_seen": "bedroom"}, {"add_styles": ["modern"], "summary": "Added modern."}])
    settings = Settings(storage_dir=tmp_path / "s", portkey_api_key=FAKE_KEY, live_disabled=False)
    c = TestClient(create_app(settings, ai_transport=httpx2.MockTransport(gateway)))

    pid = c.post("/api/projects", json={"name": "Live", "room_type": "bedroom"}).json()["project"]["id"]
    c.post(f"/api/projects/{pid}/uploads", data={"kind": "photo"},
           files=[("files", ("a.jpg", make_image(), "image/jpeg")), ("files", ("b.jpg", make_image(color=(9, 9, 9)), "image/jpeg"))])
    analyzed = c.post(f"/api/projects/{pid}/analyze", json={})
    assert analyzed.status_code == 200 and analyzed.json()["state"]["room"]["method"] == "live_ai"
    edited = c.post(f"/api/projects/{pid}/edit", json={"message": "add a modern touch"})
    assert edited.status_code == 200 and edited.json()["method"] == "live_ai"

    assert len(gateway.requests) == 2  # one bounded call per agent, nothing else went out
    photo, pref = gateway.requests
    for r in (photo, pref):
        assert r["method"] == "POST" and r["url"] == f"{config.PORTKEY_BASE_URL}/responses"
        assert r["body"]["model"] == "gpt-6-luna" == config.MODEL
        assert DECOY not in json.dumps(r["body"]) and "example.invalid" not in r["url"]
        assert r["headers"]["x-portkey-provider"] == "openai"
        assert r["headers"]["x-portkey-api-key"] == FAKE_KEY and r["headers"]["authorization"] == f"Bearer {FAKE_KEY}"
    # The photo agent really sends image pixels (vision); the preference agent sends text only.
    photo_parts = [p for item in photo["body"]["input"] if isinstance(item.get("content"), list) for p in item["content"]]
    assert sum(1 for p in photo_parts if p.get("type") == "input_image") == 2
    assert all(p.get("image_url", "").startswith("data:image/jpeg;base64,") for p in photo_parts if p.get("type") == "input_image")
    assert "input_image" not in json.dumps(pref["body"])
    assert "Room Evidence inspector" in json.dumps(photo["body"]) and "PreferencePatch" in json.dumps(pref["body"])
    assert photo["body"]["tools"] and pref["body"]["tools"]  # structured output tool only (no model-callable app tools)
    assert all(len(r["body"]["tools"]) == 1 for r in (photo, pref))

    # Real token accounting from the returned usage (cached tokens only because the response returned them).
    calls = c.get(f"/api/projects/{pid}/usage").json()["calls"]
    assert [x["purpose"] for x in calls] == ["room_analysis", "preference_edit"]
    assert all(x["input_tokens"] == 1200 and x["cached_input_tokens"] == 200 and x["output_tokens"] == 80 for x in calls)
    assert all(x["estimated_cost_usd"] == pytest.approx((1000 * 0.10 + 200 * 0.01 + 80 * 0.50) / 1e6) for x in calls)


def test_no_code_path_reads_a_model_name_from_settings_or_environment(tmp_path, decoy_env):
    s = config.get_settings(tmp_path, environ={"PORTKEY_API_KEY": FAKE_KEY, "MODEL_NAME": DECOY, "OPENAI_MODEL": DECOY})
    assert s.public_status()["model"] == "gpt-6-luna"
    assert not any(DECOY in str(v) for v in vars(s).values())
