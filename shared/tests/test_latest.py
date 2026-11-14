import queue

from shared.latest import drain_newest, offer_latest


def test_offer_latest_replaces_the_waiting_item_without_blocking():
    q = queue.Queue(maxsize=1)
    offer_latest(q, "old")
    offer_latest(q, "new")
    assert q.get_nowait() == "new" and q.empty()


def test_drain_newest_returns_last_item_or_current():
    q = queue.Queue()
    assert drain_newest(q, "kept") == "kept"
    for item in ("a", "b", "c"):
        q.put(item)
    assert drain_newest(q, None) == "c" and q.empty()
