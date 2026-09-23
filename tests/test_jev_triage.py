"""Jev triage stays a judgment. The message and the safety gate are code."""

from __future__ import annotations

from app.services.jev_triage import (
    TriageIn,
    build_triage_state,
    decide_intent,
    decide_triage,
    intent_questions,
)


def _answers(cause: str, cause_p: float, action: str, human: float, cause_conf: float = 0.9):
    return {
        "cause": {
            "choice": cause,
            "confidence": cause_conf,
            "probabilities": {cause: cause_p, "unclear": round(1 - cause_p, 2)},
        },
        "action": {"choice": action, "confidence": 0.8, "probabilities": {action: 0.8}},
        "needs_human": {"noul": human},
    }


def test_state_accepts_n8n_percent_strings():
    body = TriageIn.model_validate(
        {
            "alert": {"title": "CPU alta", "severity": "warning", "service": "n8n"},
            "summary": {"cpu_percent": 91},
            "topCpu": [{"name": "n8n", "cpu": "88.0%"}],
            "logs": "error" * 800,
        }
    )
    state = build_triage_state(body, None)
    assert state["top_cpu"] == [{"name": "n8n", "cpu_percent": 88.0}]
    assert state["alert"]["service"] == "n8n"
    assert len(state["log_tail"]) == 1500


def test_low_confidence_cause_is_not_acted_on():
    state = {"alert": {"service": "plex"}, "top_cpu": []}
    decided = decide_triage(state, _answers("single_container", 0.4, "restart_after_confirm", 0.2, 0.4))
    assert decided["needs_review"] is True
    assert decided["action"] == "human"
    assert "Sin cambios automáticos" in decided["text"]


def test_confident_log_read_names_the_container():
    state = {"alert": {"service": "adguard-home"}, "top_cpu": []}
    decided = decide_triage(state, _answers("container_down", 0.91, "read_logs", 0.2, 0.88))
    assert decided["action"] == "read_logs"
    assert "`adguard-home`" in decided["text"]
    assert decided["needs_review"] is False


def test_restart_always_asks_for_a_person():
    state = {"alert": {"service": "grafana"}, "top_cpu": []}
    decided = decide_triage(state, _answers("single_container", 0.95, "restart_after_confirm", 0.1, 0.93))
    assert decided["action"] == "restart_after_confirm"
    assert decided["needs_review"] is True


def test_intent_drops_unknown_container_and_uncertain_routes():
    names = ["adguard-home", "n8n"]
    routed = decide_intent(
        "logs de adguard",
        names,
        {
            "intent": {"choice": "logs", "confidence": 0.9},
            "container": {"choice": "adguard-home", "confidence": 0.8},
        },
    )
    assert routed["endpoint"] == "/api/v1/containers/adguard-home/logs?lines=30"
    unsure = decide_intent(
        "hola",
        names,
        {
            "intent": {"choice": "status", "confidence": 0.4},
            "container": {"choice": "n8n", "confidence": 0.2},
        },
    )
    assert unsure["intent"] == "unknown"
    assert unsure["endpoint"] is None


def test_intent_questions_reject_odd_names():
    questions = intent_questions(["n8n", "has space", "../x"])
    assert set(questions["container"]["criteria"]) == {"none", "n8n"}


def test_triage_without_key_is_unavailable(client):
    res = client.post(
        "/api/v1/triage",
        headers={"X-API-Key": "test-token"},
        json={"alert": {"title": "CPU", "service": "n8n"}},
    )
    assert res.status_code == 503
    assert "TYPESAFE_API_KEY" in res.json()["detail"]
