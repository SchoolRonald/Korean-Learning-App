from app.memory import in_scope, word_stats

LIST_SIZE = 10


def summary(conn, max_lesson, now=None, topic_ids=None):
    all_words = in_scope(word_stats(conn, max_lesson, now), topic_ids)
    words = [w for w in all_words if w["learned"]]
    practiced = [w for w in words if w["attempts"]]
    weakest = sorted(
        (w for w in practiced if w["fails"]), key=lambda w: (-w["fail_rate"], -w["fails"])
    )[:LIST_SIZE]
    stale = sorted(practiced, key=lambda w: -w["days_since"])[:LIST_SIZE]
    return {
        "total": len(all_words),
        "learned": len(words),
        "practiced": len(practiced),
        "avg_confidence": sum(w["confidence"] for w in words) / len(words) if words else 0.0,
        "weakest": weakest,
        "stale": stale,
        "words": sorted(words, key=lambda w: (w["confidence"], w["lesson"], w["id"])),
    }
