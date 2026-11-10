"""Sample task processor. Never executed by RepoLens."""
from storage import StateStore


class Processor:
    def __init__(self, store: StateStore):
        self.store = store

    def run(self, task_id):
        self.store.save(task_id, "running")
        return {"status": "done"}


def main():
    return Processor(StateStore()).run("demo")
