import os
from groq import Groq


class GroqProvider:
    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.models = [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "gemma2-9b-it",
        ]

    def chat(self, messages):
        for model in self.models:
            try:
                response = self.client.chat.completions.create(
                    model=model, messages=messages, temperature=0.7, max_tokens=1000
                )
                return response.choices[0].message.content
            except Exception as e:
                print(f"Groq {model} failed: {e}")
        return None

    def stream_chat(self, messages):
        for model in self.models:
            try:
                got_chunk = False
                stream = self.client.chat.completions.create(
                    model=model, messages=messages, temperature=0.7, max_tokens=1000, stream=True
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                        got_chunk = True
                if got_chunk:
                    return
            except Exception as e:
                print(f"Groq stream {model} failed: {e}")
