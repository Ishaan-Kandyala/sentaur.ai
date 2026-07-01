import os
from openai import OpenAI


class CerebrasProvider:
    def __init__(self):
        api_key = os.getenv("CEREBRAS_API_KEY")
        if not api_key:
            self.client = None
        else:
            self.client = OpenAI(api_key=api_key, base_url="https://api.cerebras.ai/v1")
        self.models = [
            "llama-4-scout-17b-16e-instruct",
            "llama-3.3-70b",
            "llama3.3-70b",
            "llama-3.1-70b",
            "llama3.1-70b",
            "llama-3.1-8b",
            "llama3.1-8b",
        ]

    def chat(self, messages):
        if not self.client:
            return None
        for model in self.models:
            try:
                response = self.client.chat.completions.create(
                    model=model, messages=messages, temperature=0.7, max_tokens=1500
                )
                return response.choices[0].message.content
            except Exception as e:
                print(f"Cerebras {model} failed: {e}")
        return None

    def stream_chat(self, messages):
        if not self.client:
            return
        for model in self.models:
            try:
                got_chunk = False
                stream = self.client.chat.completions.create(
                    model=model, messages=messages, temperature=0.7, max_tokens=1500, stream=True
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                        got_chunk = True
                if got_chunk:
                    return
            except Exception as e:
                print(f"Cerebras stream {model} failed: {e}")
