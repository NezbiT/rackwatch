# Home Assistant integration

RackWatch talks to HA in both directions. Nothing HA-side is required except a long-lived token (REST) and, optionally, an MQTT broker already used by HA.

---

## REST (always start here)

1. HA → your profile → **Security** → **Long-lived access tokens** → create “RackWatch”.
2. Settings in RackWatch (or `.env`):

```env
HA_URL=http://192.168.1.20:8123
HA_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
HA_NOTIFY_SERVICE=notify.mobile_app_pixel
HA_PINNED_ENTITIES=sensor.office_temp,switch.desk_lamp,binary_sensor.leak_laundry
```

Empty `HA_PINNED_ENTITIES` = auto-pick the first 24 entities in `sensor`, `binary_sensor`, `switch`, `light`, `climate`, `cover`, `fan`, `lock`.

### What REST does

| Direction | Endpoint | Purpose |
|---|---|---|
| Pull | `GET /api/states` | Dashboard + `/home-assistant` cards |
| Push | `POST /api/states/sensor.rackwatch_*` | HA sees live CPU/RAM/disk/status |
| Push | `POST /api/services/<notify>` | Phone / TTS / Telegram via HA |

Entities created on the HA side:

- `sensor.rackwatch_cpu` (%)
- `sensor.rackwatch_ram` (%)
- `sensor.rackwatch_disk` (%)
- `sensor.rackwatch_containers_down`
- `sensor.rackwatch_status` (`ok` / `warning` / `error`)

Use them in HA automations as you would any other sensor:

```yaml
automation:
  - alias: RackWatch is unhappy
    trigger:
      - platform: state
        entity_id: sensor.rackwatch_status
        to: "error"
    action:
      - service: notify.mobile_app_pixel
        data:
          title: RackWatch
          message: "A host or container is down."
```

---

## Notify service names

`HA_NOTIFY_SERVICE` is `domain.service`:

| You want | Value |
|---|---|
| Default persistent notification | `notify.notify` |
| Companion app | `notify.mobile_app_<device>` |
| HA Telegram bot | `notify.telegram` |
| A notify group | `notify.family` |

---

## MQTT + discovery (optional, nicer)

If HA already has MQTT (Mosquitto add-on, or the compose profile):

```env
MQTT_HOST=core-mosquitto
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_BASE_TOPIC=rackwatch
MQTT_HA_DISCOVERY=true
MQTT_HA_DISCOVERY_PREFIX=homeassistant
```

On connect RackWatch publishes retained discovery configs:

```
homeassistant/sensor/rackwatch_<instance>_cpu/config
...
rackwatch/status          online | offline   (last will)
rackwatch/snapshot        {"cpu":..,"ram":..,"disk":..,"containers_down":..,"overall":..}
rackwatch/alerts          last alert JSON
```

HA then creates the same sensors without the REST `POST /api/states` path. REST push still runs as a fallback so you can use either transport.

Compose broker for labs that do not have one yet:

```bash
docker compose --profile mqtt up -d
# MQTT_HOST=mosquitto
```

Point HA’s MQTT integration at `mosquitto:1883` (same Docker network) or at the host IP `:1883`.

---

## Sending HA events *into* RackWatch

An HA automation can open a ticket on the RackWatch alerts page:

```yaml
action:
  - service: rest_command.rackwatch_alert
```

```yaml
rest_command:
  rackwatch_alert:
    url: "http://192.168.1.10:8080/api/v1/hooks/alert"
    method: POST
    headers:
      X-API-Key: !secret rackwatch_token
      Content-Type: application/json
    payload: >
      {"title":"{{ title }}","message":"{{ message }}","severity":"warning","source":"homeassistant"}
```

Restart a container from HA the same way against `/api/v1/hooks/restart`.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| “Home Assistant is not connected” | `HA_URL` reachable from the *container* (`docker compose exec rackwatch curl -I $HA_URL`). `homeassistant.local` often does not resolve inside Docker — use the IP. |
| 401 from HA | Token copied with a newline, or token revoked. |
| Entities missing | They are filtered by domain. Pin them explicitly. |
| MQTT sensors unknown | Discovery prefix must match HA (`homeassistant` is the default). |
| Notify silent | Developer Tools → Services → call that notify service by hand first. |
