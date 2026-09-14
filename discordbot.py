# /// script
# dependencies = [
#   "davey>=0.1.6",
#   "moonshine-voice",
#   "numpy",
#   "py-cord[voice]",
# ]
#
# [tool.uv.sources]
# py-cord = { git = "https://github.com/Pycord-Development/pycord", rev = "refs/pull/3159/head" }
# ///

# python deps
import asyncio
import os
import wave

# discord
import discord
from discord.ext import commands
from discord.sinks import Sink

# voice transcription / generation
import moonshine_voice as msv
import numpy as np


bot = None


async def main(token):
    # listener for moonshine
    class LineListener(msv.TranscriptEventListener):
        def register_username(self, username):
            self.username = username
            print(f"Registered username {username} to LineListener")

        def on_line_started(self, event): pass
        def on_line_text_changed(self, event): pass
        def on_line_completed(self, event):
            print(f"{self.username}: {event.line.text}")

    # load moonshine for voice transcription
    moonshine_streams = {}
    model_path, model_arch = msv.get_model_for_language("en", msv.ModelArch.MEDIUM_STREAMING)
    transcriber = msv.Transcriber(model_path=model_path, model_arch=model_arch)

    # setup bot with intents
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    # setup sink to receive PCM audio
    class ReceiveSink(Sink):
        def __init__(self) -> None:
            super().__init__()
    
        def write(self, data, user) -> None:
            if user is None or getattr(user, "bot", False): return
    
            userid = user.id
            if userid not in moonshine_streams:
                moonshine_streams[userid] = {}
                stream = moonshine_streams[userid]
                stream["username"] = user.display_name
                stream["stream"] = transcriber.create_stream(update_interval=0.1)
                stream["listener"] = LineListener()
                stream["listener"].register_username(user.name)
                stream["stream"].add_listener(stream["listener"])
                stream["stream"].start()
                print(f"Transcriber for {user.name} started")

            stream = moonshine_streams[userid]

            pcm = data.pcm
            if not pcm: return

            samples = np.frombuffer(pcm, dtype=np.int16)
            samples = samples[::2]
            samples = samples.astype(np.float32) / 32768.0

            try:
                stream["stream"].add_audio(samples, 48000)
            except Exception as e:
                print(str(e))

    # have bot connect to VC on startup and start listening using the sink
    @bot.event
    async def on_ready() -> None:
        print(f"Logged in as {bot.user}")
    
        guild_id = os.getenv("TRANSCRIBE_GUILD_ID")
        if not token: raise SystemExit("TRANSCRIBE_GUILD_ID environment variable not found")
        channel_id = os.getenv("TRANSCRIBE_CHANNEL_ID")
        if not token: raise SystemExit("TRANSCRIBE_CHANNEL_ID environment variable not found")
    
        print("Joining channel...")
        guild = bot.get_guild(int(guild_id))
        channel = guild.get_channel(int(channel_id))
        vc = await channel.connect()
        dave = vc.is_dave_connection()
        vc.start_recording(ReceiveSink())
        print(f"Joined voice channel, DAVE={dave}!")

    # capture Ctrl-C
    try:
        # start bot
        await bot.start(token)
        while True: pass
    except asyncio.CancelledError:
        print("\n\nPress Ctrl-C again...")

        guild_id = os.getenv("TRANSCRIBE_GUILD_ID")
        if not token: raise SystemExit("TRANSCRIBE_GUILD_ID environment variable not found")
        guild = bot.get_guild(int(guild_id))
        vc = guild.voice_client
        await vc.disconnect()
        print("\nDisconnected from VC!")

        await bot.close()
        print("Bot disconnected!")


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token: raise SystemExit("DISCORD_TOKEN environment variable not found")

    try:
        asyncio.run(main(token))
    except KeyboardInterrupt:
        print("Keyboard interrupt, shutting down...")

