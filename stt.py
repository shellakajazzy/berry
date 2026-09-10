# ~/~ begin <<README.md#stt.py>>[init]
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

streams = {}
model_path, model_arch = msv.get_model_for_language("en", msv.ModelArch.MEDIUM_STREAMING)
transcriber = msv.Transcriber(model_path=model_path, model_arch=model_arch)

class StoatListener(msv.TranscriptEventListener):
    def register_user(self, userid):
        self.userid = userid
        print(f"Registered userid {userid} to StoatListener")

    def on_line_started(self, event): pass

    def on_line_text_changed(self, event): pass

    def on_line_completed(self, event):
        print(f"{streams[self.userid]["username"]}: {event.line.text}")

class STTHandler(server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        if args and str(args[-1]) not in ("200", "304"):
            super().log_message(format, *args)
    def log_request(self, code='-', size='-'): pass

    def build_send_response(self, code, response_json):
        response_bytes = json.dumps(response_json).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            if "from" not in data or data["from"] not in ["stoat"]: raise Exception("From field not found")
            if data["from"] == "stoat":
                # register user if register command is given
                if "register" in data and type(data["register"]) == str and data["register"] not in streams:
                    print(f"Registering user {data["register"]}")

                    streams[data["register"]] = {}
                    streams[data["register"]]["ready"] = False
                    streams[data["register"]]["stream"] = transcriber.create_stream(update_interval=0.1)
                    streams[data["register"]]["listener"] = StoatListener()

                    streams[data["register"]]["listener"].register_user(data["register"])
                    streams[data["register"]]["stream"].add_listener(streams[data["register"]]["listener"])
                    streams[data["register"]]["stream"].start()

                    streams[data["register"]]["ready"] = True
                    print(f"User {data["register"]} registered in streams")
                    self.build_send_response(200, {"success": True})
                    return

                # check if user is already registered in streams
                if "userid" not in data or type(data["userid"]) != str: Exception("No userid (string) provided")
                if data["userid"] not in streams or streams[data["userid"]]["ready"] != True:
                    self.build_send_response(200, {"success": True})
                    return

                # check for necessary fields
                if "username" not in data or type(data["username"]) != str: Exception("No username (string) provided")
                if "username" not in streams[data["userid"]]: streams[data["userid"]]["username"] = data["username"]
                if "channels" not in data or type(data["channels"]) != int: Exception("No channels (int) provided")
                # TODO: do something if channels is not mono
                if "framerate" not in data or type(data["framerate"]) != int: Exception("No framerate (int) provided")
                if "data" not in data or type(data["data"]) != str: Exception("No data (string) provided")

                # decode audio frame from base64
                audio_frame = None
                try: audio_frame = bytes(base64.b64decode(data["data"]))
                except Exception as e: raise e
                samples = np.frombuffer(audio_frame, dtype=np.int16)
                samples = samples.astype(np.float32) / 32768.0

                # add audio to stream
                streams[data["userid"]]["stream"].add_audio(audio_data=samples, sample_rate=data["framerate"])

            self.build_send_response(200, {"success": True})
            return
        except Exception as e:
            print(str(e))
            self.build_send_response(400, {"success": False, "error": str(e)})
            return

def main():
    with server.HTTPServer(("localhost", 8000), STTHandler) as stt_server:
        print("STT server started")
        stt_server.serve_forever()

if __name__ == "__main__":
    main()
# ~/~ end
