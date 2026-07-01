import os
from openai import OpenAI, AuthenticationError


class OpenRouterProvider:
    def __init__(self):
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            self.client = None
        else:
            self.client = OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
            )
        self.models = [
            "meta-llama/llama-3.3-70b-instruct:free",
            "qwen/qwen3-235b-a22b:free",
            "microsoft/phi-4:free",
            "mistralai/mistral-small-3.2-24b-instruct:free",
            "tngtech/deepseek-r1t-chimera:free",
            "nousresearch/hermes-3-llama-3.1-405b:free",
            "meta-llama/llama-3.2-3b-instruct:free",
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
            except AuthenticationError:
                print("OpenRouter: invalid API key — disabling provider")
                self.client = None
                return None
            except Exception as e:
                print(f"OpenRouter {model} failed: {e}")
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
                print("OpenRouter: invalid API key — disabling provider")
                self.client = None
                return
            except Exception as e:
                print(f"OpenRouter stream {model} failed: {e}")
