"""Cost and abuse guards for a public deployment.

All limits are counted in requests and tokens rather than dollars, because model prices change and are not
hard-coded here. Set the ANTHROPIC_PRICE_* variables to also get a dollar estimate in the logs.

When the daily token budget is used up the agent is switched off and plans fall back to the rule-based planner;
when the per-address or daily job limits are hit, new plans are refused with 429.
"""

import logging
import math
import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import config

log = logging.getLogger("limits")

HOUR_S = 3600
COST_NEARBY_SEARCH_USD = 0.035  # Places Nearby Search, Enterprise fields (see places.py)


def _number(name, default):
    raw = config.get(name)
    try:
        return type(default)(raw) if raw not in (None, "") else default
    except ValueError:
        log.warning("%s=%r is not a number; using %s", name, raw, default)
        return default


class Guard:
    def __init__(self, per_ip_per_hour=None, plans_per_day=None, daily_tokens=None, clock=time.time):
        self.per_ip_per_hour = _number("PLANS_PER_IP_PER_HOUR", 8) if per_ip_per_hour is None else per_ip_per_hour
        self.plans_per_day = _number("PLANS_PER_DAY", 150) if plans_per_day is None else plans_per_day
        self.daily_tokens = _number("AGENT_DAILY_TOKENS", 2_000_000) if daily_tokens is None else daily_tokens
        self._clock = clock
        self._lock = threading.Lock()
        self._by_ip = defaultdict(deque)
        self._day = None
        self._plans_today = 0
        self._tokens_today = 0

    def _today(self):
        return datetime.fromtimestamp(self._clock(), timezone.utc).date()

    def _roll_day(self):
        today = self._today()
        if today != self._day:
            self._day, self._plans_today, self._tokens_today = today, 0, 0

    def _seconds_until_midnight(self):
        now = datetime.fromtimestamp(self._clock(), timezone.utc)
        return int(86400 - (now.hour * 3600 + now.minute * 60 + now.second))

    def check_new_plan(self, ip):
        """None when a new plan may start, else (message, retry_after_seconds). Does not count the plan."""
        with self._lock:
            self._roll_day()
            now = self._clock()
            recent = self._by_ip[ip]
            while recent and now - recent[0] > HOUR_S:
                recent.popleft()
            if len(recent) >= self.per_ip_per_hour:
                wait = math.ceil(HOUR_S - (now - recent[0]))
                return "You've planned a lot of trips in the last hour. Please try again later.", wait
            if self._plans_today >= self.plans_per_day:
                return "Leeway has reached today's planning limit. Please try again tomorrow.", self._seconds_until_midnight()
            return None

    def count_plan(self, ip):
        with self._lock:
            self._roll_day()
            self._by_ip[ip].append(self._clock())
            self._plans_today += 1

    def agent_allowed(self):
        with self._lock:
            self._roll_day()
            return self._tokens_today < self.daily_tokens

    def record_usage(self, usage):
        used = sum(usage.get(key, 0) for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"))
        with self._lock:
            self._roll_day()
            self._tokens_today += used
            return self._tokens_today

    def snapshot(self):
        with self._lock:
            self._roll_day()
            return {"plans_today": self._plans_today, "tokens_today": self._tokens_today}


guard = Guard()


def total_tokens(usage):
    return sum(usage.get(key, 0) for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"))


def claude_cost_usd(usage):
    """Dollar estimate from ANTHROPIC_PRICE_* (USD per million tokens); None unless all four are set."""
    prices = {
        "input_tokens": config.get("ANTHROPIC_PRICE_INPUT_PER_MTOK"),
        "output_tokens": config.get("ANTHROPIC_PRICE_OUTPUT_PER_MTOK"),
        "cache_read_tokens": config.get("ANTHROPIC_PRICE_CACHE_READ_PER_MTOK"),
        "cache_write_tokens": config.get("ANTHROPIC_PRICE_CACHE_WRITE_PER_MTOK"),
    }
    try:
        return sum(usage.get(key, 0) * float(price) / 1_000_000 for key, price in prices.items())
    except (TypeError, ValueError):
        return None


def cost_line(usage, searches, rounds):
    """One log line per agent run, so cost per plan can be read from the logs."""
    claude = claude_cost_usd(usage)
    places = round(searches * COST_NEARBY_SEARCH_USD, 4)
    parts = [
        f"rounds={rounds}",
        f"tokens={total_tokens(usage)}",
        f"input={usage.get('input_tokens', 0)}",
        f"output={usage.get('output_tokens', 0)}",
        f"cache_read={usage.get('cache_read_tokens', 0)}",
        f"cache_write={usage.get('cache_write_tokens', 0)}",
        f"places_searches={searches}",
        f"places_usd={places}",
    ]
    if claude is not None:
        parts += [f"claude_usd={claude:.4f}", f"total_usd={claude + places:.4f}"]
    return "cost " + " ".join(parts)


# Query strings carry locations and search text; keep them out of the access log.
_PRIVATE_PARAMS = re.compile(r"\b(lat|lon|from_lat|from_lon|to_lat|to_lon|q)=[^&\s\"]*")


class RedactQueryFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(
                _PRIVATE_PARAMS.sub(r"\1=redacted", arg) if isinstance(arg, str) else arg for arg in record.args
            )
        return True
