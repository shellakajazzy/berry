import asyncio
import discord
from discord.ext import commands
from discord.sinks import Sink
import os


class VoskSink(Sink):
    def __init__(self):
        super().__init__()

    def write(self, data, user):
        # check if the user is defined
        if user is None or getattr(user, "bot", False):
            return

        # get the PCM and user data
        userid = user.id
        username = user.display_name
        pcm = data.pcm
        if not pcm:
            return

        print(f"Received packet from user {user}")


async def main():
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready() -> None:
        print(f"Logged in as {bot.user}")
        print("Beggining connection to VC...")

        # get the guildID and confirm it is real
        guildID = os.getenv("DISCORD_TRANSCRIBE_GUILD_ID")
        if guildID == None:
            print("Please specify the GUILD ID of the voice channel in the DISCORD_TRANSCRIBE_GUILD_ID environment variable")
            return
        guild = bot.get_guild(int(guildID))
        if guild == None:
            print(f"Could not find guild with ID {guildID}")
            return

        # get the channelID and confirm it is real
        channelID = os.getenv("DISCORD_TRANSCRIBE_CHANNEL_ID")
        if channelID == None:
            print("Please specify the CHANNEL ID of the voice channel in the DISCORD_TRANSCRIBE_CHANNEL_ID environment variable")
            return
        channel = guild.get_channel(int(channelID))
        if not isinstance(channel, discord.VoiceChannel):
            print(f"Could not connect to voice channel with ID {channelID} in guild with ID {guildID}")
            return

        # connect to VC and check DAVE connection
        vc = await channel.connect()
        dave = vc.is_dave_connection()
        if dave == False:
            print("Could not get the DAVE connection setup")
            return
        print(f"Successfully connect to channel with ID {channelID} in guild with ID {guildID}, with DAVE connection being set to {dave}")
        print("Press Ctrl-C to disconenct")


    # get the Discord bot token and confirm it is real
    token = os.getenv("DISCORD_TOKEN")
    if token == None:
        print("Please specify the DISCORDD BOT TOKEN in the DISCORD_TOKEN environment variable")
        return

    try:
        asyncio.create_task(bot.start(token))

        # wait for shutdown response
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        # cleanup when shutting down
        guildID = os.getenv("DISCORD_TRANSCRIBE_GUILD_ID")
        if guildID == None:
            print("Please specify the GUILD ID of the voice channel in the DISCORD_TRANSCRIBE_GUILD_ID environment variable")
            return
        guild = bot.get_guild(int(guildID))
        if guild == None:
            print(f"Could not find guild with ID {guildID}")
            return
        vc = guild.voice_client
        if vc == None:
            print("Could not find VC")
            return
        await vc.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Received exception: {str(e)}")
        print("Shutting down...")
    finally:
        print("Finished shutting down")


