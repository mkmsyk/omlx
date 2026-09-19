# SPDX-License-Identifier: Apache-2.0
"""Preserve model-specific structured text blocks for mlx-lm chat templates."""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _is_translation_block_list(content: Any) -> bool:
    """Return whether content is the TranslateGemma text-block contract."""
    return (
        isinstance(content, list)
        and bool(content)
        and all(
            isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("source_lang_code"), str)
            and isinstance(block.get("target_lang_code"), str)
            and isinstance(block.get("text"), str)
            for block in content
        )
    )


def _wrap(original: Callable[[list[dict]], Any]) -> Callable[[list[dict]], Any]:
    @functools.wraps(original)
    def process_message_content(messages: list[dict]) -> Any:
        # Keep the mutation and validation semantics of mlx-lm for every ordinary
        # message. Only the explicitly recognised translation contract bypasses
        # its generic list-to-string conversion.
        ordinary = []
        for message in messages:
            if _is_translation_block_list(message.get("content")):
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
