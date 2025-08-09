# vless_scanner/core/stats.py
import json
import time
from collections import defaultdict

class StatsCollector:
    """An enhanced class for collecting detailed runtime and performance statistics."""
    def __init__(self):
        self.counters = defaultdict(int)
        self.timings = defaultdict(list)

    def increment(self, key, value=1):
        self.counters[key] += value

    def get_summary(self) -> dict:
        summary = dict(self.counters)
        timing_summary = {}
        for key, durations in self.timings.items():
            if durations:
                timing_summary[key] = {
                    "calls": len(durations),
                    "total_seconds": round(sum(durations), 4),
                    "avg_seconds": round(sum(durations) / len(durations), 4)
                }
        summary['performance_timings'] = timing_summary
        return summary

    def print_summary(self):
        print("\n--- Execution Summary ---")
        print(json.dumps(self.get_summary(), indent=2))
        print("-----------------------")
