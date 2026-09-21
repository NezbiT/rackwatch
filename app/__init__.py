"""RackWatch application package.

Self-hosted homelab monitor: Prometheus metrics, Docker restarts,
webhook alerts, and MQTT telemetry.

The public HTTP surface lives in `app.main:app`. Background work
(collector, restarter, alerter, MQTT) is started from the FastAPI
lifespan in `app.main`.
"""

__version__ = "0.1.0"
__app_name__ = "RackWatch"
