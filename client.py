# client.py
# Connect Four client for CS 457.
#
#   python3 client.py -h
#   python3 client.py -i server.kuykendall.edu -p 8080
#   python3 client.py -i localhost -p 8080 -n PowderDay
#
# The main thread reads from the server and prints the board. A second
# thread reads what the user types and sends it. The client never changes
# the board itself, it just shows whatever the server sends.

import argparse
import socket
import sys
import threading

from protocol import (COLS, DISCS, LineReader, decode_frame, is_valid_alias,
                      make_msg, port_number, safe_close, send_msg)

EMPTY_BOARD = ["." * COLS] * 6


def parse_args():
    parser = argparse.ArgumentParser(
        description="Connect Four client.",
        epilog="examples:\n"
               "  python3 client.py -i server.kuykendall.edu -p 8080\n"
               "  python3 client.py -i localhost -p 8080 -n PowderDay",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-i", dest="hostname", required=True,
                        metavar="HOSTNAME",
                        help="server hostname (looked up with DNS) or IP")
    parser.add_argument("-p", dest="port", type=port_number, required=True,
                        help="server port (1024-65535)")
    parser.add_argument("-n", dest="name", metavar="NAME",
                        help="your player name (optional, asks if missing)")
    return parser.parse_args()


def resolve(hostname):
    """DNS lookup. Exits with status 1 instead of crashing if it fails."""
    try:
        return socket.gethostbyname(hostname)
    except (socket.gaierror, socket.herror, UnicodeError) as e:
        # UnicodeError shows up for weird names like "a..b"
        print(f"[ERROR] Unable to resolve DNS hostname '{hostname}'.")
        print("Please check your Cisco router DNS configuration "
              "('ip dns server' / 'ip host') or verify domain spelling.")
        print(f"        ({e})")
        sys.exit(1)


def connect(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    try:
        sock.connect((ip, port))
    except ConnectionRefusedError:
        print(f"[ERROR] Connection refused by {ip}:{port}. "
              "Is the server running?")
        sys.exit(1)
    except OSError as e:
        print(f"[ERROR] Couldn't connect to {ip}:{port} ({e})")
        sys.exit(1)
    # short timeout so recv() wakes up now and then and Ctrl+C works
    sock.settimeout(0.5)
    return sock


def ask_name():
    while True:
        name = input("Enter your player name: ").strip()
        if is_valid_alias(name):
            return name
        print("Names are 1-16 letters, digits or _.")


def draw_board(rows):
    line = "  +" + "-" * (2 * COLS + 1) + "+"
    out = ["    " + " ".join(str(c) for c in range(COLS)), line]
    for row in rows:
        out.append("  | " + " ".join(row) + " |")
    out.append(line)
    return "\n".join(out)


class Client:
    def __init__(self, sock, alias):
        self.sock = sock
        self.alias = alias
        self.lock = threading.Lock()
        self.registered = False    # True after LOBBY_WAIT or GAME_START
        self.picking_name = False  # True after the server rejects my name
        self.quitting = False
        self.role = None
        self.opponent = None
        self.round = 0

    def send(self, msg_type, payload=None):
        try:
            with self.lock:  # both threads can send
                send_msg(self.sock, make_msg(msg_type, self.alias, payload))
            return True
        except OSError:
            return False

    def quit(self):
        with self.lock:
            if self.quitting:
                return
            self.quitting = True
        print("Leaving the game...")
        # the server closes the socket after DISCONNECT, which ends the
        # receive loop in main()
        if not self.send("DISCONNECT"):
            safe_close(self.sock)

    def keyboard_loop(self):
        """Runs in its own thread so typing never blocks receiving."""
        while True:
            try:
                text = input().strip()
            except (EOFError, KeyboardInterrupt):
                text = "q"
            if not text:
                continue
            if text.lower() in ("q", "quit", "exit"):
                self.quit()
                return

            with self.lock:
                picking = self.picking_name
            if picking:
                if not is_valid_alias(text):
                    print("Names are 1-16 letters, digits or _. Try again: ",
                          end="", flush=True)
                    continue
                with self.lock:
                    self.alias = text
                    self.picking_name = False
                self.send("CONNECT")
                continue

            try:
                col = int(text)
            except ValueError:
                print("Type a column number (0-6), or q to quit.")
                continue
            # no turn or range check here, the server decides that
            if not self.send("MOVE", {"col": col}):
                return

    def receive_loop(self):
        for line in LineReader(self.sock).frames():
            try:
                msg = decode_frame(line)
            except ValueError:
                print("[warning] got a bad message from the server")
                continue
            msg_type = msg.get("msg_type")
            payload = msg.get("payload") or {}
            if msg_type == "LOBBY_WAIT":
                self.on_lobby_wait(payload)
            elif msg_type == "GAME_START":
                self.on_game_start(payload)
            elif msg_type == "STATE_UPDATE":
                self.on_state_update(payload)
            elif msg_type == "ERROR":
                self.on_error(payload)
            elif msg_type == "GAME_OVER":
                self.on_game_over(payload)
            else:
                print(f"[warning] unknown message type {msg_type}")

    def on_lobby_wait(self, payload):
        with self.lock:
            self.registered = True
        print(f"\nConnected as {self.alias}. {payload.get('message', '')}...")
        print("Waiting for Player 2... (type q to quit)")

    def on_game_start(self, payload):
        with self.lock:
            self.registered = True
        self.role = payload["your_role"]
        self.opponent = payload["opponent"]
        self.round += 1
        print("\n" + "=" * 40)
        print(f"  ROUND {self.round}: {self.alias} vs {self.opponent}")
        print(f"  You are {self.role} ({payload['your_disc']}). "
              f"{payload['first_turn']} goes first.")
        print("=" * 40)
        print(draw_board(EMPTY_BOARD))
        self.show_turn(payload["first_turn"])

    def on_state_update(self, payload):
        last = payload["last_move"]
        who = "You" if last["role"] == self.role else self.opponent
        print(f"\nMove {payload['move_number']}: {who} dropped "
              f"{DISCS[last['role']]} in column {last['col']}.")
        print(draw_board(payload["board"]))
        self.show_turn(payload["turn"])

    def on_error(self, payload):
        code = payload.get("code", "ERROR")
        print(f"[server] {code}: {payload.get('message', '')}")
        # name got rejected before we were registered, so ask again
        if code in ("NAME_TAKEN", "INVALID_FIELD"):
            with self.lock:
                bad_name = not self.registered
                if bad_name:
                    self.picking_name = True
            if bad_name:
                print("Choose a different name: ", end="", flush=True)

    def on_game_over(self, payload):
        print("\n" + draw_board(payload["final_board"]))
        if payload["result"] == "DRAW":
            print("*** DRAW: the board is full. ***")
        else:
            reasons = {"FOUR_IN_A_ROW": "four in a row",
                       "OPPONENT_QUIT": "opponent quit",
                       "OPPONENT_CONNECTION_LOST": "opponent lost connection"}
            how = reasons.get(payload["reason"], payload["reason"])
            if payload["winner"] == self.role:
                print(f"*** You win ({payload['result']}: {how}). ***")
            else:
                print(f"*** {self.opponent} wins "
                      f"({payload['result']}: {how}). ***")
        if payload["winning_cells"]:
            cells = " ".join(f"({r},{c})" for r, c in payload["winning_cells"])
            print(f"Winning cells (row,col): {cells}")
        self.show_scores(payload["scores"])

    def show_turn(self, turn):
        if turn == self.role:
            print(">>> Your Turn! Choose a column (0-6), or q to quit: ",
                  end="", flush=True)
        else:
            num = "1" if turn == "PLAYER_1" else "2"
            print(f"Waiting for Player {num} ({self.opponent})...")

    def show_scores(self, scores):
        mine = scores.get(self.role, 0)
        theirs = scores.get("PLAYER_2" if self.role == "PLAYER_1"
                            else "PLAYER_1", 0)
        print("-" * 40)
        print(f"  SCORE  {self.alias}: {mine}  |  {self.opponent}: {theirs}")
        print("-" * 40)


def main():
    args = parse_args()
    ip = resolve(args.hostname)
    print(f"Resolved {args.hostname} -> {ip}")

    try:
        name = args.name if is_valid_alias(args.name) else ask_name()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    sock = connect(ip, args.port)
    print(f"Connected to {ip}:{args.port}")
    client = Client(sock, name)
    client.send("CONNECT")
    threading.Thread(target=client.keyboard_loop, daemon=True).start()

    code = 0
    try:
        client.receive_loop()
        if not client.quitting:
            print("\nThe server closed the connection.")
            code = 1
    except KeyboardInterrupt:
        client.quit()
    except OSError as e:
        if not client.quitting:
            print(f"\n[ERROR] Lost connection to the server ({e})")
            code = 1
    finally:
        safe_close(sock)
    print("Goodbye!")
    sys.exit(code)


if __name__ == "__main__":
    main()