import os
from openai import OpenAI


class WhiteRabbitProvider:
    def __init__(self):
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self.client = OpenAI(api_key="ollama", base_url=base_url)
        self.model = "WhiteRabbitNeo/WhiteRabbitNeo-V3-7B:latest"

    def chat(self, messages):
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=0.7, max_tokens=1500
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"WhiteRabbitNeo failed: {e}")
            return None

    def stream_chat(self, messages):
        try:
            stream = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=0.7, max_tokens=1500, stream=True
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            print(f"WhiteRabbitNeo stream failed: {e}")
            return
