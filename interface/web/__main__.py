"""Start Xavier: one command, one browser window.

    python -m interface.web               start the local server, wait until it answers, open the browser
    python -m interface.web --no-browser  server only (e.g. when using the hosted page at projectxavier.vercel.app)

If Xavier is already running, this just opens the browser on it (no second copy fighting over cameras).
Motor commands go to a test port unless a human passes --serial PORT (the ESP32), as with demo.sh chair.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
import urllib.request
import webbrowser

from interface.web.server import HOST, PORT, create_app

LOG_DIR = "data/raw/sessions"
HEALTH_TIMEOUT_S = 20.0


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=1.0) as response:
            return response.status == 200 and b'"xavier"' in response.read()
    except OSError:
        return False


def open_when_ready(url: str) -> None:
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        if healthy(url):
            webbrowser.open(url)  # once: the page reconnects by itself after that
            return
        time.sleep(0.2)
    logging.getLogger("interface.web").error("server did not answer within %.0f s; not opening the browser",
                                            HEALTH_TIMEOUT_S)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Xavier web app (local)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--serial", metavar="PORT", default=None,
                        help="ESP32 chair port: the REAL wheels move (HUMANS ONLY, wheels up, kill switch in hand)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(f"{LOG_DIR}/web.log")])
    url = f"http://{HOST}:{args.port}"
    if healthy(url):
        print(f"Xavier is already running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    import uvicorn

    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    # Loopback only: nothing outside this laptop can reach the server (or the motors behind it).
    uvicorn.run(create_app(port=args.port, serial_port=args.serial), host=HOST, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
