"""Unit test: LLM priority gate admits urgent before normal before low,
and sheds load when the waiting bound is exceeded.
Run: python3 tests/test_priority_queue.py
"""
import asyncio
import sys
sys.path.insert(0, ".")
from mps_server.services.ollama_client import _PriorityGate, Priority, QueueFullError


async def _worker(gate, name, prio, order):
    await gate.acquire(prio)
    order.append(name)


async def main():
    gate = _PriorityGate(slots=1, max_waiting=10)
    order = []
    await gate.acquire(Priority.NORMAL)  # occupy the only slot
    tasks = [
        asyncio.create_task(_worker(gate, "low", Priority.LOW, order)),
        asyncio.create_task(_worker(gate, "urgent", Priority.URGENT, order)),
        asyncio.create_task(_worker(gate, "normal", Priority.NORMAL, order)),
    ]
    await asyncio.sleep(0.1)
    for _ in range(3):
        await gate.release()
        await asyncio.sleep(0.05)
    await asyncio.gather(*tasks)
    assert order == ["urgent", "normal", "low"], f"wrong order: {order}"
    print("PASS: priority ordering", order)

    gate2 = _PriorityGate(slots=1, max_waiting=1)
    await gate2.acquire(Priority.NORMAL)
    asyncio.create_task(_worker(gate2, "parked", Priority.LOW, []))
    await asyncio.sleep(0.05)
    try:
        await gate2.acquire(Priority.NORMAL)
        raise SystemExit("FAIL: did not shed load")
    except QueueFullError:
        print("PASS: load shedding")


if __name__ == "__main__":
    asyncio.run(main())
