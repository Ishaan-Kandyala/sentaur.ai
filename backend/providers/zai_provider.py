import os
from openai import OpenAI, AuthenticationError


class ZaiProvider:
    def __init__(self):
        api_key = os.getenv("ZAI_API_KEY")
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.z.ai/api/paas/v4/",
        ) if api_key else None
        self.models = ["glm-4.7-flash", "glm-4.5-air"]

    def chat(self, messages):
        if not self.client:
            return None
        for model in self.models:
            try:
                response = self.client.chat.completions.create(
                    model=model, messages=messages, temperature=0.7, max_tokens=1500
                )
                return response.choices[0].message.content
            except AuthenticationError:
                print("Z.ai: invalid API key — disabling")
                self.client = None
                return None
            except Exception as e:
                print(f"Z.ai {model} failed: {e}")
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
            except AuthenticationError:
                print("Z.ai: invalid API key — disabling")
                self.client = None
                return
            except Exception as e:
                print(f"Z.ai stream {model} failed: {e}")
