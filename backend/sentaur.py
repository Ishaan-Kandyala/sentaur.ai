import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.providers.gemini_provider import GeminiProvider
from backend.providers.deepseek_provider import DeepSeekProvider
from backend.providers.groq_provider import GroqProvider
from backend.providers.cerebras_provider import CerebrasProvider
from backend.providers.together_provider import TogetherProvider
from backend.providers.local_provider import LocalProvider


class CentaurAI:
    def __init__(self):
        self.providers = [
            GeminiProvider(),
            DeepSeekProvider(),
            TogetherProvider(),
            CerebrasProvider(),
            GroqProvider(),
            LocalProvider()
        ]

        self.history = []

        self.system_prompt = {
            "role": "system",
            "content": (
                "You are Sentaur AI — a calm, highly intelligent assistant with deep expertise in cybersecurity. "
                "You think step-by-step, explain your reasoning clearly, and avoid mistakes. "
                "You never guess; you analyze. "
                "You keep answers concise but insightful. "
                "You maintain context from the conversation."
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


if __name__ == "__main__":
    ai = CentaurAI()
    print("Sentaur AI is online. Type 'quit' to exit.\n")

    while True:
        user_input = input("You: ")
        if user_input.lower() in ["quit", "exit"]:
            print("Goodbye.")
            break

        reply = ai.ask(user_input)
        print("Sentaur:", reply)
