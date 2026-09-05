import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import campaign_store
import judge_service
from events_normalizer import dedupe_by_id, normalize_events


def test_format_transcript_for_judge_with_normalized_steps():
    steps = [
        {"id": "1:0", "author": "user", "kind": "text", "text": "Create breast cancer awareness campaign"},
        {"id": "2:0", "author": "creative_director", "kind": "text", "text": "Consulting Brand Strategist"},
        {"id": "2:1", "author": "creative_director", "kind": "tool_call", "toolName": "brand_strategist"},
        {"id": "3:0", "author": "creative_director", "kind": "tool_result", "toolName": "brand_strategist", "text": "Audience persona: Women 25-50"},
        {"id": "4:0", "author": "creative_director", "kind": "image", "imageUrl": "https://storage.googleapis.com/test.png", "text": "Infographic concept"},
        {"id": "5:transfer", "author": "critic", "kind": "transfer"},
        {"id": "6:0", "author": "critic", "kind": "text", "text": "Approved without revisions."},
    ]
    prompt = "Create breast cancer awareness campaign"
    transcript = judge_service._format_transcript_for_judge(steps, prompt)

    assert "CAMPAIGN BRIEF PROMPT: Create breast cancer awareness campaign" in transcript
    assert "[user]: Create breast cancer awareness campaign" in transcript
    assert "[creative_director]: Consulting Brand Strategist" in transcript
    assert "[TOOL CALL - brand_strategist]" in transcript
    assert "[TOOL RESPONSE - brand_strategist]: Audience persona: Women 25-50" in transcript
    assert "[IMAGE GENERATED]: Infographic concept - URL: https://storage.googleapis.com/test.png" in transcript
    assert "[AGENT TRANSFER]: critic" in transcript
    assert "[critic]: Approved without revisions." in transcript


def test_heuristic_evaluate_with_normalized_steps():
    steps = [
        {"id": "1:0", "author": "user", "kind": "text", "text": "Launch a sustainable sneaker brand for Gen Z"},
        {"id": "2:0", "author": "creative_director", "kind": "text", "text": "Strategist researched demographic persona"},
        {"id": "3:0", "author": "creative_director", "kind": "tool_call", "toolName": "copywriter"},
        {"id": "3:1", "author": "creative_director", "kind": "tool_result", "toolName": "copywriter", "text": "Caption with hook and CTA"},
        {"id": "4:0", "author": "creative_director", "kind": "image", "imageUrl": "https://storage.googleapis.com/shoe.png", "text": "Sneaker render"},
        {"id": "5:0", "author": "critic", "kind": "text", "text": "Quality gate review approved"},
        {"id": "6:0", "author": "project_manager", "kind": "text", "text": "Notion timeline schedule created"},
    ]
    prompt = "Launch a sustainable sneaker brand for Gen Z"
    eval_result = judge_service._heuristic_evaluate(steps, prompt)

    assert eval_result["overallScore"] >= 90.0
    assert eval_result["overallGrade"] == "Excellent"
    assert len(eval_result["criteria"]) == 7
    for c in eval_result["criteria"]:
        assert c["score"] >= 75
        assert c["passed"] is True


def test_format_transcript_for_judge_with_project_manager_and_notion_deliverables():
    steps = [
        {"id": "1:0", "author": "user", "kind": "text", "text": "Create athletic shoe launch campaign"},
        {"id": "2:0", "author": "creative_director", "kind": "tool_call", "toolName": "brand_strategist"},
        {"id": "2:1", "author": "creative_director", "kind": "tool_result", "toolName": "brand_strategist", "text": "Target: Trail runners"},
        {"id": "3:0", "author": "creative_director", "kind": "tool_call", "toolName": "copywriter"},
        {"id": "3:1", "author": "creative_director", "kind": "tool_result", "toolName": "copywriter", "text": "Hook: Conquer Every Ridge"},
        {"id": "4:0", "author": "creative_director", "kind": "image", "imageUrl": "https://storage.googleapis.com/shoe.png", "text": "Shoe render"},
        {"id": "5:0", "author": "creative_director", "kind": "tool_call", "toolName": "critic"},
        {"id": "5:1", "author": "creative_director", "kind": "tool_result", "toolName": "critic", "text": "Status: APPROVED"},
        {"id": "6:0", "author": "creative_director", "kind": "tool_call", "toolName": "project_manager"},
        {
            "id": "6:1",
            "author": "creative_director",
            "kind": "tool_result",
            "toolName": "project_manager",
            "text": "**Project Timeline:**\nPhase 1: Strategy | Sept 1 -> Sept 5\n**Notion Status:** Project page created (id: 12345), 8 tasks linked to Notion database.",
        },
        {"id": "7:0", "author": "creative_director", "kind": "text", "text": "Campaign Presentation Delivered to User!"},
    ]
    prompt = "Create athletic shoe launch campaign"
    transcript = judge_service._format_transcript_for_judge(steps, prompt)

    assert "[TOOL CALL - project_manager]" in transcript
    assert "[TOOL RESPONSE - project_manager]: **Project Timeline:**" in transcript
    assert "Notion Status" in transcript
    assert "Project page created (id: 12345)" in transcript

    eval_result = judge_service._heuristic_evaluate(steps, prompt)
    assert eval_result["overallScore"] == 100.0
    c5 = next(c for c in eval_result["criteria"] if c["id"] == 5)
    assert c5["score"] == 100
    assert c5["passed"] is True


@pytest.mark.asyncio
async def test_evaluate_campaign_transcript_persists_and_returns(monkeypatch):
    session_id = "test-judge-session"
    prompt = "Test brief"
    steps = [
        {"id": "1:0", "author": "user", "kind": "text", "text": "Create brief"},
    ]
    monkeypatch.setattr(judge_service, "save_evaluation", AsyncMock())

    result = await judge_service.evaluate_campaign_transcript(session_id, prompt, steps)
    assert result["sessionId"] == session_id
    assert result["prompt"] == prompt
    assert "overallScore" in result
    assert "criteria" in result
    assert len(result["criteria"]) == 7
    judge_service.save_evaluation.assert_awaited_once()


# ---- compute_user_average_evaluation ----

def _make_evaluation(session_id: str, overall_score: float, criterion_scores: dict[int, float]) -> dict:
    return {
        "sessionId": session_id,
        "overallScore": overall_score,
        "overallGrade": judge_service._grade_from_score(overall_score),
        "criteria": [
            {"id": crit_id, "name": f"Criterion {crit_id}", "weight": 0.1, "score": score}
            for crit_id, score in criterion_scores.items()
        ],
    }


@pytest.mark.asyncio
async def test_compute_user_average_evaluation_averages_across_evaluated_runs(monkeypatch):
    monkeypatch.setattr(
        campaign_store, "list_campaigns_for_user",
        AsyncMock(return_value=[{"session_id": "s1"}, {"session_id": "s2"}, {"session_id": "s3"}]),
    )

    evaluations = {
        "s1": _make_evaluation("s1", 100.0, {1: 100, 2: 50}),
        "s2": _make_evaluation("s2", 50.0, {1: 50, 2: 50}),
        "s3": None,  # not yet evaluated -- must be excluded, not treated as 0
    }
    monkeypatch.setattr(
        judge_service, "get_cached_evaluation",
        AsyncMock(side_effect=lambda session_id: evaluations[session_id]),
    )

    result = await judge_service.compute_user_average_evaluation("user-123")

    assert result["userId"] == "user-123"
    assert result["totalRunCount"] == 3
    assert result["evaluatedRunCount"] == 2
    assert result["averageScore"] == 75.0
    assert result["averageGrade"] == "Good"
    criteria_by_id = {c["id"]: c for c in result["criteria"]}
    assert criteria_by_id[1]["averageScore"] == 75.0
    assert criteria_by_id[2]["averageScore"] == 50.0


@pytest.mark.asyncio
async def test_compute_user_average_evaluation_with_no_evaluated_runs(monkeypatch):
    monkeypatch.setattr(
        campaign_store, "list_campaigns_for_user",
        AsyncMock(return_value=[{"session_id": "s1"}]),
    )
    monkeypatch.setattr(judge_service, "get_cached_evaluation", AsyncMock(return_value=None))

    result = await judge_service.compute_user_average_evaluation("user-456")

    assert result["totalRunCount"] == 1
    assert result["evaluatedRunCount"] == 0
    assert result["averageScore"] == 0.0
    assert result["criteria"] == []


@pytest.mark.asyncio
async def test_compute_user_average_evaluation_with_no_campaigns(monkeypatch):
    monkeypatch.setattr(campaign_store, "list_campaigns_for_user", AsyncMock(return_value=[]))
    monkeypatch.setattr(judge_service, "get_cached_evaluation", AsyncMock(return_value=None))

    result = await judge_service.compute_user_average_evaluation("user-789")

    assert result["totalRunCount"] == 0
    assert result["evaluatedRunCount"] == 0
    assert result["averageScore"] == 0.0
