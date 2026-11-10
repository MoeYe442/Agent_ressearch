"""Memory storage: no disk persistence and no restart recovery."""


class StateStore:
    def __init__(self):
        self.states = {}

    def save(self, task_id, status):
        self.states[task_id] = status

    def load(self, task_id):
        return self.states.get(task_id)
