"""MQTT bridge + Home Assistant discovery.

Publishes:
  {base}/status          online / offline (last will)
  {base}/snapshot        compact JSON each tick
  {base}/alerts          last alert payload
  homeassistant/sensor/rackwatch_*/config   MQTT discovery

HA then creates entities automatically. No YAML required on the HA
side if MQTT integration is already set up.

Uses paho-mqtt in a background thread; publish() is non-blocking.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from app.config import Settings
from app.schemas import Snapshot

log = logging.getLogger("rackwatch.mqtt")


def _clean_topic(topic: str) -> str:
    cleaned = topic.strip().strip("/")
    for bad in ("#", "+", "\0"):
        cleaned = cleaned.replace(bad, "")
    return cleaned or "rackwatch"


class MqttBridge:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ok = False
        self._client = None
        self._lock = threading.Lock()

    def bind(self, settings: Settings) -> None:
        changed = (
            self.settings.mqtt_host != settings.mqtt_host
            or self.settings.mqtt_port != settings.mqtt_port
            or self.settings.mqtt_username != settings.mqtt_username
            or self.settings.mqtt_password != settings.mqtt_password
            or self.settings.mqtt_base_topic != settings.mqtt_base_topic
            or getattr(self.settings, "mqtt_tls", False) != getattr(settings, "mqtt_tls", False)
        )
        self.settings = settings
        if changed:
            self.stop()
            if self.enabled:
                self.start()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.mqtt_host)

    def start(self) -> None:
        if not self.enabled:
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            log.warning("paho-mqtt not installed")
            return

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"rackwatch-{self.settings.instance_name}")
        if self.settings.mqtt_username:
            client.username_pw_set(self.settings.mqtt_username, self.settings.mqtt_password)

        if getattr(self.settings, "mqtt_tls", False) or self.settings.mqtt_port == 8883:
            try:
                import ssl
                client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
            except Exception as exc:
                log.warning("MQTT TLS setup failed: %s", exc)

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        base_topic = _clean_topic(self.settings.mqtt_base_topic)
        client.will_set(
            f"{base_topic}/status",
            payload="offline",
            retain=True,
        )
        try:
            client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=30)
            client.loop_start()
            self._client = client
        except Exception as exc:
            log.warning("MQTT connect failed: %s", exc)
            self.ok = False

    def stop(self) -> None:
        if self._client is None:
            return
        try:
            base_topic = _clean_topic(self.settings.mqtt_base_topic)
            self._publish(f"{base_topic}/status", "offline", retain=True)
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
        self._client = None
        self.ok = False

    def _on_connect(self, client: Any, _userdata: Any, _flags: Any, reason: Any, _props: Any = None) -> None:
        rc = getattr(reason, "value", reason)
        self.ok = rc == 0
        log.info("MQTT connected rc=%s", rc)
        if self.ok:
            base_topic = _clean_topic(self.settings.mqtt_base_topic)
            self._publish(f"{base_topic}/status", "online", retain=True)
            if self.settings.mqtt_ha_discovery:
                self._announce_discovery()

    def _on_disconnect(self, _client: Any, _userdata: Any, _flags: Any, reason: Any, _props: Any = None) -> None:
        self.ok = False
        log.warning("MQTT disconnected (%s)", reason)

    def _announce_discovery(self) -> None:
        prefix = _clean_topic(self.settings.mqtt_ha_discovery_prefix)
        base = _clean_topic(self.settings.mqtt_base_topic)
        node = self.settings.instance_name
        sensors = (
            ("cpu", "CPU", "%", "mdi:cpu-64-bit", "{{ value_json.cpu }}"),
            ("ram", "RAM", "%", "mdi:memory", "{{ value_json.ram }}"),
            ("disk", "Disk", "%", "mdi:harddisk", "{{ value_json.disk }}"),
            ("containers_down", "Containers down", None, "mdi:docker", "{{ value_json.containers_down }}"),
            ("status", "Status", None, "mdi:server", "{{ value_json.overall }}"),
        )
        device = {
            "identifiers": [f"rackwatch_{node}"],
            "name": f"RackWatch {node}",
            "manufacturer": "RackWatch",
            "model": "homelab-monitor",
        }
        for key, name, unit, icon, tpl in sensors:
            payload: dict[str, Any] = {
                "name": f"RackWatch {name}",
                "unique_id": f"rackwatch_{node}_{key}",
                "state_topic": f"{base}/snapshot",
                "value_template": tpl,
                "icon": icon,
                "availability_topic": f"{base}/status",
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device,
            }
            if unit:
                payload["unit_of_measurement"] = unit
            topic = f"{prefix}/sensor/rackwatch_{node}_{key}/config"
            self._publish(topic, json.dumps(payload), retain=True)

    def publish_snapshot(self, snapshot: Snapshot) -> None:
        if not self.ok:
            return
        base = _clean_topic(self.settings.mqtt_base_topic)
        body = {
            "cpu": snapshot.summary.get("cpu"),
            "ram": snapshot.summary.get("ram"),
            "disk": snapshot.summary.get("disk"),
            "containers_down": snapshot.summary.get("containers_down"),
            "overall": snapshot.summary.get("overall"),
            "instance": snapshot.instance,
            "ts": snapshot.ts,
        }
        self._publish(f"{base}/snapshot", json.dumps(body), retain=True)

    def publish_alert(self, payload: dict[str, Any]) -> bool:
        if not self.ok:
            return False
        base = _clean_topic(self.settings.mqtt_base_topic)
        self._publish(f"{base}/alerts", json.dumps(payload), retain=False)
        return True

    def _publish(self, topic: str, payload: str, retain: bool = False) -> None:
        if self._client is None:
            return
        with self._lock:
            try:
                self._client.publish(topic, payload, qos=0, retain=retain)
            except Exception as exc:
                log.debug("MQTT publish %s failed: %s", topic, exc)
