from __future__ import annotations

import types

from omlx.patches.structured_message_content import (
    _is_translation_block_list,
    install_structured_message_content_patch,
    translation_block_list_as_dicts,
)
from omlx.api.openai_models import Message
from omlx.api.utils import extract_text_content


def test_translategemma_block_is_preserved_and_ordinary_fragments_are_flattened(monkeypatch):
    calls = []

    def original(messages):
        calls.extend(messages)
        for message in messages:
            content = message.get("content")
            if isinstance(content, list):
                message["content"] = "".join(
                    fragment["text"] for fragment in content
                    if fragment["type"] == "text"
                )

    server = types.ModuleType("mlx_lm.server")
    server.process_message_content = original
    monkeypatch.setitem(__import__("sys").modules, "mlx_lm.server", server)
    monkeypatch.setitem(__import__("sys").modules, "mlx_lm", types.ModuleType("mlx_lm"))

    structured = [{
        "type": "text",
        "source_lang_code": "ja",
        "target_lang_code": "en",
        "text": "こんにちは",
        "image": None,
    }]
    ordinary = [{"type": "text", "text": "hello"}]
    assert _is_translation_block_list(structured)
    assert not _is_translation_block_list(ordinary)
    assert install_structured_message_content_patch() is True

    messages = [
        {"role": "user", "content": structured},
        {"role": "user", "content": ordinary},
    ]
    server.process_message_content(messages)

    assert messages[0]["content"] == structured
    assert messages[1]["content"] == "hello"


def test_translategemma_fields_survive_message_validation_and_text_extraction():
    structured = [{
        "type": "text",
        "source_lang_code": "ja",
        "target_lang_code": "en",
        "text": "こんにちは",
        "image": None,
    }]
    message = Message(role="user", content=structured)

    normalized = translation_block_list_as_dicts(message.content)
    assert normalized == structured
    extracted = extract_text_content([message], consolidate_system_messages=False)
    assert extracted == [{"role": "user", "content": structured}]


def test_ordinary_content_parts_are_still_flattened():
    message = Message(
        role="user",
        content=[{"type": "text", "text": "Hello"}],
    )

    extracted = extract_text_content([message], consolidate_system_messages=False)
    assert extracted == [{"role": "user", "content": "Hello"}]
