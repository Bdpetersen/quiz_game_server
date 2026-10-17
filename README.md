# Overview

I built a multiplayer quiz game to practice writing software that communicates across a network. One Python program runs as the server and keeps the questions and scores. Another runs as a client so players can choose Disney or Star Wars, answer questions, and view a leaderboard. Players can switch topics without losing their progress while the server is running. Answer choices are shuffled for each new question.

To play on one computer, open a terminal in this folder and start the server:

```text
python server.py
```

Open a second terminal in the same folder and start a client:

```text
python client.py --name Alice
```

Run another client with a different name to demonstrate multiple players. In the client, enter a topic number, then an answer number. Enter `L` to see that topic's leaderboard, `M` to return to the topic menu, or `Q` at the menu to quit. If your computer uses `py` or `python3`, use that command instead of `python`.

To play on two computers on the same local network, start the server with `python server.py --host 0.0.0.0 --port 5050`. On the other computer, run `python client.py --host SERVER_IP --port 5050 --name NAME`, replacing `SERVER_IP` with the server computer's local IPv4 address and NAME with your name. The server computer may need to allow port 5050 through its firewall on private networks.

[Software Demo Video](https://www.youtube.com/watch?v=pZdrkzB-rPY)

# Network Communication

This project uses a client/server architecture. The server listens for connections, owns the question data, checks answers, and stores scores. Each client connects to the server and sends requests when a player chooses a topic, asks for a question, submits an answer, or views the leaderboard.

Communication uses **TCP** on port **5050** by default. The server listens on `127.0.0.1` for play on one computer. Binding it to `0.0.0.0` lets clients on the local network connect using the server computer's IP address.

Each message is one UTF-8 JSON object followed by a newline. The newline marks the end of a message in the TCP byte stream. The client sends these actions: `get_topics`, `get_question`, `submit_answer`, and `get_leaderboard`. The server replies with JSON containing a `status` such as `ok`, `finished`, or `error`.

For example, a client can request a question with:

```json
{"action":"get_question","topic":"disney","player":"Alice"}
```

The server replies with the question ID, question text, shuffled choices, question number, total, and current score. The correct answer is not sent until the player submits a choice. A `submit_answer` request includes the topic, player, question ID, and exact choice text. The server checks it and returns whether it was correct and the updated score.

Scores and progress are stored in memory, so they reset when the server stops. Player names are not authenticated, and messages are not encrypted; use this version on a trusted local network.

# Development Environment

The game is written in **Python 3** and can be run from a terminal with no third-party packages. The server uses `socketserver` and `threading` to handle several clients, `random` to shuffle choices, and `json` and `pathlib` to load the question file. The client uses `socket` for the TCP connection and `json` for messages. Command-line options are handled with `argparse`.


# Useful Websites

These official Python references explain the libraries used in this project:

* [Python socket documentation](https://docs.python.org/3/library/socket.html)
* [Python socketserver documentation](https://docs.python.org/3/library/socketserver.html)
* [Python json documentation](https://docs.python.org/3/library/json.html)

# Future Work

* Save player scores and progress to a file or database so they survive a server restart.
* Add player accounts and encrypted connections before allowing play across the public internet.
* Add more topics and randomize the question order as well as the answer choices.
