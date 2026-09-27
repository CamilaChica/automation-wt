"""Best-effort token counting with a deterministic character fallback."""

from __future__ import annotations

import math


class TokenCounter:
    def __init__(self, *, characters_per_token: float = 4.0):
        if characters_per_token <= 0:
            raise ValueError("characters_per_token must be positive.")
        self.characters_per_token = characters_per_token

    def count(self, text: str, model: str = "gpt-4o-mini") -> int:
        try:
            import tiktoken

            encoding = tiktoken.encoding_for_model(model)
            return len(encoding.encode(text))
        except Exception:
            return self.estimate(text)

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text) / self.characters_per_token))


token_counter = TokenCounter()