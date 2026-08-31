import asyncio
import discord
from discord.ext import commands
from discord.sinks import Sink
import json
import multiprocessing as mp
import os
import subprocess
import time
from vosk import Model, KaldiRecognizer


def vosk_proc(uid, username, vosk_model, is_transcribing, pcm_queue):
    print("Vosk processor spawned!")

    rec = KaldiRecognizer(vosk_model, 16000)
    pcm_capture = b""
    pcm_timestamp = 0

    def vosk_transcribe(uid, username, rec, pcm_capture):
        if len(pcm_capture) == 0: return
        ffmpeg_process = subprocess.run(
            [
                "ffmpeg",
                "-f", "s16le", "-ar", "48000", "-ac", "2", "-i", "pipe:0",
                "-f", "s16le", "-ar", "16000", "-ac", "1", "pipe:1"
            ],
            input=pcm_capture,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        pcm_mono = ffmpeg_process.stdout

        rec.AcceptWaveform(pcm_mono)
        result = json.loads(rec.FinalResult())
        if result["text"] == "": return
        print(f"{username}: {result["text"]}")

    while is_transcribing.value != 0:
        timestamp = int(time.time() * 1000)

        if not pcm_queue.empty():
            pcm_data = pcm_queue.get()

            if pcm_data[1] - pcm_timestamp > 750:
                vosk_transcribe(uid, username, rec, pcm_capture)
                pcm_capture = b""

            pcm_capture += pcm_data[0]
            pcm_timestamp = pcm_data[1]
            continue

        if timestamp - pcm_timestamp <= 750: continue

        vosk_transcribe(uid, username, rec, pcm_capture)
        pcm_capture = b""

    return


class VoskSink(Sink):
    def __init__(self, vosk_model, is_transcribing, recognizers):
        super().__init__()
        self.vosk_model = vosk_model
        self.recognizers = recognizers
        self.is_transcribing = is_transcribing

    def write(self, data, user):
        # check if the user is defined
        if user is None or getattr(user, "bot", False):
            return

        # get the PCM and user data
        uid = user.id
        username = user.display_name
        pcm = data.pcm
        if not uid or not username or not pcm: return

        # create recognizer for user if one doesn't already exist
        if uid not in self.recognizers:
            self.recognizers[uid] = {}
            self.recognizers[uid]["queue"] = mp.Queue()
            self.recognizers[uid]["proc"] = mp.Process(target=vosk_proc, args=(uid, username, self.vosk_model, self.is_transcribing, self.recognizers[uid]["queue"]))
            self.recognizers[uid]["proc"].start()
            print(f"Spawned recognizer for {username}")

        recognizer = self.recognizers[uid]
        # print(f"Obtained recognizer for {username}")

        timestamp = int(time.time() * 1000)
        recognizer["queue"].put_nowait((pcm, timestamp))



async def main():
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    # get the Discord bot token and confirm it is real
    token = os.getenv("DISCORD_TOKEN")
    if token == None:
        print("Please specify the DISCORDD BOT TOKEN in the DISCORD_TOKEN environment variable")
        return

    # get the Vosk model path
    vosk_model_path = os.getenv("VOSK_MODEL_PATH")
    if vosk_model_path == None:
        print(f"Could not find the Vosk model path, please specify it in the VOSK_MODLE_PATH envionrment variable")
        return
    print(f"Loading Vosk model from {vosk_model_path}")
    vosk_model = Model(vosk_model_path)

    asyncio.create_task(bot.start(token))
    await bot.wait_until_ready()
    print("Bot is logged in")

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
    # TODO: current issue: does not receive user audio when there are users already in the call
    vc = await channel.connect()
    if vc == None:
        print("Could not connect to VC")
        return
    if not vc.is_dave_connection():
        print("Could not get the DAVE connection setup")
        return
    print(f"Successfully connect to channel with ID {channelID} in guild with ID {guildID}")
    print("Press Ctrl-C to disconenct")

    # listen to users and transcribe
    recognizers = {}
    is_transcribing = mp.Value('i', 1)
    vc.start_recording(VoskSink(vosk_model, is_transcribing, recognizers))
    print("Transcriber has started")


    try:
        # wait for shutdown response
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        # cleanup when shutting down
        is_transcribing.value = 0
        await vc.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Received exception: {str(e)}")
        print("Shutting down...")
    finally:
        print("Finished shutting down")
