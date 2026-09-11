[![Entangled badge](https://img.shields.io/badge/entangled-Use%20the%20source!-%2300aeff)](https://entangled.github.io/)

# berry
A system of AI systems made to entertain, in the vein of [Neuro-sama](https://vedal.ai/). (Go support Vedal!)

## Stoat Integration
I am using [Stoat](https://stoat.chat/) as the main way for me and my friends to communicate with b"rry.

I chose Stoat over [Discord](https://discord.com/) due to running into issues over voice reception and [DAVE](https://discord.com/blog/meet-dave-e2ee-for-audio-video), as well as the fact that a Discord bot would be unable to send and receive video.

Additionally, I want the option to self host Stoat in the future, in case I run into issues regarding Discord.

[`stoatbot.py`](./stoatbot.py):
```{.python file=stoatbot.py}
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
stt_url = f"http://{os.environ["STT_IP"]}:{os.environ["STT_PORT"]}"
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
Stoat uses [LiveKit](https://docs.livekit.io/reference/python/livekit/rtc/index.html) to handle voice and video connections.

I am planning to have b"rry be able to only join 1 LiveKit Room in Stoat.
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
            data = {
                "from": "stoat",
                "register": participant.identity,
            }
            try: requests.post(stt_url, json=data)
            except: pass
            task = asyncio.create_task(handle_audio(pub.track, participant))
            tasks.append(task)
```

Then, the users that subsequently join the voice channel need to also be subscribed to.

`stoat_voice_recv_sub_to_users`:
``` {.python #stoat_voice_recv_sub_to_users}
# for users that will join the voice channel
@room.on("track_subscribed")
def on_track_subscribe(track, publication, participant):
    if track.kind == rtc.TrackKind.KIND_AUDIO:
        data = {
            "from": "stoat",
            "register": participant.identity,
        }
        try: requests.post(stt_url, json=data)
        except: pass
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
            data = {
                "from": "stoat",
                "userid": participant.identity,
                "username": participant.name,
                "channels": frame.num_channels,
                "framerate": frame.sample_rate,
                "data": base64.b64encode(bytes(frame.data)).decode("utf-8")
            }
            try: requests.post(stt_url, json=data)
            except: pass

    # close the stream
    except asyncio.CancelledError: pass
    finally: await audio_stream.aclose()
```

## Speech to Text
Speech to text is handled through [Moonshine Voice](https://moonshine-voice.readthedocs.io/en/latest/).
This program is an HTTP server that accepts audio encoded into JSON and runs them through a Moonshine transcriber stream.

[`stt.py`](stt.py):
``` {.python file=stt.py}
# /// script
# dependencies = [
#   "moonshine-voice",
#   "numpy",
# ]
# ///

import base64
import http.server as server
import json
import moonshine_voice as msv
import numpy as np
import os


streams = {}
server_ip = os.environ["STT_IP"]
server_port = os.environ["STT_PORT"]
<<stt_moonshine_setup>>


# setup server handler
class STTHandler(server.BaseHTTPRequestHandler):
    <<stt_http_helpers>>
    def do_POST(self):
        try:
            # get request contents
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            if "from" not in data or data["from"] not in ["stoat"]: raise Exception("From field not found")
            if data["from"] == "stoat":
                <<stt_stoat_reg_user>>
                <<stt_stoat_data_checks>>
                <<stt_stoat_process_audio>>

            self.build_send_response(200, {"success": True})
            return
        except Exception as e:
            print(str(e))
            self.build_send_response(400, {"success": False, "error": str(e)})
            return


# run the server
def main():
    with server.HTTPServer((server_ip, int(server_port)), STTHandler) as stt_server:
        print("STT server started")
        stt_server.serve_forever()
if __name__ == "__main__": main()
```

### Moonshine Setup

`stt_moonshine_setup`:
``` {.python #stt_moonshine_setup}
model_path, model_arch = msv.get_model_for_language("en", msv.ModelArch.MEDIUM_STREAMING)
transcriber = msv.Transcriber(model_path=model_path, model_arch=model_arch)
```

`stt_moonshine_setup`:
``` {.python #stt_moonshine_setup}
class LineListener(msv.TranscriptEventListener):
    def register_user(self, userid):
        self.userid = userid
        print(f"Registered userid {userid} to LineListener")
    def on_line_started(self, event): pass
    def on_line_text_changed(self, event): pass

    def on_line_completed(self, event):
        print(f"{streams[self.userid]["username"]}: {event.line.text}")
```

### HTTP Server Helpers
Here are some helper methods to make the output of the 

If we print out all logs from the server, even if they are a successes, the console gets crowded and it becomes harder to catch when other events happen that are logged through printing to the console.

`stt_http_helpers`:
``` {.python #stt_http_helpers}
# suppress non-error messages
def log_message(self, format, *args):
    if args and str(args[-1]) not in ("200"): super().log_message(format, *args)
def log_request(self, code='-', size='-'): pass
```

This method is simply a helper to make it easier to build responses to requests.

`stt_http_helpers`:
``` {.python #stt_http_helpers}
# make JSON responses easy
def build_send_response(self, code, response_json):
    response_bytes = json.dumps(response_json).encode("utf-8")
    self.send_response(code)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(response_bytes)))
    self.end_headers()
    self.wfile.write(response_bytes)
```


### Stoat
For now, Stoat is the only integration for this server.
From the Stoat bot, the data that can be parsed in the STT server are:
- `register`: Contains the `userid` of the user to register a Moonshine stream for
  - If it is provided, it will register the user and continue to the next request
- `userid`: The ID of the user whose audio data is being provided
- `username`: The name of the user whose audio data is being provided
- `channels`: How many audio channels the audio data has
- `framerate`: The sample rate of the audio data
- `data`: The bytes of the `int16` audio data provided by LiveKit RTC encoded as base64
  - Needs to be decoded and transformed into a float32 from [-1.0, 1.0] in order to be processed by Moonshine

#### Register New User
Handles the `register` field, if provided in the JSON body.

`stt_stoat_reg_user`:
``` {.python #stt_stoat_reg_user}
# register user if register command is given
if "register" in data and type(data["register"]) == str and data["register"] not in streams:
    print(f"Registering user {data["register"]}")

    streams[data["register"]] = {}
    streams[data["register"]]["ready"] = False
    streams[data["register"]]["stream"] = transcriber.create_stream(update_interval=0.1)
    streams[data["register"]]["listener"] = LineListener()

    streams[data["register"]]["listener"].register_user(data["register"])
    streams[data["register"]]["stream"].add_listener(streams[data["register"]]["listener"])
    streams[data["register"]]["stream"].start()

    streams[data["register"]]["ready"] = True
    print(f"User {data["register"]} registered in streams")
    self.build_send_response(200, {"success": True})
    return
```

#### JSON Data Checks
First, we need to ensure `userid` is in the `streams` dictionary, in which case the program can receive.

`stt_stoat_data_checks`:
``` {.python #stt_stoat_data_checks}
# check if user is already registered in streams
if "userid" not in data or type(data["userid"]) != str: Exception("No userid (string) provided")
if data["userid"] not in streams or streams[data["userid"]]["ready"] != True:
    self.build_send_response(200, {"success": True})
    return
```

Once it is confirmed that the `userid` field exists, we can proceed to checking for the other necessary data for Stoat.

`stt_stoat_data_checks`:
``` {.python #stt_stoat_data_checks}
# check for necessary fields
if "username" not in data or type(data["username"]) != str: Exception("No username (string) provided")
if "username" not in streams[data["userid"]]: streams[data["userid"]]["username"] = data["username"]
if "channels" not in data or type(data["channels"]) != int: Exception("No channels (int) provided")
# TODO: do something if channels is not mono
if "framerate" not in data or type(data["framerate"]) != int: Exception("No framerate (int) provided")
if "data" not in data or type(data["data"]) != str: Exception("No data (string) provided")
```

#### Process Audio
The audio data needs to be decoded from base64 and turned into a float from [-1.0, 1.0], in which case we use NumPy.

`stt_stoat_process_audio`:
``` {.python #stt_stoat_process_audio}
# decode audio frame from base64
audio_frame = None
try: audio_frame = bytes(base64.b64decode(data["data"]))
except Exception as e: raise e
samples = np.frombuffer(audio_frame, dtype=np.int16)
samples = samples.astype(np.float32) / 32768.0

# add audio to stream
streams[data["userid"]]["stream"].add_audio(audio_data=samples, sample_rate=data["framerate"])
```
