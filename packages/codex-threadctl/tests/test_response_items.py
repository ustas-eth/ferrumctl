import unittest
import uuid

from codex_threadctl.response_items import agent_message_id


class AgentMessageIdTests(unittest.TestCase):
    def parse(self, item_id):
        prefix, suffix = item_id.split("_", 1)
        self.assertEqual(prefix, "amsg")
        value = uuid.UUID(suffix)
        self.assertEqual(suffix, str(value))
        return value

    def test_new_messages_have_distinct_native_ids(self):
        first, second = agent_message_id(), agent_message_id()
        self.assertEqual(self.parse(first).version, 4)
        self.assertEqual(self.parse(second).version, 4)
        self.assertNotEqual(first, second)

    def test_stable_keys_keep_identity_without_custom_item_syntax(self):
        key = "codex-wakectl:event:job123:1"
        first = agent_message_id(key)
        self.assertEqual(self.parse(first).version, 5)
        self.assertEqual(first, agent_message_id(key))
        self.assertEqual(first, f"amsg_{uuid.uuid5(uuid.NAMESPACE_URL, key)}")
        self.assertNotEqual(first, agent_message_id("codex-wakectl:event:job123:2"))
        self.assertNotEqual(first, agent_message_id("codex-wakectl:event:job456:1"))
