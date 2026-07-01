import os
from openai import OpenAI, AuthenticationError


class SambanovaProvider:
    def __init__(self):
        api_key = os.getenv("SAMBANOVA_API_KEY")
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.sambanova.ai/v1",
        ) if api_key else None
        self.model = "Meta-Llama-3.3-70B-Instruct"

    def chat(self, messages):
        if not self.client:
            return None
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=0.7, max_tokens=1500
            )
            return response.choices[0].message.content
        except AuthenticationError:
            print("SambaNova: invalid API key — disabling")
            self.client = None
            return None
        except Exception as e:
            print(f"SambaNova failed: {e}")
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
            print("SambaNova: invalid API key — disabling")
            self.client = None
        except Exception as e:
            print(f"SambaNova stream failed: {e}")
