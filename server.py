"""Multiplayer, multi-topic quiz server using newline-delimited JSON over TCP."""

from __future__ import annotations

import argparse
import json
import random
import socket
import socketserver
import threading
from pathlib import Path
from typing import Any

MAX_MESSAGE_BYTES = 8192


def load_topics(path: Path) -> dict[str, dict[str, Any]]:
    """Validate the question file before opening the server socket."""
    data = json.loads(path.read_text(encoding="utf-8"))
    # Check the topic and question data before the game starts.
    if not isinstance(data, dict) or not data:
        raise ValueError("The question file must contain a nonempty topic object.")
    for topic_id, topic in data.items():
        if not isinstance(topic_id, str) or not topic_id or not isinstance(topic, dict):
            raise ValueError("Each topic needs an ID and an object value.")
        if not isinstance(topic.get("name"), str) or not topic["name"].strip():
            raise ValueError(f"Topic {topic_id} needs a name.")
        questions = topic.get("questions")
        if not isinstance(questions, list) or not questions:
            raise ValueError(f"Topic {topic_id} needs a nonempty questions list.")
        seen = set()
        for number, question in enumerate(questions, start=1):
            label = f"{topic_id} question {number}"
            if not isinstance(question, dict):
                raise ValueError(f"{label} must be an object.")
            question_id = question.get("id")
            choices = question.get("choices")
            if not isinstance(question_id, str) or not question_id or question_id in seen:
                raise ValueError(f"{label} needs a unique ID within its topic.")
            if not isinstance(question.get("question"), str) or not question["question"].strip():
                raise ValueError(f"{label} needs question text.")
            if (not isinstance(choices, list) or len(choices) < 2
                    or any(not isinstance(choice, str) or not choice.strip() for choice in choices)
                    or len(set(choices)) != len(choices)):
                raise ValueError(f"{label} needs at least two distinct choices.")
            if question.get("answer") not in choices:
                raise ValueError(f"{label} answer must match a choice exactly.")
            seen.add(question_id)
    return data


class QuizGame:
    """The lock makes scoring safe when multiple clients answer at once."""

    def __init__(self, topics: dict[str, dict[str, Any]]) -> None:
        self.topics = topics
        self.players: dict[str, dict[str, dict[str, Any]]] = {}
        self.lock = threading.Lock()

    def handle_request(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self.error("Request must be a JSON object.")
        action = request.get("action")
        if action == "get_topics":
            return {"status": "ok", "topics": [
                {"id": topic_id, "name": topic["name"], "total": len(topic["questions"])}
                for topic_id, topic in self.topics.items()
            ]}
        if action not in ("get_question", "submit_answer", "get_leaderboard"):
            return self.error("Unknown action.")
        topic_id = request.get("topic")
        if not isinstance(topic_id, str) or topic_id not in self.topics:
            return self.error("Choose a topic from get_topics.")
        topic = self.topics[topic_id]
        questions = topic["questions"]

        if action == "get_leaderboard":
            with self.lock:
                leaders = sorted(
                    ({"player": player, "score": progress[topic_id]["score"]}
                     for player, progress in self.players.items() if topic_id in progress),
                    key=lambda entry: (-entry["score"], entry["player"].casefold()),
                )
            return {"status": "ok", "topic": topic_id, "leaderboard": leaders}

        player = request.get("player")
        if (not isinstance(player, str) or not player.strip() or len(player.strip()) > 32
                or any(ord(char) < 32 for char in player)):
            return self.error("Provide a player name of 1 to 32 printable characters.")
        player = player.strip()
        # Players have separate progress in each topic.
        with self.lock:
            progress = self.players.setdefault(player, {}).setdefault(
                topic_id, {"index": 0, "score": 0, "choices": None}
            )
            index = progress["index"]
            if action == "get_question":
                if index >= len(questions):
                    return {"status": "finished", "topic": topic_id,
                            "score": progress["score"], "total": len(questions)}
                question = questions[index]
                # Shuffle once, then keep this order until the answer is sent.
                if progress["choices"] is None:
                    progress["choices"] = random.sample(question["choices"], k=len(question["choices"]))
                return {"status": "ok", "topic": topic_id, "question_id": question["id"],
                        "question": question["question"], "choices": progress["choices"],
                        "number": index + 1, "total": len(questions), "score": progress["score"]}

            if index >= len(questions):
                return {"status": "finished", "topic": topic_id,
                        "score": progress["score"], "total": len(questions)}
            question = questions[index]
            if request.get("question_id") != question["id"]:
                return self.error("Question ID does not match your current question.")
            if request.get("answer") not in question["choices"]:
                return self.error("Answer must exactly match one of the choices.")
            # Score this question and move to the next one.
            correct = request["answer"] == question["answer"]
            if correct:
                progress["score"] += 1
            progress["index"] += 1
            progress["choices"] = None
            return {"status": "ok", "topic": topic_id, "correct": correct,
                    "correct_answer": question["answer"], "score": progress["score"],
                    "finished": progress["index"] >= len(questions)}

    @staticmethod
    def error(message: str) -> dict[str, str]:
        return {"status": "error", "message": message}


class QuizRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(300)
        try:
            while True:
                # Each line contains one JSON request.
                line = self.rfile.readline(MAX_MESSAGE_BYTES + 1)
                if not line:
                    return
                if len(line) > MAX_MESSAGE_BYTES or not line.endswith(b"\n"):
                    self.send(QuizGame.error("Message is too long or missing a newline."))
                    return
                try:
                    request = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    response = QuizGame.error("Send one valid UTF-8 JSON object per line.")
                else:
                    response = self.server.game.handle_request(request)
                self.send(response)
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            pass  # A disconnected client does not affect other clients.

    def send(self, response: dict[str, Any]) -> None:
        self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()


class QuizServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], game: QuizGame) -> None:
        super().__init__(address, QuizRequestHandler)
        self.game = game


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Disney and Star Wars quiz server.")
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 for local network clients")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--questions", type=Path, default=Path(__file__).with_name("questions.json"))
    args = parser.parse_args()
    # Load questions before accepting clients.
    game = QuizGame(load_topics(args.questions))
    with QuizServer((args.host, args.port), game) as server:
        print(f"Quiz server listening on {args.host}:{server.server_address[1]}")
        print("Topics:", ", ".join(topic["name"] for topic in game.topics.values()))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


if __name__ == "__main__":
    main()
