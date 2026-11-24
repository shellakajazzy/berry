# /// script
# dependencies = [
#   "davey>=0.1.6",
#   "numpy",
#   "py-cord[voice]",
#   "websockets"
# ]
#
# [tool.uv.sources]
# py-cord = { git = "https://github.com/Pycord-Development/pycord", rev = "refs/pull/3159/head" }
# ///


# python deps
import asyncio
import json
import numpy
import os
import threading
import wave
import websockets

# discord
import discord
from discord.ext import commands
from discord.sinks import Sink


# config
import config


bot = None


async def main(token):
    # setup bot with intents
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    # only contains the voice websocket for voice send and receive packets, not JSON
    sockets = {
        "core": None,
        "voice": None
    }
    maintain_websockets = True

    # asyncio tasks that need to be finished
    tasks = []

    # setup sink to receive PCM audio
    class ReceiveSink(Sink):
        def __init__(self, loop) -> None:
            super().__init__()
            self.loop = loop
            self.uid_lock = threading.Lock()
            self.uid_map = {} # for Neuro API, speaker ID must be in a uint16,
                              # but Discord has 17-19 digit UID's, so we will
                              # make a map that maps Discord UIDs to a uint16
                              # there should be no way that the bot meets 2^16
                              # unique people, and it caches for the current run
        def write(self, data, user) -> None:
            if user is None or getattr(user, "bot", False): return

            userid = user.id
            username = user.display_name
            with self.uid_lock:
                if userid not in self.uid_map:
                    self.uid_map[userid] = len(self.uid_map)
                    print(f"Assigned {username} ID {self.uid_map[userid]}")

            pcm = data.pcm
            if not pcm: return
            samples = numpy.frombuffer(pcm, dtype="<i2")
            stereo = samples.reshape(-1, 2)
            mono = stereo.astype(numpy.float32).mean(axis=1) / 32768.0

            voice_payload = b"\x01\x00" + self.uid_map[userid].to_bytes(2, "little") + mono.astype("<f4").tobytes()
            try:
                # register user, easier to do it everytime so that everything is always up to date,
                # and also registering shouldn't take too much time
                asyncio.run_coroutine_threadsafe(
                    sockets["core"].send(json.dumps({
                        "command": "voice/speakers/register",
                        "game": "discord",
                        "data": {
                            "speakers": [{
                                "id": self.uid_map[userid],
                                "name": username
                            }]
                        }
                    })),
                    self.loop
                )

                # send the voice packet
                asyncio.run_coroutine_threadsafe(
                    sockets["voice"].send(voice_payload),
                    self.loop
                )
            except: return

    class PlaybackSource(discord.AudioSource):
        def __init__(self, loop) -> None:
            super().__init__()
            self.loop = loop

            self.buf = bytearray()
            self.lock = threading.Lock()
            self.speaking = False

            async def packet_receive():
                # receive audio packets from voice server
                while True:
                    try:
                        async for frame in sockets["voice"]:
                            with self.lock: self.buf += frame
                    except: await asyncio.sleep(0.01)
            async def poll_cancel():
                # wait for a cancel message from core server
                while True:
                    try:
                        async for msg in sockets["core"]:
                            msg_json = json.loads(msg)
                            if msg_json["command"] == "voice/cancelled":
                                with self.lock: self.buf = bytearray()
                                self.speaking = False
                            elif msg_json["command"] == "voice/speaking":
                                self.speaking = msg_json["data"]["speaking"]
                    except: await asyncio.sleep(0.01)
            self.recv_future = asyncio.run_coroutine_threadsafe(packet_receive(), self.loop)
            self.cancel_future = asyncio.run_coroutine_threadsafe(poll_cancel(), self.loop)

        def is_opus(self): return False
        def read(self):
            raw = None 

            with self.lock:
                # takes in 20ms packets at 48kHZ (3840 bytes):
                if len(self.buf) < 3840 or self.speaking == False: return b"x\00" * 3480
                raw = self.buf[:3840]
                del self.buf[:3840]

            # convert to Discord compatible audio from what is received from Neuro API
            mono = numpy.frombuffer(raw, dtype="<f4")
            pcm = (numpy.clip(mono, -1.0, 1.0) * 32767).astype("<i2")

            return numpy.repeat(pcm, 2).tobytes()


    # connect to websockets, and keep retrying
    async def ws_maintain(name, url):
        if name not in ["core", "voice"]: return

        while maintain_websockets == True:
            try:
                async with websockets.connect(url) as socket:
                    sockets[name] = socket
                    print(f"Connected to {url}!")

                    if name == "core":
                        # run startup handshake for voice
                        await socket.send(json.dumps({
                            "command": "voice/start",
                            "game": "discord"
                        }))
                        reply = await socket.recv()
                        data = json.loads(reply)
                        if data["command"] == "voice/unavailable": raise ValueError("Voice is unavailable")

                    await socket.wait_closed()
            except: print(f"Failed to connect to {url}, attempting to reconnect...")
            finally: sockets[name] = None

            await asyncio.sleep(config.NEUROAPI_WEBSOCKET_RETRY)


    # have bot connect to VC on startup and start listening using the sink

    @bot.event
    async def on_ready() -> None:
        print(f"Logged in as {bot.user}")


        # join VC and setup sink/source
        print("Joining channel...")
        guild = bot.get_guild(config.DISCORD_GUILD_ID)
        channel = guild.get_channel(config.DISCORD_CHANNEL_ID)
        vc = await channel.connect()
        dave = vc.is_dave_connection()
        vc.start_recording(ReceiveSink(bot.loop))
        vc.play(PlaybackSource(bot.loop))
        print(f"Joined voice channel, DAVE={dave}!")

        # connect to websockets w/retries
        asyncio.create_task(ws_maintain("core", f"ws://{config.NEUROAPI_IP}:{config.NEUROAPI_PORT}"))
        asyncio.create_task(ws_maintain("voice", f"ws://{config.NEUROAPI_IP}:{config.NEUROAPI_PORT}/game/discord/voice"))

    # capture Ctrl-C
    try:
        # start bot
        await bot.start(token)
        while True: pass
    except asyncio.CancelledError:
        print("\n\nPress Ctrl-C again...")
        maintain_websockets = False
        if type(sockets["core"]) == websockets.asyncio.client.ClientConnection:
            await sockets["core"].send(json.dumps({
                "command": "voice/stop",
                "game": "discord"
            }))
            print("Sent voice/stop websocket message")
            print("\nPress Ctrl-C again...")
        for _, socket in sockets.items():
            if type(socket) != websockets.asyncio.client.ClientConnection: continue
            await socket.close()
        print("\nClosed websocket connections.")

        print("\nPress Ctrl-C again...")
        guild = bot.get_guild(config.DISCORD_GUILD_ID)
        vc = guild.voice_client
        await vc.disconnect()
        print("\nDisconnected from VC!")

        await bot.close()
        print("Bot disconnected!")


if __name__ == "__main__":
    try:
        asyncio.run(main(config.DISCORD_TOKEN))
    except KeyboardInterrupt:
        print("Keyboard interrupt, shutting down...")

