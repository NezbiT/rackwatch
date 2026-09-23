"""Structured homelab triage with TypeSafe Jev.

Jev picks a cause and a safe next step. This module writes the message
and never restarts a container. A low-confidence cause becomes a request
for a person to look.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.schemas import Snapshot

TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
CAUSE_CONFIDENCE_MIN = 0.6
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")

CAUSES: dict[str, str] = {
    "single_container": "One container accounts for the load or the failure",
    "host_cpu": "Host CPU is saturated across more than one container",
    "host_memory": "Host memory is under pressure",
    "disk": "Disk space or disk health is the problem",
    "container_down": "A container is stopped, restarting, or unhealthy",
    "unclear": "The evidence does not identify a single cause",
}

ACTIONS: dict[str, str] = {
    "watch": "Keep monitoring and do not change anything yet",
    "read_logs": "Read the logs of the container named in the alert or the top consumer",
    "restart_after_confirm": "Restart the named container only after a person confirms",
    "check_disk": "Check what is filling the disk",
    "human": "A person should look; do not automate a change",
}

CAUSE_ES = {
    "single_container": "un contenedor concentra el problema",
    "host_cpu": "la CPU del host está saturada",
    "host_memory": "falta memoria en el host",
    "disk": "el problema está en el disco",
    "container_down": "un contenedor está caído o reiniciando",
    "unclear": "la evidencia no señala una sola causa",
}

ACTION_ES = {
    "watch": "seguir mirando, sin cambios",
    "read_logs": "leer los logs",
    "restart_after_confirm": "reiniciar solo después de que alguien confirme",
    "check_disk": "revisar qué está llenando el disco",
    "human": "que lo revise una persona, sin cambios automáticos",
}

INTENTS: dict[str, str] = {
    "status": "Overall host status: CPU, memory, disk, or uptime",
    "cpu": "Which containers are using the most CPU",
    "memory": "Which containers are using the most memory",
    "alerts": "Current or recent alerts",
    "logs": "Logs, errors, or why a specific container failed",
    "help": "What the bot can do, or a list of commands",
    "unknown": "Greeting, thanks, or not a question about this homelab",
}

INTENT_ENDPOINTS = {
    "status": "/api/v1/snapshot",
    "cpu": "/api/v1/snapshot",
    "memory": "/api/v1/snapshot",
    "alerts": "/api/v1/alerts",
    "logs": None,
    "help": None,
    "unknown": None,
}


class TriageError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class ContainerBit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_bytes: int | None = None
    status: str = ""
    severity: str = ""
    cpu: str | None = None
    ram: str | None = None


class AlertBit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = "Alerta RackWatch"
    message: str = ""
    severity: str = "warning"
    source: str = ""
    service: str = ""
    host: str = ""


class TriageIn(BaseModel):
    """Accepts the JSON already built by the n8n 'Preparar Alerta' node."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    alert: AlertBit = Field(default_factory=AlertBit)
    summary: dict[str, Any] = Field(default_factory=dict)
    top_cpu: list[ContainerBit] = Field(default_factory=list, alias="topCpu")
    top_ram: list[ContainerBit] = Field(default_factory=list, alias="topRam")
    bad_containers: list[ContainerBit] = Field(default_factory=list, alias="badContainers")
    containers: list[ContainerBit] | None = None
    log_tail: str = Field(default="", max_length=4000)
    logs: str = Field(default="", max_length=4000)


class IntentIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1, max_length=500)
    containers: list[str] | None = None


def _pct(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


def _clean_name(raw: str) -> str:
    name = raw.strip()
    return name if _NAME.match(name) else ""


def _rows(items: list[ContainerBit], kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items[:5]:
        name = _clean_name(item.name)
        if not name:
            continue
        if kind == "cpu":
            value = item.cpu_percent if item.cpu_percent is not None else _pct(item.cpu)
            rows.append({"name": name, "cpu_percent": value})
        else:
            value = item.memory_percent if item.memory_percent is not None else _pct(item.ram)
            rows.append({"name": name, "memory_percent": value})
    return rows


def evidence_from_snapshot(snap: Snapshot) -> dict[str, Any]:
    containers = list(snap.containers)
    top_cpu = sorted(
        (c for c in containers if c.cpu_percent),
        key=lambda c: c.cpu_percent or 0,
        reverse=True,
    )[:5]
    top_ram = sorted(
        (c for c in containers if c.memory_bytes or c.memory_percent),
        key=lambda c: c.memory_bytes or c.memory_percent or 0,
        reverse=True,
    )[:5]
    bad = [c for c in containers if c.severity and c.severity != "ok"][:8]
    host = snap.hosts[0] if snap.hosts else None
    summary = dict(snap.summary)
    if host is not None:
        summary.setdefault("cpu_percent", host.cpu_percent)
        summary.setdefault("ram_percent", host.ram_percent)
        summary.setdefault("disk_percent", host.disk_percent)
    return {
        "summary": {
            "cpu_percent": summary.get("cpu_percent"),
            "ram_percent": summary.get("ram_percent"),
            "disk_percent": summary.get("disk_percent"),
        },
        "top_cpu": [{"name": c.name, "cpu_percent": c.cpu_percent} for c in top_cpu],
        "top_ram": [
            {"name": c.name, "memory_percent": c.memory_percent, "memory_bytes": c.memory_bytes}
            for c in top_ram
        ],
        "unhealthy": [
            {"name": c.name, "status": c.status, "severity": c.severity} for c in bad
        ],
        "container_names": [_clean_name(c.name) for c in containers if _clean_name(c.name)][:40],
    }


def build_triage_state(body: TriageIn, snap: Snapshot | None) -> dict[str, Any]:
    live = evidence_from_snapshot(snap) if snap is not None else {}
    top_cpu = _rows(body.top_cpu, "cpu") or live.get("top_cpu") or []
    top_ram = _rows(body.top_ram, "ram") or live.get("top_ram") or []
    unhealthy = [
        {"name": _clean_name(c.name), "status": c.status, "severity": c.severity}
        for c in body.bad_containers
        if _clean_name(c.name)
    ] or live.get("unhealthy") or []
    if body.containers:
        named = [_clean_name(c.name) for c in body.containers if _clean_name(c.name)]
    else:
        named = live.get("container_names") or []
    summary = {
        "cpu_percent": _pct(body.summary.get("cpu_percent")),
        "ram_percent": _pct(body.summary.get("ram_percent")),
        "disk_percent": _pct(body.summary.get("disk_percent")),
    }
    if summary["cpu_percent"] is None and summary["ram_percent"] is None and summary["disk_percent"] is None:
        summary = live.get("summary") or summary
    log_tail = (body.log_tail or body.logs or "")[-1500:]
    service = _clean_name(body.alert.service)
    return {
        "alert": {
            "title": body.alert.title[:200],
            "message": body.alert.message[:500],
            "severity": body.alert.severity,
            "source": body.alert.source,
            "service": service,
            "host": body.alert.host[:80],
        },
        "host": summary,
        "top_cpu": top_cpu,
        "top_ram": top_ram,
        "unhealthy_containers": unhealthy,
        "known_containers": named[:40],
        "log_tail": log_tail,
    }


def triage_questions() -> dict[str, Any]:
    return {
        "cause": {
            "type": "choice",
            "instructions": "What is the single most likely cause of this RackWatch alert",
            "criteria": CAUSES,
        },
        "action": {
            "type": "choice",
            "instructions": "Which one safe next step should a person take",
            "criteria": ACTIONS,
        },
        "needs_human": {
            "type": "noul",
            "instructions": "A person should review this before any container or host change",
        },
    }


def decide_triage(state: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    cause = answers["cause"]
    action = answers["action"]
    needs_human = float(answers["needs_human"]["noul"])
    cause_id = str(cause["choice"])
    action_id = str(action["choice"])
    cause_confidence = float(cause.get("confidence") or 0)
    if cause_id not in CAUSES:
        cause_id = "unclear"
    if action_id not in ACTIONS:
        action_id = "human"
    needs_review = (
        cause_id == "unclear"
        or cause_confidence < CAUSE_CONFIDENCE_MIN
        or action_id in {"restart_after_confirm", "human"}
        or needs_human >= 0.5
    )
    shown = "human" if cause_id == "unclear" or cause_confidence < CAUSE_CONFIDENCE_MIN else action_id
    target = state["alert"].get("service") or ""
    if not target and state["top_cpu"]:
        target = state["top_cpu"][0]["name"]
    action_text = ACTION_ES[shown]
    if shown in {"read_logs", "restart_after_confirm"} and target:
        action_text = f"{action_text} de `{target}`"
    probability = float((cause.get("probabilities") or {}).get(cause_id, 0))
    text = (
        f"Causa: {CAUSE_ES[cause_id]} ({int(round(probability * 100))}%).\n"
        f"Acción: {action_text}."
    )
    if needs_review:
        text += "\nSin cambios automáticos: hace falta que lo vea una persona."
    return {
        "cause": cause_id,
        "cause_confidence": cause_confidence,
        "cause_probabilities": cause.get("probabilities") or {},
        "action": shown,
        "action_confidence": float(action.get("confidence") or 0),
        "needs_human": needs_human,
        "needs_review": needs_review,
        "target": target,
        "text": text,
    }


def container_names(body: IntentIn, snap: Snapshot | None) -> list[str]:
    raw = body.containers
    if raw is None and snap is not None:
        raw = [c.name for c in snap.containers]
    names: list[str] = []
    for item in raw or []:
        name = _clean_name(str(item))
        if name and name not in names:
            names.append(name)
        if len(names) == 40:
            break
    return names


def intent_questions(names: list[str]) -> dict[str, Any]:
    criteria = {"none": "No specific container is named"}
    for raw in names:
        name = _clean_name(raw)
        if name:
            criteria[name] = f"The question is about the container {name}"
    return {
        "intent": {
            "type": "choice",
            "instructions": "What RackWatch information is this message asking for",
            "criteria": INTENTS,
        },
        "container": {
            "type": "choice",
            "instructions": "Which container, if any, the message names",
            "criteria": criteria,
        },
    }


def decide_intent(text: str, names: list[str], answers: dict[str, Any]) -> dict[str, Any]:
    intent = str(answers["intent"]["choice"])
    container = str(answers["container"]["choice"])
    intent_confidence = float(answers["intent"].get("confidence") or 0)
    if intent not in INTENTS:
        intent = "unknown"
    if container not in names:
        container = "none"
    if intent_confidence < CAUSE_CONFIDENCE_MIN:
        intent = "unknown"
        container = "none"
    endpoint = INTENT_ENDPOINTS[intent]
    if intent == "logs" and container != "none":
        endpoint = f"/api/v1/containers/{container}/logs?lines=30"
    return {
        "text": text,
        "intent": intent,
        "intent_confidence": intent_confidence,
        "container": container,
        "endpoint": endpoint,
        "needs_review": intent == "unknown",
    }


async def ask_jev(api_key: str, model: str, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
    if not api_key:
        raise TriageError(503, "TYPESAFE_API_KEY is not set")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(
                TYPESAFE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"state": state, "model": model or "jev-latest", "questions": questions},
            )
            res.raise_for_status()
            payload = res.json()
    except TriageError:
        raise
    except Exception as exc:
        raise TriageError(502, "TypeSafe triage request failed") from exc
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise TriageError(502, "TypeSafe triage response had no answers")
    return answers


async def run_triage(
    api_key: str,
    model: str,
    body: TriageIn,
    snap: Snapshot | None,
) -> dict[str, Any]:
    state = build_triage_state(body, snap)
    answers = await ask_jev(api_key, model, state, triage_questions())
    try:
        decided = decide_triage(state, answers)
    except (KeyError, TypeError, ValueError) as exc:
        raise TriageError(502, "TypeSafe triage response was incomplete") from exc
    return decided


async def run_intent(
    api_key: str,
    model: str,
    body: IntentIn,
    snap: Snapshot | None,
) -> dict[str, Any]:
    names = container_names(body, snap)
    answers = await ask_jev(api_key, model, body.text.strip(), intent_questions(names))
    try:
        return decide_intent(body.text.strip(), names, answers)
    except (KeyError, TypeError, ValueError) as exc:
        raise TriageError(502, "TypeSafe intent response was incomplete") from exc
