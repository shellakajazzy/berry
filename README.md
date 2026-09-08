[![Entangled badge](https://img.shields.io/badge/entangled-Use%20the%20source!-%2300aeff)](https://entangled.github.io/)

# berry
A system of AI systems made to entertain, in the vein of [Neuro-sama](https://vedal.ai/). (Go support Vedal!)

## Sloat Integration
I am using [Sloat](https://stoat.chat/) as the main way for me and my friends to communicate with b"rry.

I chose Sloat over [Discord](https://discord.com/) due to running into issues over voice reception and [DAVE](https://discord.com/blog/meet-dave-e2ee-for-audio-video), as well as the fact that a Discord bot would be unable to send and receive video.

Additionally, I want the option to self host Sloat in the future, in case I run into issues regarding Discord.

[`stoatbot.py`](./stoatbot.py):
```{.python file=stoatbot.py}
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
tasks = []
<<stoat_globals>>

# setup commands
@client.on(stoat.MessageCreateEvent)
async def on_message(event, /):
    global room, tasks
    message = event.message
    if message.author.relationship is stoat.RelationshipStatus.user: return

    # join command
    if message.content == "$berryjoin":
        <<stoat_join_vc>>
        <<stoat_voice_receive>>
        await message.channel.send("b\"rry has joined the voice channel")
        print(room)

    # leave command
    elif message.content == "$berryleave":
        <<stoat_dc_cleanup>>
        <<stoat_leave_vc>>

# run the bot
@client.on(stoat.ReadyEvent)
async def on_ready(event, /): print(f"Logged in as {event.me.tag}")
client.run(os.environ["STOAT_TOKEN"])
```

### Join Voice Channel
Sloat uses [LiveKit](https://docs.livekit.io/reference/python/livekit/rtc/index.html) to handle voice and video connections.

I am planning to have b"rry be able to only join 1 LiveKit Room in Sloat.
Thus, we need to ensure that the `room` global is `None` before attempting to connect to a VC.

`stoat_globals`:
``` {.python #stoat_globals}
room = None
```

`stoat_join_vc`:
``` {.python #stoat_join_vc}
if room != None:
    await message.channel.send("b\"rry is already in a voice channel")
    return
```

Next, we need to check if the user calling the command is in a voice channel and obtain the channel's ID.
If the user is not in a voice channel, then we need to tell them to join one.

`stoat_join_vc`:
``` {.python #stoat_join_vc}
voice_states = client.voice_states
voice_channel_id = None
for channel_id, voice_channel in voice_states.items():
    if message.author_id in voice_channel.participants:
        voice_channel_id = channel_id
        break
if voice_channel_id == None:
    await message.channel.send("You are not in a voice channel")
    return
```

Finally, we can have the bot join the voice channel.

`stoat_join_vc`:
``` {.python #stoat_join_vc}
voice_channel = client.get_channel(voice_channel_id)
room = await voice_channel.connect()
```

### Leave Voice Channel
Leaving a voice channel requires the bot to actually be in a voice channel.
If the bot isn't in a voice channel, tell the user and continue.

`stoat_leave_vc`:
``` {.python #stoat_leave_vc}
if room == None:
    await message.channel.send("b\"rry is not in a voice channel to leave")
    return
```

Then, we can actually disconnect from the voice channel and ensure that the `room` variable is set to `None` so that the bot can join another voice channel if needed.

`stoat_leave_vc`:
``` {.python #stoat_leave_vc}
await room.disconnect()
room = None
await message.channel.send("b\"rry has left the voice channel")
```

### Voice Receive

There are two parts to receiving voice through LiveKit:
1. Subscribing to users
1. Handling received audio packets

`stoat_voice_receive`:
``` {.python #stoat_voice_receive}
<<stoat_voice_recv_handle_audio>>
<<stoat_voice_recv_sub_to_users>>
```

#### Subscribing
First we need to subcribe to the users that are already in the voice channel.

`stoat_voice_recv_sub_to_users`:
``` {.python #stoat_voice_recv_sub_to_users}
# for users that are already in the voice channel
for participant in room.remote_participants.values():
    for pub in participant.track_publications.values():
        if pub.track and pub.kind == rtc.TrackKind.KIND_AUDIO:
            task = asyncio.create_task(handle_audio(pub.track, participent))
            tasks.append(task)
```

Then, the users that subsequently join the voice channel need to also be subscribed to.

`stoat_voice_recv_sub_to_users`:
``` {.python #stoat_voice_recv_sub_to_users}
# for users that will join the voice channel
@room.on("track_subscribed")
def on_track_subscribe(track, publication, participant):
    if track.kind == rtc.TrackKind.KIND_AUDIO:
        task = asyncio.create_task(handle_audio(track, participant))
        tasks.append(task)
```


The tasks created by these code snippets contain need to be stored in a global variable.

`stoat_globals`:
``` {.python #stoat_globals}
tasks = []
```

And, these tasks need to be cleaned up when disconnecting from the VC.

`stoat_dc_cleanup`:
``` {.python #stoat_dc_cleanup}
for task in tasks: task.cancel()
tasks = []
```

#### Handling
For now, I am having the user's audio be recorded to a Wave file, which is the placeholder until I implement the speech to text server.

`stoat_voice_receive_handle_audio`:
``` {.python #stoat_voice_recv_handle_audio}
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
```
