from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
import chardet
import sys
import json
import locale
import os
import base64
import mimetypes

from log_writer import logger
import config


def _create_client(provider: str, api_key: str, base_url: str, model_name: str):
    provider = provider.lower()
    if provider == "anthropic":
        return ChatAnthropic(api_key=api_key, model_name=model_name, max_tokens=10000)
    if provider == "google":
        return ChatGoogleGenerativeAI(
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
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


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
        provider: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
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

    def _get_client(self, model_name: str | None = None):
        if model_name and model_name != self.model_name:
            return _create_client(
                self.provider, self.api_key, self.base_url, model_name
            )
        return self.client

    def ask(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: str | None = None,
        model_name: str | None = None,
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
            user_message = HumanMessage(content=json.dumps(user_content))
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
        self, messages: list[dict], model_name: str | None = None
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

    def send(self, user_prompt: str, model_name: str | None = None) -> str:
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
    image_path: str | None = None,
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
