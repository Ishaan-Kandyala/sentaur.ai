import os
import base64
from dotenv import load_dotenv
import google.genai as genai
from google.genai import types

load_dotenv()


class GeminiProvider:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = "gemini-2.5-flash-preview-04-17"

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

    def _vision_contents(self, messages, image_data, image_mime):
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        system_text = "\n".join(m["content"] for m in messages if m["role"] == "system")
        img_bytes = base64.b64decode(image_data)
        img_part = types.Part.from_bytes(data=img_bytes, mime_type=image_mime or "image/jpeg")
        return [img_part, system_text + "\n\n" + last_user]

    def chat(self, messages, image_data=None, image_mime=None):
        try:
            if image_data:
                contents = self._vision_contents(messages, image_data, image_mime)
            else:
                contents = self._build_prompt(messages)
            response = self.client.models.generate_content(model=self.model, contents=contents)
            return response.text
        except Exception as e:
            print("Gemini failed:", e)
            return None

    def stream_chat(self, messages, image_data=None, image_mime=None):
        try:
            if image_data:
                contents = self._vision_contents(messages, image_data, image_mime)
            else:
                contents = self._build_prompt(messages)
            for chunk in self.client.models.generate_content_stream(model=self.model, contents=contents):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            print("Gemini stream failed:", e)
            return
