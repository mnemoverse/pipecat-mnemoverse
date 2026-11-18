#
# Copyright (c) 2026, Mnemoverse
#
# SPDX-License-Identifier: BSD-2-Clause
#

import asyncio
import unittest
from types import SimpleNamespace

from pipecat.processors.aggregators.llm_context import LLMContext

from pipecat_mnemoverse import MnemoverseMemoryService


class _FakeClient:
    """Stand-in for AsyncMnemoClient: read, recent and write, no network."""

    def __init__(self, memories=None, delay=0.0, fail=False):
        self.memories = memories or []
        self.delay = delay
        self.fail = fail
        self.reads = []
        self.writes = []
        self.closed = False

    async def read(self, query, **kwargs):
        self.reads.append((query, kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("network down")
        return SimpleNamespace(items=[SimpleNamespace(content=m) for m in self.memories])

    async def recent(self, **kwargs):
        if self.fail:
            raise RuntimeError("network down")
        return SimpleNamespace(items=[SimpleNamespace(content=m) for m in self.memories])

    async def write(self, content, **kwargs):
        self.writes.append((content, kwargs))
        return SimpleNamespace(stored=True)

    async def close(self):
        self.closed = True


def _service(client, **params):
    return MnemoverseMemoryService(
        user_id="u1", client=client, params=MnemoverseMemoryService.InputParams(**params)
    )


class TestInit(unittest.IsolatedAsyncioTestCase):
    async def test_user_id_sets_domain(self):
        self.assertEqual(_service(_FakeClient()).domain, "user:u1")

    async def test_domain_wins_over_user_id(self):
        svc = MnemoverseMemoryService(user_id="u1", domain="project:x", client=_FakeClient())
        self.assertEqual(svc.domain, "project:x")

    async def test_needs_user_id_or_domain(self):
        with self.assertRaises(ValueError):
            MnemoverseMemoryService(client=_FakeClient())

    async def test_domain_over_the_api_limit_is_refused(self):
        MnemoverseMemoryService(domain="d" * 100, client=_FakeClient())
        with self.assertRaises(ValueError):
            MnemoverseMemoryService(domain="d" * 101, client=_FakeClient())
        with self.assertRaises(ValueError):
            MnemoverseMemoryService(user_id="u" * 96, client=_FakeClient())


class TestCleanup(unittest.IsolatedAsyncioTestCase):
    async def test_a_client_passed_in_stays_open(self):
        client = _FakeClient()
        await _service(client).cleanup()
        self.assertFalse(client.closed)

    async def test_its_own_client_is_closed(self):
        svc = MnemoverseMemoryService(user_id="u1", api_key="mk_live_test")
        own = _FakeClient()
        svc.client = own
        await svc.cleanup()
        self.assertTrue(own.closed)


class TestRecall(unittest.IsolatedAsyncioTestCase):
    async def test_no_memories_injects_nothing(self):
        svc = _service(_FakeClient([]))
        ctx = LLMContext(messages=[{"role": "user", "content": "hello"}])
        await svc._enhance_context_with_memories(ctx, "hello")
        self.assertEqual(ctx.get_messages(), [{"role": "user", "content": "hello"}])

    async def test_memories_are_injected_as_developer_message(self):
        client = _FakeClient(["Prefers morning calls", "Lives in Lisbon"])
        svc = _service(client)
        ctx = LLMContext(messages=[{"role": "user", "content": "hello"}])
        await svc._enhance_context_with_memories(ctx, "hello")
        injected = [m for m in ctx.get_messages() if m.get("role") == "developer"]
        self.assertEqual(len(injected), 1)
        self.assertIn("Prefers morning calls", injected[0]["content"])
        self.assertIn("Lives in Lisbon", injected[0]["content"])
        query, kwargs = client.reads[0]
        self.assertEqual(query, "hello")
        self.assertEqual(kwargs["domain"], "user:u1")
        self.assertEqual(kwargs["top_k"], 5)

    async def test_same_query_is_not_read_twice(self):
        client = _FakeClient(["a fact"])
        svc = _service(client)
        ctx = LLMContext(messages=[{"role": "user", "content": "hello"}])
        await svc._enhance_context_with_memories(ctx, "hello")
        await svc._enhance_context_with_memories(ctx, "hello")
        self.assertEqual(len(client.reads), 1)

    async def test_previous_memory_message_is_replaced(self):
        client = _FakeClient(["first fact"])
        svc = _service(client)
        ctx = LLMContext(messages=[{"role": "user", "content": "one"}])
        await svc._enhance_context_with_memories(ctx, "one")
        client.memories = ["second fact"]
        ctx.add_message({"role": "user", "content": "two"})
        await svc._enhance_context_with_memories(ctx, "two")
        injected = [m for m in ctx.get_messages() if m.get("role") == "developer"]
        self.assertEqual(len(injected), 1)
        self.assertIn("second fact", injected[0]["content"])

    async def test_slow_recall_is_skipped(self):
        svc = _service(_FakeClient(["late fact"], delay=0.5), read_timeout_secs=0.05)
        ctx = LLMContext(messages=[{"role": "user", "content": "hello"}])
        await svc._enhance_context_with_memories(ctx, "hello")
        self.assertEqual(ctx.get_messages(), [{"role": "user", "content": "hello"}])

    async def test_failed_recall_is_skipped(self):
        svc = _service(_FakeClient(fail=True))
        ctx = LLMContext(messages=[{"role": "user", "content": "hello"}])
        await svc._enhance_context_with_memories(ctx, "hello")
        self.assertEqual(ctx.get_messages(), [{"role": "user", "content": "hello"}])

    async def test_long_query_is_cut_to_the_api_limit(self):
        client = _FakeClient()
        svc = _service(client)
        query = "a" * 10 + "b" * 5000
        ctx = LLMContext(messages=[{"role": "user", "content": query}])
        await svc._enhance_context_with_memories(ctx, query)
        self.assertEqual(client.reads[0][0], "b" * 5000)

    async def test_get_memories(self):
        svc = _service(_FakeClient(["a", "b"]))
        self.assertEqual(await svc.get_memories(), ["a", "b"])
        self.assertEqual(await _service(_FakeClient(fail=True)).get_memories(), [])


class TestStore(unittest.IsolatedAsyncioTestCase):
    async def test_only_new_user_messages_are_stored_once(self):
        svc = _service(_FakeClient())
        first = [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "I prefer morning calls"},
            {"role": "assistant", "content": "Noted."},
        ]
        self.assertEqual(svc._new_messages(first), [("user", "I prefer morning calls")])
        second = [*first, {"role": "user", "content": "Call me Ana"}]
        self.assertEqual(svc._new_messages(second), [("user", "Call me Ana")])

    async def test_assistant_messages_when_configured(self):
        svc = _service(_FakeClient(), store_roles=("user", "assistant"))
        msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        self.assertEqual(svc._new_messages(msgs), [("user", "hi"), ("assistant", "hello")])

    async def test_injected_memories_are_not_stored(self):
        client = _FakeClient(["a fact"])
        svc = _service(client, add_as_system_message=False)
        ctx = LLMContext(messages=[{"role": "user", "content": "hello"}])
        await svc._enhance_context_with_memories(ctx, "hello")
        self.assertEqual(svc._new_messages(ctx.get_messages()), [("user", "hello")])

    async def test_store_writes_to_the_domain(self):
        client = _FakeClient()
        svc = _service(client)
        await svc._store_messages([("user", "I prefer morning calls")])
        content, kwargs = client.writes[0]
        self.assertEqual(content, "I prefer morning calls")
        self.assertEqual(kwargs["domain"], "user:u1")
        self.assertEqual(kwargs["metadata"], {"platform": "pipecat", "role": "user"})

    async def test_long_message_is_cut_to_the_api_limit(self):
        client = _FakeClient()
        svc = _service(client)
        await svc._store_messages([("user", "x" * 10000 + "y" * 50)])
        self.assertEqual(client.writes[0][0], "x" * 10000)


if __name__ == "__main__":
    unittest.main()
