import asyncio
import json

from app import hub


class FakeWS:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def accept(self):
        pass

    async def send_text(self, text):
        if self.fail:
            raise RuntimeError("closed")
        self.sent.append(json.loads(text))


def test_broadcast_sends_and_drops_dead_clients():
    async def scenario():
        ok, dead = FakeWS(), FakeWS(fail=True)
        await hub.connect(ok)
        await hub.connect(dead)
        await hub.broadcast("event", {"path": "/고객"})
        assert ok.sent == [{"type": "event", "data": {"path": "/고객"}}]
        assert dead not in hub._clients
        hub.disconnect(ok)
        assert not hub.has_clients()

    asyncio.run(scenario())
