# Connect Four over TCP: Application Protocol

| Item | Choice |
|---|---|
| Game | Connect Four (6 rows x 7 columns, 2 players, turn-based) |
| Transport | TCP |
| Serialization | UTF-8 JSON |
| Framing | Newline-delimited JSON (one JSON object per line, ended by `\n`) |
| Authority | The server owns the board and checks every rule. Clients only send a column number. |

---

## 1. Game Rules and Conventions

- The board is 6 rows by 7 columns. I am treating row `0` as the top and row `5` as the bottom. Column `0` is the far left.
- The server is the authority, similar to how Rocket League works: clients only send inputs (here, a column number) and the server decides what actually happened.
- A player does not send a row when making a move. It only sends a column from `0` through `6`, and the server puts the disc in the lowest open spot.
- The first player connected to the game becomes `PLAYER_1`, uses `R`, and goes first. The second player becomes `PLAYER_2` and uses `Y`.
- A player wins by getting four of their discs in a row horizontally, vertically, or diagonally. If all 42 spaces are filled and nobody has won, the game is a draw.
- When the board is sent over the network, it is represented as six strings. Each string has seven characters. A `.` means empty, `R` is PLAYER_1, and `Y` is PLAYER_2. The first string is the top row.

```json
[".......", ".......", ".......", ".......", ".......", "...R..."]
```

---

## 2. TCP Framing

### 2.1 Why framing is needed

The main thing I had to account for with TCP is that it does not know where my application messages start and end. One `send()` does not automatically equal one `recv()`:

- **Coalescing:** two or more messages can show up together in one `recv()`.
- **Fragmentation:** one message can be split across multiple `recv()` calls.

The way I think about it: TCP is like a playlist with no gaps between tracks. The audio just keeps streaming, so I need something in the stream itself, the `\n`, to mark where one song ends and the next one starts.

### 2.2 How I handle it

1. Every message is one JSON object encoded as UTF-8.
2. I put one `\n` (0x0A) at the end of every message. That newline is the message delimiter.
3. Newlines inside JSON strings are escaped by the serializer, so a real newline byte does not accidentally get treated as the end of the message. Python's `json.dumps` handles this.
4. The receiver never assumes that one `recv()` call contains exactly one message.

### 2.3 What this looks like on the wire

`\n` below stands for the delimiter byte.

**(a) Back-to-back messages from a client**

```text
{"msg_type":"CONNECT","player_id":"PowderDay","payload":{},"timestamp":1727000000}\n{"msg_type":"MOVE","player_id":"PowderDay","payload":{"col":3},"timestamp":1727000005}\n
```

**(b) Coalescing: one `recv()` gives two full messages**

```text
recv() #1 -> {"msg_type":"LOBBY_WAIT","player_id":"SERVER","payload":{"message":"Waiting for opponent to drop in"},"timestamp":1727000001}\n{"msg_type":"GAME_START","player_id":"SERVER","payload":{"your_role":"PLAYER_1","your_disc":"R","opponent":"BassDrop","first_turn":"PLAYER_1"},"timestamp":1727000002}\n
```

Since there are two newline delimiters in the received data, the receiver can pull out two separate messages.

**(c) Fragmentation: one message split over two `recv()` calls**

```text
recv() #1 -> {"msg_type":"MOVE","player_id":"PowderDay","payl
recv() #2 -> oad":{"col":3},"timestamp":1727000005}\n
```

After the first chunk there is no newline, so I keep those bytes in the buffer. Once the second chunk arrives, the message is complete and can be parsed.

### 2.4 How the receiver handles messages

1. Keep a separate `bytearray` for each connection.
2. Call `recv(4096)`. If it returns `b""`, the other side closed the connection.
3. Add the new bytes to the buffer.
4. Look for a newline. If there is one, everything before it is one complete message. Remove that message and the newline from the buffer, then parse it as JSON.
5. If there is no newline yet, the message is incomplete. Leave those bytes in the buffer and wait for the next `recv()`.

```python
import json


class LineReader:
    """Collects TCP bytes and yields one complete frame (bytes) at a time."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = bytearray()

    def frames(self):
        while True:
            chunk = self.sock.recv(4096)
            if not chunk:                  # EOF, peer closed
                return
            self.buf.extend(chunk)
            while True:                    # pull out EVERY complete frame
                idx = self.buf.find(b"\n")
                if idx == -1:              # partial frame, wait for more bytes
                    break
                line = bytes(self.buf[:idx])
                del self.buf[:idx + 1]
                yield line


def send_msg(sock, msg: dict):
    data = json.dumps(msg, separators=(",", ":")).encode("utf-8") + b"\n"
    sock.sendall(data)
```

---

## 3. Message Format

I use the same basic envelope for every message. The actual information changes depending on the message type.

| Key | Type | Description |
|---|---|---|
| `msg_type` | string | One of the 8 types in Section 4 (upper-case) |
| `player_id` | string | Client alias (1-16 chars, `[A-Za-z0-9_]`), or `"SERVER"` for server messages |
| `payload` | object | Type specific body, `{}` if empty |
| `timestamp` | integer | Unix epoch seconds |

The server also checks that a client's `player_id` is the same name it used when it connected. If it changes, the server returns `INVALID_FIELD`.

---

## 4. Messages Used by the Game

| Message Type | Direction | Purpose |
|---|---|---|
| `CONNECT` | Client -> Server | Join the game room with a player alias |
| `LOBBY_WAIT` | Server -> Client | First player is told to wait for an opponent |
| `GAME_START` | Server -> Clients | Game begins, each client gets its own role (sent once per client) |
| `MOVE` | Client -> Server | Active player picks a column |
| `STATE_UPDATE` | Server -> Clients | New board, last move, and whose turn is next |
| `ERROR` | Server -> Client | Rejects a bad, out-of-turn, or invalid message (sender only) |
| `DISCONNECT` | Client -> Server | Intentional quit, opponent wins by forfeit if a game is running |
| `GAME_OVER` | Server -> Clients | Final result (WIN / DRAW / FORFEIT) |

---

## 5. Message Details

### 5.1 `CONNECT` (Client -> Server)

This is the first message a client sends. It basically says, "I want to join, and this is the name I am using."

| Field | Type | Constraints |
|---|---|---|
| `msg_type` | string | `"CONNECT"` |
| `player_id` | string | 1-16 chars, `[A-Za-z0-9_]`, not already in use |
| `payload` | object | `{}` |
| `timestamp` | integer | Unix epoch seconds |

```json
{"msg_type":"CONNECT","player_id":"PowderDay","payload":{},"timestamp":1727000000}
```

The server then either puts the player in the lobby, starts the game when the second player arrives, or sends an error if something about the connection is invalid.

### 5.2 `LOBBY_WAIT` (Server -> Client)

If this player got there first, the server sends this so the client knows it is connected but still waiting for another player.

| Field | Type | Constraints |
|---|---|---|
| `msg_type` | string | `"LOBBY_WAIT"` |
| `player_id` | string | `"SERVER"` |
| `payload.message` | string | Status text |
| `timestamp` | integer | Unix epoch seconds |

```json
{"msg_type":"LOBBY_WAIT","player_id":"SERVER","payload":{"message":"Waiting for opponent to drop in"},"timestamp":1727000001}
```

### 5.3 `GAME_START` (Server -> Clients)

Once there are two players, the server sends this once to each client. Each client gets information about its own role, disc, and opponent.

| Field | Type | Constraints |
|---|---|---|
| `msg_type` | string | `"GAME_START"` |
| `player_id` | string | `"SERVER"` |
| `payload.your_role` | string | `"PLAYER_1"` or `"PLAYER_2"` |
| `payload.your_disc` | string | `"R"` for PLAYER_1, `"Y"` for PLAYER_2 |
| `payload.opponent` | string | Opponent's alias |
| `payload.first_turn` | string | Always `"PLAYER_1"` |
| `timestamp` | integer | Unix epoch seconds |

To PowderDay:

```json
{"msg_type":"GAME_START","player_id":"SERVER","payload":{"your_role":"PLAYER_1","your_disc":"R","opponent":"BassDrop","first_turn":"PLAYER_1"},"timestamp":1727000002}
```

To BassDrop:

```json
{"msg_type":"GAME_START","player_id":"SERVER","payload":{"your_role":"PLAYER_2","your_disc":"Y","opponent":"PowderDay","first_turn":"PLAYER_1"},"timestamp":1727000002}
```

### 5.4 `MOVE` (Client -> Server)

On its turn, the client sends the column it wants to play.

| Field | Type | Constraints |
|---|---|---|
| `msg_type` | string | `"MOVE"` |
| `player_id` | string | Must equal the sender's registered alias |
| `payload.col` | integer | `0` to `6` |
| `timestamp` | integer | Unix epoch seconds |

```json
{"msg_type":"MOVE","player_id":"PowderDay","payload":{"col":3},"timestamp":1727000005}
```

The server checks the move before changing anything. A valid move gets sent to both players as a `STATE_UPDATE`. If that move ends the game, the server sends `GAME_OVER` instead. If the move is bad, only that client gets an `ERROR`. A bad move does not change the board or give the turn to the other player.

### 5.5 `STATE_UPDATE` (Server -> Clients)

After every legal move, both clients need to know what the board looks like now, so the server sends the same state update to both of them.

| Field | Type | Constraints |
|---|---|---|
| `msg_type` | string | `"STATE_UPDATE"` |
| `player_id` | string | `"SERVER"` |
| `payload.board` | array of 6 strings | Each 7 chars from `{".","R","Y"}`, row 0 first |
| `payload.last_move` | object | `{"role": string, "row": integer, "col": integer}` |
| `payload.turn` | string | `"PLAYER_1"` or `"PLAYER_2"`, whose move is next |
| `payload.move_number` | integer | Accepted moves so far (`1`-`41`) |
| `timestamp` | integer | Unix epoch seconds |

```json
{"msg_type":"STATE_UPDATE","player_id":"SERVER","payload":{"board":[".......",".......",".......",".......",".......","...R..."],"last_move":{"role":"PLAYER_1","row":5,"col":3},"turn":"PLAYER_2","move_number":1},"timestamp":1727000005}
```

If the move ends the game, there is no normal state update. The server sends `GAME_OVER`, which includes the final board.

### 5.6 `ERROR` (Server -> Client)

This is how the server tells a client that something went wrong with its request. Only the client that caused the error gets the message. The board stays the same, and the connection can keep going.

| Field | Type | Constraints |
|---|---|---|
| `msg_type` | string | `"ERROR"` |
| `player_id` | string | `"SERVER"` |
| `payload.code` | string | One of the codes below |
| `payload.message` | string | Human-readable text |
| `timestamp` | integer | Unix epoch seconds |

```json
{"msg_type":"ERROR","player_id":"SERVER","payload":{"code":"OUT_OF_TURN","message":"It is PLAYER_2's turn"},"timestamp":1727000006}
```

| `code` | Trigger |
|---|---|
| `MALFORMED_JSON` | Frame is not valid UTF-8, not valid JSON, or not a JSON object |
| `UNKNOWN_MSG_TYPE` | `msg_type` missing, or not a type the client may send in the current state |
| `INVALID_FIELD` | Missing key, wrong data type, bad alias, or `player_id` does not match the registered alias |
| `NAME_TAKEN` | `CONNECT` alias already in use |
| `NOT_IN_GAME` | `MOVE` sent while no game is running |
| `OUT_OF_TURN` | `MOVE` from the player who is not the active player |
| `COLUMN_OUT_OF_RANGE` | `col` is an integer but not in `0-6` |
| `COLUMN_FULL` | The column already has 6 discs |

### 5.7 `DISCONNECT` (Client -> Server)

If a player wants to quit normally, it sends this message first. If a game is already happening, the other player wins by forfeit.

| Field | Type | Constraints |
|---|---|---|
| `msg_type` | string | `"DISCONNECT"` |
| `player_id` | string | Sender's registered alias |
| `payload` | object | `{}` |
| `timestamp` | integer | Unix epoch seconds |

```json
{"msg_type":"DISCONNECT","player_id":"BassDrop","payload":{},"timestamp":1727000042}
```

The server does not need to reply to the player that is leaving. It stops using that socket and closes it.

### 5.8 `GAME_OVER` (Server -> Clients)

This is the final message for the game. It tells the remaining connected players whether the result was a normal win, a draw, or a forfeit.

| Field | Type | Constraints |
|---|---|---|
| `msg_type` | string | `"GAME_OVER"` |
| `player_id` | string | `"SERVER"` |
| `payload.result` | string | `"WIN"`, `"DRAW"`, or `"FORFEIT"` |
| `payload.winner` | string or null | `"PLAYER_1"`, `"PLAYER_2"`, or `null` for a draw |
| `payload.reason` | string | `"FOUR_IN_A_ROW"`, `"BOARD_FULL"`, `"OPPONENT_QUIT"`, or `"OPPONENT_CONNECTION_LOST"` |
| `payload.final_board` | array of 6 strings | Same encoding as `STATE_UPDATE.board` |
| `payload.winning_cells` | array of `[row, col]` | The 4 winning cells for a WIN, otherwise `[]` |
| `payload.scores` | object | `{"PLAYER_1": int, "PLAYER_2": int}`: 1/0 for a win or forfeit, 0/0 for a draw |
| `timestamp` | integer | Unix epoch seconds |

WIN (PowderDay gets four in column 3):

```json
{"msg_type":"GAME_OVER","player_id":"SERVER","payload":{"result":"WIN","winner":"PLAYER_1","reason":"FOUR_IN_A_ROW","final_board":[".......",".......","...R...","...RY..","...RY..","...RY.."],"winning_cells":[[2,3],[3,3],[4,3],[5,3]],"scores":{"PLAYER_1":1,"PLAYER_2":0}},"timestamp":1727000030}
```

DRAW:

```json
{"msg_type":"GAME_OVER","player_id":"SERVER","payload":{"result":"DRAW","winner":null,"reason":"BOARD_FULL","final_board":["RYRYRYR","RYRYRYR","YRYRYRY","YRYRYRY","RYRYRYR","RYRYRYY"],"winning_cells":[],"scores":{"PLAYER_1":0,"PLAYER_2":0}},"timestamp":1727000300}
```

FORFEIT (BassDrop quits, PowderDay wins):

```json
{"msg_type":"GAME_OVER","player_id":"SERVER","payload":{"result":"FORFEIT","winner":"PLAYER_1","reason":"OPPONENT_QUIT","final_board":[".......",".......",".......",".......","...Y...","...R..."],"winning_cells":[],"scores":{"PLAYER_1":1,"PLAYER_2":0}},"timestamp":1727000042}
```

---

## 6. What Happens When a Connection Ends

There are two main ways a connection can end: the player can leave normally, or the connection can disappear unexpectedly. From the game's point of view, both eventually become the same `CLIENT_DISCONNECTED` event for the FSM to handle.

### 6.1 Normal disconnect

| Layer | What happens |
|---|---|
| Application | The client sends `DISCONNECT`, then closes its socket. The server knows the quit was intentional, tells the opponent, and declares a forfeit win. |
| Transport | `sock.close()` makes the OS send a TCP FIN (4-way close). The peer's next `recv()` returns `b""`. |

### 6.2 Unexpected disconnect

If a client gets killed, loses power, or loses its network connection, it might never get the chance to send `DISCONNECT`. The TCP connection can disappear without the game getting a clean goodbye message.

- Process killed but OS alive: the OS closes the socket. The server sees EOF (`b""`) or `ConnectionResetError` (TCP RST).
- Network or power loss: the server may notice nothing until its next `send()` fails with `BrokenPipeError` or `ConnectionResetError`.

### 6.3 The important `recv()` rule

When the other side closes the connection normally, `recv()` does not throw an exception. It returns `b""`. The server has to check for this. Otherwise, it can keep calling `recv()` over and over instead of handling the disconnect.

```python
data = sock.recv(4096)
if not data:
    # peer closed the connection (FIN received)
    logger.info("Remote peer disconnected (EOF received).")
    trigger_state_transition("CLIENT_DISCONNECTED", player_id)
    sock.close()
    return
```

This is also why `LineReader.frames()` has the `if not chunk: return` check. If the connection closes while a message is only partially received, that incomplete message is discarded.

### 6.4 Socket errors

| Exception | Meaning |
|---|---|
| `ConnectionResetError` | TCP RST, peer crashed or forcibly closed |
| `BrokenPipeError` | Writing to a socket whose remote end is already closed |
| `ConnectionAbortedError` | Connection aborted locally or by the network stack |
| `TimeoutError` | Only if a socket timeout is configured and the peer goes silent |

```python
try:
    for line in reader.frames():       # EOF ends this loop
        handle_frame(player_id, line)  # may call send_msg() -> BrokenPipeError
    trigger_state_transition("CLIENT_DISCONNECTED", player_id)   # EOF reached
except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError) as e:
    logger.warning(f"Connection lost abruptly: {e}")
    trigger_state_transition("CLIENT_DISCONNECTED", player_id)
finally:
    safe_close(sock)                   # ignores errors if already closed
```

If sending an update to one player fails, I treat that the same way as that player disconnecting. There is no point trying to keep sending data to a socket that is already gone.

### 6.5 What happens after a disconnect

| When it happens | Result |
|---|---|
| In the lobby | Client removed from the queue, socket closed, no forfeit |
| During a game, either player (`DISCONNECT`, EOF, or a socket exception) | `GAME_OVER` with `result: "FORFEIT"`, the remaining player is the winner. Reason is `OPPONENT_QUIT` for an explicit `DISCONNECT`, otherwise `OPPONENT_CONNECTION_LOST`. |
| Both players drop at once | No `GAME_OVER` can be delivered, server goes straight to cleanup |
| After `GAME_OVER` | Send failures are ignored, dead sockets are dropped in cleanup |

Leaving mid-game counts as a forfeit, the same idea as bailing out of a ranked Rocket League match.

Cleanup closes the socket of any player who left, frees their name, and discards their receive buffer. A player who is still connected stays connected and goes back to the lobby (see `fsm_specification.md`, Section 6).

---

## 7. Full Example Session

```text
C(PowderDay)->S  {"msg_type":"CONNECT","player_id":"PowderDay","payload":{},"timestamp":1727000000}\n
S->C(PowderDay)  {"msg_type":"LOBBY_WAIT","player_id":"SERVER","payload":{"message":"Waiting for opponent to drop in"},"timestamp":1727000001}\n
C(BassDrop)->S    {"msg_type":"CONNECT","player_id":"BassDrop","payload":{},"timestamp":1727000002}\n
S->C(PowderDay)  {"msg_type":"GAME_START","player_id":"SERVER","payload":{"your_role":"PLAYER_1","your_disc":"R","opponent":"BassDrop","first_turn":"PLAYER_1"},"timestamp":1727000003}\n
S->C(BassDrop)    {"msg_type":"GAME_START","player_id":"SERVER","payload":{"your_role":"PLAYER_2","your_disc":"Y","opponent":"PowderDay","first_turn":"PLAYER_1"},"timestamp":1727000003}\n
C(BassDrop)->S    {"msg_type":"MOVE","player_id":"BassDrop","payload":{"col":4},"timestamp":1727000004}\n
S->C(BassDrop)    {"msg_type":"ERROR","player_id":"SERVER","payload":{"code":"OUT_OF_TURN","message":"It is PLAYER_1's turn"},"timestamp":1727000004}\n
C(PowderDay)->S  {"msg_type":"MOVE","player_id":"PowderDay","payload":{"col":3},"timestamp":1727000005}\n
S->C(both)   {"msg_type":"STATE_UPDATE","player_id":"SERVER","payload":{"board":[".......",".......",".......",".......",".......","...R..."],"last_move":{"role":"PLAYER_1","row":5,"col":3},"turn":"PLAYER_2","move_number":1},"timestamp":1727000005}\n
C(BassDrop)->S    {"msg_type":"DISCONNECT","player_id":"BassDrop","payload":{},"timestamp":1727000009}\n
S->C(PowderDay)  {"msg_type":"GAME_OVER","player_id":"SERVER","payload":{"result":"FORFEIT","winner":"PLAYER_1","reason":"OPPONENT_QUIT","final_board":[".......",".......",".......",".......",".......","...R..."],"winning_cells":[],"scores":{"PLAYER_1":1,"PLAYER_2":0}},"timestamp":1727000009}\n
```
