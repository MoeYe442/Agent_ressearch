import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from repolens.config import Settings
from repolens.model_client import HTTPChatModel, ProviderError


def test_provider_stream_obeys_total_deadline(tmp_path):
    class Trickling(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode()
            try:
                for i in range(0, len(body), 2):
                    self.wfile.write(body[i:i + 2])
                    self.wfile.flush()
                    time.sleep(.1)
            except OSError:
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Trickling)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    settings = Settings(workspace_root=tmp_path, data_dir=tmp_path / "data", model_url=f"http://127.0.0.1:{server.server_port}", model_key="test-only", provider_timeout=.5)
    model = HTTPChatModel(settings)
    model.deadline = time.monotonic() + .5
    started = time.monotonic()
    try:
        with pytest.raises(ProviderError):
            model.complete([], [], 20)
        assert time.monotonic() - started < 1.5
    finally:
        server.shutdown()
        server.server_close()
