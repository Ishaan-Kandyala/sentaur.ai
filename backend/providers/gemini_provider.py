import os
import base64
from dotenv import load_dotenv
import google.genai as genai
from google.genai import types

load_dotenv()


class GeminiProvider:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.models = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]

    def _build_prompt(self, messages):
        prompt = ""
        for m in messages:
            role = m["role"]
            content = m["content"]
            if role == "system":
                prompt += f"System: {content}\n"
            elif role == "user":
                prompt += f"User: {content}\n"
            elif role == "assistant":
                prompt += f"Assistant: {content}\n"
        return prompt

    def _vision_contents(self, messages, images):
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        system_text = "\n".join(m["content"] for m in messages if m["role"] == "system")
        parts = []
        for img in images:
            img_bytes = base64.b64decode(img["data"])
            parts.append(types.Part.from_bytes(data=img_bytes, mime_type=img.get("mime", "image/jpeg")))
        parts.append(system_text + "\n\n" + last_user)
        return parts

    def chat(self, messages, images=None):
        contents = self._vision_contents(messages, images) if images else self._build_prompt(messages)
        for model in self.models:
            try:
                response = self.client.models.generate_content(model=model, contents=contents)
                return response.text
            except Exception as e:
                print(f"Gemini {model} failed:", e)
        return None

    def stream_chat(self, messages, images=None):
        contents = self._vision_contents(messages, images) if images else self._build_prompt(messages)
        for model in self.models:
            try:
                got_chunk = False
                for chunk in self.client.models.generate_content_stream(model=model, contents=contents):
                    if chunk.text:
                        yield chunk.text
                        got_chunk = True
                if got_chunk:
                    return
            except Exception as e:
                print(f"Gemini stream {model} failed:", e)
