# /// script
# dependencies = [
#   "davey>=0.1.6",
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
        def __init__(self) -> None:
            super().__init__()
    
        def write(self, data, user) -> None:
            if user is None or getattr(user, "bot", False): return

            # TODO: implement sending audio to the Neuro API server
            userid = user.id
            pcm = data.pcm
            if not pcm: return

    # have bot connect to VC on startup and start listening using the sink
    @bot.event
    async def on_ready() -> None:
        print(f"Logged in as {bot.user}")
    
        print("Joining channel...")
        guild = bot.get_guild(config.DISCORD_GUILD_ID)
        channel = guild.get_channel(config.DISCORD_CHANNEL_ID)
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

