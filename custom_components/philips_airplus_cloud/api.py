from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
import time
import urllib.parse
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from aiohttp import ClientResponseError, ClientSession, WSMsgType

from .const import (
    AUTH_URL,
    CLIENT_ID,
    CLIENT_SECRET,
    DA_BASE,
    MQTT_URL,
    REDIRECT_URI,
    SCOPE,
    TENANT,
    TOKEN_URL,
)


def b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def make_pkce() -> tuple[str, str]:
    verifier = b64url_no_pad(secrets.token_bytes(64))
    challenge = b64url_no_pad(hashlib.sha256(verifier.encode("iso-8859-1")).digest())
    return verifier, challenge


def make_auth_url(challenge: str, locale: str = "pl-PL") -> str:
    scope = urllib.parse.quote(SCOPE, safe="")
    return (
        f"{AUTH_URL}?client_id={CLIENT_ID}"
        f"&code_challenge={challenge}"
        "&code_challenge_method=S256"
        "&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&ui_locales={locale}"
        f"&scope={scope}"
    )


def extract_code(redirect_url: str) -> str | None:
    value = redirect_url.strip()
    if not value:
        return None

    if code_match := re.search(r"[?&]code=([^&'\"\s]+)", value):
        return urllib.parse.unquote(code_match.group(1))

    parsed = urllib.parse.urlparse(value)
    if not parsed.scheme and "://" not in value and "?" not in value and "=" not in value:
        return value

    query = urllib.parse.parse_qs(parsed.query)
    if code := query.get("code", [None])[0]:
        return code

    fragment = urllib.parse.parse_qs(parsed.fragment)
    return fragment.get("code", [None])[0]


def enc_str(value: str) -> bytes:
    data = value.encode()
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


class AirplusClient:
    def __init__(
        self,
        session: ClientSession,
        token: dict,
        token_updated: Callable[[dict], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._token = token
        self._token_updated = token_updated
        self._user: dict | None = None
        self._devices: list[dict] | None = None

    async def async_exchange_code(self, code: str, verifier: str) -> dict:
        token = await self._token_request(
            {
                "client_id": CLIENT_ID,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
                "client_secret": CLIENT_SECRET,
                "code_verifier": verifier,
            }
        )
        self._token = token
        return token

    async def _token_request(self, data: dict[str, str]) -> dict:
        async with self._session.post(TOKEN_URL, data=data) as response:
            response.raise_for_status()
            token = await response.json()
        token["obtained_at"] = int(time.time())
        if "expires_in" in token:
            token["expires_at"] = token["obtained_at"] + int(token["expires_in"]) - 60
        return token

    async def _ensure_token(self) -> None:
        if int(self._token.get("expires_at", 0)) > int(time.time()):
            return
        refresh_token = self._token.get("refresh_token")
        if not refresh_token:
            return
        token = await self._token_request(
            {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "access_token": self._token["access_token"],
            }
        )
        self._token = token
        if self._token_updated:
            await self._token_updated(token)

    async def _get(self, path: str) -> dict | list:
        await self._ensure_token()
        async with self._session.get(
            f"{DA_BASE}{path}",
            headers={"authorization": f"Bearer {self._token['access_token']}"},
        ) as response:
            response.raise_for_status()
            return await response.json()

    async def async_get_user(self) -> dict:
        if self._user is None:
            self._user = await self._get("/user/self")
        return self._user

    async def async_get_devices(self) -> list[dict]:
        if self._devices is None:
            self._devices = await self._get("/user/self/device")
        return self._devices

    async def async_get_signature(self) -> str:
        data = await self._get("/user/self/signature")
        return data["signature"]

    async def _mqtt_roundtrip(
        self,
        thing_name: str,
        publish_topic: str,
        publish_payload: bytes,
        accepted_topic: str,
        rejected_topic: str,
    ) -> dict:
        user = await self.async_get_user()
        signature = await self.async_get_signature()
        client_id = f"{user['id']}_{uuid.uuid4()}"
        headers = {
            "x-amz-customauthorizer-name": "CustomAuthorizer",
            "x-amz-customauthorizer-signature": signature,
            "token-header": f"Bearer {self._token['access_token']}",
            "content-type": "application/json",
            "tenant": TENANT,
        }

        async with self._session.ws_connect(
            MQTT_URL,
            protocols=("mqtt",),
            headers=headers,
            heartbeat=20,
            receive_timeout=15,
        ) as ws:
            await ws.send_bytes(connect_packet(client_id))
            connack = await ws.receive_bytes()
            if not (len(connack) >= 4 and connack[0] == 0x20 and connack[3] == 0):
                raise RuntimeError(f"MQTT connect rejected for {thing_name}")

            await ws.send_bytes(subscribe_packet(1, [accepted_topic, rejected_topic]))
            await ws.receive_bytes()
            await ws.send_bytes(publish_packet(publish_topic, publish_payload))

            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                msg = await ws.receive(timeout=max(0.5, deadline - time.monotonic()))
                if msg.type == WSMsgType.BINARY:
                    parsed = parse_publish(msg.data)
                    if not parsed:
                        continue
                    topic, body = parsed
                    if topic == rejected_topic:
                        raise RuntimeError(body.decode("utf-8", errors="replace"))
                    if topic == accepted_topic:
                        return json.loads(body.decode("utf-8"))
                if msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
        raise TimeoutError(f"No MQTT response for {thing_name}")

    async def _mqtt_ncp_command(
        self,
        thing_name: str,
        command_name: str,
        data: dict | None = None,
        expected_port_name: str | None = None,
    ) -> dict:
        user = await self.async_get_user()
        signature = await self.async_get_signature()
        client_id = f"{user['id']}_{uuid.uuid4()}"
        headers = {
            "x-amz-customauthorizer-name": "CustomAuthorizer",
            "x-amz-customauthorizer-signature": signature,
            "token-header": f"Bearer {self._token['access_token']}",
            "content-type": "application/json",
            "tenant": TENANT,
        }
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

        publish_topic = f"da_ctrl/{thing_name}/to_ncp"
        subscribe_topic = f"da_ctrl/{thing_name}/from_ncp"

        async with self._session.ws_connect(
            MQTT_URL,
            protocols=("mqtt",),
            headers=headers,
            heartbeat=20,
            receive_timeout=15,
        ) as ws:
            await ws.send_bytes(connect_packet(client_id))
            connack = await ws.receive_bytes()
            if not (len(connack) >= 4 and connack[0] == 0x20 and connack[3] == 0):
                raise RuntimeError(f"MQTT connect rejected for {thing_name}")

            await ws.send_bytes(subscribe_packet(1, [subscribe_topic]))
            await ws.receive_bytes()
            await ws.send_bytes(
                publish_packet(
                    publish_topic,
                    json.dumps(payload, separators=(",", ":")).encode(),
                )
            )

            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                msg = await ws.receive(timeout=max(0.5, deadline - time.monotonic()))
                if msg.type == WSMsgType.BINARY:
                    parsed = parse_publish(msg.data)
                    if not parsed:
                        continue
                    topic, body = parsed
                    if topic != subscribe_topic:
                        continue
                    decoded = json.loads(body.decode("utf-8"))
                    if decoded.get("cn") != command_name:
                        continue
                    response_cid = str(decoded.get("cid", ""))
                    if response_cid and not (
                        correlation_id.startswith(response_cid)
                        or response_cid.startswith(correlation_id)
                    ):
                        continue
                    if expected_port_name is not None:
                        response_data = decoded.get("data")
                        if not isinstance(response_data, dict):
                            continue
                        if response_data.get("portName") != expected_port_name:
                            continue
                    status = decoded.get("status", 0)
                    if status != 0:
                        raise RuntimeError(json.dumps(decoded, separators=(",", ":")))
                    return decoded
                if msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
        raise TimeoutError(f"No NCP response for {thing_name}")

    async def async_get_ncp_port(self, device: dict, port_name: str) -> dict:
        response = await self._mqtt_ncp_command(
            device["thingName"],
            "getPort",
            {"portName": port_name},
            expected_port_name=port_name,
        )
        data = response.get("data")
        return data if isinstance(data, dict) else {}

    async def async_set_ncp_properties(
        self,
        device: dict,
        port_name: str,
        properties: dict,
    ) -> dict:
        return await self._mqtt_ncp_command(
            device["thingName"],
            "setPort",
            {"portName": port_name, "properties": properties},
        )

    async def async_get_shadow(self, device: dict) -> dict:
        thing_name = device["thingName"]
        shadow_prefix = f"$aws/things/{thing_name}/shadow"
        return await self._mqtt_roundtrip(
            thing_name,
            f"{shadow_prefix}/get",
            b"{}",
            f"{shadow_prefix}/get/accepted",
            f"{shadow_prefix}/get/rejected",
        )

    async def async_set_shadow_state(self, device: dict, state: dict) -> dict:
        thing_name = device["thingName"]
        shadow_prefix = f"$aws/things/{thing_name}/shadow"
        payload = json.dumps(
            {"state": {"desired": state}},
            separators=(",", ":"),
        ).encode()
        return await self._mqtt_roundtrip(
            thing_name,
            f"{shadow_prefix}/update",
            payload,
            f"{shadow_prefix}/update/accepted",
            f"{shadow_prefix}/update/rejected",
        )

    async def async_set_power(self, device: dict, power_on: bool) -> dict:
        return await self.async_set_shadow_state(
            device,
            {
                "powerOn": power_on,
                "pwr": "1" if power_on else "0",
            },
        )

    async def async_get_device_data(self, device: dict) -> dict:
        data = await self.async_get_shadow(device)
        ncp_ports = ("Status", "filtRd", "devRd", "Config")
        ncp_results = await asyncio.gather(
            *(self.async_get_ncp_port(device, port) for port in ncp_ports),
            return_exceptions=True,
        )
        ncp: dict[str, dict] = {}
        for port, result in zip(ncp_ports, ncp_results, strict=False):
            if not isinstance(result, Exception):
                ncp[port] = result.get("properties", {})
        data["ncp"] = ncp
        return data

    async def async_get_all_device_data(self) -> dict[str, dict]:
        devices = await self.async_get_devices()
        results = await asyncio.gather(
            *(self.async_get_device_data(device) for device in devices),
            return_exceptions=True,
        )
        data: dict[str, dict] = {}
        for device, result in zip(devices, results, strict=False):
            if isinstance(result, Exception):
                raise result
            data[device["id"]] = result
        return data

    async_get_all_shadows = async_get_all_device_data
