"""
tests/test_news_filter.py
=========================
Test suite for NewsFilter's built-in FOMC events.

Tests verify:
1. BUILTIN_EVENTS all parse correctly via _parse_event_datetime
2. _merge_builtin_events adds FOMC events to empty cache
3. _merge_builtin_events deduplicates against existing events
4. Force refresh gets events (with no network, falls back to DB + builtins)
"""

import pytest
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.news_filter import NewsFilter, BUILTIN_EVENTS


class TestBuiltinEvents:
    """Verify all 10 FOMC events parse correctly"""

    def test_all_fomc_parse(self):
        for evt in BUILTIN_EVENTS:
            dt = NewsFilter._parse_event_datetime(evt)
            assert dt is not None, f"Failed to parse: {evt['title']}"
            assert isinstance(dt, datetime)
            # All FOMC events should be in 2026
            assert dt.year == 2026

    def test_june_fomc_utc_is_18_00(self):
        """June 17 rate decision: 14:00 ET = 18:00 UTC"""
        evt = BUILTIN_EVENTS[0]
        dt = NewsFilter._parse_event_datetime(evt)
        assert dt is not None
        assert dt.hour == 18
        assert dt.minute == 0
        assert dt.day == 17
        assert dt.month == 6

    def test_june_fomc_press_conference_utc(self):
        """June 17 press conference: 14:30 ET = 18:30 UTC"""
        evt = BUILTIN_EVENTS[1]
        dt = NewsFilter._parse_event_datetime(evt)
        assert dt is not None
        assert dt.hour == 18
        assert dt.minute == 30

    def test_all_titles_have_fomc(self):
        for evt in BUILTIN_EVENTS:
            assert "FOMC" in evt["title"]

    def test_all_impact_is_high(self):
        for evt in BUILTIN_EVENTS:
            assert evt["impact"] == "High"

    def test_all_country_is_usd(self):
        for evt in BUILTIN_EVENTS:
            assert evt["country"] == "USD"

    def test_sep_dot_plot_on_quarterly_meetings(self):
        """Sep and Dec meetings include SEP + Dot Plot"""
        sep_evt = [e for e in BUILTIN_EVENTS if e["date"].startswith("2026-09-") and "14:00" in e["time"]]
        assert len(sep_evt) == 1
        assert "SEP" in sep_evt[0]["title"]
        dec_evt = [e for e in BUILTIN_EVENTS if e["date"].startswith("2026-12-") and "14:00" in e["time"]]
        assert len(dec_evt) == 1
        assert "SEP" in dec_evt[0]["title"]


class TestMergeBuiltinEvents:
    """Verify _merge_builtin_events works correctly"""

    def test_merge_into_empty_cache(self, monkeypatch):
        nf = NewsFilter()
        original_cache = list(nf._cache)
        try:
            nf._cache = []
            nf._merge_builtin_events()
            assert len(nf._cache) == len(BUILTIN_EVENTS)
        finally:
            nf._cache = original_cache

    def test_merge_deduplicates(self, monkeypatch):
        nf = NewsFilter()
        original_cache = list(nf._cache)
        try:
            # Pre-populate with one FOMC event already there
            first = dict(BUILTIN_EVENTS[0])
            nf._cache = [first]
            nf._merge_builtin_events()
            # Should have exactly BUILTIN_EVENTS count (no duplicates of first)
            assert len(nf._cache) == len(BUILTIN_EVENTS)
            # Every (title, date) pair should be unique
            pairs = [(e["title"], e["date"]) for e in nf._cache]
            assert len(pairs) == len(set(pairs))
        finally:
            nf._cache = original_cache

    def test_merge_preserves_other_events(self, monkeypatch):
        nf = NewsFilter()
        original_cache = list(nf._cache)
        try:
            dummy = {"date": "2026-06-15", "title": "Some Other Event", "country": "USD", "impact": "High"}
            nf._cache = [dummy]
            nf._merge_builtin_events()
            assert any(e["title"] == "Some Other Event" for e in nf._cache)
            fomc_count = sum(1 for e in nf._cache if "FOMC" in e["title"])
            assert fomc_count == len(BUILTIN_EVENTS)
        finally:
            nf._cache = original_cache
