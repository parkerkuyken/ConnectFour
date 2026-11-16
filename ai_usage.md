# AI Usage and Protocol Constraints

## 1. Disclosure

**Tool used:** Claude, OpenAI

**What the AI helped me with**

* Helped me brainstorm possible ideas for the game and compare which type of game would work well with a client/server protocol.
* Helped me review the FSM and identify cases that needed to be accounted for, such as invalid moves, out-of-turn moves, EOF, connection errors, and player forfeits.
* Helped me review the Markdown formatting and organization of the protocol and FSM documents.
* Helped me make some of the explanations more readable and easier to understand.
* Helped me check whether the protocol and FSM were consistent with each other.
* Answered questions about how the code works so I could explain it myself.

**What the AI did not do**

* It did not decide the protocol, the FSM, or the concurrency model. Those came from my Sprint 1 and Sprint 2 documents.
* It did not replace my decisions about the game rules or the final FSM.
* I reviewed the AI suggestions and decided which ones to keep or change.
* I reviewed the code it wrote, ran it myself, and tested it with two clients on my own machine.


## 2. Constraint Prompt

When using AI for implementation, I will provide the protocol blueprint and FSM specification and tell the AI to treat them as the only specification.

The main constraints are:

* Do not add message types that are not in the specification.
* Do not change the JSON fields or error codes.
* Do not add features that are not required by the specification.
* If something is ambiguous, ask before inventing behavior.

## 4. Task Prompts for the Coding Phase

Examples of the types of assistance I may ask AI for:

```text
Review my LineReader implementation against Section 2.4 of the
protocol blueprint. Do not rewrite it yet. Point out anything that
does not match the specification.
```

```text
Review my implementation of the WAITING_FOR_PLAYERS and GAME_START
states against transitions T3 through T7. Identify anything that
does not follow the FSM.
```

```text
Review my MOVE validation logic against Section 4 of the FSM.
Pay particular attention to the order of the validation checks.
Do not add behavior that is not specified.
```

```text
Review my disconnect handling against Section 5 of the FSM and
identify any cases I have missed.
```

## 5. Review Checklist

* [x] Every `msg_type` in the code is one of the 8 in the blueprint
* [x] Every JSON key and error code in the code appears in the blueprint
* [x] The receive loop has an EOF check and the required exception handlers
* [x] No state or transition exists in the code that is not in the diagram
* [x] Invalid and out of-turn moves return `ERROR` and leave the board and `turn` unchanged
* [x] Wire samples from the blueprint parse and produce the documented replies

## 6. Prompt Log

| # | Date      | What I asked                                                           | What the AI did                                                            | What I did with it                                        |
| - | --------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------- | --------------------------------------------------------- |
| 1 | [September 24] | Asked for help understanding the assignment requirements               | Helped break the protocol requirements into smaller pieces                 | Used the explanation to plan the documents                |
| 2 | [September 24] | Asked for ideas for a multiplayer game that would work well over TCP   | Suggested several options and discussed their complexity                   | Chose Connect Four                                        |
| 3 | [Septemeber 27] | Asked how TCP message framing should work                              | Explained newline-delimited JSON, fragmentation, and coalescing            | Used this approach in the protocol                        |
| 4 | [] | Asked for help thinking through the server states                      | Helped identify the lobby, game, evaluation, game-over, and cleanup stages | Designed and edited the final FSM                         |
| 5 | [October 1] | Asked what kinds of invalid moves and disconnects needed to be handled | Listed possible validation and connection cases                            | Decided which cases belonged in the final specification   |
| 6 | [October 4] | Asked for a review of the protocol and FSM                             | Pointed out areas that could be clarified or made more consistent          | Reviewed the suggestions and made the final edits         |
| 7 | [October 4] | Asked for help making the documents sound more natural and readable    | Suggested clearer wording and organization                                 | Edited the wording and kept the parts that fit my writing |
| 8 | [October 19] | Asked for help drafting the Sprint 2 concurrency doc and Mermaid sequence diagram from my protocol and FSM | Drafted a threading design (reader and writer thread per client) and a sequence diagram | Wrote my own version with a simpler model: one handler thread per client and one lock, and made my own diagrams |
| 9 | [November 15] | Asked it to check my README | Pointed out the run example used a hostname that won't resolve yet | Changed the example to use `localhost` |
| 10 | [November 15] | Asked it to walk me through what the server does, step by step, when a player sends a MOVE | Traced the path from `recv()` through `LineReader`, the parsing checks, `apply_move` under the lock, `_validate`, dropping the disc, the win/draw check, and the broadcast | Used it to understand the move flow well enough to explain it |
| 11 | [November 15] | Asked why the turn check comes before the column checks in `_validate` | Explained that an out-of-turn move is wrong no matter the column, so the most relevant error comes first, and the server does no extra work for the waiting player | Kept the order as specified in my FSM |
| 12 | [November 15] | Asked what would go wrong without the lock in `apply_move` | Described a race where the turn flips before the broadcast, the other player moves right away, and both threads write to the same socket, so updates arrive out of order or get mixed together | Kept the single lock around the whole move |
| 13 | [November 15] | Asked how `LineReader` handles a message split across two `recv()` calls | Explained that bytes stay in the buffer until a newline shows up, and a partial message at EOF is thrown away | No changes needed |
| 14 | [November 15] | Asked why the client uses two threads | Explained that `input()` and `recv()` both block, so with one thread you can't see the opponent's move while typing, or quit while waiting | No changes needed |
| 15 | [November 15] | Asked what happens if a player closes their terminal mid-game | Explained the EOF path to `remove_player`, the forfeit `GAME_OVER` to the other player, and the survivor going back to the lobby. Pointed out that a dropped network with no FIN is only noticed on the next send | Noted the limitation for Sprint 4 testing |
| 16 | [November 15] | Asked it to review `server.py` against my FSM transition table | Confirmed T1-T16 are all handled. Found that invalid aliases and parse errors aren't logged with T4/T8, and shutdown only closes the listener socket | Decided whether to fix the logging gaps |
| 17 | [November 15] | Asked what to test before Sprint 4 when the client runs on another machine | Listed checks: the macOS firewall prompt, testing by IP before DNS, copying `protocol.py` with the client, and pulling a cable mid-game | Made a test list for Sprint 4 |
| 18 | [November 15] | Asked it to update this file | Added the Sprint 2 and Sprint 3 rows, corrected the disclosure section, and checked off the review checklist | Reviewed the changes before committing |