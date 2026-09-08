# ~/~ begin <<README.md#sloatbot.py>>[init]
# /// script
# dependencies = [
#   "stoat.py[voice,speed]",
# ]
# ///

import asyncio
from livekit import rtc
import os
import stoat
import wave

client = stoat.Client()
room = None
tasks = []


# setup commands
@client.on(stoat.MessageCreateEvent)
async def on_message(event, /):
    global room, tasks

    message = event.message
    if message.author.relationship is stoat.RelationshipStatus.user: return

    # join command
    if message.content == "$berryjoin":
        if room != None:
            await message.channel.send("b\"rry is already in a voice channel")
            return

        voice_states = client.voice_states
        voice_channel_id = None
        for channel_id, voice_channel in voice_states.items():
            if message.author_id in voice_channel.participants:
                voice_channel_id = channel_id
                break
        if voice_channel_id == None:
            await message.channel.send("You are not in a voice channel")
            return

        voice_channel = client.get_channel(voice_channel_id)
        room = await voice_channel.connect()

        # manage what happens when audio packet is received
        async def handle_audio(track, participant):
            print("Subscribed to user:", participant)

            audio_stream = rtc.AudioStream(track)
            wav_file = None
            try:
                # receives packets even during silence, which is nice
                async for event in audio_stream:
                    frame = event.frame
                    if wav_file is None:
                        wav_file = wave.open(str(participant.identity), "wb")
                        wav_file.setnchannels(frame.num_channels)
                        wav_file.setsampwidth(2)
                        wav_file.setframerate(frame.sample_rate)
                    wav_file.writeframes(frame.data)

            # close the stream
            except asyncio.CancelledError: pass
            finally:
                if wav_file: wav_file.close()
                await audio_stream.aclose()

        # subscribe to the user tasks
        ## for users already in the voice channel
        @room.on("track_subscribed")
        def on_track_subscribe(track, publication, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                task = asyncio.create_task(handle_audio(track, participant))
                tasks.append(task)
        ## for users that will join the voice channel
        for participant in room.remote_participants.values():
            for pub in participant.track_publications.values():
                if pub.track and pub.kind == rtc.TrackKind.KIND_AUDIO:
                    task = asyncio.create_task(handle_audio(pub.track, participent))
                    tasks.append(task)

        await message.channel.send("b\"rry has joined the voice channel")
        print(room)

    # leave command
    elif message.content == "$berryleave":
        if room == None:
            await message.channel.send("b\"rry is not in a voice channel to leave")
            return

        for task in tasks: task.cancel()
        tasks = []

        await room.disconnect()
        room = None

        await message.channel.send("b\"rry has left the voice channel")


# run the bot
@client.on(stoat.ReadyEvent)
async def on_ready(event, /):
    print(f"Logged in as {event.me.tag}")

client.run(os.environ["STOAT_TOKEN"])
# ~/~ end
