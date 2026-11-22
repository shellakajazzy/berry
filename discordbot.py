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
import os
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

    # setup sink to receive PCM audio
    class ReceiveSink(Sink):
        def __init__(self, loop, sockets) -> None:
            super().__init__()
            self.loop = loop
            self.sockets = sockets
            self.uid_map = {} # for Neuro API, speaker ID must be in a uint16,
                              # but Discord has 17-19 digit UID's, so we will
                              # make a map that maps Discord UIDs to a uint16
                              # there should be no way that the bot meets 2^16
                              # unique people, and it caches for the current run
        def write(self, data, user) -> None:
            if user is None or getattr(user, "bot", False): return

            userid = user.id
            username = user.display_name
            self.uid_map[userid] = len(self.uid_map)

            pcm = data.pcm
            if not pcm: return

            voice_payload = b""
            try:
                # register user, easier to do it everytime so that everything is always up to date,
                # and also registering shouldn't take too much time
                asyncio.run_coroutine_threadsafe(
                    self.sockets["core"].send(json.dumps({
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
                    self.sockets["voice"].send(voice_payload),
                    self.loop
                )
            except: return

    # TODO: setup source to send PCM audio
    class PlaybackSource(discord.AudioSource):
        def __init__(self, loop) -> None:
            super().__init__()
            self.loop = loop
        def is_opus(self): return False
        def read(self):
            pass


    # connect to websockets, and keep retrying
    tasks = []
    async def ws_maintain(sockets, name, url):
        if name not in ["core", "voice"]: return

        while True:
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
                        print(data)
                        if data["command"] == "voice/unavailable": raise ValueError("Voice is unavailable")

                    await socket.wait_closed()
            except: print(f"Failed to connect to {url}, attempting to reconnect...")
            finally: sockets[name] = None

            await asyncio.sleep(config.NEUROAPI_WEBSOCKET_RETRY)


    # have bot connect to VC on startup and start listening using the sink

    @bot.event
    async def on_ready() -> None:
        print(f"Logged in as {bot.user}")

        # only contains the voice websocket for voice send and receive packets, not JSON
        sockets = {
            "core": None,
            "voice": None
        }

        # join VC and setup sink/source
        print("Joining channel...")
        guild = bot.get_guild(config.DISCORD_GUILD_ID)
        channel = guild.get_channel(config.DISCORD_CHANNEL_ID)
        vc = await channel.connect()
        dave = vc.is_dave_connection()
        vc.start_recording(ReceiveSink(bot.loop, sockets))
        vc.play(PlaybackSource(bot.loop))
        print(f"Joined voice channel, DAVE={dave}!")

        # connect to websockets w/retries
        asyncio.create_task(ws_maintain(sockets, "core", f"ws://{config.NEUROAPI_IP}:{config.NEUROAPI_PORT}"))
        asyncio.create_task(ws_maintain(sockets, "voice", f"ws://{config.NEUROAPI_IP}:{config.NEUROAPI_PORT}/game/discord/voice"))


    # capture Ctrl-C
    try:
        # start bot
        await bot.start(token)
        while True: pass
    except asyncio.CancelledError:
        print("\n\nPress Ctrl-C again...")

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

