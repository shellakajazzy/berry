# /// script
# dependencies = [
#   "pydantic",
#   "websockets"
# ]
# ///


import config

import asyncio
import json
import pydantic
import signal
import typing
import websockets


EVENTS = []       # ordered list of events that took place
CLIENTS = ()      # list of ALL clients connected to the main websocket
ACTIONS = {}      # contains actions for games and clients associated with games
VOICE_ROUTES = {} # contains routes for voices, and the clients and speakers for a route


# JSON encoding validation types
class Message(pydantic.BaseModel):
    command: str
    game: str
    data: typing.Optional[dict[str, typing.Any]] = None

# "data" field validations
UInt16 = Annotated[int, pydantic.Field(ge = 0, le = 65535)]
class Action(pydantic.BaseModel):
    class Schema(pydantic.BaseModel):
        type: pydantic.Literal["object"]
        model_config = ConfigDict(extra="allow")
    model_config = ConfigDict(populate_by_name=True)

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
    priority: Literal["low", "medium", "high", "critical"] = "low"
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
    CLIENTS.add(websocket)

    # if this is for voice, pass it to the voice handler
    if websocket.request.path in VOICE_ROUTES:
        await voice_recv_handler(websocket)
        return

    try:
        async for message in websocket:
            await websocket.send(f"echo: {message}")
            print(f"from: {id(websocket)}, msg: {message}")

            msg_json = None
            try:
                msg_json = json.loads(message)
                Message.model_validate(msg_json)
            except: pass

            game = msg_json["game"]
            data = msg_json["data"]
            match msg_json["command"]:
                case "startup":
                    # clear all actions for a game
                    ACTIONS[game] = {
                            "clients": (),
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

                    # create the route and add the client to it
                    VOICE_ROUTES = {}
                    if f"/game/{game}/voice" not in VOICE_ROUTES:
                        VOICE_ROUTES[f"/game/{game}/voice"] = {
                            "clients": (),
                            "speakers": {}
                        }
                        print(f"Added voice route for {game} at ws://0.0.0.0/game/{game}/voice")
                    VOICE_ROUTES[f"/game/{game}/voice"]["clients"].add(websocket)
                    print(f"Added client {} to voice route /game/{game}/voice")
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
                        VOICE_ROUTES[f"/game/{game}/voice"]["speakers"][speaker["id"]] = speaker["name"]
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
async def voice_recv_handler(websocket):
    async for message in websocket:
        msg_bytes = message.encode("utf-8")
        print(f"Received audio bytes {msg_bytes}")
        # TODO: speech to text, add to events


# run the server
async def main():
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)

    async with websockets.serve(handler, "0.0.0.0", config.NEUROAPI_PORT):
        print(f"Server running on ws://0.0.0.0:{config.NEUROAPI_PORT}")
        await stop

if __name__ == "__main__":
    asyncio.run(main())
