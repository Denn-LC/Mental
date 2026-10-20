"""Turn a list of attempt records into accuracy and speed numbers.

"accuracy" counts clean answers: correct on the first try with no hints.
"avg_time_ms" is over solved questions only, so skips don't drag it down.
"""


def stats(attempts):
    solved = [a for a in attempts if a["correct"]]
    clean = [a for a in solved if not a["wrong_tries"] and a["hints_used"] == 0]
    return {
        "count": len(attempts),
        "score": len(solved),
        "skipped": sum(1 for a in attempts if a["skipped"]),
        "accuracy": len(clean) / len(attempts) if attempts else 0.0,
        "avg_time_ms": round(sum(a["time_ms"] for a in solved) / len(solved)) if solved else 0,
    }


def group_stats(attempts, key):
    groups = {}
    for a in attempts:
        groups.setdefault(a[key], []).append(a)
    return {name: stats(group) for name, group in groups.items()}


def summarise(attempts):
    slowest = sorted(attempts, key=lambda a: a["time_ms"], reverse=True)[:5]
    return {
        "overall": stats(attempts),
        "by_category": group_stats(attempts, "category"),
        "by_strategy": group_stats(attempts, "strategy"),
        "slowest": [a["question_id"] for a in slowest],
    }
