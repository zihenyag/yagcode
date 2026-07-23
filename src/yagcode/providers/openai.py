"""OpenAI Responses adapter candidate extraction."""

from __future__ import annotations


def extract_candidate(decoded_response: dict[str, object]) -> object:
    output = decoded_response["output"]
    if not isinstance(output, list) or len(output) != 1:
        raise ValueError("PROVIDER_CANDIDATE_COUNT_INVALID")
    item = output[0]
    if not isinstance(item, dict):
        raise ValueError("PROVIDER_RESPONSE_SHAPE_INVALID")
    content = item["content"]
    if not isinstance(content, list) or len(content) != 1:
        raise ValueError("PROVIDER_CANDIDATE_COUNT_INVALID")
    content_item = content[0]
    if not isinstance(content_item, dict) or "json" not in content_item:
        raise ValueError("PROVIDER_RESPONSE_SHAPE_INVALID")
    return content_item["json"]


__all__ = ["extract_candidate"]
