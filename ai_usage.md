# AI Usage and Protocol Constraints

## 1. Disclosure

**Tool used:** Claude 

**What the AI helped me with**

* Helped me brainstorm possible ideas for the game and compare which type of game would work well with a client/server protocol.
* Helped me review the FSM and identify cases that needed to be accounted for, such as invalid moves, out-of-turn moves, EOF, connection errors, and player forfeits.
* Helped me review the Markdown formatting and organization of the protocol and FSM documents.
* Helped me make some of the explanations more readable and easier to understand.
* Helped me check whether the protocol and FSM were consistent with each other.

**What the AI did not do**

* It did not independently decide the entire protocol for me.
* It did not write the final server or client implementation.
* It did not replace my decisions about the game rules or the final FSM.
* I reviewed the AI suggestions and decided which ones to keep or change.


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

* [ ] Every `msg_type` in the code is one of the 8 in the blueprint
* [ ] Every JSON key and error code in the code appears in the blueprint
* [ ] The receive loop has an EOF check and the required exception handlers
* [ ] No state or transition exists in the code that is not in the diagram
* [ ] Invalid and out of-turn moves return `ERROR` and leave board and `active` unchanged
* [ ] Wire samples from the blueprint parse and produce the documented replies

## 6. Prompt Log (design phase)

| # | Date      | What I asked                                                           | What the AI did                                                            | What I did with it                                        |
| - | --------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------- | --------------------------------------------------------- |
| 1 | [September 24] | Asked for help understanding the assignment requirements               | Helped break the protocol requirements into smaller pieces                 | Used the explanation to plan the documents                |
| 2 | [September 24] | Asked for ideas for a multiplayer game that would work well over TCP   | Suggested several options and discussed their complexity                   | Chose Connect Four                                        |
| 3 | [Septemeber 27] | Asked how TCP message framing should work                              | Explained newline-delimited JSON, fragmentation, and coalescing            | Used this approach in the protocol                        |
| 4 | [] | Asked for help thinking through the server states                      | Helped identify the lobby, game, evaluation, game-over, and cleanup stages | Designed and edited the final FSM                         |
| 5 | [October 1] | Asked what kinds of invalid moves and disconnects needed to be handled | Listed possible validation and connection cases                            | Decided which cases belonged in the final specification   |
| 6 | [October 4] | Asked for a review of the protocol and FSM                             | Pointed out areas that could be clarified or made more consistent          | Reviewed the suggestions and made the final edits         |
| 7 | [October 4] | Asked for help making the documents sound more natural and readable    | Suggested clearer wording and organization                                 | Edited the wording and kept the parts that fit my writing |
