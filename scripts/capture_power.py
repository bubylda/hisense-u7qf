#!/usr/bin/env python3
"""Capture power evidence without changing the TV's power or input."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import ssl
import sys
import threading
import time
from uuid import uuid4


MOBILE = "/remoteapp/mobile/hisenseservice/"
AUTH_TOPIC = MOBILE + "ui_service/data/authentication"
TOPICS = (
    "/remoteapp/mobile/broadcast/ui_service/state",
    "/remoteapp/mobile/broadcast/platform_service/actions/tvsleep",
    MOBILE + "platform_service/data/gettvinfo",
    MOBILE + "platform_service/data/getdeviceinfo",
    MOBILE + "ui_service/data/capability",
    MOBILE + "ui_service/data/state",
    MOBILE + "ui_service/data/gettvstate",
)


def message_event(topic, payload, retained):
    """Export only power-related scalar values and field names, without guessing."""
    if topic not in TOPICS or len(payload) > 65536:
        return None
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    fields = {}
    for key, value in data.items():
        lower = key.lower()
        if any(word in lower for word in ("token", "password", "secret", "pin", "deviceid", "mac")):
            continue
        if key == "statetype" or any(word in lower for word in ("power", "sleep", "standby")):
            fields[key] = value if value is None or type(value) in (str, bool, int, float) else "[non-scalar]"
    return {
        "time": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "retained": bool(retained),
        "fields": fields,
        "keys": sorted(data),
    }


def request_information(client, query_state=False):
    """Read information; the explicit gettvstate probe can trigger a PIN dialog."""
    if query_state:
        client.publish("/remoteapp/tv/ui_service/hisenseservice/actions/gettvstate", "0")
    client.publish("/remoteapp/tv/platform_service/hisenseservice/actions/gettvinfo", "")
    client.publish("/remoteapp/tv/ui_service/hisenseservice/actions/capability", "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True, help="TV IP address")
    parser.add_argument("--seconds", type=int, default=90, help="capture duration (default: 90)")
    parser.add_argument("--query-state", action="store_true",
                        help="send gettvstate with payload 0 once; may display a pairing PIN")
    args = parser.parse_args()
    if args.seconds < 1 or args.seconds > 600:
        parser.error("--seconds must be between 1 and 600")
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        parser.error("install paho-mqtt==2.1.0 in a virtual environment first")
    certs = Path(__file__).resolve().parents[1] / "custom_components" / "hisense_u7qf" / "public_app_certs"
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.load_cert_chain(certs / "rcm_certchain_pem.cer", certs / "rcm_pem_privkey.pkcs8")
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="ha-power-capture-" + uuid4().hex[:16],
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set("hisenseservice", "multimqttservice")
    client.tls_set_context(context)
    ready = threading.Event()
    connected = threading.Event()
    pairing_required = threading.Event()

    def on_connect(transport, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print("MQTT connection rejected: " + str(reason_code), file=sys.stderr, flush=True)
            return
        connected.set()
        topics = TOPICS + (AUTH_TOPIC,) if args.query_state else TOPICS
        transport.subscribe([(topic, 0) for topic in topics])

    def on_subscribe(transport, userdata, mid, reason_codes, properties):
        if not any(code.is_failure for code in reason_codes):
            ready.set()

    def on_disconnect(transport, userdata, flags, reason_code, properties):
        connected.clear()
        ready.clear()
        print("MQTT disconnected; this alone does not establish TV power.", file=sys.stderr, flush=True)

    def on_message(transport, userdata, msg):
        if args.query_state and msg.topic == AUTH_TOPIC and not msg.retain:
            pairing_required.set()
            print(json.dumps({"time": datetime.now(timezone.utc).isoformat(),
                              "event": "pairing_required"}), flush=True)
            return
        event = message_event(msg.topic, msg.payload, msg.retain)
        if event is not None:
            print(json.dumps(event, ensure_ascii=True), flush=True)

    client.on_connect, client.on_subscribe = on_connect, on_subscribe
    client.on_disconnect, client.on_message = on_disconnect, on_message
    client.connect_async(args.ip, 36669, 30)
    client.loop_start()
    try:
        if not ready.wait(10):
            print("No MQTT connection/subscription confirmation within 10 seconds.", file=sys.stderr)
            return 1
        if args.query_state:
            print("State probe enabled: leave TV on HDMI. A PIN may appear; the capture will then stop.",
                  file=sys.stderr, flush=True)
        else:
            print("Capture started. Leave TV on HDMI, then use the physical remote to enter standby and wake it.",
                  file=sys.stderr, flush=True)
        deadline = time.monotonic() + args.seconds
        next_query = 0.0
        query_state_pending = args.query_state
        while time.monotonic() < deadline:
            if pairing_required.is_set():
                print("TV requested pairing; stopping without submitting a PIN or retrying gettvstate.",
                      file=sys.stderr, flush=True)
                return 2
            if connected.is_set() and ready.is_set() and time.monotonic() >= next_query:
                request_information(client, query_state=query_state_pending)
                query_state_pending = False
                next_query = time.monotonic() + 5
            time.sleep(0.2)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    raise SystemExit(main())
