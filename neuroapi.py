# /// script
# dependencies = [
#   "httpx",
#   "pydantic",
#   "websockets"
# ]
# ///


import config

import asyncio
import copy
import http
import httpx
import json
import pydantic
import signal
import struct
import time
import typing
import websockets


CLIENTS = set()   # list of ALL clients connected to the main websocket
ACTIONS = {}      # contains actions for games and clients associated with games
VOICE_ROUTES = {} # contains routes for voices, and the clients and speakers for a route


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
    global CLIENTS, ACTIONS, VOICE_ROUTES

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

                    pass
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


# handler for voice receive (speech to text)
async def stt_processor():
    global VOICE_ROUTES

    print("Started speech to text processor")
    while True:
        for _, route in VOICE_ROUTES.items():
            for speaker_id, speaker in route["speakers"].items():
                # create a copy of the speaker segment and info so that the buffer can be cleared
                # for more streamed in audio packets
                speaker_copy = {"id": speaker_id}
                async with speaker["lock"]:
                    timestamp = round(time.time() * 1000)
                    if (speaker["timestamp"] == None or
                        speaker["timestamp"] + config.VOICE_THRESHOLD_MS > timestamp):
                        continue

                    speaker_copy["name"] = copy.deepcopy(speaker["name"])
                    speaker_copy["segment"] = copy.deepcopy(speaker["segment"])

                    speaker["timestamp"] = None
                    speaker["segment"] = b""

                # convert from 48 kHz mono PCM to something acceptable by whisper.cpp
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

                async with httpx.AsyncClient() as http_client:
                    res = await http_client.post(
                        f"http://{config.WHISPER_IP}:{config.WHISPER_PORT}/inference",
                        files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                        data={"temperature": "0.0", "response_formate": "json"},
                        timeout=60.0
                    )
                    transcription = res.json()["text"][1:-1]
                    print(f"{speaker_copy["name"]} ({speaker_copy["id"]}): {transcription}")

        await asyncio.sleep(0.01)

async def voice_recv_handler(websocket):
    global CLIENTS, ACTIONS, VOICE_ROUTES

    voice_route = VOICE_ROUTES[websocket.request.path]
    VOICE_ROUTES[websocket.request.path]["clients"].add(websocket)
    print(f"{id(websocket)} connected to core {websocket.request.path}")


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
    if request.path in VOICE_ROUTES or request.path == "/": return None
    return connection.respond(http.HTTPStatus.NOT_FOUND, "Unknown path\n")

async def main():
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)

    asyncio.create_task(stt_processor())
    async with websockets.serve(handler, "0.0.0.0", config.NEUROAPI_PORT, process_request=process_request):
        print(f"Server running on ws://0.0.0.0:{config.NEUROAPI_PORT}")
        await stop

if __name__ == "__main__":
    asyncio.run(main())
