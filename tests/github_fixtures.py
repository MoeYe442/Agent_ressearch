import hashlib
import io
from pathlib import Path
import zipfile
import httpx

COMMIT = "a" * 40
TREE = "b" * 40


def blob(raw):
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def archive(files, prefix="demo-commit"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(prefix + "/" + name, content)
    return buffer.getvalue()


def sample_files():
    return {p.name: p.read_bytes() for p in (Path(__file__).parent / "fixtures/sample_repo").iterdir() if p.is_file()}


class Peer:
    def get_extra_info(self, name):
        return ("140.82.112.4", 443) if name == "server_addr" else None


def response(status=200, **kwargs):
    return httpx.Response(status, extensions={"network_stream": Peer()}, **kwargs)


async def public_dns(host):
    return ["140.82.112.4"]


class GitHubFixture:
    def __init__(self, files=None):
        self.files = files if files is not None else sample_files()
        self.requests = []
        self.sha = COMMIT

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        if request.url.host == "codeload.github.com":
            assert COMMIT in path
            return response(content=archive(self.files))
        if path.endswith("/zipball/" + COMMIT):
            return response(302, headers={"Location": f"https://codeload.github.com/example/demo/legacy.zip/{COMMIT}"})
        if "/commits/" in path:
            return response(json={"sha": self.sha, "commit": {"tree": {"sha": TREE}}})
        if "/git/trees/" in path:
            return response(json={"sha": TREE, "truncated": False, "tree": [{"path": path, "mode": "100644", "type": "blob", "sha": blob(raw), "size": len(raw)} for path, raw in self.files.items()]})
        return response(json={"private": False, "default_branch": "main"})
