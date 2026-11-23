# /// script
# dependencies = [
#   "httpx",
#   "pydantic",
#   "websockets",
#
#   "qwen_tokenizer"
# ]
# ///


import config

import asyncio
import copy
import http
import httpx
import json
import os
import pydantic
import signal
import struct
import time
import typing
import websockets

from qwen_tokenizer import get_tokenizer
TOKENIZER = get_tokenizer("qwen3.5-4b")


CLIENTS = set()   # list of ALL clients connected to the main websocket
ACTIONS = {}      # contains actions for games and clients associated with games

# contains routes for voices, and the clients and speakers for a route
VOICE_ROUTES = {}
SPEECH_STATE = {
    "lock": None,
    "end_time": round(time.time() * 1000)
}

# stores the context necessary, as well as caching token length for each line
# these events are shared for both speech and action generation
EVENTS = {
    "lock": None,
    "timestamp": round(time.time() * 1000),
    "speech_idx": -1, # set >= 0 to make the speech generator run
    "msgs": []
}
LLAMA_LOCK = None

# JSON encoding validation types
class Message(pydantic.BaseModel):
    command: str
    game: str
    data: typing.Optional[dict[str, typing.Any]] = None

# "data" field validations
UInt16 = typing.Annotated[int, pydantic.Field(ge = 0, le = 65535)]
class Action(pydantic.BaseModel):
    class Schema(pydantic.BaseModel):
        type: typing.Literal["object"]
        model_config = pydantic.ConfigDict(extra="allow")
    model_config = pydantic.ConfigDict(populate_by_name=True)

    name: str
    description: str
    schema_: Schema | None = pydantic.Field(default=None, alias="schema")
class ContextData(pydantic.BaseModel):
    message: str
    silent: bool
class ActionsRegisterData(pydantic.BaseModel):
    actions: list[Action]
class ActionsUnregisterData(pydantic.BaseModel):
    action_names: list[str]
class ActionsForceData(pydantic.BaseModel):
    state: str | None = None
    query: str
    ephemeral_context: bool = False
    priority: typing.Literal["low", "medium", "high", "critical"] = "low"
    silent: bool = False
    action_names: list[str] = pydantic.Field(min_length=1)
class ActionsResultData(pydantic.BaseModel):
    id: str
    success: bool
    message: str | None = None
class VoiceSpeakersRegisterData(pydantic.BaseModel):
    class Speaker(pydantic.BaseModel):
        id: UInt16
        name: str
    speakers: list[Speaker]
class VoiceSpeakersUnregisterData(pydantic.BaseModel):
    ids: list[UInt16]


# handler for JSON websocket requests
async def handler(websocket):
    global CLIENTS, ACTIONS, VOICE_ROUTES, EVENTS

    # if this is for voice, pass it to the voice handler
    if websocket.request.path in VOICE_ROUTES:
        await voice_recv_handler(websocket)
        return

    CLIENTS.add(websocket)
    print(f"{id(websocket)} connected to core!")

    try:
        async for message in websocket:
            msg_json = None
            try:
                msg_json = json.loads(message)
                Message.model_validate(msg_json)
            except: pass

            game = msg_json["game"]
            data = None
            if "data" in msg_json: data = msg_json["data"]
            match msg_json["command"]:
                case "startup":
                    # clear all actions for a game
                    ACTIONS[game] = {
                            "clients": set(),
                            "actions": []
                    }
                    ACTIONS[game]["clients"].add(websocket)

                    await websocket.send(json.dumps({
                        "command": "startup",
                        "data": {
                            "session": {
                                "sessionId": str(websocket.id),
                                "characterId": config.CHARACTER_ID,
                                "displayName": config.DISPLAY_NAME
                            }
                        }
                    }))
                case "context":
                    # validate context and add to events

                    try: ContextData.model_validate(data)
                    except: continue

                    async with EVENTS["lock"]:
                        msg = f"[Event From Game {game}]: {data["message"]}\n"
                        EVENTS["msgs"] += [{
                            "msg": msg,
                            "tokens": len(TOKENIZER.encode(msg))
                        }]
                        EVENTS["timestamp"] = round(time.time() * 1000)
                        print(msg)
                case "speech/started":
                    pass # TODO
                case "speech/ended":
                    pass # TODO
                case "actions/register":
                    try: ActionsRegisterData.model_validate(data)
                    except: continue

                    ACTIONS[game]["actions"] += data["actions"]
                case "actions/unregister":
                    try: ActionsUnregisterData.model_validate(data)
                    except: continue
                case "actions/force":
                    try: ActionsForceData.model_validate(data)
                    except: continue

                    # TODO: perform task
                case "actions/result":
                    try: ActionsResultData.model_validate(data)
                    except: continue

                    if data["success"] == False:
                        pass # TODO: retry action
                case "voice/start":
                    # registers a game that has voice support (if not already there)

                    # if game does not support voice chat, return an error
                    if game not in config.SUPPORTED_VOICE_GAMES:
                        await websocket.send(json.dumps({
                            "command": "voice/unavailable",
                            "data": {
                                "reason": f"Voice chat not supported for {game}"
                            }
                        }))
                        continue

                    # create the route
                    VOICE_ROUTES = {}
                    if f"/game/{game}/voice" not in VOICE_ROUTES:
                        VOICE_ROUTES[f"/game/{game}/voice"] = {
                            "clients": set(),
                            "speakers": {}
                        }
                        print(f"Added voice route for {game} at ws://0.0.0.0/game/{game}/voice")
                    await websocket.send(json.dumps({
                        "command": "voice/ready",
                        "data": {
                            "sample_rate": 48000,
                            "channels": 1
                        }
                    }))
                case "voice/speakers/register":
                    # registers speakers by their ID

                    try: VoiceSpeakersRegisterData.model_validate(data)
                    except: continue

                    for speaker in data["speakers"]:
                        if speaker["id"] in VOICE_ROUTES[f"/game/{game}/voice"]["speakers"]:
                            async with VOICE_ROUTES[f"/game/{game}/voice"]["speakers"][speaker["id"]]["lock"]:
                                if VOICE_ROUTES[f"/game/{game}/voice"]["speakers"][speaker["id"]]["name"] != speaker["name"]:
                                    VOICE_ROUTES[f"/game/{game}/voice"]["speakers"][speaker["id"]]["name"] = speaker["name"]
                                    print(f"Updated name of id {speaker["id"]} with name {speaker["name"]}")
                        else:
                            VOICE_ROUTES[f"/game/{game}/voice"]["speakers"][speaker["id"]] = {
                                "lock": asyncio.Lock(),
                                "name": speaker["name"],
                                "timestamp": None,
                                "segment": b""
                            }
                            print(f"Registered speaker with id {speaker["id"]} and name {speaker["name"]}")
                case "voice/speakers/unregister":
                    # deletes speakers by their ID

                    try: VoiceSpeakersUnregisterData.model_validate(data)
                    except: continue

                    for speaker_id in data["ids"]:
                        try: del VOICE_ROUTES[f"/game/{game}/voice"]["speakers"][speaker_id]
                        except: continue
    except websockets.ConnectionClosed: pass
    finally: CLIENTS.discard(websocket)


# helper functions for voice support
async def stt_processor():
    # processes speech provided through a /game/<game>/voice websocket
    # runs speech to text on it
    global VOICE_ROUTES, EVENTS
    print("Started speech to text processor!")

    while True:
        for route_name, route in VOICE_ROUTES.items():
            for speaker_id, speaker in route["speakers"].items():
                # create a copy of the speaker segment and info so that the buffer can be cleared
                # for more streamed in audio packets
                speaker_copy = {"id": speaker_id}
                async with speaker["lock"]:
                    timestamp = round(time.time() * 1000)
                    if (speaker["timestamp"] == None or
                        speaker["timestamp"] + config.VOICE_THRESHOLD_MS > timestamp):
                        continue

                    # copy over name and segment if necessary
                    speaker_copy["name"] = copy.deepcopy(speaker["name"])
                    speaker_copy["segment"] = copy.deepcopy(speaker["segment"])
                    # reset to get new frames
                    speaker["timestamp"] = None
                    speaker["segment"] = b""

                # get event lock
                async with EVENTS["lock"]:
                    # convert from 48 kHz mono PCM to something acceptable by whisper.cpp (16 kHz, wav)
                    proc = await asyncio.create_subprocess_exec(
                        "ffmpeg",
                        "-f", "f32le", "-ar", "48000", "-ac", "1", "-i", "pipe:0",
                        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                        "-f", "wav", "pipe:1",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    wav_bytes, err = await proc.communicate(input=bytes(speaker_copy["segment"]))
                    if proc.returncode != 0:
                        print(f"ffmpeg failed: {err.decode()}")
                        continue

                    # make the HTTP request to the whisper server
                    async with httpx.AsyncClient() as http_client:
                        res = await http_client.post(
                            f"http://{config.WHISPER_IP}:{config.WHISPER_PORT}/inference",
                            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                            data={"temperature": "0.0", "response_formate": "json"},
                            timeout=60.0
                        )
                        transcription = res.json()["text"][1:-1] # can cut off start (" ") and end ("\n") characters
                        if transcription == "": continue

                        # route_name[6:-6] is the name of the game that has voice support, it cuts off "/game/" and "/voice"
                        msg = f"[Voice Chat From {route_name[6:-6]} User {speaker_copy["name"]}]: {transcription}\n"
                        EVENTS["msgs"] += [{
                            "msg": msg,
                            "tokens": len(TOKENIZER.encode(msg))
                        }]
                        EVENTS["timestamp"] = round(time.time() * 1000)
                        print(msg)

                        # only respond to current message if we are done speaking the previous time
                        if round(time.time() * 1000) > SPEECH_STATE["end_time"]:
                            # will include up to the latest new event message
                            EVENTS["speech_idx"] = len(EVENTS["msgs"]) # will include up to the latest new event message

        await asyncio.sleep(0.01)

# generator that runs the LLM for speech
# also sends out the websocket request to the clients
# architecture is heavily inspired by LimitCantCode
async def speech_gen():
    global EVENTS, LLAMA_LOCK

    print("Started speech generator!")

    sys_prompt_tokens = len(TOKENIZER.encode(config.SPEECH_SYS_PROMPT))
    token_budget = int((config.LLAMA_CTX_SIZE - config.SPEECH_MAX_GEN_SIZE - sys_prompt_tokens) * 0.95) # arbitrary 5% token buffer lol

    while True:
        speech_idx = EVENTS["speech_idx"]
        if speech_idx < 0:
            # only run the generator pass once the speech_idx is >= 0
            await asyncio.sleep(0.01)
            continue

        # don't create a response if the bot is still speaking
        # this should also cancel the current speech index because otherwise it would try again
        if round(time.time() * 1000) <= SPEECH_STATE["end_time"]:
            speech_idx = -1
            continue

        # create prompt
        events = EVENTS["msgs"][:speech_idx][::-1]
        prompt = ""
        prompt_tokens = 0
        for event in events:
            # we are cramming as many events as possible into the context if possible
            if event["tokens"] + prompt_tokens >= token_budget: break
            prompt = event["msg"] + prompt
            prompt_tokens += event["tokens"]

        # make request to llama.cpp
        reply = None
        async with LLAMA_LOCK:
            async with httpx.AsyncClient() as http_client:
                res = await http_client.post(
                    f"http://{config.LLAMA_IP}:{config.LLAMA_PORT}/v1/chat/completions",
                    json={
                        "model": "local",
                        "messages": [
                            {"role": "system", "content": config.SPEECH_SYS_PROMPT},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.7,
                        "max_tokens": config.SPEECH_MAX_GEN_SIZE
                    },
                    timeout = 60.0
                )
                reply = res.json()["choices"][0]["message"]["content"]

        # add response to events
        async with EVENTS["lock"]:
            msg = f"[YOU ({config.DISPLAY_NAME}) SAID]: {reply}\n"
            print(msg)
            EVENTS["msgs"] += [{
                "msg": msg,
                "tokens": len(TOKENIZER.encode(msg))
            }]

        # get clients to broadcast to
        targets = set()
        for _, route in VOICE_ROUTES.items(): targets.update(route["clients"])

        # generate TTS and stream to clients
        r, w = os.pipe()
        # using espeak for now
        espeak = await asyncio.create_subprocess_exec(
            "espeak-ng",
            "--stdout",
            "-v", "en-us+f3",
            "-s", "150",
            "--", reply,
            stdout=w,
            stderr=asyncio.subprocess.DEVNULL
        )
        # need to make it match the Neuro API spec
        ffmpeg = await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "quiet",
            "-f", "wav", "-i", "pipe:0",
            "-f", "f32le", "-acodec", "pcm_f32le",
            "-ar", "48000", "-ac", "1",
            "pipe:1",
            stdin=r,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        os.close(w)
        os.close(r)

        # stream bytes to clients
        end_time = round(time.time() * 1000)
        try:
            leftover = b""
            # 20 ms packets (3840 bytes), 4 bytes per sample
            while chunk := await ffmpeg.stdout.read(3840):
                data = leftover + chunk
                cut = len(data) - len(data) % 4
                leftover = data[cut:]
                if cut:
                    websockets.broadcast(targets, data[:cut])
                    end_time += round((len(data[:cut]) / 3840) * 20)
        except: pass # funny haha no errors !!!!!!!
        finally:
            # clean subprocesses
            for p in (espeak, ffmpeg):
                if p.returncode is None: p.kill()
            await p.wait()
        async with SPEECH_STATE["lock"]: SPEECH_STATE["end_time"] = end_time

        # set the lock to < 0 iff it has not been updated since the start of the generation pass
        if EVENTS["speech_idx"] != speech_idx: continue
        async with EVENTS["lock"]: EVENTS["speech_idx"] = -1 # only runs if the speech_idx in EVENTS
                                                             # is equal to the speech_idx of the current pass

        await asyncio.sleep(0.01)

# websocket handler for voice receive
async def voice_recv_handler(websocket):
    global CLIENTS, ACTIONS, VOICE_ROUTES, EVENTS

    voice_route = VOICE_ROUTES[websocket.request.path]
    VOICE_ROUTES[websocket.request.path]["clients"].add(websocket)
    print(f"{id(websocket)} connected to route {websocket.request.path}")


    async for message in websocket:
        timestamp = round(time.time() * 1000)
        speaker_id = int.from_bytes(message[2:4], byteorder="little", signed=False)

        if (speaker_id not in voice_route["speakers"] or
            type(voice_route["speakers"][speaker_id]["lock"]) != asyncio.Lock):
            continue

        speaker = voice_route["speakers"][speaker_id]
        async with speaker["lock"]:
            speaker["timestamp"] = timestamp
            speaker["segment"] += message[4:]


# run the server
def process_request(connection, request):
    # make a client raise an exception when connecting to an invalid path
    if request.path in VOICE_ROUTES or request.path == "/": return None
    return connection.respond(http.HTTPStatus.NOT_FOUND, "Unknown path\n")

async def main():
    global EVENTS, LLAMA_LOCK

    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)

    EVENTS["lock"] = asyncio.Lock()      # put the async lock on the events collection
    SPEECH_STATE["lock"] = asyncio.Lock()
    LLAMA_LOCK = asyncio.Lock()
    asyncio.create_task(stt_processor()) # run the stt processor in the background
    asyncio.create_task(speech_gen())    # run the speech generator in the background

    async with websockets.serve(handler, "0.0.0.0", config.NEUROAPI_PORT, process_request=process_request):
        print(f"Server running on ws://0.0.0.0:{config.NEUROAPI_PORT}")
        await stop

if __name__ == "__main__":
    asyncio.run(main())
