import multiprocessing
import unittest
from threading import Event
from time import monotonic
from unittest.mock import patch

from app.services.collection_timeout import collect_with_timeout


def completed_collector(state, emit):
    record = {"url": "https://example.test/article", "body": "initial"}
    emit(record)
    record["body"] = "complete"
    emit(record)


def stalled_collector(state, emit):
    if state.get("partial"):
        emit({"url": "https://example.test/article", "body": "extracted"})
    Event().wait(30)


def failed_collector(state, emit):
    raise ValueError("Search failed")


class CollectionTimeoutTests(unittest.TestCase):
    def test_completed_records_keep_latest_update(self):
        result = collect_with_timeout(__name__, "completed_collector", {}, timeout_s=5)
        self.assertEqual(result, {"raw_sources": [
            {"url": "https://example.test/article", "body": "complete"},
        ]})

    def test_stalled_worker_returns_partial_records_and_is_stopped(self):
        before = {child.pid for child in multiprocessing.active_children()}
        started = monotonic()
        result = collect_with_timeout(__name__, "stalled_collector", {"partial": True}, timeout_s=2)
        self.assertLess(monotonic() - started, 5)
        self.assertEqual(result, {"raw_sources": [
            {"url": "https://example.test/article", "body": "extracted"},
        ]})
        self.assertEqual({child.pid for child in multiprocessing.active_children()}, before)

    def test_timeout_without_records_returns_empty_list(self):
        self.assertEqual(
            collect_with_timeout(__name__, "stalled_collector", {}, timeout_s=2),
            {"raw_sources": []},
        )

    def test_collector_errors_still_propagate(self):
        with self.assertRaisesRegex(ValueError, "Search failed"):
            collect_with_timeout(__name__, "failed_collector", {}, timeout_s=5)

    def test_all_services_use_timeout_wrapper(self):
        from app.services import hacker_news, substack, web_search

        for module, name in (
            (web_search, "collect_web_content"),
            (hacker_news, "collect_hackernews_content"),
            (substack, "collect_substack_content"),
        ):
            with self.subTest(service=name), patch.object(module, "collect_with_timeout") as collect:
                collect.return_value = {"raw_sources": []}
                self.assertEqual(getattr(module, name)({}), {"raw_sources": []})
                collect.assert_called_once_with(module.__name__, "_" + name, {})
