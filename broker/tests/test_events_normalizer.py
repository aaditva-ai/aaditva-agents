"""Tests for events_normalizer.py against realistic event shapes.

The dict shapes below mirror actual `sessions.events.list` output captured
by scripts/spikes/ against the live Agent Engine (snake_case field names:
`function_call`, `function_response`, `name` as a full
`.../events/{id}` resource path) -- not guessed at, since Step 1 confirmed
the exact wire shape before any of this was written.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from events_normalizer import dedupe_by_id, normalize_events  # noqa: E402

SESSION_PREFIX = "projects/p/locations/l/reasoningEngines/e/sessions/s/events"


def _event(event_id: str, author: str, parts: list[dict], timestamp: str = "2026-08-29T00:00:00Z", actions: dict | None = None):
    return {
        "name": f"{SESSION_PREFIX}/{event_id}",
        "author": author,
        "timestamp": timestamp,
        "content": {"parts": parts},
        "actions": actions or {},
    }


def test_user_text_event_becomes_text_step():
    events = [_event("1", "user", [{"text": "Create a campaign for X"}])]
    steps = normalize_events(events)
    assert steps == [{
        "id": "1:0", "author": "user", "kind": "text",
        "text": "Create a campaign for X", "timestamp": "2026-08-29T00:00:00Z",
    }]


def test_function_call_becomes_tool_call_step():
    events = [_event("2", "creative_director", [
        {"text": "Calling the strategist"},
        {"function_call": {"name": "brand_strategist", "args": {}}},
    ])]
    steps = normalize_events(events)
    kinds = [(s["kind"], s.get("toolName")) for s in steps]
    assert kinds == [("text", None), ("tool_call", "brand_strategist")]


def test_function_response_becomes_tool_result_step_with_result_text():
    events = [_event("3", "creative_director", [
        {"function_response": {"name": "brand_strategist", "response": {"result": "Strategy: ..."}}},
    ])]
    steps = normalize_events(events)
    assert steps[0]["kind"] == "tool_result"
    assert steps[0]["toolName"] == "brand_strategist"
    assert steps[0]["text"] == "Strategy: ..."


def test_get_image_links_response_becomes_image_steps():
    events = [_event("4", "creative_director", [
        {"function_response": {
            "name": "get_image_links",
            "response": {
                "status": "success",
                "signed": True,
                "links": [
                    {"concept": "hydration", "title": "Post 1", "url": "https://storage.googleapis.com/a.png?sig=1"},
                    {"concept": "focus", "title": "Post 2", "url": "https://storage.googleapis.com/b.png?sig=2"},
                ],
            },
        }},
    ])]
    steps = normalize_events(events)
    assert len(steps) == 2
    assert all(s["kind"] == "image" for s in steps)
    assert steps[0]["imageUrl"] == "https://storage.googleapis.com/a.png?sig=1"
    assert steps[0]["text"] == "Post 1"
    assert steps[1]["imageUrl"] == "https://storage.googleapis.com/b.png?sig=2"


def test_display_image_tool_result_is_a_plain_tool_result_not_an_image():
    """display_image's own function_response carries only
    {"status": "success", "concept_name": "..."} -- no bytes, no URL (Step
    1 finding). Only get_image_links should ever produce an "image" step.
    """
    events = [_event("5", "creative_director", [
        {"function_response": {"name": "display_image", "response": {"status": "success", "concept_name": "hydration"}}},
    ])]
    steps = normalize_events(events)
    assert steps[0]["kind"] == "tool_result"
    assert steps[0]["toolName"] == "display_image"


def test_artifact_delta_alone_produces_no_image_step():
    """actions.artifact_delta carries only {"filename.png": version} -- no
    URL -- so it must never be surfaced as a renderable image on its own.
    """
    events = [_event("6", "creative_director", [{"text": "generated an image"}],
                      actions={"artifact_delta": {"hydration.png": 0}})]
    steps = normalize_events(events)
    assert len(steps) == 1
    assert steps[0]["kind"] == "text"
    assert not any(s["kind"] == "image" for s in steps)


def test_compaction_event_is_filtered_typed_field():
    class FakeActions:
        compaction = object()
        transfer_agent = None

    events = [{
        "name": f"{SESSION_PREFIX}/7",
        "author": "creative_director",
        "timestamp": "t",
        "content": {"parts": [{"text": "summary of prior turns"}]},
        "actions": FakeActions(),
    }]
    steps = normalize_events(events)
    assert steps == []


def test_compaction_event_is_filtered_raw_fallback():
    events = [_event("8", "creative_director", [{"text": "summary"}])]
    events[0]["raw_event"] = {"actions": {"compaction": {"summary": "..."}}}
    steps = normalize_events(events)
    assert steps == []


def test_transfer_with_no_content_parts_still_surfaces():
    events = [_event("9", "creative_director", [], actions={"transfer_agent": "designer"})]
    steps = normalize_events(events)
    assert steps == [{"id": "9:transfer", "author": "creative_director", "kind": "transfer", "timestamp": "2026-08-29T00:00:00Z"}]


def test_multiple_parts_in_one_event_each_get_distinct_ids():
    events = [_event("10", "creative_director", [
        {"function_call": {"name": "display_image", "args": {}}},
        {"function_call": {"name": "display_image", "args": {}}},
    ])]
    steps = normalize_events(events)
    ids = [s["id"] for s in steps]
    assert ids == ["10:0", "10:1"]
    assert len(set(ids)) == 2


def test_dedupe_by_id_keeps_first_occurrence_and_order():
    steps = [
        {"id": "a", "v": 1}, {"id": "b", "v": 2}, {"id": "a", "v": 3}, {"id": "c", "v": 4},
    ]
    deduped = dedupe_by_id(steps)
    assert [s["id"] for s in deduped] == ["a", "b", "c"]
    assert deduped[0]["v"] == 1  # first occurrence wins


def test_dedupe_is_idempotent_across_overlapping_cursor_pages():
    """Simulates two overlapping pages from a poll -- the second page
    re-includes the last event of the first page.
    """
    page1 = normalize_events([_event("1", "user", [{"text": "hi"}])])
    page2 = normalize_events([
        _event("1", "user", [{"text": "hi"}]),
        _event("2", "creative_director", [{"text": "hello"}]),
    ])
    combined = dedupe_by_id(page1 + page2)
    assert [s["id"] for s in combined] == ["1:0", "2:0"]


def test_empty_events_list_returns_empty_steps():
    assert normalize_events([]) == []


def test_event_with_no_content_and_no_actions_produces_no_steps():
    events = [{"name": f"{SESSION_PREFIX}/11", "author": "user", "timestamp": "t"}]
    assert normalize_events(events) == []
