"""Gives every token of every response's input context to a source.

Between two responses of the same segment, the tokens that entered are known
exactly from the usage:

    entered(n) = context(n) - context(n-1) - output(n-1)

One item in between: it gets all of them ("measured"). Several: they share
them in proportion to their bytes ("split"). At the first response of a
segment (session start or right after a compaction) the context also holds
the system prompt and the tools, which are not in the transcript: each item
gets its bytes divided by the transcript's own bytes-per-token ratio
("estimated") and the remainder is unattributed.

So in every response the sources plus the unattributed add up to the usage,
and the cost of a source is its tokens summed over every response it stayed
in, until a compaction drops it.
"""
import statistics
from dataclasses import dataclass, field

from .transcript import read

# Measured in October 2026 on 1,831 pairs from 12 projects (mostly Portuguese):
# 2.25 bytes per token. Used only when a transcript has too few pairs of its own.
DEFAULT_BYTES_PER_TOKEN = 2.25
MIN_PAIR_BYTES = 2000
MAX_PAIR_OUTPUT = 400   # the previous output includes thinking that may not come back
MIN_PAIRS = 3

OUTPUT = ("output", "responses")
FLOOR = ("unattributed", "system prompt, tools, overhead")


@dataclass
class Source:
    kind: str
    name: str
    entered: int = 0     # tokens that entered the context, summed over every time it entered
    bytes: int = 0
    chars: int = 0
    opaque: int = 0      # items whose size is not in the text (images, tool references)
    cost: int = 0       # tokens x responses it stayed in
    responses: int = 0
    how: dict = field(default_factory=dict)

    @property
    def estimate_div4(self):
        """What a characters / 4 estimate would say it entered, or None if it has no text."""
        return self.chars / 4 if self.chars and not self.opaque else None


@dataclass
class Report:
    path: str
    responses: list
    compactions: int
    bad_lines: int
    bytes_per_token: float
    ratio_pairs: int
    ratio_is_default: bool
    sources: dict

    @property
    def total(self):
        return sum(r.context for r in self.responses)


def allocate(total, weights):
    """Integers proportional to the weights that add up to total exactly (largest remainder)."""
    s = sum(weights)
    if not weights or s <= 0:
        return [0] * len(weights)
    raw = [total * w / s for w in weights]
    out = [int(x // 1) for x in raw]
    order = sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)
    for i in order[:total - sum(out)]:
        out[i] += 1
    return out


def calibrate(responses):
    """Bytes per token from the steps where only text entered: the median, or the default."""
    ratios = []
    for prev, r in zip(responses, responses[1:]):
        if r.segment_start or not r.entered or any(i.opaque for i in r.entered):
            continue
        delta = r.context - prev.context - prev.output
        size = sum(i.bytes for i in r.entered)
        if size >= MIN_PAIR_BYTES and prev.output < MAX_PAIR_OUTPUT and delta > 0:
            ratios.append(size / delta)
    if len(ratios) >= MIN_PAIRS:
        return statistics.median(ratios), len(ratios), False
    return DEFAULT_BYTES_PER_TOKEN, len(ratios), True


def _estimated(items, budget, ratio):
    """Segment start: bytes / ratio for each item, never more than the budget; returns the rest."""
    known = [i for i in items if not i.opaque]
    est = round(sum(i.bytes for i in known) / ratio)
    share = allocate(min(est, max(budget, 0)), [i.bytes for i in known])
    for i, t in zip(known, share):
        i.tokens, i.how = t, "estimated"
    for i in items:
        if i.opaque:
            i.tokens, i.how = 0, "unknown"
    return budget - sum(share)


def _split(items, delta, ratio):
    """Between two responses: all of delta goes to the items; returns what is left unattributed."""
    if delta <= 0:
        for i in items:
            i.tokens, i.how = 0, "shrank"
        return delta
    if len(items) == 1:
        items[0].tokens, items[0].how = delta, "measured"
        return 0
    known = [i for i in items if not i.opaque]
    opaque = [i for i in items if i.opaque]
    if opaque:
        text = min(round(sum(i.bytes for i in known) / ratio), delta)
        shares = allocate(text, [i.bytes for i in known]) + allocate(delta - text, [1] * len(opaque))
        ordered = known + opaque
    else:
        shares, ordered = allocate(delta, [i.bytes for i in known]), known
    for i, t in zip(ordered, shares):
        i.tokens, i.how = t, "split"
    return delta - sum(shares)


def attribute(transcript):
    ratio, pairs, default = calibrate(transcript.responses)
    sources = {}

    def source(key):
        if key not in sources:
            sources[key] = Source(*key)
        return sources[key]

    prev, ledger = None, {}
    for r in transcript.responses:
        if r.segment_start or prev is None:
            ledger = {}
            rest = _estimated(r.entered, r.context, ratio)
        else:
            ledger = dict(ledger)
            ledger[OUTPUT] = ledger.get(OUTPUT, 0) + prev.output
            source(OUTPUT).entered += prev.output
            rest = _split(r.entered, r.context - prev.context - prev.output, ratio)
        for i in r.entered:
            ledger[i.key] = ledger.get(i.key, 0) + i.tokens
            s = source(i.key)
            s.entered += i.tokens
            s.bytes += i.bytes
            s.chars += i.chars
            s.opaque += i.opaque
            s.how[i.how] = s.how.get(i.how, 0) + 1
        if rest:
            ledger[FLOOR] = ledger.get(FLOOR, 0) + rest
            source(FLOOR).entered += rest
        ledger = {k: v for k, v in ledger.items() if v}
        r.ledger = ledger
        for k, v in ledger.items():
            source(k).cost += v
            source(k).responses += 1
        prev = r
    sources = {k: s for k, s in sources.items() if s.entered or s.cost}
    return Report(transcript.path, transcript.responses, transcript.compactions, transcript.bad_lines,
                  ratio, pairs, default, sources)


def analyze(path):
    """Read one transcript and attribute its context. See `Report`."""
    return attribute(read(path))
