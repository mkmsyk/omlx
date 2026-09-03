# SPDX-License-Identifier: Apache-2.0
"""Literal think-tag guard: a ``</think>`` the model spells out is not a boundary.

Observed failure (Gemma 4 31B, 2026-09-03): the prompt discussed the
"``</think>`` closes on the first token" accident, so the model quoted the
tag inside its thought block. The text-based thinking parser closed the
reasoning block there and returned the rest of the reasoning as content.
"""

from __future__ import annotations

from omlx.adapter.gemma4 import Gemma4OutputParserSession
from omlx.api.thinking import (
    LITERAL_TAG_GUARD,
    LiteralThinkTagGuard,
    ThinkingParser,
    extract_thinking,
    guard_literal_think_tags,
    guard_literal_think_tags_by_token_ids,
    unguard_literal_think_tags,
)

GUARD = LITERAL_TAG_GUARD


class _FakeDetokenizer:
    def __init__(self, decode_one):
        self._decode_one = decode_one
        self.last_segment = ""

    def reset(self):
        self.last_segment = ""

    def add_token(self, token_id: int):
        self.last_segment = self._decode_one(token_id)

    def finalize(self):
        self.last_segment = ""


class _MapTokenizer:
    """Token-id → text map with the minimal tokenizer surface the code uses."""

    def __init__(self, token_map: dict[int, str]):
        self._token_map = token_map

    @property
    def detokenizer(self):
        return _FakeDetokenizer(lambda token_id: self._token_map[token_id])

    def decode(self, token_ids, skip_special_tokens: bool = True):
        return "".join(self._token_map[token_id] for token_id in token_ids)


def _drive_gemma4(token_map: dict[int, str], token_ids: list[int]) -> tuple[str, str]:
    session = Gemma4OutputParserSession(_MapTokenizer(token_map))
    stream: list[str] = []
    visible: list[str] = []
    for token_id in token_ids:
        result = session.process_token(token_id)
        stream.append(result.stream_text)
        visible.append(result.visible_text)
    final = session.finalize()
    stream.append(final.stream_text)
    visible.append(final.visible_text)
    return "".join(stream), "".join(visible)


def _stream_parse(chunks: list[str]) -> tuple[str, str, ThinkingParser]:
    parser = ThinkingParser()
    thinking: list[str] = []
    content: list[str] = []
    for chunk in chunks:
        t, c = parser.feed(chunk)
        thinking.append(t)
        content.append(c)
    t, c = parser.finish()
    thinking.append(t)
    content.append(c)
    # The streaming parser keeps the newline after ``<think>``; the API
    # layer strips it, so compare stripped text here as well.
    return "".join(thinking).strip(), "".join(content).strip(), parser


# ---------------------------------------------------------------------------
# Guard helpers
# ---------------------------------------------------------------------------


class TestGuardHelpers:
    def test_guard_and_unguard_roundtrip(self):
        text = "quote </think> and <think> and <mm:think> here"
        guarded = guard_literal_think_tags(text)
        assert "</think>" not in guarded
        assert "<think>" not in guarded
        assert "<mm:think>" not in guarded
        assert guarded.count(GUARD) == 3
        assert unguard_literal_think_tags(guarded) == text

    def test_guard_leaves_plain_text_untouched(self):
        assert guard_literal_think_tags("no tags <b>here</b>") == "no tags <b>here</b>"
        assert unguard_literal_think_tags("no guard") == "no guard"

    def test_streaming_guard_across_token_splits(self):
        guard = LiteralThinkTagGuard()
        out = guard.feed("quote ")
        assert out == "quote "
        assert guard.feed("</") == ""  # held: could still become a tag
        assert guard.feed("think") == ""
        out = guard.feed(">")
        assert out == "</think" + GUARD + ">"
        assert guard.guarded_count == 1
        assert guard.flush() == ""

    def test_streaming_guard_releases_non_tag_partial(self):
        guard = LiteralThinkTagGuard()
        assert guard.feed("a <") == "a "
        assert guard.feed("b>") == "<b>"
        assert not guard.pending

    def test_streaming_guard_flush_returns_held_partial(self):
        guard = LiteralThinkTagGuard()
        assert guard.feed("tail </think") == "tail "
        assert guard.pending
        assert guard.flush() == "</think"
        assert not guard.pending

    def test_token_id_guard_keeps_real_marker(self):
        token_map = {
            1: "Let me quote ",
            2: "</",
            3: "think",
            4: ">",
            5: " then finish",
            99: "</think>",  # the model's real close-think token
            6: "Answer",
        }
        tokenizer = _MapTokenizer(token_map)
        ids = [1, 2, 3, 4, 5, 99, 6]
        text = tokenizer.decode(ids)
        guarded = guard_literal_think_tags_by_token_ids(tokenizer, ids, text, [99])
        assert guarded == (
            "Let me quote </think" + GUARD + "> then finish</think>Answer"
        )
        thinking, content = extract_thinking("<think>\n" + guarded)
        assert thinking == "Let me quote </think> then finish"
        assert content == "Answer"

    def test_token_id_guard_without_marker_token_guards_everything(self):
        token_map = {1: "see ", 2: "</", 3: "think", 4: "> ok"}
        tokenizer = _MapTokenizer(token_map)
        ids = [1, 2, 3, 4]
        text = tokenizer.decode(ids)
        guarded = guard_literal_think_tags_by_token_ids(tokenizer, ids, text, [99])
        assert guarded == "see </think" + GUARD + "> ok"

    def test_token_id_guard_falls_back_when_decode_disagrees(self):
        token_map = {1: "a </think> b", 99: "</think>"}
        tokenizer = _MapTokenizer(token_map)
        ids = [1, 99]
        # Text that the piecewise decode cannot reproduce (e.g. stop-trimmed).
        text = "a </think> b</think> trailing"
        assert (
            guard_literal_think_tags_by_token_ids(tokenizer, ids, text, [99]) == text
        )


# ---------------------------------------------------------------------------
# Non-streaming extraction
# ---------------------------------------------------------------------------


class TestExtractThinkingWithGuard:
    def test_quoted_close_tag_stays_in_reasoning(self):
        raw = (
            "<think>\nThe prompt is about the </think"
            + GUARD
            + "> accident. Plan: write in Japanese.\n</think>\n本文です。"
        )
        thinking, content = extract_thinking(raw)
        assert thinking == "The prompt is about the </think> accident. Plan: write in Japanese."
        assert content == "本文です。"
        assert GUARD not in thinking and GUARD not in content

    def test_quoted_tag_inside_code_span(self):
        raw = (
            "<think>\nUse `</think" + GUARD + ">` literally.\n</think>\nAnswer"
        )
        thinking, content = extract_thinking(raw)
        assert thinking == "Use `</think>` literally."
        assert content == "Answer"

    def test_quoted_open_tag_in_content_does_not_reopen(self):
        raw = "<think>\nplan\n</think>\nThe <think" + GUARD + "> tag opens a block."
        thinking, content = extract_thinking(raw)
        assert thinking == "plan"
        assert content == "The <think> tag opens a block."

    def test_immediate_close_on_first_token(self):
        thinking, content = extract_thinking("<think>\n</think>\nAnswer only")
        assert thinking == ""
        assert content == "Answer only"


# ---------------------------------------------------------------------------
# Streaming parser
# ---------------------------------------------------------------------------


class TestThinkingParserWithGuard:
    def test_quoted_close_tag_split_across_chunks(self):
        chunks = [
            "<think>\nquote ",
            "</think",
            GUARD + ">",
            " more\n</think>\n",
            "本文",
        ]
        thinking, content, parser = _stream_parse(chunks)
        assert thinking == "quote </think> more"
        assert content == "本文"
        assert GUARD not in thinking and GUARD not in content
        assert parser.anomalies == []

    def test_quoted_tag_inside_code_span(self):
        chunks = ["<think>\nuse `</th", "ink" + GUARD + ">`", "\n</think>\nok"]
        thinking, content, _ = _stream_parse(chunks)
        assert thinking == "use `</think>`"
        assert content == "ok"

    def test_immediate_close_on_first_token(self):
        thinking, content, parser = _stream_parse(["<think>\n", "</think>\n", "Answer"])
        assert thinking.strip() == ""
        assert content.strip() == "Answer"
        assert parser.anomalies == []

    def test_unguarded_stray_close_is_reported(self):
        chunks = ["<think>\nplan</think>\nbody ", "</think>", " tail"]
        thinking, content, parser = _stream_parse(chunks)
        assert thinking == "plan"
        assert content == "body  tail"
        assert "stray_close" in parser.anomalies

    def test_reopen_after_close_is_reported(self):
        _, _, parser = _stream_parse(["<think>a</think>b<think>c</think>d"])
        assert "reopen" in parser.anomalies


# ---------------------------------------------------------------------------
# Gemma 4 output parser end to end
# ---------------------------------------------------------------------------


class TestGemma4LiteralTags:
    def test_quoted_close_tag_inside_thought_block(self):
        token_map = {
            1: "<|channel>thought\n",
            2: "The prompt discusses the `",
            3: "</",
            4: "think",
            5: ">` accident",
            6: ". Plan: Japanese only.",
            7: "<channel|>",
            8: "日本語の本文です。",
        }
        stream, visible = _drive_gemma4(token_map, [1, 2, 3, 4, 5, 6, 7, 8])
        assert visible == stream
        # Streamed path
        thinking, content, parser = _stream_parse([stream])
        assert thinking == "The prompt discusses the `</think>` accident. Plan: Japanese only."
        assert content == "日本語の本文です。"
        assert parser.anomalies == []
        # Non-streamed path (request.output_text → extract_thinking)
        thinking, content = extract_thinking(visible)
        assert thinking == "The prompt discusses the `</think>` accident. Plan: Japanese only."
        assert content == "日本語の本文です。"

    def test_quoted_tag_per_token_streaming(self):
        token_map = {
            1: "<|channel>thought\n",
            2: "quote ",
            3: "</",
            4: "think",
            5: ">",
            6: " done",
            7: "<channel|>",
            8: "answer",
        }
        session = Gemma4OutputParserSession(_MapTokenizer(token_map))
        parser = ThinkingParser()
        thinking: list[str] = []
        content: list[str] = []
        for token_id in [1, 2, 3, 4, 5, 6, 7, 8]:
            t, c = parser.feed(session.process_token(token_id).stream_text)
            thinking.append(t)
            content.append(c)
        t, c = parser.feed(session.finalize().stream_text)
        thinking.append(t)
        content.append(c)
        t, c = parser.finish()
        thinking.append(t)
        content.append(c)
        assert "".join(thinking).strip() == "quote </think> done"
        assert "".join(content).strip() == "answer"
        assert parser.anomalies == []

    def test_partial_tag_before_real_close_is_flushed_in_order(self):
        token_map = {
            1: "<|channel>thought\n",
            2: "ends with </think",
            3: "<channel|>",
            4: "answer",
        }
        stream, _ = _drive_gemma4(token_map, [1, 2, 3, 4])
        assert stream == "<think>\nends with </think</think>\nanswer"
        thinking, content, _ = _stream_parse([stream])
        assert thinking == "ends with </think"
        assert content == "answer"

    def test_quoted_open_tag_in_visible_answer(self):
        token_map = {
            1: "<|channel>thought\n",
            2: "plan",
            3: "<channel|>",
            4: "The <think> tag opens a block.",
        }
        stream, _ = _drive_gemma4(token_map, [1, 2, 3, 4])
        thinking, content, parser = _stream_parse([stream])
        assert thinking == "plan"
        assert content == "The <think> tag opens a block."
        assert parser.anomalies == []

    def test_immediate_close_on_first_token(self):
        token_map = {1: "<|channel>thought\n", 2: "<channel|>", 3: "answer"}
        stream, _ = _drive_gemma4(token_map, [1, 2, 3])
        thinking, content = extract_thinking(stream)
        assert thinking == ""
        assert content == "answer"

    def test_process_text_path(self):
        session = Gemma4OutputParserSession(_MapTokenizer({}))
        out = session.process_text(
            "<|channel>thought\nsee </think> here<channel|>answer"
        ).visible_text
        out += session.finalize().visible_text
        thinking, content = extract_thinking(out)
        assert thinking == "see </think> here"
        assert content == "answer"

    def test_held_partial_is_released_at_finalize(self):
        token_map = {1: "<|channel>thought\n", 2: "x", 3: "<channel|>", 4: "trail </think"}
        stream, _ = _drive_gemma4(token_map, [1, 2, 3, 4])
        assert stream.endswith("trail </think")
        thinking, content = extract_thinking(stream)
        assert thinking == "x"
        assert content == "trail </think"
