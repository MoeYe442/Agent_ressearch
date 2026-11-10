import uvicorn
from repolens.api import create_app
from repolens.config import Settings


def application():
    return create_app(Settings.from_env())


if __name__ == "__main__":
    uvicorn.run("repolens.main:application", factory=True, host="127.0.0.1", port=8000)
