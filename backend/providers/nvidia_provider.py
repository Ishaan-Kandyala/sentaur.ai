import os
from openai import OpenAI, AuthenticationError


class NvidiaProvider:
    def __init__(self):
        api_key = os.getenv("NVIDIA_API_KEY")
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://integrate.api.nvidia.com/v1",
        ) if api_key else None
        self.model = "meta/llama-3.3-70b-instruct"

    def chat(self, messages):
        if not self.client:
            return None
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=0.7, max_tokens=1500
            )
            return response.choices[0].message.content
        except AuthenticationError:
            print("NVIDIA NIM: invalid API key — disabling")
            self.client = None
            return None
        except Exception as e:
            print(f"NVIDIA NIM failed: {e}")
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
        except AuthenticationError:
            print("NVIDIA NIM: invalid API key — disabling")
            self.client = None
        except Exception as e:
            print(f"NVIDIA NIM stream failed: {e}")
