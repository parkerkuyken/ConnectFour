# protocol.py
# Stuff the client and server both need: framing, the message envelope,
# and a few small helpers. See protocol_blueprint.md sections 2 and 3.

import argparse
import json
import re
import socket
import time

ROWS = 6
COLS = 7
EMPTY = "."
DISCS = {"PLAYER_1": "R", "PLAYER_2": "Y"}
SERVER_ID = "SERVER"

ALIAS_PATTERN = re.compile(r"[A-Za-z0-9_]{1,16}")

# ports under 1024 need root, so I only allow 1024-65535
MIN_PORT = 1024
MAX_PORT = 65535


class LineReader:
    """Reads newline-delimited frames off a TCP socket.

    One recv() isn't one message. It can be half a message or two
    messages stuck together, so bytes sit in a buffer until a newline
    shows up.
    """

    def __init__(self, sock):
        self.sock = sock
        self.buf = bytearray()

    def frames(self):
        while True:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                # only happens on sockets with a timeout set, nothing was
                # read so just go back to waiting
                continue
            if not chunk:
                return  # EOF, other side closed
            self.buf.extend(chunk)
            # pull out every full line before calling recv() again
            while True:
                idx = self.buf.find(b"\n")
                if idx == -1:
                    break
                line = bytes(self.buf[:idx])
                del self.buf[:idx + 1]
                yield line


def make_msg(msg_type, player_id, payload=None):
    return {
        "msg_type": msg_type,
        "player_id": player_id,
        "payload": payload if payload is not None else {},
        "timestamp": int(time.time()),
    }


def send_msg(sock, msg):
    # json.dumps escapes newlines inside strings, so the only real \n
    # on the wire is the one I add at the end
    data = json.dumps(msg, separators=(",", ":")).encode("utf-8") + b"\n"
    sock.sendall(data)


def decode_frame(line):
    """Turn one frame into a dict. Raises ValueError if it's bad."""
    try:
        msg = json.loads(line.decode("utf-8"))
    except UnicodeDecodeError:
        raise ValueError("not utf-8")
    if not isinstance(msg, dict):
        raise ValueError("not a JSON object")
    return msg


def is_valid_alias(alias):
    return (isinstance(alias, str)
            and ALIAS_PATTERN.fullmatch(alias) is not None
            and alias != SERVER_ID)


def port_number(text):
    """argparse type for -p."""
    try:
        port = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"'{text}' is not a number (use {MIN_PORT}-{MAX_PORT})")
    if port < MIN_PORT or port > MAX_PORT:
        raise argparse.ArgumentTypeError(
            f"{port} is out of range (use {MIN_PORT}-{MAX_PORT})")
    return port


def safe_close(sock):
    try:
        sock.close()
    except OSError:
        pass