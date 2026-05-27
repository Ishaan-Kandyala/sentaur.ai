import os
from openai import OpenAI


class CerebrasProvider:
    def __init__(self):
        api_key = os.getenv("CEREBRAS_API_KEY")
        if not api_key:
            self.client = None
        else:
            self.client = OpenAI(api_key=api_key, base_url="https://api.cerebras.ai/v1")
        self.model = "llama-3.3-70b"

    def chat(self, messages):
        if not self.client:
            return None
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=0.7, max_tokens=1500
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Cerebras failed: {e}")
            return None

    def stream_chat(self, messages):
        if not self.client:
            return
        try:
            stream = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=0.7, max_tokens=1500, stream=True
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            print(f"Cerebras stream failed: {e}")
            return
