"""Shared strict extraction for compatible chat-completions responses."""

from __future__ import annotations


def extract_chat_candidate(decoded_response: dict[str, object]) -> object:
    choices = decoded_response["choices"]
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("PROVIDER_CANDIDATE_COUNT_INVALID")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("PROVIDER_RESPONSE_SHAPE_INVALID")
    message = choice["message"]
    if not isinstance(message, dict) or "content" not in message:
        raise ValueError("PROVIDER_RESPONSE_SHAPE_INVALID")
    return message["content"]


__all__ = ["extract_chat_candidate"]
