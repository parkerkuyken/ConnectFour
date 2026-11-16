 # server.py
# Connect Four server for CS 457.
#
#   python3 server.py -h
#   python3 server.py -p 8080
#
# Main thread accepts connections, every client gets its own handler
# thread, and everything shared lives in GameState behind one lock (see
# concurrency_design.md). States and transition numbers (T1-T16) come
# from fsm_specification.md and get printed in the log so I can follow
# what the server is doing.

import argparse
import logging
import socket
import sys
import threading

from protocol import (COLS, DISCS, EMPTY, ROWS, SERVER_ID, LineReader,
                      decode_frame, is_valid_alias, make_msg, port_number,
                      safe_close, send_msg)

HOST = "0.0.0.0"
MAX_PLAYERS = 2
SEND_TIMEOUT = 5.0  # give up on a client that stops reading

# GAME_START, EVALUATE_MOVE, GAME_OVER and CLEANUP all happen inside one
# lock hold, so the only states another thread can ever see are these two
WAITING_FOR_PLAYERS = "WAITING_FOR_PLAYERS"
PLAYER_TURN = "PLAYER_TURN"

log = logging.getLogger("server")


def other(role):
    return "PLAYER_2" if role == "PLAYER_1" else "PLAYER_1"


def find_four(board, row, col):
    """Look for four in a row through the disc at (row, col).

    Returns the 4 winning cells, or [] if there's no win.
    """
    disc = board[row][col]
    # horizontal, vertical, and the two diagonals
    for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
        cells = [(row, col)]
        for step in (1, -1):
            r, c = row + dr * step, col + dc * step
            while 0 <= r < ROWS and 0 <= c < COLS and board[r][c] == disc:
                cells.append((r, c))
                r += dr * step
                c += dc * step
        if len(cells) >= 4:
            # if the line is longer than 4, keep 4 that include the new disc
            cells.sort()
            i = cells.index((row, col))
            start = min(max(0, i - 3), len(cells) - 4)
            return [[r, c] for r, c in cells[start:start + 4]]
    return []


def state_update(board, row, col, role, turn, move_number):
    return make_msg("STATE_UPDATE", SERVER_ID, {
        "board": board,
        "last_move": {"role": role, "row": row, "col": col},
        "turn": turn,
        "move_number": move_number,
    })


def game_over(result, winner, reason, board, cells, scores):
    return make_msg("GAME_OVER", SERVER_ID, {
        "result": result,
        "winner": winner,
        "reason": reason,
        "final_board": board,
        "winning_cells": cells,
        "scores": dict(scores),
    })


def error(code, text):
    return make_msg("ERROR", SERVER_ID, {"code": code, "message": text})


def lobby_wait(text):
    return make_msg("LOBBY_WAIT", SERVER_ID, {"message": text})


class GameState:
    """Everything the handler threads share.

    board, turn, status, players, move_number, scores and clients are only
    touched while holding self.lock. The public methods take the lock;
    the ones starting with _ expect it to already be held. It's a plain
    Lock on purpose, so if I ever nest it by mistake it hangs right away
    instead of hiding the bug.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.clients = set()   # every connected handler
        self.players = {}      # "PLAYER_1"/"PLAYER_2" -> handler
        self.status = WAITING_FOR_PLAYERS
        self.scores = {"PLAYER_1": 0, "PLAYER_2": 0}
        self.round = 0
        self.winning_cells = []
        self._reset_board()

    def add_client(self, handler):
        """Returns False if two people are already connected."""
        with self.lock:
            if len(self.clients) >= MAX_PLAYERS:
                return False
            self.clients.add(handler)
            return True

    def register(self, handler, alias):
        """CONNECT with a valid alias (T3, T4, T6, T7)."""
        with self.lock:
            if any(p.alias == alias for p in self.players.values()):
                log.info("T4  %s tried taken name '%s'",
                         handler.addr, alias)
                self._send(handler, error(
                    "NAME_TAKEN", f"Alias '{alias}' is already in use"))
                return

            role = "PLAYER_1" if "PLAYER_1" not in self.players else "PLAYER_2"
            handler.alias = alias
            handler.role = role
            self.players[role] = handler
            log.info("Registered %s as %s (%s)", alias, role, DISCS[role])

            if len(self.players) == 1:
                log.info("T3  %s, 1 player waiting", WAITING_FOR_PLAYERS)
                self._send(handler, lobby_wait("Waiting for opponent to "
                                               "drop in"))
            else:
                # new matchup, so scores start over
                self.scores = {"PLAYER_1": 0, "PLAYER_2": 0}
                self.round = 0
                log.info("T6  %s -> GAME_START", WAITING_FOR_PLAYERS)
                self._start_game()

    def remove_player(self, handler, reason):
        """DISCONNECT, EOF or a dead socket (T5, T10).

        Can get called twice for the same handler, so the second call just
        returns.
        """
        with self.lock:
            if handler not in self.clients:
                return
            self.clients.discard(handler)
            role = handler.role
            if role is None or self.players.get(role) is not handler:
                return  # never registered
            del self.players[role]
            handler.role = None

            if self.status == WAITING_FOR_PLAYERS:
                log.info("T5  %s left the lobby (%s)", handler.alias, reason)
                if self.players:
                    # only happens if a round just ended and this player's
                    # socket had already died
                    self._requeue_survivor()
                return

            # leaving mid-game is a forfeit
            winner = other(role)
            log.info("T10 %s -> GAME_OVER, %s left (%s)",
                     PLAYER_TURN, handler.alias, reason)
            self.scores[winner] += 1
            self._send(self.players[winner], game_over(
                "FORFEIT", winner, reason, self._board_rows(), [],
                self.scores))
            log.info("T14 GAME_OVER -> CLEANUP")
            self.status = WAITING_FOR_PLAYERS
            self._requeue_survivor()

    def send_error(self, handler, code, text):
        # still takes the lock so this can't get mixed into a broadcast
        # that the other thread is writing to the same socket
        with self.lock:
            self._send(handler, error(code, text))

    def apply_move(self, handler, col):
        """Validate and play a move, all under one lock hold (T8, T9)."""
        with self.lock:
            role = handler.role
            problem = self._validate(role, col)
            if problem:
                log.info("T8  rejected %s's move: %s", handler.alias,
                         problem[0])
                self._send(handler, error(*problem))
                return

            row = self._drop_disc(col, DISCS[role])
            self.move_number += 1
            log.info("T9  %s (%s) col %d -> row %d, move %d",
                     handler.alias, role, col, row, self.move_number)
            result = self._check_result(row, col)

            if result is None:
                self.turn = other(role)
                log.info("T11 EVALUATE_MOVE -> %s, %s's turn",
                         PLAYER_TURN, self.turn)
                self._broadcast(state_update(self._board_rows(), row, col,
                                             role, self.turn,
                                             self.move_number))
                return

            if result == "WIN":
                log.info("T12 EVALUATE_MOVE -> GAME_OVER, %s wins", role)
                self.scores[role] += 1
                self._end_round("WIN", role, "FOUR_IN_A_ROW")
            else:
                log.info("T13 EVALUATE_MOVE -> GAME_OVER, draw")
                self._end_round("DRAW", None, "BOARD_FULL")

    # --- everything below expects self.lock to be held ---

    def _validate(self, role, col):
        """Returns (code, message) for a bad move, or None if it's fine.

        Same order as fsm_specification.md section 4. Turn gets checked
        before the column so the other player can't poke at the board.
        """
        if self.status != PLAYER_TURN or role is None:
            return "NOT_IN_GAME", "No game is in progress"
        if role != self.turn:
            return "OUT_OF_TURN", f"It is {self.turn}'s turn"
        if type(col) is not int:  # catches True/False too
            return "INVALID_FIELD", "col has to be an integer"
        if col < 0 or col >= COLS:
            return "COLUMN_OUT_OF_RANGE", f"Column {col} is not 0-6"
        if self.board[0][col] != EMPTY:
            return "COLUMN_FULL", f"Column {col} is full"
        return None

    def _drop_disc(self, col, disc):
        for row in range(ROWS - 1, -1, -1):
            if self.board[row][col] == EMPTY:
                self.board[row][col] = disc
                return row
        raise RuntimeError("column full")  # _validate already checked

    def _check_result(self, row, col):
        self.winning_cells = find_four(self.board, row, col)
        if self.winning_cells:
            return "WIN"
        if self.move_number == ROWS * COLS:
            return "DRAW"
        return None

    def _start_game(self):
        self._reset_board()
        self.round += 1
        p1, p2 = self.players["PLAYER_1"], self.players["PLAYER_2"]
        for me, them in ((p1, p2), (p2, p1)):
            self._send(me, make_msg("GAME_START", SERVER_ID, {
                "your_role": me.role,
                "your_disc": DISCS[me.role],
                "opponent": them.alias,
                "first_turn": "PLAYER_1",
            }))
        self.status = PLAYER_TURN
        log.info("T7  GAME_START -> %s, round %d: %s vs %s",
                 PLAYER_TURN, self.round, p1.alias, p2.alias)

    def _end_round(self, result, winner, reason):
        self._broadcast(game_over(result, winner, reason, self._board_rows(),
                                  self.winning_cells, self.scores))
        log.info("T14 GAME_OVER -> CLEANUP, scores %s", self.scores)
        log.info("T15 CLEANUP -> %s", WAITING_FOR_PLAYERS)
        self.status = WAITING_FOR_PLAYERS
        # both still here? start the next round right away. If one of them
        # died during the broadcast, their thread will call remove_player()
        # once I let go of the lock and the other player goes to the lobby.
        if not any(p.dead for p in self.players.values()):
            log.info("T6  %s -> GAME_START (rematch)", WAITING_FOR_PLAYERS)
            self._start_game()

    def _requeue_survivor(self):
        # whoever is left waited the longest, so they're PLAYER_1 next time
        (survivor,) = self.players.values()
        self.players = {"PLAYER_1": survivor}
        survivor.role = "PLAYER_1"
        self.scores = {"PLAYER_1": 0, "PLAYER_2": 0}
        self._reset_board()
        log.info("T15 CLEANUP -> %s, %s back in the lobby",
                 WAITING_FOR_PLAYERS, survivor.alias)
        self._send(survivor, lobby_wait("Opponent left. Waiting for a new "
                                        "opponent"))

    def _reset_board(self):
        self.board = [[EMPTY] * COLS for _ in range(ROWS)]
        self.turn = "PLAYER_1"
        self.move_number = 0

    def _board_rows(self):
        return ["".join(row) for row in self.board]

    def _broadcast(self, msg):
        # same message to both players while still holding the lock, so
        # they always see the same updates in the same order
        for handler in list(self.players.values()):
            self._send(handler, msg)

    def _send(self, handler, msg):
        # sendall() under the lock is the known limitation from my Sprint 2
        # doc. SEND_TIMEOUT keeps a stuck client from freezing the game.
        if handler.dead:
            return
        try:
            send_msg(handler.sock, msg)
        except OSError as e:
            log.warning("Send to %s failed (%s)", handler.who, e)
            handler.mark_dead()


class ClientHandler(threading.Thread):
    """One of these per connected client. Owns the recv() loop."""

    def __init__(self, state, sock, addr, number):
        super().__init__(name=f"Handler-{number}", daemon=True)
        self.state = state
        self.sock = sock
        self.addr = f"{addr[0]}:{addr[1]}"
        self.alias = None
        self.role = None
        self.dead = False

    @property
    def who(self):
        return self.alias or self.addr

    def mark_dead(self):
        # shutdown() wakes up this thread's recv() so it goes through the
        # normal disconnect path
        self.dead = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def run(self):
        log.info("Connection from %s", self.addr)
        reason = "OPPONENT_CONNECTION_LOST"
        try:
            for line in LineReader(self.sock).frames():
                if not self.handle_frame(line):
                    reason = "OPPONENT_QUIT"
                    break
            else:
                log.info("EOF from %s", self.who)
        except OSError as e:  # reset, broken pipe, aborted, etc.
            log.warning("Lost connection to %s: %s", self.who, e)
        finally:
            self.state.remove_player(self, reason)
            safe_close(self.sock)
            log.info("Closed connection to %s", self.who)

    def handle_frame(self, line):
        """Check one message and pass it on. Returns False on DISCONNECT.

        The parsing checks don't touch shared state, so they happen here
        before any lock gets taken.
        """
        try:
            msg = decode_frame(line)
        except ValueError:
            self.state.send_error(self, "MALFORMED_JSON",
                                  "Frame is not a JSON object")
            return True

        msg_type = msg.get("msg_type")
        if self.alias is None:
            allowed = ("CONNECT", "DISCONNECT")
        else:
            allowed = ("MOVE", "DISCONNECT")
        if msg_type not in allowed:
            self.state.send_error(self, "UNKNOWN_MSG_TYPE",
                                  f"{msg_type} is not allowed right now")
            return True

        player_id = msg.get("player_id")
        fields_ok = (isinstance(player_id, str)
                     and isinstance(msg.get("payload"), dict)
                     and type(msg.get("timestamp")) is int)
        if not fields_ok:
            self.state.send_error(self, "INVALID_FIELD",
                                  "Missing or wrong-type field")
            return True
        if self.alias is not None and player_id != self.alias:
            self.state.send_error(self, "INVALID_FIELD",
                                  "player_id doesn't match your alias")
            return True

        log.info("RECV %-16s %s %s", self.who, msg_type,
                 msg["payload"] or "")

        if msg_type == "DISCONNECT":
            return False
        if msg_type == "CONNECT":
            if is_valid_alias(player_id):
                self.state.register(self, player_id)
            else:
                self.state.send_error(self, "INVALID_FIELD",
                                      "Alias must be 1-16 letters, digits "
                                      "or _")
        else:
            self.state.apply_move(self, msg["payload"].get("col"))
        return True


def parse_args():
    parser = argparse.ArgumentParser(
        description="Connect Four server.",
        epilog="example: python3 server.py -p 8080")
    parser.add_argument("-p", "--port", type=port_number, required=True,
                        help="port to listen on (1024-65535), binds to "
                             "0.0.0.0")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(threadName)-10s] %(message)s",
                        datefmt="%H:%M:%S")

    log.info("T1  [*] -> INIT")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind((HOST, args.port))
        listener.listen(5)
    except OSError as e:
        log.error("Can't listen on port %d: %s", args.port, e)
        sys.exit(1)
    # accept() times out every second so Ctrl+C actually works
    listener.settimeout(1.0)
    log.info("T2  INIT -> %s, listening on %s:%d",
             WAITING_FOR_PLAYERS, HOST, args.port)

    state = GameState()
    count = 0
    try:
        while True:
            try:
                sock, addr = listener.accept()
            except socket.timeout:
                continue
            count += 1
            sock.settimeout(SEND_TIMEOUT)
            handler = ClientHandler(state, sock, addr, count)
            if not state.add_client(handler):
                log.info("Refused %s, already have 2 players", handler.addr)
                safe_close(sock)
                continue
            handler.start()
    except KeyboardInterrupt:
        log.info("T16 CLEANUP -> [*], shutting down")
    finally:
        safe_close(listener)


if __name__ == "__main__":
    main()