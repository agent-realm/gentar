"""Agent numbers come out of a transcript; its text never does.

The rule agreed with the first adopter: a Claude Code session transcript is
the whole conversation and can hold a credential verbatim, while the export
store is shared and the dashboard can be a public artifact. So extraction
yields numbers and a closed set of labels only — pinned here by planting a
fake secret everywhere a transcript can carry text and checking it appears
nowhere in what comes out.
"""

import json
import unittest

from gentar.agentstats import extract, model_label, tool_class

SECRET = "sk-ant-FAKE-0123456789-planted"


def line(**kw):
    return json.dumps(kw)


def fixture():
    """A transcript shaped like Claude Code's: streamed assistant blocks
    repeating usage, tool_use / tool_result pairs, and text everywhere."""
    return "\n".join([
        line(type="user", timestamp="2026-09-24T10:00:00Z",
             message={"role": "user", "content": f"export KEY={SECRET}"}),
        line(type="assistant", timestamp="2026-09-24T10:00:01Z", uuid="u1",
             message={"id": "msg_1", "model": "claude-opus-5-5",
                      "usage": {"input_tokens": 100, "output_tokens": 5,
                                "cache_read_input_tokens": 40,
                                "cache_creation_input_tokens": 7},
                      "content": [{"type": "thinking", "thinking": f"the key is {SECRET}"}]}),
        line(type="assistant", timestamp="2026-09-24T10:00:02Z", uuid="u2",
             message={"id": "msg_1", "model": "claude-opus-5-5",
                      "usage": {"input_tokens": 100, "output_tokens": 50,
                                "cache_read_input_tokens": 40,
                                "cache_creation_input_tokens": 7},
                      "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                   "input": {"command": f"echo {SECRET}"}},
                                  {"type": "tool_use", "id": "t2",
                                   "name": f"mcp__{SECRET}__read",
                                   "input": {"q": SECRET}}]}),
        line(type="user", timestamp="2026-09-24T10:00:04Z",
             message={"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1", "content": SECRET},
                 {"type": "tool_result", "tool_use_id": "t2", "is_error": True,
                  "content": f"denied {SECRET}"}]}),
        line(type="assistant", timestamp="2026-09-24T10:00:05Z", uuid="u3",
             message={"id": "msg_2", "model": f"{SECRET} evil model",
                      "usage": {"input_tokens": 200, "output_tokens": 10},
                      "content": [{"type": "text", "text": f"done: {SECRET}"},
                                  {"type": "tool_use", "id": "t3",
                                   "name": f"Custom{SECRET}"}]}),
        "not json at all " + SECRET,
    ])


class ExtractTest(unittest.TestCase):

    def test_no_text_ever_comes_out(self):
        turns, tools, totals = extract([fixture()])
        blob = json.dumps([turns, tools, totals])
        self.assertNotIn(SECRET, blob)
        self.assertNotIn("sk-ant", blob)
        for row in turns:
            for v in row.values():
                self.assertTrue(isinstance(v, (int, bool)) or v in (
                    "claude-opus-5-5", "other"), v)
        for row in tools:
            self.assertIn(row["tool"], ("Bash", "mcp", "other"))

    def test_streamed_blocks_count_once_per_message(self):
        turns, _, totals = extract([fixture()])
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["output_tokens"], 50)      # last block wins
        self.assertEqual(turns[0]["tool_calls"], 2)
        self.assertEqual(totals["input_tokens"], 300)
        self.assertEqual(totals["output_tokens"], 60)
        self.assertEqual(totals["cache_read_tokens"], 40)

    def test_tool_calls_have_durations_and_errors(self):
        _, tools, totals = extract([fixture()])
        by = {t["tool"]: t for t in tools}
        self.assertEqual(by["Bash"]["duration_ms"], 2000)
        self.assertFalse(by["Bash"]["is_error"])
        self.assertTrue(by["mcp"]["is_error"])
        self.assertEqual(by["other"]["duration_ms"], None)    # never answered
        self.assertFalse(by["other"]["completed"])
        self.assertEqual(totals["tool_calls"], 3)
        self.assertEqual(totals["tool_errors"], 1)

    def test_a_suspicious_model_id_becomes_other(self):
        turns, _, _ = extract([fixture()])
        self.assertEqual(turns[1]["model"], "other")

    def test_labels_are_a_closed_set(self):
        self.assertEqual(tool_class("Read"), "Read")
        self.assertEqual(tool_class("mcp__acme-internal__deploy"), "mcp")
        self.assertEqual(tool_class("rm -rf /"), "other")
        self.assertEqual(tool_class(None), "other")
        self.assertEqual(model_label("claude-sonnet-5"), "claude-sonnet-5")
        self.assertEqual(model_label("a" * 80), "other")
        # token-shaped strings are not model ids (agy review)
        self.assertEqual(model_label("9f86d081884c7d659a2feaa0c55ad015"), "other")
        self.assertEqual(model_label("sk-ant-api03-abcdef"), "other")
        self.assertEqual(model_label("glm-5.3"), "glm-5.3")
        self.assertEqual(model_label("deepseek-v4-pro"), "deepseek-v4-pro")

    def test_empty_and_garbage_input_yields_zeroes(self):
        turns, tools, totals = extract(["", "garbage\n{}\n[1,2]"])
        self.assertEqual((turns, tools), ([], []))
        self.assertEqual(totals["turns"], 0)

    def test_sessions_are_counted(self):
        _, _, totals = extract([fixture(), fixture()])
        self.assertEqual(totals["sessions"], 2)
        self.assertEqual(totals["turns"], 4)


if __name__ == "__main__":
    unittest.main()
