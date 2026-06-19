#!/usr/bin/env python3
"""Minimal MQTT-over-WebSocket probe for Philips Air+ / Versuni DA.

It avoids external MQTT dependencies by sending MQTT 3.1.1 packets directly over
the WebSocket connection used by the Android app.
"""

from __future__ import annotations

import argparse
import json
import ssl
import socket
import time
import uuid

import websocket
from websocket import WebSocketTimeoutException

from airplus_probe import DA_BASE, get_json, load_or_login


MQTT_HOST = "ats.prod.eu-da.iot.versuni.com"
MQTT_URL = f"wss://{MQTT_HOST}:443/mqtt"


def enc_str(value: str) -> bytes:
    data = value.encode("utf-8")
    return len(data).to_bytes(2, "big") + data


def enc_remaining(length: int) -> bytes:
    out = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length:
            digit |= 0x80
        out.append(digit)
        if not length:
            return bytes(out)


def packet(packet_type_flags: int, payload: bytes) -> bytes:
    return bytes([packet_type_flags]) + enc_remaining(len(payload)) + payload


def connect_packet(client_id: str) -> bytes:
    variable = enc_str("MQTT") + bytes([4, 2]) + (30).to_bytes(2, "big")
    return packet(0x10, variable + enc_str(client_id))


def subscribe_packet(packet_id: int, topics: list[str]) -> bytes:
    payload = packet_id.to_bytes(2, "big")
    for topic in topics:
        payload += enc_str(topic) + bytes([0])
    return packet(0x82, payload)


def publish_packet(topic: str, payload: bytes = b"{}") -> bytes:
    return packet(0x30, enc_str(topic) + payload)


def decode_remaining(data: bytes, offset: int = 1) -> tuple[int, int]:
    multiplier = 1
    value = 0
    while True:
        digit = data[offset]
        offset += 1
        value += (digit & 127) * multiplier
        if (digit & 128) == 0:
            return value, offset
        multiplier *= 128


def parse_publish(data: bytes) -> tuple[str, bytes] | None:
    if not data or data[0] >> 4 != 3:
        return None
    _remaining, offset = decode_remaining(data)
    topic_len = int.from_bytes(data[offset : offset + 2], "big")
    offset += 2
    topic = data[offset : offset + topic_len].decode("utf-8", errors="replace")
    offset += topic_len
    return topic, data[offset:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-file", default=".airplus_token.json")
    parser.add_argument("--seconds", type=int, default=25)
    parser.add_argument("--thing-name")
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--minimal", action="store_true", help="Subscribe only to get accepted/rejected topics.")
    parser.add_argument("--no-from-ncp", action="store_true", help="Skip the from_ncp topic.")
    parser.add_argument(
        "--set-power",
        choices=["on", "off"],
        help="Publish the same power shadow update used by Air+.",
    )
    args = parser.parse_args()

    token = load_or_login(args)
    access_token = token["access_token"]
    user = get_json("/user/self", access_token)
    devices = get_json("/user/self/device", access_token)
    signature = get_json("/user/self/signature", access_token)["signature"]

    device = devices[args.device_index]
    thing_name = args.thing_name or device["thingName"]
    client_id = f"{user['id']}_{uuid.uuid4()}"
    shadow_prefix = f"$aws/things/{thing_name}"
    ncp_prefix = f"da_ctrl/{thing_name}"
    subscribe_topics = [
        f"{shadow_prefix}/shadow/get/accepted",
        f"{shadow_prefix}/shadow/get/rejected",
    ]
    if args.set_power or not args.minimal:
        subscribe_topics.extend(
            [
                f"{shadow_prefix}/shadow/update/accepted",
                f"{shadow_prefix}/shadow/update/rejected",
            ]
        )
    if not args.minimal and not args.no_from_ncp:
        subscribe_topics.append(f"{ncp_prefix}/from_ncp")
    get_topic = f"{shadow_prefix}/shadow/get"

    print(f"device: {device.get('friendlyName')} ({device.get('ctn')})")
    print(f"thing:  {thing_name}")
    print(f"client: {client_id}")
    print(f"wss:    {MQTT_URL}")

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

        ws.send_binary(subscribe_packet(1, subscribe_topics))
        suback = ws.recv()
        if isinstance(suback, str):
            suback = suback.encode()
        print(f"SUBACK:  {suback.hex()}")

        print(f"PUBLISH: {get_topic} {{}}")
        ws.send_binary(publish_packet(get_topic))
        if args.set_power:
            update_topic = f"{shadow_prefix}/shadow/update"
            power_on = args.set_power == "on"
            update_payload = json.dumps(
                {"state": {"desired": {"powerOn": power_on}}},
                separators=(",", ":"),
            ).encode("utf-8")
            print(f"PUBLISH: {update_topic} {update_payload.decode('utf-8')}")
            ws.send_binary(publish_packet(update_topic, update_payload))

        deadline = time.time() + args.seconds
        while time.time() < deadline:
            ws.settimeout(max(0.5, deadline - time.time()))
            try:
                msg = ws.recv()
            except (TimeoutError, socket.timeout, WebSocketTimeoutException):
                break
            if isinstance(msg, str):
                print(f"TEXT: {msg}")
                continue
            parsed = parse_publish(msg)
            if parsed:
                topic, body = parsed
                print(f"\n## {topic}")
                try:
                    print(json.dumps(json.loads(body.decode("utf-8")), indent=2, ensure_ascii=False))
                except Exception:
                    print(body.decode("utf-8", errors="replace"))
            else:
                print(f"PACKET: {msg.hex()}")
    finally:
        ws.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
