# ConnectFour

Two-player Connect Four over TCP for CS 457. The server keeps the board and checks every move. The clients just send a column and print what the server sends back.

Needs Python 3. No extra packages.

## How to run

Start the server first:

```bash
python3 server.py -p 8080
```

Then start a client in each of two other terminals:

```bash
python3 client.py -i localhost -p 8080 -n PowderDay
python3 client.py -i localhost -p 8080 -n BassDrop
```

- `-h` shows help (both)
- `-p` is the port, 1024-65535 (both, required)
- `-i` is the server hostname or IP (client, required)
- `-n` is your player name (client, optional, it asks if you leave it out)

If the hostname can't be looked up, the client says to check the router DNS setup and exits with code 1.

## Playing

Type a column `0`-`6` when it says `Your Turn`. Type `q` to leave, which counts as a forfeit if a game is going. After a round ends a new one starts automatically. Ctrl+C stops the server.