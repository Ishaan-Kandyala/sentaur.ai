import os
from openai import OpenAI, AuthenticationError


class MistralProvider:
    def __init__(self):
        api_key = os.getenv("MISTRAL_API_KEY")
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.mistral.ai/v1",
        ) if api_key else None
        self.models = ["mistral-small-latest", "mistral-small-2503"]

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
                print("Mistral: invalid API key — disabling")
                self.client = None
                return None
            except Exception as e:
                print(f"Mistral {model} failed: {e}")
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
                print("Mistral: invalid API key — disabling")
                self.client = None
                return
            except Exception as e:
                print(f"Mistral stream {model} failed: {e}")
