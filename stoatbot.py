# ~/~ begin <<README.md#stoatbot.py>>[init]
# /// script
# dependencies = [
#   "requests",
#   "stoat.py[voice,speed]",
# ]
# ///

import asyncio
import base64
from livekit import rtc
import os
import requests
import stoat
import wave

client = stoat.Client()
tasks = []
# ~/~ begin <<README.md#stoat_globals>>[init]
room = None
# ~/~ end
# ~/~ begin <<README.md#stoat_globals>>[1]
tasks = []
# ~/~ end

# setup commands
@client.on(stoat.MessageCreateEvent)
async def on_message(event, /):
    global room, tasks
    message = event.message
    if message.author.relationship is stoat.RelationshipStatus.user: return

    # join command
    if message.content == "$berryjoin":
        # ~/~ begin <<README.md#stoat_join_vc>>[init]
        if room != None:
            await message.channel.send("b\"rry is already in a voice channel")
            return
        # ~/~ end
        # ~/~ begin <<README.md#stoat_join_vc>>[1]
        voice_states = client.voice_states
        voice_channel_id = None
        for channel_id, voice_channel in voice_states.items():
            if message.author_id in voice_channel.participants:
                voice_channel_id = channel_id
                break
        if voice_channel_id == None:
            await message.channel.send("You are not in a voice channel")
            return
        # ~/~ end
        # ~/~ begin <<README.md#stoat_join_vc>>[2]
        voice_channel = client.get_channel(voice_channel_id)
        room = await voice_channel.connect()
        # ~/~ end
        # ~/~ begin <<README.md#stoat_voice_receive>>[init]
        # ~/~ begin <<README.md#stoat_voice_recv_handle_audio>>[init]
        # manage what happens when audio packet is received
        async def handle_audio(track, participant):
            print("Subscribed to user:", participant)
        
            audio_stream = rtc.AudioStream(track)
            wav_file = None
            try:
                # receives packets even during silence, which is nice
                async for event in audio_stream:
                    frame = event.frame
                    data = {
                        "from": "stoat",
                        "userid": participant.identity,
                        "username": participant.name,
                        "channels": frame.num_channels,
                        "framerate": frame.sample_rate,
                        "data": base64.b64encode(bytes(frame.data)).decode("utf-8")
                    }
                    try: requests.post("http://localhost:8000", json=data)
                    except: pass
        
            # close the stream
            except asyncio.CancelledError: pass
            finally: await audio_stream.aclose()
        # ~/~ end
        # ~/~ begin <<README.md#stoat_voice_recv_sub_to_users>>[init]
        # for users that are already in the voice channel
        for participant in room.remote_participants.values():
            for pub in participant.track_publications.values():
                if pub.track and pub.kind == rtc.TrackKind.KIND_AUDIO:
                    data = {
                        "from": "stoat",
                        "register": participant.identity,
                    }
                    try: requests.post("http://localhost:8000", json=data)
                    except: pass
                    task = asyncio.create_task(handle_audio(pub.track, participant))
                    tasks.append(task)
        # ~/~ end
        # ~/~ begin <<README.md#stoat_voice_recv_sub_to_users>>[1]
        # for users that will join the voice channel
        @room.on("track_subscribed")
        def on_track_subscribe(track, publication, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                data = {
                    "from": "stoat",
                    "register": participant.identity,
                }
                try: requests.post("http://localhost:8000", json=data)
                except: pass
                task = asyncio.create_task(handle_audio(track, participant))
                tasks.append(task)
        # ~/~ end
        # ~/~ end
        await message.channel.send("b\"rry has joined the voice channel")
        print(room)

    # leave command
    elif message.content == "$berryleave":
        # ~/~ begin <<README.md#stoat_dc_cleanup>>[init]
        for task in tasks: task.cancel()
        tasks = []
        # ~/~ end
        # ~/~ begin <<README.md#stoat_leave_vc>>[init]
        if room == None:
            await message.channel.send("b\"rry is not in a voice channel to leave")
            return
        # ~/~ end
        # ~/~ begin <<README.md#stoat_leave_vc>>[1]
        await room.disconnect()
        room = None
        await message.channel.send("b\"rry has left the voice channel")
        # ~/~ end

# run the bot
@client.on(stoat.ReadyEvent)
async def on_ready(event, /): print(f"Logged in as {event.me.tag}")
client.run(os.environ["STOAT_TOKEN"])
# ~/~ end
