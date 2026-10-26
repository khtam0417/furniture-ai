"""Design helper: questions never change anything; changes are typed proposals applied once after review
(MOCKED gpt-6-luna via FunctionModel; nothing leaves the machine)."""

import json

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from test_design_refine import ONE_BED, client, setup

from furnishai.app import create_app
from furnishai.config import Settings

UNIT = "Apt 9Z-PRIVATE"


def ask(c, aid, s, msg, step="choose"):
    return c.post(f"/api/apartments/{aid}/design/assistant", json={"message": msg, "step": step,
                                                                    "expected_version": s["design"]["version"]})


QUESTION = {"reply": "Use “Find furniture” under Choose furniture. See https://evil.example/deal <b>now</b>",
            "intent": "answer", "actions": [{"kind": "add_piece", "category": "desk"},  # a misbehaving model
                                            {"kind": "go_to", "value": "choose"}]}
CHANGE = {"reply": "I can add a desk, set the budget to $2,800 and add the modern style.", "intent": "change",
          "actions": [{"kind": "add_piece", "category": "desk", "room": "Living"}, {"kind": "set_budget", "amount_usd": 2800},
                      {"kind": "add_style", "style": "modern"}, {"kind": "add_piece", "category": "jacuzzi"},
                      {"kind": "add_style", "style": "gothic"}]}


def test_a_question_gets_an_answer_and_changes_nothing(tmp_path):
    c, app, calls = client(tmp_path, [ONE_BED, QUESTION])
    aid, anchor, s = setup(c, unit=UNIT)
    r = ask(c, aid, s, "How do I find a sofa?").json()
    assert r["intent"] == "answer" and r["mode"] == "mocked" and r["proposal_id"] is None
    assert [p["kind"] for p in r["proposals"]] == ["go_to"]  # navigation only; the stray add_piece was dropped
    assert any("not proposed for a question" in x for x in r["dropped"])
    assert "evil.example" not in r["reply"] and "<b>" not in r["reply"] and "[link removed]" in r["reply"]
    assert c.get(f"/api/apartments/{aid}/design").json()["design"]["version"] == s["design"]["version"]


def test_proposed_changes_apply_exactly_once_after_review(tmp_path):
    c, app, calls = client(tmp_path, [ONE_BED, CHANGE])
    aid, anchor, s = setup(c, unit=UNIT)
    r = ask(c, aid, s, "Add a desk in the living room, make my budget 2800 and add modern").json()
    kinds = [p["kind"] for p in r["proposals"]]
    assert kinds == ["add_piece", "set_budget", "add_style"] and r["proposal_id"]  # jacuzzi and "gothic" were refused
    assert len(r["dropped"]) == 2
    v = s["design"]["version"]
    assert c.get(f"/api/apartments/{aid}/design").json()["design"]["version"] == v  # proposing changes nothing
    # Another browser session can't apply (or even see) this design's proposals.
    assert TestClient(app).post(f"/api/apartments/{aid}/design/assistant/apply",
                                json={"expected_version": v, "proposal_id": r["proposal_id"], "accept": [0]}).status_code == 404
    a = c.post(f"/api/apartments/{aid}/design/assistant/apply",
               json={"expected_version": v, "proposal_id": r["proposal_id"], "accept": [0, 1, 2]})
    assert a.status_code == 200, a.text
    st = a.json()
    assert st["design"]["version"] == v + 1
    d = st["design"]["data"]
    assert sum(1 for i in d["items"] if i["category"] == "desk") == 1 and d["prefs"]["budget_cents"] == 280000
    assert "modern" in d["prefs"]["styles"] and any(ch.startswith("Applied:") for ch in st["changes"])
    # Searches and "Choose for me" plan from the SAVED $2,800 (minus the 10% reserve), not an older budget.
    t = st["evaluation"]["targets"]
    assert t and sum(x["target_cents"] for x in t.values()) <= 252000 and {x["left_cents"] for x in t.values()} == {252000}
    again = c.post(f"/api/apartments/{aid}/design/assistant/apply",
                   json={"expected_version": v + 1, "proposal_id": r["proposal_id"], "accept": [0, 1, 2]})
    assert again.status_code == 409  # made for an older version: never applied twice
    stale = c.post(f"/api/apartments/{aid}/design/assistant/apply",
                   json={"expected_version": v, "proposal_id": r["proposal_id"], "accept": [0]})
    assert stale.status_code == 409
    after = c.get(f"/api/apartments/{aid}/design").json()["design"]["data"]
    assert sum(1 for i in after["items"] if i["category"] == "desk") == 1  # still exactly one desk
    assert ask(c, aid, {"design": {"version": v}}, "hi").status_code == 409  # asking about an old version too


def test_the_model_sees_the_design_but_not_the_address_unit_or_sources(tmp_path):
    prompts = []
    out = {"reply": "Your budget isn’t set yet.", "intent": "answer", "actions": []}

    def fn(messages, info):
        prompts.append(json.dumps([str(m) for m in messages]))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(ONE_BED if len(prompts) == 1 else out))])
    s_ = Settings(storage_dir=tmp_path / "s", portkey_api_key=None, live_disabled=True)
    c = TestClient(create_app(s_, test_model=FunctionModel(fn)))
    aid, anchor, s = setup(c, unit=UNIT)
    r = ask(c, aid, s, "What's my budget?").json()
    p = prompts[-1]
    assert r["reply"] == "Your budget isn’t set yet." and "CURRENT DESIGN" in p and "queen bed frame" in p
    for private in ("PRIVATE", "The Example", "06511", "New Haven", "/storage", "/Users", "src_", ".png", "http"):
        assert private not in p, private


def test_unsupported_requests_are_said_plainly_and_without_ai_it_points_to_the_step(tmp_path):
    out = {"reply": "I can’t buy things, but I can take you to the checklist.", "intent": "unsupported",
           "actions": [{"kind": "set_budget", "amount_usd": 100}, {"kind": "go_to", "value": "list"}]}
    c, app, calls = client(tmp_path, [ONE_BED, out])
    aid, anchor, s = setup(c, unit=UNIT)
    r = ask(c, aid, s, "Buy everything for me").json()
    assert r["intent"] == "unsupported" and [p["kind"] for p in r["proposals"]] == ["go_to"] and r["proposal_id"] is None
    # No AI connected at all (no test model, no key): a plain pointer, never a fake action.
    from conftest import make_image
    c2 = TestClient(create_app(Settings(storage_dir=tmp_path / "off", portkey_api_key=None, live_disabled=True)))
    a = c2.post("/api/apartments", json={"name": "Flat", "preset": "1b1b", "context": {
        "property_name": "", "city": "", "state": "", "zip": "", "unit_label": UNIT, "property_url": "",
        "condition": "either", "fulfillment": "either", "timing": ""}}).json()
    aid2, anchor2 = a["apartment"]["id"], a["rooms"][0]["project_id"]
    up = c2.post(f"/api/projects/{anchor2}/uploads", data={"kind": "floorplan"},
                 files=[("files", ("plan.png", make_image("PNG", size=(640, 480)), "image/png"))]).json()
    st2 = c2.post(f"/api/apartments/{aid2}/design/plan", json={"source_id": up["results"][0]["id"]}).json()  # not read
    r2 = ask(c2, aid2, st2, "where do I change my budget?").json()
    assert r2["mode"] == "offline" and "isn’t connected" in r2["reply"]
    assert r2["proposals"] == [{"kind": "go_to", "step": "choose", "label": "Go to Choose furniture", "nav": True}]
    assert r2["proposal_id"] is None
