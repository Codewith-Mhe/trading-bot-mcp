"""
utils/ollama_client.py
=======================
Local LLM inference via Ollama.
No cloud API needed — uses whatever model you have installed locally.

Setup:
  ollama serve          (start Ollama if not running)
  ollama list           (see installed models)
  ollama pull llama3    (or mistral, phi3, gemma, etc.)
  
Then set OLLAMA_MODEL in your .env to your model name.
"""

from __future__ import annotations
import logging
import httpx
from config.settings import settings

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url
        self.model = settings.ollama_model

    async def chat(self, user_prompt: str, system_prompt: str = "") -> str:
        """Send a chat prompt to Ollama and return the response text."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]

    async def analyze_market(self, snapshot_summary: dict) -> str:
        """Generate a plain-English market analysis from a snapshot summary."""
        import json
        system = (
            "You are a DeFi market analyst. Receive structured market data and produce "
            "concise, actionable analysis. Always highlight key risks, opportunities, "
            "and signal strength. Be direct."
        )
        prompt = f"Analyze this DeFi market snapshot:\n\n{json.dumps(snapshot_summary, default=str, indent=2)}"
        return await self.chat(prompt, system)

    async def explain_alert(self, alert_data: dict) -> str:
        """Explain a triggered alert in plain English."""
        import json
        system = (
            "You are a DeFi risk analyst. Given alert data, provide a 2-3 sentence "
            "plain-English explanation of what it means and whether action is needed."
        )
        return await self.chat(json.dumps(alert_data, default=str), system)

    async def answer(self, question: str, context: dict | None = None) -> str:
        """Answer a natural language DeFi question with optional data context."""
        import json
        system = (
            "You are a DeFi research assistant. Answer concisely and accurately. "
            "If uncertain, say so."
        )
        prompt = question
        if context:
            prompt += f"\n\nContext data:\n{json.dumps(context, default=str, indent=2)}"
        return await self.chat(prompt, system)

    async def health_check(self) -> tuple[bool, str]:
        """Check if Ollama is running and the configured model is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                models = [m["name"] for m in resp.json().get("models", [])]
                match = any(self.model in m for m in models)
                if not match:
                    msg = (
                        f"Model '{self.model}' not found locally. "
                        f"Available: {', '.join(models) or 'none'}. "
                        f"Run: ollama pull {self.model}"
                    )
                    logger.warning(msg)
                    return False, msg
                return True, f"Ollama OK — model '{self.model}' ready"
        except Exception as exc:
            msg = f"Ollama unreachable at {self.base_url}: {exc}"
            logger.error(msg)
            return False, msg
