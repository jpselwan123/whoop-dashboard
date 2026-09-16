"""Chat backend tests against a local fake AI provider — no network, no API key, no cost."""
import json, os, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from helpers import make_data_dir
import ai_context
import chat_server as cs


class FakeProvider(BaseHTTPRequestHandler):
    mode = "ok"
    last = {}

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeProvider.last = {"path": self.path, "body": body, "headers": {k.lower(): v for k, v in self.headers.items()}}
        responses = {
            "ok": (200, {"output": [{"type": "reasoning"}, {"type": "message", "content": [
                {"type": "output_text", "text": "Answer."}]}], "usage": {"input_tokens": 10, "output_tokens": 2,
                "input_tokens_details": {"cached_tokens": 8}}}) if self.path.endswith("/responses")
                  else (200, {"content": [{"type": "text", "text": "Claude answer."}], "usage": {}}),
            "401": (401, {"error": {"message": "bad key", "code": "invalid_api_key"}}),
            "quota": (429, {"error": {"message": "quota", "code": "insufficient_quota"}}),
            "rate": (429, {"error": {"message": "slow", "code": "rate_limit_exceeded"}}),
            "500": (500, {"error": {"message": "boom"}}),
            "incomplete": (200, {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []}),
        }
        code, obj = responses[FakeProvider.mode]
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class ChatServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = make_data_dir(days=60)
        cls.patches = [
            mock.patch.object(ai_context, "RAW_FILE", os.path.join(d, "whoop_data.json")),
            mock.patch.object(ai_context, "DASH_FILE", os.path.join(d, "dashboard_data.json")),
            mock.patch.object(cs, "DATA_FILE", os.path.join(d, "dashboard_data.json")),
        ]
        for p in cls.patches:
            p.start()
        cls.provider, provider_url = serve(FakeProvider)
        os.environ["OPENAI_BASE_URL"] = provider_url + "/v1"
        os.environ["ANTHROPIC_BASE_URL"] = provider_url + "/v1"
        cls.app, cls.url = serve(cs.Handler)
        cls.env = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False).name
        cs.ENV_FILE = cls.env
        cs._loaded_from_file = {"AI_PROVIDER", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_MODEL"}
        for k in cs._loaded_from_file:
            os.environ.pop(k, None)

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.app, cls.provider):
            srv.shutdown()
            srv.server_close()
        for p in cls.patches:
            p.stop()

    def setUp(self):
        FakeProvider.mode = "ok"
        self.set_env("OPENAI_API_KEY=sk-test\n")

    def set_env(self, text):
        with open(self.env, "w") as f:
            f.write(text)

    def ask(self, payload):
        req = urllib.request.Request(self.url + "/ask", data=json.dumps(payload).encode(),
                                     headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    Q = {"messages": [{"role": "user", "content": "How was my sleep?"}]}

    def test_answer_and_request_shape(self):
        status, data = self.ask(self.Q)
        self.assertEqual(status, 200)
        self.assertEqual(data["answer"], "Answer.")
        body = FakeProvider.last["body"]
        self.assertEqual(body["model"], "gpt-5.6-luna")
        self.assertFalse(body["store"])
        self.assertEqual(FakeProvider.last["headers"]["authorization"], "Bearer sk-test")
        self.assertIn("## workouts", body["input"][0]["content"])
        self.assertTrue(body["input"][-1]["content"].startswith("[Now:"))

    def test_key_is_never_returned_to_the_page(self):
        _, data = self.ask(self.Q)
        self.assertNotIn("sk-test", json.dumps(data))

    def test_missing_key(self):
        self.set_env("OPENAI_API_KEY=\n")
        status, data = self.ask(self.Q)
        self.assertEqual(status, 400)
        self.assertIn("OPENAI_API_KEY", data["error"])

    def test_conversation_history_is_forwarded_in_order(self):
        convo = {"messages": [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"},
                              {"role": "user", "content": "q2"}]}
        self.assertEqual(self.ask(convo)[0], 200)
        roles = [m["role"] for m in FakeProvider.last["body"]["input"][1:]]
        self.assertEqual(roles, ["user", "assistant", "user"])

    def test_long_history_is_trimmed(self):
        msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 7000} for i in range(50)]
        msgs.append({"role": "user", "content": "latest"})
        self.assertEqual(self.ask({"messages": msgs})[0], 200)
        sent = FakeProvider.last["body"]["input"][1:]
        self.assertLessEqual(sum(len(m["content"]) for m in sent), cs.MAX_HISTORY_CHARS + 200)
        self.assertEqual(sent[0]["role"], "user")

    def test_rejects_malformed_requests(self):
        for payload in ({"messages": []}, {"messages": [{"role": "system", "content": "x"}]},
                        {"messages": [{"role": "assistant", "content": "x"}]}, {"nope": 1}):
            self.assertEqual(self.ask(payload)[0], 400, payload)

    def test_provider_errors_become_plain_sentences(self):
        cases = {"401": "didn't accept the API key", "quota": "out of credit", "rate": "rate-limiting",
                 "500": "having problems", "incomplete": "ran out of room"}
        for mode, phrase in cases.items():
            FakeProvider.mode = mode
            status, data = self.ask(self.Q)
            self.assertGreaterEqual(status, 400)
            self.assertIn(phrase, data["error"], mode)

    def test_anthropic_provider(self):
        self.set_env("AI_PROVIDER=anthropic\nANTHROPIC_API_KEY=ak-test\n")
        status, data = self.ask(self.Q)
        self.assertEqual((status, data["answer"]), (200, "Claude answer."))
        self.assertTrue(FakeProvider.last["path"].endswith("/messages"))

    def test_data_endpoint(self):
        with urllib.request.urlopen(self.url + "/data") as r:
            self.assertIn("asOf", json.load(r))


if __name__ == "__main__":
    unittest.main()
