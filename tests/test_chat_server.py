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
        cls.token = "test-token-not-secret"
        cs.TOKEN = cls.token
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
                                     headers={"content-type": "application/json", cs.TOKEN_HEADER: self.token})
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
        req = urllib.request.Request(self.url + "/data", headers={cs.TOKEN_HEADER: self.token})
        with urllib.request.urlopen(req) as r:
            self.assertIn("asOf", json.load(r))



class PlanWordsTest(unittest.TestCase):
    def test_the_prompt_maps_every_internal_plan_key_to_its_words(self):
        """The chat once answered "readiness 39 (moderate)" — the code's key, not the plan's name."""
        prompt = cs.SYSTEM_PROMPT if hasattr(cs, "SYSTEM_PROMPT") else open(cs.__file__).read()
        for key, words in (("moderate", "Train as planned"), ("easy", "Go easy"), ("rest", "Rest")):
            self.assertIn('%s = "%s"' % (key, words), prompt)

class LocalAuthTest(unittest.TestCase):
    """Binding to 127.0.0.1 keeps other devices out, not other PAGES on this Mac. The token does that."""

    @classmethod
    def setUpClass(cls):
        d = make_data_dir(days=60)
        cls.patches = [mock.patch.object(cs, "DATA_FILE", os.path.join(d, "dashboard_data.json")),
                       mock.patch.object(ai_context, "RAW_FILE", os.path.join(d, "whoop_data.json")),
                       mock.patch.object(ai_context, "DASH_FILE", os.path.join(d, "dashboard_data.json"))]
        for p in cls.patches:
            p.start()
        cls.saved_token = cs.TOKEN
        cs.TOKEN = "right-token"
        cls.app, cls.url = serve(cs.Handler)
        cls.port = cls.app.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.app.server_close()
        cs.TOKEN = cls.saved_token
        for p in cls.patches:
            p.stop()

    def call(self, method, path, token=None, host=None, origin=None, body=None):
        headers = {"content-type": "text/plain"}               # a "simple" request: no preflight
        if token is not None:
            headers[cs.TOKEN_HEADER] = token
        if host is not None:
            headers["Host"] = host
        if origin is not None:
            headers["Origin"] = origin
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    ENDPOINTS = (("GET", "/data", None), ("POST", "/ask", {"messages": [{"role": "user", "content": "hi"}]}),
                 ("POST", "/refresh", {}))

    def test_no_token_is_refused_on_every_endpoint_before_any_work(self):
        with mock.patch.object(cs.subprocess, "run") as ran, mock.patch.object(cs, "build_context_text") as ctx:
            for method, path, body in self.ENDPOINTS:
                status, _h, raw = self.call(method, path, body=body)
                self.assertEqual(status, 403, path)
                self.assertNotIn(b"readiness", raw)
            ran.assert_not_called()                          # /refresh never ran its subprocesses
            ctx.assert_not_called()                          # /ask never built the data context

    def test_a_wrong_token_is_refused(self):
        for method, path, body in self.ENDPOINTS:
            self.assertEqual(self.call(method, path, token="wrong-token", body=body)[0], 403, path)
        self.assertEqual(self.call("GET", "/data", token="right-token-plus")[0], 403)

    def test_the_right_token_works(self):
        status, _h, raw = self.call("GET", "/data", token="right-token")
        self.assertEqual(status, 200)
        self.assertIn("readiness", json.loads(raw))

    def test_a_foreign_host_is_refused_even_with_the_token(self):
        """DNS rebinding: an attacker's hostname resolving to 127.0.0.1 arrives with that Host."""
        for host in ("evil.example:%d" % self.port, "127.0.0.1", "127.0.0.1:1", "localhost"):
            self.assertEqual(self.call("GET", "/data", token="right-token", host=host)[0], 403, host)
        self.assertEqual(self.call("GET", "/data", token="right-token", host="localhost:%d" % self.port)[0], 200)

    def test_never_a_wildcard_and_only_the_null_origin_is_answered(self):
        _s, h, _b = self.call("GET", "/data", token="right-token", origin="null")
        self.assertEqual(h.get("Access-Control-Allow-Origin"), "null")
        _s, h, _b = self.call("GET", "/data", token="right-token", origin="https://evil.example")
        self.assertNotIn("Access-Control-Allow-Origin", h)
        for method, path, body in self.ENDPOINTS:
            _s, h, _b = self.call(method, path, body=body, origin="null")
            self.assertNotEqual(h.get("Access-Control-Allow-Origin"), "*")

    def test_the_real_pages_preflight_still_works(self):
        req = urllib.request.Request(self.url + "/ask", method="OPTIONS", headers={
            "Origin": "null", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, x-dashboard-token"})
        with urllib.request.urlopen(req, timeout=15) as r:
            self.assertEqual(r.status, 204)
            self.assertEqual(r.headers["Access-Control-Allow-Origin"], "null")
            self.assertIn("x-dashboard-token", r.headers["Access-Control-Allow-Headers"])

    def test_the_token_is_compared_in_constant_time(self):
        src = open(cs.__file__).read()
        self.assertIn("hmac.compare_digest", src)
        self.assertNotIn('"Access-Control-Allow-Origin", "*"', src)


class TokenIssueTest(unittest.TestCase):
    def test_a_fresh_private_token_is_written_and_put_into_the_page(self):
        import stat
        d = tempfile.mkdtemp()
        tok_file, page = os.path.join(d, ".dashboard_token"), os.path.join(d, "index.html")
        with open(page, "w") as f:
            f.write('<script>const DASHBOARD_TOKEN = "old";</script>')
        with mock.patch.object(cs, "TOKEN_FILE", tok_file), mock.patch.object(cs, "INDEX_FILE", page):
            t1, t2 = cs.issue_token(), cs.issue_token()
        self.assertNotEqual(t1, t2)                                   # fresh every run
        self.assertGreaterEqual(len(t2), 40)
        self.assertEqual(open(tok_file).read(), t2)
        self.assertEqual(stat.S_IMODE(os.stat(tok_file).st_mode), 0o600)
        self.assertIn('const DASHBOARD_TOKEN = "%s";' % t2, open(page).read())

    def test_the_token_file_is_ignored_and_scanned(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertIn(".dashboard_token", open(os.path.join(root, ".gitignore")).read().split())
        self.assertIn('".dashboard_token"', open(os.path.join(root, "scripts", "privacy_scan.py")).read())


if __name__ == "__main__":
    unittest.main()
