import base64
import http.client
import io
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from campuspulse.server import Handler


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = patch.dict("os.environ", {"CAMPUSPULSE_MODE": "local", "CAMPUSPULSE_TRANSPORT": "direct", "CAMPUSPULSE_ALLOW_CLOUD": "0"})
        cls.env.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=3); cls.env.stop()

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = json.dumps(data).encode() if data is not None else None
        final_headers = {"Content-Type": "application/json", **(headers or {})}
        if getattr(self, "cookie", None):
            final_headers["Cookie"] = self.cookie
        connection.request(method, path, body=body, headers=final_headers)
        response = connection.getresponse()
        if response.getheader("Set-Cookie"):
            self.cookie = response.getheader("Set-Cookie").split(";", 1)[0]
        result = json.loads(response.read())
        status = response.status
        connection.close()
        return status, result

    def test_status_reports_cloud_off(self):
        status, result = self.request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertFalse(result["cloud_allowed"])
        self.assertFalse(result["cloud_deployed"])

    def test_host_and_origin_are_checked(self):
        self.assertEqual(self.request("GET", "/api/status", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/query", {"message": "plan"}, {"Origin": "https://evil.example"})[0], 403)

    def test_utf8_text_is_extracted_without_saving_file(self):
        text = "Рекурсия и базовый случай"
        status, result = self.request("POST", "/api/extract", {"name": "lecture.txt", "data": base64.b64encode(text.encode()).decode()})
        self.assertEqual(status, 200)
        self.assertEqual(result["text"], text)

    def test_image_only_pdf_is_not_claimed_as_text(self):
        from pypdf import PdfWriter
        writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
        stream = io.BytesIO(); writer.write(stream)
        status, result = self.request("POST", "/api/extract", {"name": "scan.pdf", "data": base64.b64encode(stream.getvalue()).decode()})
        self.assertEqual(status, 400)
        self.assertIn("OCR", result["error"])

    def test_query_works_and_invalid_input_fails(self):
        status, result = self.request("POST", "/api/query", {"message": "Составь план", "context": {}})
        self.assertEqual(status, 200)
        self.assertEqual(result["mode"], "local")
        self.assertEqual(result["plan"]["blocks"], [])
        self.assertEqual(self.request("POST", "/api/query", {"message": ""})[0], 400)

    def test_key_connect_status_disconnect_and_no_secret_in_responses(self):
        key = "fake_developer_key_1234567890123456"
        with patch("campuspulse.free_gemini.verify_unbilled_key", return_value="123"):
            status, connected = self.request("POST", "/api/gemini/connect", {"api_key": key})
        self.assertEqual(status, 200)
        self.assertTrue(connected["gemini_connected"])
        self.assertEqual(connected["mode"], "developer")
        self.assertNotIn(key, str(connected))
        self.assertTrue(self.request("GET", "/api/status")[1]["gemini_connected"])
        self.assertFalse(self.request("POST", "/api/gemini/disconnect", {})[1]["gemini_connected"])
        self.assertFalse(self.request("GET", "/api/status")[1]["gemini_connected"])

    def test_expired_or_missing_developer_session_never_silently_runs_locally(self):
        with patch("campuspulse.server.run_query") as agent:
            status, result = self.request("POST", "/api/query", {"message": "План", "mode": "developer"})
        self.assertEqual(status, 400)
        self.assertIn("Сессия", result["error"])
        agent.assert_not_called()

    def test_failed_key_verification_does_not_initialize_model(self):
        from campuspulse.free_gemini import ConnectionError
        with patch("campuspulse.free_gemini.verify_unbilled_key", side_effect=ConnectionError("Биллинг не подтверждён")), patch("google.genai.Client") as model:
            status, _ = self.request("POST", "/api/gemini/connect", {"api_key": "fake_developer_key_1234567890123456"})
        self.assertEqual(status, 400)
        self.assertFalse(self.request("GET", "/api/status")[1]["gemini_connected"])
        model.assert_not_called()

    def test_mcp_wrapped_provider_error_stays_actionable_and_safe(self):
        from campuspulse.free_gemini import ConnectionError
        error = ExceptionGroup("MCP cleanup", [ConnectionError("Лимит бесплатного Gemini исчерпан.")])
        with patch("campuspulse.server.run_query", side_effect=error):
            status, response = self.request("POST", "/api/query", {"message": "План"})
        self.assertEqual(status, 400)
        self.assertIn("бесплатного", response["error"])


if __name__ == "__main__":
    unittest.main()
