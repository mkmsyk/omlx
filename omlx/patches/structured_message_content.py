# SPDX-License-Identifier: Apache-2.0
"""Preserve model-specific structured text blocks for mlx-lm chat templates."""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _content_block_as_dict(block: Any) -> dict[str, Any] | None:
    if isinstance(block, dict):
        return block
    model_dump = getattr(block, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else None
    dict_method = getattr(block, "dict", None)
    if callable(dict_method):
        dumped = dict_method()
        return dumped if isinstance(dumped, dict) else None
    return None


def translation_block_list_as_dicts(content: Any) -> list[dict[str, Any]] | None:
    """Normalize a TranslateGemma block list, or return None for other content."""
    if not isinstance(content, list) or not content:
        return None

    normalized: list[dict[str, Any]] = []
    for block in content:
        block_dict = _content_block_as_dict(block)
        if block_dict is None:
            return None
        image = block_dict.get("image")
        if not (
            block_dict.get("type") == "text"
            and isinstance(block_dict.get("source_lang_code"), str)
            and isinstance(block_dict.get("target_lang_code"), str)
            and isinstance(block_dict.get("text"), str)
            and (image is None or isinstance(image, str))
        ):
            return None
        normalized.append(
            {
                "type": "text",
                "source_lang_code": block_dict["source_lang_code"],
                "target_lang_code": block_dict["target_lang_code"],
                "text": block_dict["text"],
                "image": image,
            }
        )
    return normalized


def is_translation_block_list(content: Any) -> bool:
    """Return whether content is the TranslateGemma text-block contract."""
    return translation_block_list_as_dicts(content) is not None


# Kept as a private compatibility alias for existing patch tests and callers.
_is_translation_block_list = is_translation_block_list


def _wrap(original: Callable[[list[dict]], Any]) -> Callable[[list[dict]], Any]:
    @functools.wraps(original)
    def process_message_content(messages: list[dict]) -> Any:
        # Keep the mutation and validation semantics of mlx-lm for every ordinary
        # message. Only the explicitly recognised translation contract bypasses
        # its generic list-to-string conversion.
        ordinary = []
        for message in messages:
            if is_translation_block_list(message.get("content")):
                if ordinary:
                    original(ordinary)
                    ordinary = []
                continue
            ordinary.append(message)
        if ordinary:
            original(ordinary)
        return None

    process_message_content._omlx_structured_content = True  # type: ignore[attr-defined]
    return process_message_content


def install_structured_message_content_patch() -> bool:
    """Patch mlx-lm's server helper once, preserving ordinary text behaviour."""
    try:
        import mlx_lm.server as server_module
    except ImportError:
        logger.debug("mlx-lm is unavailable; structured content patch skipped")
        return False
    original = getattr(server_module, "process_message_content", None)
    if original is None or getattr(original, "_omlx_structured_content", False):
        return False
    server_module.process_message_content = _wrap(original)
    logger.info("structured translation content patch installed")
    return True
