"""The LLM port: one small interface, several providers behind it (ADR 7).

Intake only ever calls `client.complete(system, user, schema)` and gets text back. The
Fake provider answers with the rules extractor, so the app and its tests run without
any key or network. Gemini and Ollama providers are added in Step 7.
"""

import re
from typing import Any, Protocol

from quote_desk.intake.rules import rules_extract


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> str:
        """Return the model's answer as text (expected to be JSON matching `schema`)."""
        ...


class FakeLLM:
    """A scripted model: the rules extractor, optionally preceded by canned bad answers.

    `script` lets tests make the first answers invalid, to exercise the re-ask loop.
    """

    name = "fake"

    def __init__(self, script: list[str] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[str] = []

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> str:
        self.calls.append(user)
        if self.script:
            return self.script.pop(0)
        # The email is the part of the prompt between the markers set by extract.py.
        match = re.search(r"<email>\n(.*)\n</email>", user, re.S)
        return rules_extract(match.group(1) if match else user)
