#!/usr/bin/env python3
"""Probe Philips Air+ NCP remote-control ports over MQTT."""

from __future__ import annotations

import argparse
import json
import ssl
import socket
import time
import uuid
from datetime import datetime, timezone

import websocket
from websocket import WebSocketConnectionClosedException, WebSocketTimeoutException

from airplus_mqtt_probe import connect_packet, parse_publish, publish_packet, subscribe_packet
from airplus_probe import get_json, load_or_login


MQTT_HOST = "ats.prod.eu-da.iot.versuni.com"
MQTT_URL = f"wss://{MQTT_HOST}:443/mqtt"


def ncp_command(command_name: str, data: object | None = None) -> tuple[str, bytes]:
    correlation_id = str(uuid.uuid4())
    payload = {
        "cid": correlation_id,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "command",
        "cn": command_name,
        "ct": "mobile",
    }
    if data is not None:
        payload["data"] = data
    return correlation_id, json.dumps(payload, separators=(",", ":")).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-file", default=".airplus_token.json")
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--thing-name")
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--command", default="getAllPorts")
    parser.add_argument("--port-name")
    parser.add_argument("--prefix", default="da_ctrl")
    parser.add_argument("--thing-id-only", action="store_true")
    args = parser.parse_args()

    token = load_or_login(args)
    access_token = token["access_token"]
    user = get_json("/user/self", access_token)
    devices = get_json("/user/self/device", access_token)
    signature = get_json("/user/self/signature", access_token)["signature"]

    device = devices[args.device_index]
    thing_name = args.thing_name or device["thingName"]
    if args.thing_id_only and thing_name.startswith("da-"):
        thing_name = thing_name[3:]
    client_id = f"{user['id']}_{uuid.uuid4()}"
    subscribe_topic = f"{args.prefix}/{thing_name}/from_ncp"
    publish_topic = f"{args.prefix}/{thing_name}/to_ncp"

    data = None
    if args.port_name:
        data = {"portName": args.port_name}
    correlation_id, payload = ncp_command(args.command, data)

    print(f"device: {device.get('friendlyName')} ({device.get('ctn')})")
    print(f"thing:  {thing_name}")
    print(f"client: {client_id}")
    print(f"sub:    {subscribe_topic}")
    print(f"pub:    {publish_topic}")
    print(f"cid:    {correlation_id}")
    print(f"body:   {payload.decode('utf-8')}")

    ws = websocket.create_connection(
        MQTT_URL,
        subprotocols=["mqtt"],
        header=[
            "x-amz-customauthorizer-name: CustomAuthorizer",
            f"x-amz-customauthorizer-signature: {signature}",
            f"token-header: Bearer {access_token}",
            "content-type: application/json",
            "tenant: da",
        ],
        sslopt={"cert_reqs": ssl.CERT_REQUIRED},
        timeout=10,
    )
    try:
        ws.send_binary(connect_packet(client_id))
        connack = ws.recv()
        if isinstance(connack, str):
            connack = connack.encode()
        print(f"CONNACK: {connack.hex()}")
        if not (len(connack) >= 4 and connack[0] == 0x20 and connack[3] == 0):
            raise SystemExit("MQTT connect was not accepted.")

        ws.send_binary(subscribe_packet(1, [subscribe_topic]))
        suback = ws.recv()
        if isinstance(suback, str):
            suback = suback.encode()
        print(f"SUBACK:  {suback.hex() if suback else '<closed>'}")
        if not suback:
            raise SystemExit("MQTT subscribe was not accepted.")

        ws.send_binary(publish_packet(publish_topic, payload))

        deadline = time.time() + args.seconds
        while time.time() < deadline:
            ws.settimeout(max(0.5, deadline - time.time()))
            try:
                msg = ws.recv()
            except (TimeoutError, socket.timeout, WebSocketTimeoutException):
                break
            except WebSocketConnectionClosedException:
                print("CLOSED")
                break
            if isinstance(msg, str):
                print(f"TEXT: {msg}")
                continue
            parsed = parse_publish(msg)
            if not parsed:
                print(f"PACKET: {msg.hex()}")
                continue
            topic, body = parsed
            print(f"\n## {topic}")
            try:
                decoded = json.loads(body.decode("utf-8"))
                print(json.dumps(decoded, indent=2, ensure_ascii=False))
            except Exception:
                print(body.decode("utf-8", errors="replace"))
    finally:
        ws.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
