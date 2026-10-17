import argparse
import json
import socket
from typing import Any


def exchange(reader: Any, writer: Any, request: dict[str, Any]) -> dict[str, Any]:
    # Send one request and read one reply.
    writer.write((json.dumps(request) + "\n").encode("utf-8"))
    writer.flush()
    line = reader.readline(8193)
    if not line:
        raise ConnectionError("The server closed the connection.")
    return json.loads(line.decode("utf-8"))


def show_leaderboard(reader: Any, writer: Any, topic: dict[str, Any]) -> None:
    # Scores are listed separately for each topic.
    response = exchange(reader, writer, {"action": "get_leaderboard", "topic": topic["id"]})
    if response.get("status") != "ok":
        print(response.get("message", "Could not get the leaderboard."))
        return
    print(f"\n{topic['name']} leaderboard")
    if not response["leaderboard"]:
        print("  No players yet.")
    for rank, entry in enumerate(response["leaderboard"], start=1):
        print(f"  {rank}. {entry['player']}: {entry['score']}")


def play_topic(reader: Any, writer: Any, player: str, topic: dict[str, Any]) -> None:
    print(f"\nPlaying {topic['name']}. Type an answer number, L for the leaderboard, or M for the topic menu.")
    while True:
        # Ask the server for this player's next question.
        response = exchange(reader, writer, {"action": "get_question", "topic": topic["id"], "player": player})
        if response.get("status") == "finished":
            print(f"\nFinished {topic['name']}! Your score: {response['score']}/{response['total']}")
            show_leaderboard(reader, writer, topic)
            return
        if response.get("status") != "ok":
            print(response.get("message", "Could not get a question."))
            return
        print(f"\n{topic['name']} question {response['number']}/{response['total']} | Score {response['score']}")
        print(response["question"])
        for number, choice in enumerate(response["choices"], start=1):
            print(f"  {number}. {choice}")
        while True:
            selection = input("Your choice: ").strip().lower()
            if selection == "m":
                return
            if selection == "l":
                show_leaderboard(reader, writer, topic)
                continue
            if selection.isdigit() and 1 <= int(selection) <= len(response["choices"]):
                break
            print("Enter one of the displayed numbers, L, or M.")
        # Send the answer text, not the menu number.
        answer = response["choices"][int(selection) - 1]
        result = exchange(reader, writer, {"action": "submit_answer", "topic": topic["id"],
                                           "player": player, "question_id": response["question_id"],
                                           "answer": answer})
        if result.get("status") != "ok":
            print(result.get("message", "Could not submit your answer."))
            return
        print("Correct!" if result["correct"] else f"Incorrect. The answer was: {result['correct_answer']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Play Disney and Star Wars trivia.")
    parser.add_argument("--host", default="127.0.0.1", help="Server address")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--name", help="Player name; prompted if omitted")
    args = parser.parse_args()
    player = args.name or input("Player name: ").strip()
    if not player or len(player) > 32 or any(ord(char) < 32 for char in player):
        parser.error("Player name must contain 1 to 32 printable characters.")
    try:
        with socket.create_connection((args.host, args.port), timeout=10) as connection:
            connection.settimeout(300)
            with connection.makefile("rb") as reader, connection.makefile("wb") as writer:
                # Build the menu from the server's topic list.
                response = exchange(reader, writer, {"action": "get_topics"})
                if response.get("status") != "ok":
                    raise ConnectionError("Could not load topics.")
                topics = response["topics"]
                while True:
                    print("\nChoose a topic:")
                    for number, topic in enumerate(topics, start=1):
                        print(f"  {number}. {topic['name']} ({topic['total']} questions)")
                    print("  Q. Quit")
                    selection = input("Topic: ").strip().lower()
                    if selection == "q":
                        print("Goodbye.")
                        return
                    if selection.isdigit() and 1 <= int(selection) <= len(topics):
                        play_topic(reader, writer, player, topics[int(selection) - 1])
                    else:
                        print("Choose one of the displayed topics or Q.")
    except (OSError, ConnectionError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Connection error: {exc}\n")
    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye.")


if __name__ == "__main__":
    main()
