from typing import Union, Optional, List, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
import chardet
import sys
import json
import locale
import os
import base64
import mimetypes
import requests

from .log_writer import logger
from . import config


def _create_client(provider: str, api_key: str, base_url: str, model_name: str):
    provider = provider.lower()
    if provider == "anthropic":
        return ChatAnthropic(api_key=api_key, model_name=model_name, max_tokens=10000)
    if provider == "google":
        return _GoogleGenerativeAIClient(
            google_api_key=api_key,
            model=model_name,
            max_output_tokens=10000,
        )
    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        max_tokens=10000,
        default_headers={
            "HTTP-Referer": "https://cynia.dev",
            "X-Title": "CyniaAI",
        },
    )


def _image_to_data_url(path: str) -> str:
    """Return the data URL for an image file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"The file at path '{path}' does not exist.")
    if not os.access(path, os.R_OK):
        raise PermissionError(f"The file at path '{path}' is not readable.")
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


class _GoogleGenerativeAIResponse:
    """Lightweight response wrapper mimicking LangChain's .content attribute."""

    def __init__(self, content: str) -> None:
        self.content = content


class _GoogleGenerativeAIClient:
    """Minimal Google Gemini chat client without the LangChain dependency."""

    API_ROOT = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        google_api_key: str,
        model: str,
        max_output_tokens: int = 10000,
    ) -> None:
        self.api_key = google_api_key
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.session = requests.Session()

    def invoke(self, messages: List[Union[HumanMessage, SystemMessage, AIMessage]]):
        payload = self._build_payload(messages)
        url = f"{self.API_ROOT}/models/{self.model}:generateContent"
        logger(f"google invoke: payload {payload}")
        try:
            response = self.session.post(
                url,
                params={"key": self.api_key},
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger(f"google invoke: transport error {exc}")
            raise Exception(
                "Failed to connect to Google Gemini. Check your API key and network."
            ) from exc

        data = response.json()
        logger(f"google invoke: raw response {data}")
        if "error" in data:
            message = data["error"].get("message", "Unknown Google Gemini error")
            raise Exception(f"Google Gemini error: {message}")

        try:
            text = self._extract_text(data)
        except Exception as exc:
            raise Exception(
                "Google Gemini response was missing text. Enable verbose logging for details."
            ) from exc

        return _GoogleGenerativeAIResponse(text)

    def _build_payload(
        self, messages: List[Union[HumanMessage, SystemMessage, AIMessage]]
    ) -> dict:
        contents: List[dict] = []
        system_instruction: Optional[dict] = None

        for message in messages:
            if isinstance(message, SystemMessage):
                if system_instruction is None:
                    system_instruction = {
                        "role": "system",
                        "parts": self._to_parts(message.content),
                    }
                    continue
                # Subsequent system messages are treated as normal user text.
                role = "user"
            elif isinstance(message, AIMessage):
                role = "model"
            else:
                role = "user"

            contents.append({"role": role, "parts": self._to_parts(message.content)})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": self.max_output_tokens,
            },
        }
        if system_instruction:
            payload["system_instruction"] = system_instruction
        return payload

    def _to_parts(self, content) -> list[dict]:
        if isinstance(content, str):
            structured = self._try_parse_structured_content(content)
            if structured is not None:
                return self._structured_to_parts(structured)
            return [{"text": content}]
        if isinstance(content, list):
            return self._structured_to_parts(content)
        if isinstance(content, dict):
            return self._structured_to_parts([content])
        return [{"text": str(content)}]

    def _try_parse_structured_content(self, content: str):
        try:
            parsed = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            return None
        if isinstance(parsed, (list, dict)):
            return parsed
        return None

    def _structured_to_parts(self, payload) -> list[dict]:
        items = payload if isinstance(payload, list) else [payload]
        parts: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                parts.append({"text": str(item)})
                continue
            part_type = item.get("type", "text")
            if part_type == "text":
                parts.append({"text": item.get("text", "")})
            elif part_type == "image_url":
                image_part = self._image_part_from_url(item.get("image_url", {}))
                if image_part:
                    parts.append(image_part)
            elif part_type == "input_text":
                parts.append({"text": item.get("text", "")})
            else:
                parts.append({"text": json.dumps(item)})
        return parts or [{"text": ""}]

    def _image_part_from_url(self, payload: dict) -> Optional[dict]:
        url = payload.get("url") if isinstance(payload, dict) else None
        if not url:
            return None
        if url.startswith("data:"):
            try:
                header, b64_data = url.split(",", 1)
            except ValueError:
                return None
            mime = "image/png"
            if ";base64" in header:
                mime = header.split("data:", 1)[-1].split(";base64", 1)[0] or mime
            return {
                "inline_data": {
                    "mime_type": mime,
                    "data": b64_data,
                }
            }
        # Fallback to remote URI reference. Gemini expects Google storage URIs but
        # allowing HTTPS keeps parity with the OpenAI format users already employ.
        return {"file_data": {"file_uri": url}}

    def _extract_text(self, data: dict) -> str:
        candidates = data.get("candidates") or []
        texts: list[str] = []
        for candidate in candidates:
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                if "text" in part:
                    texts.append(part["text"])
        if not texts:
            raise ValueError("No text parts in Gemini response.")
        return "".join(texts)


def initialize() -> None:
    """
    Initializes the software.

    This function logs the software launch and platform information.

    Args:
        None

    Returns:
        None
    """
    try:
        locale.setlocale(locale.LC_ALL, "en_US.UTF-8")
    except locale.Error:
        logger("Locale en_US.UTF-8 not available, using default locale.")
    logger(f"Launch. Platform {sys.platform}")


class LLM:
    """Helper class for interacting with the configured LLM provider."""

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        self.provider = (provider or getattr(config, "LLM_PROVIDER", "openai")).lower()
        self.api_key = api_key or config.API_KEY
        self.base_url = base_url or config.BASE_URL
        self.model_name = model_name or config.GENERATION_MODEL

        self.client = _create_client(
            self.provider, self.api_key, self.base_url, self.model_name
        )
        logger(
            f"Initialized the {self.provider} LLM client with model {self.model_name}."
        )

    def create_conversation(self, system_prompt: str) -> "Conversation":
        """Return a :class:`Conversation` object using this LLM."""

        return Conversation(self, system_prompt)

    def _get_client(self, model_name: Optional[str] = None):
        if model_name and model_name != self.model_name:
            return _create_client(
                self.provider, self.api_key, self.base_url, model_name
            )
        return self.client

    def ask(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> str:
        """Single-turn conversation returning the assistant reply as text.

        Args:
            system_prompt: The system prompt for the model.
            user_prompt: The user prompt text.
            image_path: Optional path to an image included with the prompt.
            model_name: Optional model override.
        """

        client = self._get_client(model_name)
        final_model = model_name or self.model_name

        if image_path:
            image_url = _image_to_data_url(image_path)
            user_content = [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
            user_message = HumanMessage(content=user_content)
        else:
            user_message = HumanMessage(content=user_prompt)

        if final_model in ["o1-preview", "o1-mini"]:
            messages = [
                HumanMessage(content=system_prompt),
                user_message,
            ]
        else:
            messages = [
                SystemMessage(content=system_prompt),
                user_message,
            ]

        logger(f"ask: system {system_prompt}")
        logger(f"ask: user {user_prompt}")

        try:
            response = client.invoke(messages)
        except Exception as e:
            logger(f"ask: invoke error {e}")
            if "connect" in str(e).lower():
                raise Exception(
                    "Failed to connect to your LLM provider. Please check your configuration (make sure the BASE_URL ends with /v1) and internet connection."
                )
            if "api key" in str(e).lower():
                raise Exception(
                    "Your API key is invalid. Please check your configuration."
                )
            raise

        logger(f"ask: response {response}")

        if "Too many requests" in str(response):
            logger("Too many requests. Please try again later.")
            raise Exception(
                "Your LLM provider has rate limited you. Please try again later."
            )

        try:
            assistant_reply = response.content
            logger(f"ask: extracted reply {assistant_reply}")
        except Exception as e:
            logger(f"ask: error extracting reply {e}")
            raise Exception(
                "Your LLM didn't return a valid response. Check if the API provider supports OpenAI response format."
            )

        return assistant_reply

    def _conversation(
        self, messages: List[dict], model_name: Optional[str] = None
    ) -> str:
        """Internal helper for multi-turn conversation using a history list."""

        client = self._get_client(model_name)
        final_model = model_name or self.model_name

        langchain_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                if final_model in ["o1-preview", "o1-mini"]:
                    langchain_messages.append(HumanMessage(content=content))
                else:
                    langchain_messages.append(SystemMessage(content=content))
            elif role == "assistant":
                langchain_messages.append(AIMessage(content=content))
            else:
                langchain_messages.append(HumanMessage(content=content))

        logger(f"conversation: messages {messages}")

        try:
            response = client.invoke(langchain_messages)
        except Exception as e:
            logger(f"conversation: invoke error {e}")
            raise

        logger(f"conversation: response {response}")

        try:
            assistant_reply = response.content
            logger(f"conversation: extracted reply {assistant_reply}")
        except Exception as e:
            logger(f"conversation: error extracting reply {e}")
            raise Exception(
                "Your LLM didn't return a valid response. Check if the API provider supports OpenAI response format."
            )

        return assistant_reply


class Conversation:
    """Manage a conversation with message history."""

    def __init__(self, llm: LLM, system_prompt: str) -> None:
        self.llm = llm
        self.messages: list[dict] = [
            {"role": "system", "content": system_prompt}
        ]

    def send(self, user_prompt: str, model_name: Optional[str] = None) -> str:
        """Append a user message, get the assistant reply and store it."""

        self.messages.append({"role": "user", "content": user_prompt})
        reply = self.llm._conversation(self.messages, model_name)
        self.messages.append({"role": "assistant", "content": reply})
        return reply

    @property
    def history(self) -> list[dict]:
        """Return the full conversation history."""

        return self.messages


def askgpt(
    system_prompt: str,
    user_prompt: str,
    model_name: str,
    image_path: Optional[str] = None,
) -> str:
    """Backward compatible helper calling :class:`LLM`."""

    llm = LLM(model_name=model_name)
    return llm.ask(system_prompt, user_prompt, image_path=image_path)


def mixed_decode(text: str) -> str:
    """
    Decode a mixed text containing both normal text and a byte sequence.

    Args:
        text (str): The mixed text to be decoded.

    Returns:
        str: The decoded text, where the byte sequence has been converted to its corresponding characters.

    """
    # Split the normal text and the byte sequence
    # Assuming the byte sequence is everything after the last colon and space ": "
    try:
        normal_text, byte_text = text.rsplit(": ", 1)
    except (TypeError, ValueError):
        # The text only contains normal text
        return text

    # Convert the byte sequence to actual bytes
    byte_sequence = byte_text.encode(
        "latin1"
    )  # latin1 encoding maps byte values directly to unicode code points

    # Detect the encoding of the byte sequence
    detected_encoding = chardet.detect(byte_sequence)
    encoding = detected_encoding["encoding"]

    # Decode the byte sequence
    decoded_text = byte_sequence.decode(encoding)

    # Combine the normal text with the decoded byte sequence
    final_text = normal_text + ": " + decoded_text
    return final_text


if __name__ == "__main__":
    print("This script is not meant to be run directly. Please run console.py instead.")
