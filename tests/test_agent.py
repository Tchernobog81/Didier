import pytest
from orchestrator.agent import DidierAgent
from orchestrator.memory import Memory


class StubMM:
    def __init__(self, resp=None, raise_exc=False):
        self.resp = resp
        self.raise_exc = raise_exc
        self.last_prompt = None

    def generate(self, prompt, model="llama3.2:1b", timeout=30):
        self.last_prompt = prompt
        if self.raise_exc:
            raise RuntimeError("stubbed failure")
        return self.resp


def test_agent_uses_model_and_saves(tmp_path):
    db = tmp_path / "didier.db"
    mem = Memory(str(db))
    mem.connect()

    mm = StubMM(resp="Salut du modèle")
    agent = DidierAgent(memory=mem, model_manager=mm)

    out = agent.chat("Dis quelque chose")

    assert agent._persona_prefix() in out
    assert "Salut du modèle" in out
    assert "Dis quelque chose" in mm.last_prompt

    rows = mem.get_recent(2)
    assert rows[0][0] == "assistant"
    assert "Salut du modèle" in rows[0][1]
    assert rows[1][0] == "user"
    assert "Dis quelque chose" in rows[1][1]


def test_agent_fallback_on_failure(tmp_path):
    db = tmp_path / "didier.db"
    mem = Memory(str(db))
    mem.connect()

    mm = StubMM(raise_exc=True)
    agent = DidierAgent(memory=mem, model_manager=mm)

    prompt = "Hello fallback"
    out = agent.chat(prompt)

    assert agent._persona_prefix() in out

    rows = mem.get_recent(2)
    assert rows[0][0] == "assistant"
    # fallback reply contains the prompt inside parentheses
    assert f"({prompt[:120]}" in rows[0][1]
