from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
import chardet
import sys
import json
import locale
import os

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


def askgpt(
        system_prompt: str,
        user_prompt: str,
        model_name: str
    ) -> str:
    """
    Interacts with the LLM using the specified prompts.

    Args:
        system_prompt (str): The system prompt.
        user_prompt (str): The user prompt.
        model_name (str): The model name to use.

    Returns:
        str: The response from the LLM.
    """
    provider = getattr(config, "LLM_PROVIDER", "openai")
    api_key = config.API_KEY
    base_url = config.BASE_URL

    client = _create_client(provider, api_key, base_url, model_name)

    logger(f"Initialized the {provider} LLM client.")

    # Define the messages for the conversation
    if config.GENERATION_MODEL == "o1-preview" or config.GENERATION_MODEL == "o1-mini":
        messages = [
            HumanMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
    else:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

    logger(f"askgpt: system {system_prompt}")
    logger(f"askgpt: user {user_prompt}")

    # Create a chat completion
    try:
        response = client.invoke(messages)
    except Exception as e:
        logger(f"askgpt: invoke error {e}")
        if "connect" in str(e).lower():
            raise Exception(
                "Failed to connect to your LLM provider. Please check your configuration (make sure the BASE_URL ends with /v1) and internet connection. IT IS NOT A BUG OF BUKKITGPT."
            )
        if "api key" in str(e).lower():
            raise Exception(
                "Your API key is invalid. Please check your configuration. IT IS NOT A BUG OF BUKKITGPT."
            )
        raise

    logger(f"askgpt: response {response}")

    if "Too many requests" in str(response):
        logger("Too many requests. Please try again later.")
        raise Exception(
            "Your LLM provider has rate limited you. Please try again later. IT IS NOT A BUG OF BUKKITGPT."
        )

    # Extract the assistant's reply
    try:
        assistant_reply = response.content
        logger(f"askgpt: extracted reply {assistant_reply}")
    except Exception as e:
        logger(f"askgpt: error extracting reply {e}")
        raise Exception(
            "Your LLM didn't return a valid response. Check if the API provider supportes OpenAI response format."
        )

    return assistant_reply


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
