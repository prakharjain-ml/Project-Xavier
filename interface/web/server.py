"""Xavier's local web server: the page, typed actions, live telemetry and the camera stream, on 127.0.0.1 only.

    python -m interface.web            (see __main__.py: starts this, waits until healthy, opens the browser)

Routes: GET /api/health, POST /api/hello, POST /api/action, POST /api/take_control, WS /ws, GET /video/forward.mjpg,
and the built frontend at /. State-changing requests must come from an allowed Origin (this server itself, or an
origin listed in XAVIER_ALLOWED_ORIGINS for the later Vercel-hosted page). No route runs commands or reads files
outside the frontend build.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError

from interface.web import telemetry
from interface.web.contracts import Action, Beat
from interface.web.session import TICK_HZ, ActionError, Session
from interface.web.video import BOUNDARY, JpegFeed, mjpeg

log = logging.getLogger("interface.web.server")

HOST, PORT = "127.0.0.1", 8765
FRONTEND_DIST = Path(__file__).with_name("frontend") / "dist"
TELEMETRY_HZ = 15.0
READINESS_S = 2.0
CALIBRATION_PATH = "data/raw/gaze_calibration.json"
HOSTED_ORIGIN = "https://projectxavier.vercel.app"  # the same page, hosted; it talks to THIS laptop only


def allowed_origins(port: int = PORT) -> set[str]:
    extra = {o.strip().rstrip("/") for o in os.environ.get("XAVIER_ALLOWED_ORIGINS", "").split(",") if o.strip()}
    return {f"http://127.0.0.1:{port}", f"http://localhost:{port}", "http://127.0.0.1:5173",
            "http://localhost:5173",  # 5173 = the Vite dev server (development only)
            HOSTED_ORIGIN} | extra


def make_perception(mode: str, action: dict):
    """Build the perception for a new session. Live needs two different cameras and a saved eye calibration."""
    from interface.web.perception import LivePerception

    # Synthetic perception belongs in injected test fixtures, never in the rider app.
    if mode != "live":
        raise ActionError("Real cameras required: connect the Pixel forward camera and the Mac eye webcam.")
    from vision.detect_track import load_hfov
    from vision.gaze_link import calibration_hint, calibration_ready, gaze_backend

    forward, eye = action.get("forward_camera"), action.get("eye_camera")
    if forward is None or eye is None:
        raise ActionError("Choose the eye camera and the forward camera first")
    if forward == eye:
        raise ActionError("Choose different cameras: Pixel for the room, Mac webcam for your eyes.")
    backend = gaze_backend()
    if not calibration_ready(backend, CALIBRATION_PATH):
        raise ActionError(f"No eye calibration yet for the {backend} tracker ({calibration_hint(backend)})")
    return LivePerception(forward, eye, CALIBRATION_PATH, load_hfov())


def chair_driver(serial_port: str):
    """The real hoverboard through Keshav's chair_control library, as `demo.sh chair` uses. HUMANS ONLY."""
    from motors.chair_driver import ChairDriver
    from motors.driver import looks_like_openbci_dongle
    from interface.web.session import RecordingDriver

    if looks_like_openbci_dongle(serial_port):
        raise SystemExit(f"{serial_port} looks like the OpenBCI dongle, not the ESP32: refusing to send motor commands")
    return lambda: RecordingDriver(ChairDriver(serial_port), serial_port)


def device_readiness(serial_port: str | None) -> dict[str, bool]:
    """Read-only checks for the start screen (nothing is opened): Pixel present, on the headset's Wi-Fi, a saved
    eye calibration, and whether a real chair port was given. The headset is fully verified only at Start."""
    from interface.launcher_modes import headset_ready, room_camera_ready
    from vision.gaze_link import calibration_ready, gaze_backend

    return {"phone_camera": room_camera_ready(), "headset_wifi": headset_ready(),
            "eye_calibration": calibration_ready(gaze_backend(), CALIBRATION_PATH), "chair": serial_port is not None}


class Readiness:
    """Runs device_readiness on a background thread every READINESS_S, so no request waits for system_profiler."""

    def __init__(self, serial_port: str | None) -> None:
        import threading

        self.value: dict[str, bool] = {}
        self._serial, self._stop = serial_port, threading.Event()
        threading.Thread(target=self._run, name="readiness", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.value = device_readiness(self._serial)
            except Exception:  # a failing check shows "not ready", never crashes the server
                log.exception("device check failed")
                self.value = {}
            self._stop.wait(READINESS_S)


def create_app(session: Session | None = None, port: int = PORT, serial_port: str | None = None,
               readiness: "Readiness | None" = None) -> FastAPI:
    if session is None:
        session = Session(make_perception, chair_driver(serial_port)) if serial_port else Session(make_perception)
    origins = allowed_origins(port)

    def forward_source():
        perception = session.perception
        reader = getattr(perception, "reader", None) if perception is not None else None
        return reader.latest() if reader is not None else None

    feed = JpegFeed(forward_source)
    devices = readiness or Readiness(serial_port)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async def tick_loop():
            period = 1 / TICK_HZ
            while True:
                session.tick()  # fast (a few ms); heavy work lives on worker threads
                await asyncio.sleep(period)

        task = asyncio.create_task(tick_loop())
        try:
            yield
        finally:
            task.cancel()
            feed.stop()
            devices.stop()
            session.shutdown("Server stopped")  # final STOP lines, workers and gaze process stopped

    app = FastAPI(title="Xavier", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.session, app.state.feed = session, feed
    # CORS only for the listed origins (a hosted page talking to this laptop); never a wildcard.
    app.add_middleware(CORSMiddleware, allow_origins=sorted(origins), allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-Xavier-Client"], allow_credentials=False)

    @app.middleware("http")
    async def origin_guard(request: Request, call_next):
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin is None or origin.rstrip("/") not in origins:
                return JSONResponse({"ok": False, "error": "Origin not allowed"}, status_code=403)
        response = await call_next(request)
        # Chrome's Private Network Access: a hosted page may call this loopback server only if we say so.
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

    def client_of(request: Request) -> str:
        client = request.headers.get("x-xavier-client", "")
        if not (8 <= len(client) <= 64) or not client.replace("-", "").isalnum():
            raise HTTPException(400, "missing client id")
        return client

    @app.get("/api/health")
    async def health():
        return {"ok": True, "app": "xavier", "flow": session.flow.value}

    @app.post("/api/hello")
    async def hello(request: Request):
        return session.hello(client_of(request))

    @app.post("/api/take_control")
    async def take_control(request: Request):
        try:
            session.take_control(client_of(request))
        except ActionError as error:
            return JSONResponse({"ok": False, "error": str(error)}, status_code=409)
        return {"ok": True}

    @app.post("/api/action")
    async def action(request: Request):
        client = client_of(request)
        try:
            body = Action.model_validate(await request.json())
        except (ValidationError, json.JSONDecodeError) as error:
            return JSONResponse({"ok": False, "error": f"Invalid action: {error}"}, status_code=422)
        try:
            # Starting a session can load models for a few seconds: keep the tick loop running meanwhile.
            result = await asyncio.to_thread(session.act, client, body.as_dict())
        except ActionError as error:
            return JSONResponse({"ok": False, "error": str(error)}, status_code=409)
        return result

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        origin = (socket.headers.get("origin") or "").rstrip("/")
        client = socket.query_params.get("client", "")
        if origin not in origins or not (8 <= len(client) <= 64):
            await socket.close(code=4403)
            return
        await socket.accept()
        session.hello(client)

        async def receive():
            while True:
                try:
                    beat = Beat.model_validate_json(await socket.receive_text())
                except ValidationError:
                    continue  # malformed messages are dropped whole
                session.heartbeat(client, beat.pointer)

        receiver = asyncio.create_task(receive())
        try:
            while not receiver.done():
                started = asyncio.get_running_loop().time()
                data = telemetry.snapshot(session, client, session._clock())
                data["diag"]["encode_ms"] = round(feed.encode_ms, 1)
                data["ready"] = devices.value
                await socket.send_text(json.dumps(data))
                elapsed = asyncio.get_running_loop().time() - started
                await asyncio.sleep(max(0.0, 1 / TELEMETRY_HZ - elapsed))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            receiver.cancel()  # no more heartbeats: the session's deadline stops the chair on its own

    @app.get("/video/forward.mjpg")
    async def video():
        return StreamingResponse(mjpeg(feed), media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
                                 headers={"Cache-Control": "no-store"})

    @app.get("/{path:path}")
    async def frontend(path: str):
        index = FRONTEND_DIST / "index.html"
        if not index.exists():
            return JSONResponse({"ok": False, "error": "Frontend not built: cd interface/web/frontend && npm run build"},
                                status_code=503)
        target = (FRONTEND_DIST / path).resolve()
        if path and target.is_file() and FRONTEND_DIST.resolve() in target.parents:
            return FileResponse(target)  # only files inside the build folder
        return FileResponse(index)

    return app
