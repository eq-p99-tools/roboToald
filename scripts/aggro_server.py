"""
CCHPM-compatible aggro meter relay server.

Implements the TCP protocol used by CCHPM's Online Aggro Meter feature.
Aggregates per-player threat updates and broadcasts combined threat lists
to all clients subscribed to the same channel.  Also tracks warrior
discipline state so broadcasts can include ``tank_disc_start_time``.

Usage:
    python aggro_server.py [--host 0.0.0.0] [--port 12345]

Protocol:
    Handshake (plain text):
        Server → Client: b"SERVER:HANDSHAKE"
        Client → Server: b"CLIENT:HANDSHAKE"
        Server → Client: b"SERVER:HANDSHAKE_CONFIRMED"

    Client → Server (4-byte big-endian length prefix + JSON):
        threat_update:    {"type":"threat_update","character":"X","mob_name":"Y","threat":N}
        mob_slain:        {"type":"mob_slain","character":"X","mob_name":"Y","threat":0}
        clear_all_aggro:  {"type":"clear_all_aggro","character":"X","mob_name":"NA","threat":0}
        channel_update:   {"type":"channel_update","channel_name":"Z"}
        disc_activated:   {"type":"disc_activated","character":"X","mob_name":"defensive","threat":180}
        disc_ended:       {"type":"disc_ended","character":"X","mob_name":"any_disc","threat":0}
        disc_cooling_down:{"type":"disc_cooling_down","character":"X","mob_name":"any_disc","threat":120}

    Server → Client (raw JSON, no framing):
        threat_broadcast: {"mob_name":"Y","threat_list":[{"character":"X","threat":N,
                           "tank_disc_start_time":T},...],"type":"threat_broadcast"}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import struct
import time
from dataclasses import dataclass, field

logger = logging.getLogger("aggro_server")


@dataclass
class DiscState:
    """Active warrior discipline for a character."""

    disc_type: str  # "defensive", "evasive", "furious", etc.
    start_time: float  # server-side timestamp when activated
    duration: int  # seconds


@dataclass
class ClientState:
    writer: asyncio.StreamWriter
    channel: str = "default"
    character: str = "Unknown"


@dataclass
class AggroServer:
    host: str = "0.0.0.0"
    port: int = 12345
    clients: dict[asyncio.Task, ClientState] = field(default_factory=dict)
    # channel -> mob_name -> character -> threat
    channels: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)
    # channel -> character -> DiscState (active disc, if any)
    disc_states: dict[str, dict[str, DiscState]] = field(default_factory=dict)

    async def start(self) -> None:
        server = await asyncio.start_server(self._handle_client, self.host, self.port)
        addr = server.sockets[0].getsockname()
        logger.info("Aggro server listening on %s:%d", addr[0], addr[1])
        async with server:
            await server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.info("New connection from %s", addr)

        task = asyncio.current_task()
        assert task is not None
        client = ClientState(writer=writer)
        self.clients[task] = client

        try:
            if not await self._handshake(reader, writer):
                return
            logger.info("Handshake completed with %s", addr)
            await self._message_loop(reader, client)
        except (asyncio.IncompleteReadError, ConnectionResetError, ConnectionError):
            logger.info("Client %s disconnected", addr)
        except Exception:
            logger.exception("Error handling client %s", addr)
        finally:
            self._remove_client(task, client)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionResetError, OSError):
                pass  # transport already gone (common on Windows IOCP)
            logger.info("Connection closed: %s", addr)

    async def _handshake(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
        writer.write(b"SERVER:HANDSHAKE")
        await writer.drain()

        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("Handshake timeout")
            return False

        if not data or b"CLIENT:HANDSHAKE" not in data:
            logger.warning("Invalid handshake response: %r", data)
            return False

        writer.write(b"SERVER:HANDSHAKE_CONFIRMED")
        await writer.drain()
        return True

    async def _message_loop(self, reader: asyncio.StreamReader, client: ClientState) -> None:
        while True:
            header = await reader.readexactly(4)
            (length,) = struct.unpack(">I", header)

            if length > 65536:
                logger.warning("Message too large (%d bytes), dropping client", length)
                return

            body = await reader.readexactly(length)
            msg = json.loads(body.decode("utf-8"))
            await self._dispatch(msg, client)

    async def _dispatch(self, msg: dict, client: ClientState) -> None:
        msg_type = msg.get("type")

        if msg_type == "threat_update":
            character = msg["character"]
            mob_name = msg["mob_name"]
            threat = msg["threat"]
            client.character = character
            self._upsert_threat(client.channel, mob_name, character, threat)
            await self._broadcast_mob(client.channel, mob_name)

        elif msg_type == "mob_slain":
            mob_name = msg["mob_name"]
            channel_data = self.channels.get(client.channel, {})
            channel_data.pop(mob_name, None)
            await self._broadcast_mob(client.channel, mob_name)

        elif msg_type == "clear_all_aggro":
            character = msg["character"]
            self._clear_character(client.channel, character)

        elif msg_type == "channel_update":
            old_channel = client.channel
            new_channel = msg["channel_name"]
            if old_channel != new_channel:
                self._clear_character(old_channel, client.character)
                client.channel = new_channel
            logger.debug("Client %s moved to channel '%s'", client.character, new_channel)

        elif msg_type == "disc_activated":
            character = msg["character"]
            disc_type = msg["mob_name"]  # disc name is packed into mob_name
            duration = msg["threat"]  # duration is packed into threat
            client.character = character
            ch_discs = self.disc_states.setdefault(client.channel, {})
            ch_discs[character] = DiscState(disc_type=disc_type, start_time=time.time(), duration=duration)
            logger.debug("%s activated %s (%ds)", character, disc_type, duration)

        elif msg_type in ("disc_ended", "disc_cooling_down"):
            character = msg["character"]
            client.character = character
            ch_discs = self.disc_states.get(client.channel, {})
            ch_discs.pop(character, None)
            logger.debug("%s disc %s", character, msg_type)

        else:
            logger.warning("Unknown message type: %s", msg_type)

    def _upsert_threat(self, channel: str, mob_name: str, character: str, threat: int) -> None:
        if channel not in self.channels:
            self.channels[channel] = {}
        if mob_name not in self.channels[channel]:
            self.channels[channel][mob_name] = {}
        self.channels[channel][mob_name][character] = threat

    def _clear_character(self, channel: str, character: str) -> None:
        channel_data = self.channels.get(channel, {})
        empty_mobs = []
        for mob_name, threat_table in channel_data.items():
            threat_table.pop(character, None)
            if not threat_table:
                empty_mobs.append(mob_name)
        for mob_name in empty_mobs:
            del channel_data[mob_name]

    def _remove_client(self, task: asyncio.Task, client: ClientState) -> None:
        self.clients.pop(task, None)
        self._clear_character(client.channel, client.character)
        ch_discs = self.disc_states.get(client.channel, {})
        ch_discs.pop(client.character, None)

    async def _broadcast_mob(self, channel: str, mob_name: str) -> None:
        channel_data = self.channels.get(channel, {})
        threat_table = channel_data.get(mob_name, {})
        ch_discs = self.disc_states.get(channel, {})
        now = time.time()

        threat_list = []
        for char, val in sorted(threat_table.items(), key=lambda x: x[1], reverse=True):
            entry: dict = {"character": char, "threat": val}
            disc = ch_discs.get(char)
            if disc and (now - disc.start_time) < disc.duration:
                entry["tank_disc_start_time"] = disc.start_time
            threat_list.append(entry)

        broadcast = json.dumps({"mob_name": mob_name, "threat_list": threat_list, "type": "threat_broadcast"}).encode(
            "utf-8"
        )

        stale_tasks = []
        for task, other_client in self.clients.items():
            if other_client.channel != channel:
                continue
            try:
                other_client.writer.write(broadcast)
                await other_client.writer.drain()
            except (ConnectionResetError, ConnectionError, OSError):
                stale_tasks.append(task)

        for task in stale_tasks:
            task.cancel()


def main() -> None:
    parser = argparse.ArgumentParser(description="CCHPM aggro meter relay server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=12345, help="Listen port (default: 12345)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    server = AggroServer(host=args.host, port=args.port)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Shutting down")


if __name__ == "__main__":
    main()
