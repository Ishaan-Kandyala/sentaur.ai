from backend.providers.groq_provider import GroqProvider
from backend.providers.deepseek_provider import DeepSeekProvider
from backend.providers.gemini_provider import GeminiProvider
from backend.providers.local_provider import LocalProvider

class CentaurAI:
    def __init__(self):
        self.providers = [
            GroqProvider(),
            DeepSeekProvider(),
            GeminiProvider(),
            LocalProvider()
        ]

        self.history = []
        self.system_prompt = {
            "role": "system",
            "content": (
                "You are Sentaur AI — a hybrid intelligence combining logic and intuition. "
                "You are strategic, calm, and insightful. You explain your reasoning clearly."
            )
        }

    def ask(self, user_input):
        self.history.append({"role": "user", "content": user_input})
        messages = [self.system_prompt] + self.history[-20:]

        for provider in self.providers:
            response = provider.chat(messages)
            if response:
                self.history.append({"role": "assistant", "content": response})
                return response

        return "All providers failed — even offline mode."