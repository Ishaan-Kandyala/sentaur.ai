import os
from openai import OpenAI


class TogetherProvider:
    def __init__(self):
        api_key = os.getenv("TOGETHER_API_KEY")
        if not api_key:
            self.client = None
        else:
            self.client = OpenAI(api_key=api_key, base_url="https://api.together.xyz/v1")
        self.model = "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo"

    def chat(self, messages):
        if not self.client:
            return None
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=0.7, max_tokens=1500
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Together failed: {e}")
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
            print(f"Together stream failed: {e}")
            return
