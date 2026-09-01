import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
