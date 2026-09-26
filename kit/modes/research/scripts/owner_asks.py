#!/usr/bin/env python3
"""Owner messages from this project's Claude Code transcripts, for the docs/ASKS.md registry.

Only what the owner typed: no tool results, system inserts or post-compaction summaries.

    python3 scripts/owner_asks.py --new          messages after the "Checked up to" mark in docs/ASKS.md
    python3 scripts/owner_asks.py --since 2026-09-26T12:00
    python3 scripts/owner_asks.py --dump data/owner_asks   write messages.jsonl + messages.md there
    python3 scripts/owner_asks.py --hook         one line for the SessionStart hook (scripts/check_docs.sh):
                                                 how many messages wait for a row; silent when none, never fails

Times are UTC, as in the transcripts. Two numbered series: M for ordinary turns, Q for
messages sent while the agent was working (queued) or starting with a paste; Q used to be
lost by naive readers. Numbers run from the first message of the project, so don't delete
old session transcripts or the numbers shift.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS = Path.home() / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(ROOT))
ASKS = ROOT / "docs/ASKS.md"
MARK_RE = re.compile(r"(?:Checked up to|Сверено по):\s*(\d{4}-\d\d-\d\dT\d\d:\d\d)")

SKIP_PREFIX = ("<", "[Request interrupted", "Caveat:", "This session is being continued")
PASTE_RE = re.compile(r"<pasted_content[^>]*>(.*?)</pasted_content[^>]*>", re.DOTALL)
MARKER_RE = re.compile(r"^<!-- (?:reply|attach) -->\s*")  # desktop app: reply-to-quote, attachment
SECRET_RE = re.compile(
    r"(?i)((?:api[_ -]?key|apikey|token|bearer|password|пароль)\W{0,3}[:=]?\s*)\S{6,}"
    r"|\bsk-[A-Za-z0-9_\-]{12,}"
)  # keys pasted by the owner never reach the output


def text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


def compact_comment(text):
    """An artifact comment: keep the address, the location and the owner's own text."""
    body = re.search(r"=== BEGIN ARTIFACT COMMENT \S+ ===\n(.*?)\n=== END", text, re.DOTALL)
    if not body:
        return text
    url = re.search(r"Artifact: (\S+)", text)
    loc = re.search(r"Location: (.*)", text)
    body = re.sub(r"^> ?", "", body.group(1), flags=re.MULTILINE).strip()
    return f"[artifact comment {url.group(1) if url else '?'} · {loc.group(1).strip() if loc else '?'}]\n{body}"


def owner_messages(path):
    for line in path.open(encoding="utf-8"):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") == "attachment":  # sent while the agent was working
            a = e.get("attachment") or {}
            text = a.get("prompt")
            if (a.get("type") != "queued_command" or (a.get("origin") or {}).get("kind") != "human"
                    or not isinstance(text, str)):
                continue
            text = text.strip()
            if text and (not text.startswith("<") or text.startswith("<pasted_content")):
                yield {"ts": a.get("timestamp") or e.get("timestamp", ""), "session": path.stem[:8],
                       "text": text, "kind": "Q"}
            continue
        if e.get("type") != "user" or e.get("isMeta") or e.get("isCompactSummary") or e.get("isSidechain"):
            continue
        raw = text_of(e.get("message", {}).get("content", "")).strip()
        text = MARKER_RE.sub("", raw)
        if text.startswith("[Artifact comment"):
            text = compact_comment(text)
        kind = "M"
        if text.startswith("<pasted_content") or raw.startswith("<!-- attach -->"):
            kind = "Q"
        elif not text or text.startswith(SKIP_PREFIX):
            continue
        yield {"ts": e.get("timestamp", ""), "session": path.stem[:8], "text": text, "kind": kind}


def load():
    rows = sorted((m for p in TRANSCRIPTS.glob("*.jsonl") for m in owner_messages(p)), key=lambda m: m["ts"])
    seen, num, out = set(), {"M": 0, "Q": 0}, []
    for m in rows:  # a resumed or forked session repeats messages in two transcripts
        key = (m["ts"][:16], m["text"][:200])
        if key in seen:
            continue
        seen.add(key)
        num[m["kind"]] += 1
        m["text"] = SECRET_RE.sub(lambda x: (x.group(1) or "") + "[hidden]", m["text"])
        out.append({"id": f"{m['kind']}{num[m['kind']]:03d}", **m})
    return out


def show(m, limit=1500):
    text = PASTE_RE.sub(lambda x: f"[paste, {len(x.group(1))} chars]", m["text"])
    return f"--- {m['id']} · {m['ts'][:16]} · {m['session']}\n{text[:limit]}\n"


def since_mark():
    mark = MARK_RE.search(ASKS.read_text(encoding="utf-8")) if ASKS.exists() else None
    return mark.group(1) if mark else ""


def hook():
    if not TRANSCRIPTS.is_dir():
        return
    since = since_mark()
    n = sum(1 for m in load() if m["ts"][:16] > since)
    if n:
        text = (f"agentdrop research mode: {n} owner messages since the 'Checked up to' mark in docs/ASKS.md. "
                "Before the pass ends, run `python3 scripts/owner_asks.py --new`, give every research ask a row "
                "(verbatim, mode, ticket, status) and move the mark.")
        print(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--new", action="store_true", help="messages after the mark in docs/ASKS.md")
    ap.add_argument("--since", default="", help="messages from this UTC time on, e.g. 2026-09-26T12:00")
    ap.add_argument("--dump", metavar="DIR", help="write messages.jsonl and messages.md into DIR")
    ap.add_argument("--hook", action="store_true", help="SessionStart hook output (JSON), silent if nothing new")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to a legacy code page
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.hook:
        try:
            hook()
        except Exception:  # noqa: BLE001, S110 — a reminder must never break the session
            pass
        return
    if not TRANSCRIPTS.is_dir():
        raise SystemExit(f"No Claude Code transcripts at {TRANSCRIPTS}; reread the conversation by hand.")
    rows = load()

    since = args.since
    if args.new:
        since = since_mark()
    rows = [m for m in rows if m["ts"][:16] > since] if args.new else [m for m in rows if m["ts"] >= since]

    if args.dump:
        out = Path(args.dump)
        out.mkdir(parents=True, exist_ok=True)
        with (out / "messages.jsonl").open("w", encoding="utf-8") as f:
            f.writelines(json.dumps(m, ensure_ascii=False) + "\n" for m in rows)
        (out / "messages.md").write_text("\n".join(show(m, 10**6) for m in rows), encoding="utf-8")
        print(f"{len(rows)} messages → {out}")
        return
    for m in rows:
        print(show(m))
    tail = "Give each research ask a row in docs/ASKS.md, then move the 'Checked up to' mark."
    print(f"After {since or 'the start'}: {len(rows)} messages. {tail if args.new else ''}".rstrip())


if __name__ == "__main__":
    main()
