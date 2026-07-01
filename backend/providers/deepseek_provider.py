import os
from openai import OpenAI


class DeepSeekProvider:
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com") if api_key else None

    def chat(self, messages):
        if not self.client:
            return None
        try:
            response = self.client.chat.completions.create(model="deepseek-chat", messages=messages)
            return response.choices[0].message.content
        except Exception:
            return None

    def stream_chat(self, messages):
        if not self.client:
            return
        try:
            stream = self.client.chat.completions.create(model="deepseek-chat", messages=messages, stream=True)
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception:
            return
