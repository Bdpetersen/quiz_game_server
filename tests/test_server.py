"""Integration tests for topic selection and the real TCP protocol."""

import json
import io
import socket
import sys
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import QuizGame, QuizServer, load_topics  # noqa: E402
import client  # noqa: E402


class QuizServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.topics = load_topics(Path(__file__).resolve().parents[1] / "questions.json")
        cls.server = QuizServer(("127.0.0.1", 0), QuizGame(cls.topics))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.address = cls.server.server_address

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, payload):
        with socket.create_connection(self.address, timeout=3) as connection:
            connection.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            return json.loads(connection.makefile("rb").readline())

    def test_topics_have_only_requested_trivia(self):
        response = self.request({"action": "get_topics"})
        self.assertEqual([item["name"] for item in response["topics"]], ["Disney", "Star Wars"])
        all_questions = " ".join(question["question"] for topic in self.topics.values()
                                 for question in topic["questions"]).lower()
        self.assertNotIn("tcp", all_questions)
        self.assertNotIn("protocol", all_questions)

    def test_client_can_switch_topics(self):
        output = io.StringIO()
        arguments = ["client.py", "--host", "127.0.0.1", "--port", str(self.address[1]),
                     "--name", "Menu_test"]
        with patch.object(sys, "argv", arguments), patch("builtins.input", side_effect=["1", "m", "2", "m", "q"]), redirect_stdout(output):
            client.main()
        self.assertIn("Playing Disney", output.getvalue())
        self.assertIn("Playing Star Wars", output.getvalue())
        self.assertIn("Goodbye.", output.getvalue())

    def test_choices_shuffle_once_per_question(self):
        player = "Shuffle_test"
        request = {"action": "get_question", "topic": "disney", "player": player}
        with patch("server.random.sample", side_effect=lambda choices, k: list(reversed(choices))):
            first = self.request(request)
        expected = list(reversed(self.topics["disney"]["questions"][0]["choices"]))
        self.assertEqual(first["choices"], expected)
        with patch("server.random.sample", side_effect=AssertionError("choices shuffled twice")):
            repeated = self.request(request)
        self.assertEqual(repeated["choices"], first["choices"])
        self.request({"action": "submit_answer", "topic": "disney", "player": player,
                      "question_id": first["question_id"],
                      "answer": self.topics["disney"]["questions"][0]["answer"]})
        with patch("server.random.sample", side_effect=lambda choices, k: list(reversed(choices))):
            second = self.request(request)
        self.assertEqual(second["choices"], list(reversed(self.topics["disney"]["questions"][1]["choices"])))

    def test_topic_progress_and_leaderboards_are_separate(self):
        player = "Alice_test"
        disney = self.request({"action": "get_question", "topic": "disney", "player": player})
        star_wars = self.request({"action": "get_question", "topic": "star_wars", "player": player})
        self.assertEqual(disney["number"], 1)
        self.assertEqual(star_wars["number"], 1)
        self.assertNotIn("answer", disney)
        result = self.request({"action": "submit_answer", "topic": "disney", "player": player,
                               "question_id": disney["question_id"], "answer": self.topics["disney"]["questions"][0]["answer"]})
        self.assertEqual(result["score"], 1)
        self.assertEqual(self.request({"action": "get_question", "topic": "disney", "player": player})["number"], 2)
        self.assertEqual(self.request({"action": "get_question", "topic": "star_wars", "player": player})["number"], 1)
        replay = self.request({"action": "submit_answer", "topic": "disney", "player": player,
                               "question_id": disney["question_id"], "answer": self.topics["disney"]["questions"][0]["answer"]})
        self.assertEqual(replay["status"], "error")
        disney_leaders = self.request({"action": "get_leaderboard", "topic": "disney"})["leaderboard"]
        star_leaders = self.request({"action": "get_leaderboard", "topic": "star_wars"})["leaderboard"]
        self.assertIn({"player": player, "score": 1}, disney_leaders)
        self.assertIn({"player": player, "score": 0}, star_leaders)

    def test_bad_input_and_disconnect_do_not_stop_server(self):
        with socket.create_connection(self.address, timeout=3) as connection:
            connection.sendall(b"{bad json}\n")
            self.assertEqual(json.loads(connection.makefile("rb").readline())["status"], "error")
        with socket.create_connection(self.address, timeout=3) as connection:
            connection.sendall(b'{"action":"get_topics"}\n')
        self.assertEqual(self.request({"action": "get_topics"})["status"], "ok")
        self.assertEqual(self.request({"action": "get_question", "topic": "missing", "player": "A"})["status"], "error")

    def test_simultaneous_answers_award_one_point(self):
        player = "Race_test"
        question = self.request({"action": "get_question", "topic": "star_wars", "player": player})
        payload = {"action": "submit_answer", "topic": "star_wars", "player": player,
                   "question_id": question["question_id"], "answer": self.topics["star_wars"]["questions"][0]["answer"]}
        barrier = threading.Barrier(8)
        results = []
        guard = threading.Lock()

        def submit():
            barrier.wait()
            result = self.request(payload)
            with guard:
                results.append(result)

        workers = [threading.Thread(target=submit) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
        self.assertEqual(len(results), 8)
        self.assertEqual(sum(result["status"] == "ok" for result in results), 1)
        leaders = self.request({"action": "get_leaderboard", "topic": "star_wars"})["leaderboard"]
        self.assertIn({"player": player, "score": 1}, leaders)


if __name__ == "__main__":
    unittest.main()
