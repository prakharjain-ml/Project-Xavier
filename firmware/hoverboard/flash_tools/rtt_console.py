"""Tiny RTT console for RoboDurden's hoverboard autodetect.

Connects to the OpenOCD RTT server (localhost:9090) started by 4_autodetect_console.bat.
- Everything the board prints shows up here.
- Type a letter and press ENTER to send it (e.g. "s" + ENTER).
- Just ENTER sends ENTER on its own.
- Everything is also saved to autodetect_log.txt next to this file, so you can send it to Claude.
- Ctrl+C to quit.
"""
import os
import socket
import sys
import threading
import time

HOST, PORT = "127.0.0.1", 9090
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autodetect_log.txt")


def connect():
    for _ in range(30):
        try:
            return socket.create_connection((HOST, PORT), timeout=2)
        except OSError:
            print("waiting for OpenOCD RTT server on port 9090 ...")
            time.sleep(1)
    print("Could not connect. Is the OpenOCD window open and showing 'rtt: Control block found'?")
    sys.exit(1)


def reader(sock, log):
    sock.settimeout(None)
    while True:
        try:
            data = sock.recv(1024)
        except OSError:
            break
        if not data:
            break
        text = data.decode("latin-1").replace("\r\n", "\n")
        sys.stdout.write(text)
        sys.stdout.flush()
        log.write(text)
        log.flush()
    print("\n[connection closed]")
    os._exit(0)


def main():
    sock = connect()
    print("connected. Type a letter + ENTER to send it. Ctrl+C to quit.\n")
    with open(LOG, "a", encoding="utf-8") as log:
        log.write(f"\n===== session {time.ctime()} =====\n")
        threading.Thread(target=reader, args=(sock, log), daemon=True).start()
        try:
            while True:
                line = input()
                log.write(f"[sent: {line!r} + ENTER]\n")
                # autodetect takes the LAST character typed before ENTER as the command.
                # Send only CR (not CR+LF), otherwise the command would run twice.
                sock.sendall(line.encode("latin-1", "ignore") + b"\r")
        except (KeyboardInterrupt, EOFError):
            pass
    sock.close()


if __name__ == "__main__":
    main()
