#!/usr/bin/env python3
"""agentdrop forum — talk to your agent inside the project docs, from a laptop or a phone.

One local server for every agentdrop project. Each project gets its own section: its docs,
its threads, and an agent that answers from that project's directory.

  agentdrop forum                 run in the foreground, http://127.0.0.1:5290 (this machine only)
  agentdrop forum run --lan       also listen on the home network; phones log in via a key link
  agentdrop forum install         keep it running as a macOS LaunchAgent (with --lan)
  agentdrop forum uninstall | status | url | logs
  agentdrop forum add PATH        list a project that is not under a scanned root

A comment is written straight into the markdown, under the item, as
"> **Owner, 24.09 12:30:** text". A background `claude -p` run (read-only tools) in the
project directory writes the reply under it as "> **Agent, 24.09 12:31:** …". Nothing is
committed: the next working session commits the thread with its own changes.

Settings: ~/.agentdrop/forum.json (author, agent name, language, roots, port, agent command).
Standard library only.
"""
from __future__ import annotations
import argparse, datetime as dt, glob, hashlib, json, os, queue, re, secrets, shutil, socket, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, ".agentdrop")
CONF = os.environ.get("AGENTDROP_FORUM_CONF") or os.path.join(STATE, "forum.json")
TOKEN_FILE = os.path.join(STATE, "forum_token")
LOGFILE = os.path.join(STATE, "forum.log")
LABEL = "com.agentdrop.forum"
PLIST = os.path.join(HOME, "Library", "LaunchAgents", LABEL + ".plist")
MAIN = ["QUESTIONS", "TODO", "STATE", "LOG", "DECISIONS", "CONTEXT", "PITFALLS", "CONVENTIONS", "OPERATIONS"]
TOPICS = {"ru": "## Вопросы агенту", "en": "## Questions for the agent"}
LOCK = threading.Lock()          # one markdown write at a time


def git_name():
    try:
        return subprocess.run(["git", "config", "--global", "user.name"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def config():
    c = {"author": git_name() or "Owner", "agent": "Agent", "lang": "en", "port": 5290,
         "roots": ["~/Projects", "~/code", "~/src"], "projects": [], "answer": True,
         "agent_cmd": ["claude", "-p", "--output-format", "text", "--no-session-persistence",
                       "--permission-mode", "default", "--strict-mcp-config",
                       "--allowedTools", "Read,Grep,Glob,Bash(git log:*),Bash(git show:*),Bash(git diff:*)",
                       "--disallowedTools", "Edit,Write,NotebookEdit,Agent,WebFetch,WebSearch"],
         "timeout": 900}
    try:
        with open(CONF, encoding="utf-8") as f:
            c.update(json.load(f))
    except FileNotFoundError:
        pass
    return c


C = config()
LAN = {"on": False, "token": ""}


# ---------- projects ----------

def is_project(d):
    """An agentdrop project: AGENTS.md with the managed block and the docs/ layout."""
    try:
        with open(os.path.join(d, "AGENTS.md"), encoding="utf-8") as f:
            head = f.read()
    except OSError:
        return False
    return "AGENTDROP" in head and os.path.exists(os.path.join(d, "docs", "STATE.md"))


def projects():
    """id → absolute path. Scanned roots one level deep, plus projects listed by hand."""
    found = []
    for r in C["roots"]:
        r = os.path.expanduser(r)
        for d in sorted(glob.glob(os.path.join(r, "*"))):
            if os.path.isdir(d) and is_project(d):
                found.append(os.path.realpath(d))
    for p in C["projects"]:
        p = os.path.realpath(os.path.expanduser(p))
        if os.path.isdir(p) and p not in found:
            found.append(p)
    out = {}
    for p in found:
        pid, n = os.path.basename(p), 2
        while pid in out:
            pid, n = f"{os.path.basename(p)}-{n}", n + 1
        out[pid] = p
    return out


def docs(root):
    """Doc name → path relative to the project. Only these files can be read or written."""
    out = {n: f"docs/{n}.md" for n in MAIN if os.path.exists(os.path.join(root, f"docs/{n}.md"))}
    for sub in ("specs", "reviews/inbox"):
        for p in sorted(glob.glob(os.path.join(root, "docs", sub, "*.md"))):
            rel = os.path.relpath(p, root)
            out[rel[len("docs/"):-3]] = rel
    return out


# ---------- markdown ----------

ITEM = re.compile(r"^(?:[-*] |\d+\. )")
# "> **Name, 24.09 00:52:** text"; older replies may carry the date without time
HDR = re.compile(r"^(\s*)> \*\*([^*,]+), (\d{1,2}\.\d{2}(?: \d{1,2}:\d{2})?)[^*]*:\*\*\s?(.*)$")


def blocks(lines):
    """Split markdown into blocks: heading, top-level list item (with nested lines),
    paragraph, table, code. Items and paragraphs can carry a thread."""
    out, i, n = [], 0, len(lines)
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1; continue
        start = i
        if ln.startswith("```"):
            i += 1
            while i < n and not lines[i].startswith("```"):
                i += 1
            i = min(i + 1, n); kind = "code"
        elif ln.startswith("#"):
            i += 1; kind = "heading"
        elif ln.startswith("|"):
            while i < n and lines[i].startswith("|"):
                i += 1
            kind = "table"
        elif ITEM.match(ln):
            i += 1
            while i < n:
                cur = lines[i]
                if cur.strip() == "":
                    # a blank line stays inside the item if indented text follows
                    j = i
                    while j < n and not lines[j].strip():
                        j += 1
                    if j < n and lines[j][:1] in (" ", "\t"):
                        i = j; continue
                    break
                if ITEM.match(cur) or cur.startswith("#") or cur.startswith("|") or cur.startswith("```"):
                    break
                i += 1
            kind = "item"
        else:
            i += 1
            while i < n and lines[i].strip() and not (ITEM.match(lines[i]) or lines[i].startswith(("#", "|", "```"))):
                i += 1
            kind = "para"
        text = "".join(lines[start:i])
        out.append({"start": start, "end": i, "kind": kind, "md": text,
                    "hash": hashlib.sha1(text.encode()).hexdigest()[:12]})
    return out


def thread(md):
    """Item body and the thread under it: [{author, stamp, head, md}]."""
    lines = md.splitlines()
    k = next((i for i, ln in enumerate(lines) if i > 0 and HDR.match(ln)), None)
    if k is None:
        return md, []
    msgs, indent = [], len(HDR.match(lines[k]).group(1))
    for ln in lines[k:]:
        m = HDR.match(ln)
        if m:
            msgs.append({"author": m.group(2).strip(), "stamp": m.group(3), "head": ln.strip(), "lines": [m.group(4)]})
            continue
        s = ln[indent:] if ln[:indent].strip() == "" else ln.lstrip()
        if s.startswith(">"):
            s = s[2:] if s.startswith("> ") else s[1:]
        msgs[-1]["lines"].append(s)
    for m in msgs:
        m["md"] = "\n".join(m.pop("lines")).strip("\n")
    return "\n".join(lines[:k]).rstrip() + "\n", msgs


def tid(name, body):
    """Stable thread id: doc + first line of the item."""
    first = body.strip().splitlines()[0] if body.strip() else ""
    return hashlib.sha1(f"{name}\n{first}".encode()).hexdigest()[:10]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines(keepends=True)


def write(path, lines):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.replace(tmp, path)


def stamp():
    return dt.datetime.now().strftime("%d.%m %H:%M")


def quote(author, text, indent):
    """Message → quote lines. Blank line → ">", line break inside a paragraph → two spaces."""
    body = [t.rstrip() for t in text.strip("\n").splitlines()] or [""]
    body[0] = f"**{author}, {stamp()}:** {body[0]}"
    out = []
    for k, t in enumerate(body):
        nxt = body[k + 1] if k + 1 < len(body) else None
        brk = "  " if t and nxt and not t.startswith(("```", "- ", "* ")) and not nxt.startswith(("```", "- ", "* ", "|")) else ""
        out.append(f"{indent}> {t}{brk}\n" if t else f"{indent}>\n")
    return out


def append_to_block(path, find, text, author):
    """Append a message to the end of an item's thread; find(block) picks the item.
    Returns the new message's header line, or None if the item is gone."""
    with LOCK:
        lines = read(path)
        b = next((x for x in blocks(lines) if find(x)), None)
        if b is None:
            return None
        m = next((HDR.match(ln) for ln in b["md"].splitlines() if HDR.match(ln)), None)
        indent = m.group(1) if m else ("  " if b["kind"] == "item" else "")
        new = quote(author, text, indent)
        if m:  # messages in a thread are separated by an empty quote line
            new.insert(0, f"{indent}>\n")
        end = b["end"]
        if end > 0 and not lines[end - 1].endswith("\n"):
            lines[end - 1] += "\n"
        lines[end:end] = new
        write(path, lines)
        return new[1 if m else 0].strip()


def new_topic(root, text):
    """New topic: an item at the top of the 'Questions for the agent' section of QUESTIONS."""
    path = os.path.join(root, "docs", "QUESTIONS.md")
    head = TOPICS.get(C["lang"], TOPICS["en"])
    with LOCK:
        lines = read(path) if os.path.exists(path) else ["# QUESTIONS\n", "\n"]
        h = next((i for i, ln in enumerate(lines) if ln.strip() == head), None)
        if h is None:
            h = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines))
            lines[h:h] = [head + "\n", "\n"]
        title = re.sub(r"\s+", " ", text.strip().splitlines()[0])[:90]
        item = [f"- **{title}**\n"] + quote(C["author"], text, "  ") + ["\n"]
        lines[h + 2:h + 2] = item
        write(path, lines)
        return item[1].strip()


# ---------- the agent ----------

JOBS = {}                        # (root, header line of the owner's comment) → {"state", "error", "path"}
Q = queue.Queue()

PROMPT = """You are the coding agent of this project. {author} (the owner) left a comment in the project's
docs forum, under an item of `{path}`. The item and its whole thread are below. Answer the latest
comment from {author}.

How to answer:
- in the language of the comment; short and to the point, like a colleague in a work chat; no greeting, no signature;
- check facts in the repository first (docs/, code, `git log`), do not answer from memory;
- follow the project's AGENTS.md (units, ticket numbers, wording rules);
- you cannot change files here. If the request needs work (code, docs, deploy, a letter), say exactly what
  you will do and that it happens in the next working session. If it is a decision or an answer to the agent's
  question, confirm how you understood it and what follows from it;
- if asked for a draft text, give it in full in a ```text block;
- output only the answer in markdown: no "{agent}, date" header, no ">" quote marks.

The item with its thread:

{block}
"""


def ask_agent(root, path, block_md):
    cmd = list(C["agent_cmd"])
    cmd[0] = shutil.which(cmd[0]) or os.path.join(HOME, ".local", "bin", cmd[0])
    env = dict(os.environ, PATH=os.pathsep.join([os.path.join(HOME, ".local", "bin"), "/opt/homebrew/bin",
                                                 "/usr/local/bin", os.environ.get("PATH", "")]))
    prompt = PROMPT.format(author=C["author"], agent=C["agent"], path=os.path.relpath(path, root), block=block_md)
    r = subprocess.run(cmd, input=prompt, cwd=root, env=env, capture_output=True, text=True, timeout=C["timeout"])
    out = r.stdout.strip()
    if r.returncode != 0 or not out:
        raise RuntimeError((r.stderr or r.stdout or f"exit {r.returncode}").strip()[-300:])
    return out


def worker():
    while True:
        key = Q.get()
        root, head = key
        job = JOBS[key]
        job["state"] = "running"
        try:
            b = next((x for x in blocks(read(job["path"])) if head in x["md"]), None)
            if b is None:
                raise RuntimeError("the item with this comment is gone: the doc changed")
            reply = ask_agent(root, job["path"], b["md"])
            if not append_to_block(job["path"], lambda x: head in x["md"], reply, C["agent"]):
                raise RuntimeError("the item disappeared while the agent was thinking")
            JOBS.pop(key, None)
            print(f"{stamp()} reply → {job['path']}", flush=True)
        except Exception as e:  # noqa: BLE001 — any failure is shown in the thread
            job.update(state="error", error=str(e) or type(e).__name__)
            print(f"{stamp()} agent failed: {job['error']}", flush=True)


def enqueue(root, path, head):
    key = (root, head)
    if not C["answer"] or (key in JOBS and JOBS[key]["state"] != "error"):
        return
    JOBS[key] = {"state": "queued", "path": path, "error": ""}
    Q.put(key)


# ---------- page data ----------

def view(root, name, path):
    """Blocks of a doc with parsed threads and the agent's status."""
    out = []
    for b in blocks(read(path)):
        body, msgs = thread(b["md"]) if b["kind"] in ("item", "para") else (b["md"], [])
        st, err = "", ""
        if msgs and msgs[-1]["author"] != C["agent"]:
            job = JOBS.get((root, msgs[-1]["head"]))
            st, err = (job["state"], job["error"]) if job else ("waiting", "")
        out.append({"kind": b["kind"], "start": b["start"], "hash": b["hash"], "body": body,
                    "msgs": msgs, "status": st, "error": err, "tid": tid(name, body)})
    return out


def threads(only=None):
    """Every thread in every doc of every project (or one project): the forum's feed."""
    res = []
    for pid, root in projects().items():
        if only and pid != only:
            continue
        for name, rel in docs(root).items():
            try:
                bl = view(root, name, os.path.join(root, rel))
            except OSError:
                continue
            for b in bl:
                if not b["msgs"]:
                    continue
                last = b["msgs"][-1]
                res.append({"p": pid, "doc": name, "tid": b["tid"], "title": b["body"].strip().splitlines()[0][:200],
                            "count": len(b["msgs"]), "last": last["author"], "stamp": last["stamp"],
                            "preview": last["md"][:220], "status": b["status"]})
    return res


# ---------- HTTP ----------

def load_token():
    if os.path.exists(TOKEN_FILE):
        return open(TOKEN_FILE).read().strip()
    os.makedirs(STATE, exist_ok=True)
    t = secrets.token_urlsafe(18)
    with open(os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT, 0o600), "w") as f:
        f.write(t + "\n")
    return t


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=()):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def log_message(self, *a):
        pass

    def _authed(self):
        if self.client_address[0] in ("127.0.0.1", "::1") or not LAN["on"]:
            return True
        c = self.headers.get("Cookie", "")
        return any(secrets.compare_digest(p.strip(), f"af={LAN['token']}") for p in c.split(";"))

    def _doc(self, q):
        """(root, doc path) from ?p=&name= or the JSON body; None if unknown."""
        root = projects().get(str(q.get("p", "")))
        rel = docs(root).get(str(q.get("name", ""))) if root else None
        return (root, os.path.join(root, rel)) if rel else (root, None)

    def do_GET(self):
        u = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/" and LAN["on"] and qs.get("k") and secrets.compare_digest(qs["k"], LAN["token"]):
            ck = f"af={LAN['token']}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Strict"
            return self._send(302, b"", "text/plain", [("Set-Cookie", ck), ("Location", "/")])
        if not self._authed():
            return self._send(401, "Open the key link printed by: agentdrop forum url", "text/plain; charset=utf-8")
        if u.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/projects":
            return self._json({"projects": [{"id": k, "docs": list(docs(v))} for k, v in projects().items()],
                               "answer": C["answer"], "lang": C["lang"], "author": C["author"], "agent": C["agent"]})
        if u.path == "/api/threads":
            return self._json(threads(qs.get("p") or None))
        if u.path == "/api/doc":
            root, path = self._doc(qs)
            if not path:
                return self._json({"error": "no such doc"}, 404)
            busy = any(k[0] == root and j["path"] == path and j["state"] in ("queued", "running") for k, j in JOBS.items())
            return self._json({"p": qs["p"], "name": qs["name"], "path": os.path.relpath(path, root),
                               "mtime": os.stat(path).st_mtime, "busy": busy, "blocks": view(root, qs["name"], path)})
        self._send(404, "{}")

    def do_POST(self):
        if not self._authed():
            return self._json({"error": "no access"}, 401)
        # Only from our own page: another site open in the browser must not write into a repo.
        origin = self.headers.get("Origin", "")
        if origin and urlparse(origin).netloc != self.headers.get("Host", ""):
            return self._json({"error": "foreign origin"}, 403)
        try:
            q = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            text = str(q.get("text", ""))[:8000]
            ask = bool(q.get("ask", True))
        except (ValueError, TypeError, AttributeError):
            return self._json({"error": "bad request"}, 400)
        p = urlparse(self.path).path
        if p == "/api/topic":
            root = projects().get(str(q.get("p", "")))
            if not root or not text.strip():
                return self._json({"error": "bad request"}, 400)
            head = new_topic(root, text)
            if ask:
                enqueue(root, os.path.join(root, "docs", "QUESTIONS.md"), head)
            return self._json({"ok": True})
        root, path = self._doc(q)
        if not path:
            return self._json({"error": "no such doc"}, 400)
        if p == "/api/retry":
            enqueue(root, path, str(q.get("head", "")))
            return self._json({"ok": True})
        if p != "/api/comment":
            return self._send(404, "{}")
        if not text.strip():
            return self._json({"error": "empty comment"}, 400)
        try:
            start, h = int(q["start"]), str(q["hash"])
        except (KeyError, TypeError, ValueError):
            return self._json({"error": "bad request"}, 400)
        head = append_to_block(path, lambda x: x["hash"] == h and x["start"] == start, text, C["author"]) \
            or append_to_block(path, lambda x: x["hash"] == h, text, C["author"])
        if not head:
            return self._json({"error": "stale"}, 409)
        if ask:
            enqueue(root, path, head)
        self._json({"ok": True})


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#15294d">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Forum">
<title>Forum</title>
<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
<style>
:root { --bg:#f6f5f2; --card:#fff; --ink:#1d1d1b; --ink2:#66655f; --line:#e2e0da; --acc:#1f4fa3; --acc-ink:#fff;
  --me:#eaf0fb; --me-line:#c8d6f0; --ag:#fff; --warn:#8a4b00; --warn-bg:#fff1d6; --err:#b3261e;
  --head:#15294d; --hl:#fff3c4; color-scheme:light dark }
@media (prefers-color-scheme: dark) { :root { --bg:#131416; --card:#1b1d20; --ink:#e8e8e5; --ink2:#a09f99; --line:#2e3136;
  --acc:#8fb4ff; --acc-ink:#0d1a33; --me:#1c2a44; --me-line:#2b3f66; --ag:#1f2226; --warn:#f3bd6b; --warn-bg:#33291a;
  --err:#ff8a80; --head:#0f1d38; --hl:#3a3218; } }
* { box-sizing:border-box }
html { -webkit-text-size-adjust:100% }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 -apple-system,system-ui,"Segoe UI",sans-serif }
a { color:var(--acc) }
header { position:sticky; top:0; z-index:5; background:var(--head); color:#fff; padding-top:env(safe-area-inset-top) }
.bar { display:flex; align-items:center; gap:6px; padding:8px 12px; overflow-x:auto; scrollbar-width:none; max-width:960px; margin:0 auto }
.bar::-webkit-scrollbar { display:none }
.bar button, .bar select { flex:none; font:inherit; font-size:14px; min-height:36px; border-radius:999px; cursor:pointer;
  background:none; border:1px solid rgba(255,255,255,.3); color:#fff; padding:0 12px; white-space:nowrap }
.bar button.on { background:#fff; color:var(--head); border-color:#fff; font-weight:600 }
.bar select { appearance:none; -webkit-appearance:none; background:rgba(255,255,255,.1); max-width:46vw; text-overflow:ellipsis }
.bar select.proj { font-weight:600; border-color:rgba(255,255,255,.55) }
.bar select option { color:#000 }
.sep { flex:none; width:1px; height:22px; background:rgba(255,255,255,.3) }
.badge { display:inline-block; min-width:18px; padding:0 5px; margin-left:5px; border-radius:9px; background:#f0ad4e; color:#1d1d1b;
  font-size:12px; font-weight:700; line-height:18px; text-align:center }
main { max-width:760px; margin:0 auto; padding:12px 16px 96px }
.meta { display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; color:var(--ink2); font-size:13px; margin:4px 0 8px }
.meta select { font:inherit; font-size:14px; max-width:100%; min-height:36px; padding:0 8px; border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--ink) }
.blk { padding:2px 8px; margin:0 -8px; border-radius:8px; scroll-margin-top:72px }
.blk.flash { background:var(--hl); transition:background 1.5s }
.blk h1 { font-size:24px; line-height:1.25; margin:16px 0 8px }
.blk h2 { font-size:20px; margin:24px 0 6px; padding-top:10px; border-top:1px solid var(--line) }
.blk h3 { font-size:17px; margin:18px 0 4px }
.blk ul, .blk ol { margin:4px 0; padding-left:22px }
.blk p { margin:6px 0 }
.blk code, .msg code { background:var(--card); border:1px solid var(--line); border-radius:4px; padding:0 3px; font-size:.86em; overflow-wrap:anywhere }
.blk pre { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:10px; overflow-x:auto; font-size:13px; white-space:pre-wrap }
.blk pre code { border:0; padding:0; background:none }
.tbl { overflow-x:auto; margin:6px 0 }
.blk table { border-collapse:collapse; font-size:14px }
.blk td, .blk th { border:1px solid var(--line); padding:4px 8px; vertical-align:top; text-align:left }
.blk blockquote { margin:6px 0; padding:4px 12px; border-left:3px solid var(--line); color:var(--ink2) }
.thread { margin:6px 0 10px 22px; display:grid; gap:8px }
.msg { border:1px solid var(--line); background:var(--ag); border-radius:12px; padding:8px 12px; min-width:0 }
.msg.me { background:var(--me); border-color:var(--me-line); margin-left:28px }
.msg .who { font-size:12px; color:var(--ink2); margin-bottom:2px; display:flex; gap:6px }
.msg .who b { color:var(--ink); font-weight:600 }
.msg p { margin:4px 0 } .msg ul, .msg ol { padding-left:20px; margin:4px 0 }
.state { font-size:14px; color:var(--ink2); display:flex; gap:4px 8px; align-items:center; flex-wrap:wrap }
.state.err { color:var(--err) }
.pulse { width:8px; height:8px; border-radius:50%; background:var(--acc); animation:p 1.2s ease-in-out infinite }
@keyframes p { 50% { opacity:.25 } }
@media (prefers-reduced-motion: reduce) { .pulse { animation:none } .blk.flash { transition:none } }
.act { display:flex; gap:4px; margin:0 0 6px 14px }
.lnk { font:inherit; font-size:14px; color:var(--acc); background:none; border:0; cursor:pointer; padding:0 8px; min-height:40px;
  display:inline-flex; align-items:center; gap:6px; border-radius:8px }
.lnk:hover { background:var(--card) }
.lnk svg { width:16px; height:16px }
@media (hover:hover) and (pointer:fine) { .act.quiet { opacity:0 } .blk:hover .act.quiet, .act.quiet:focus-within { opacity:1 } }
form.cmp { margin:4px 0 12px 22px; display:grid; gap:8px }
textarea { font:inherit; font-size:16px; width:100%; min-height:96px; padding:10px; border-radius:10px; border:1px solid var(--line);
  background:var(--card); color:var(--ink); resize:vertical }
textarea:focus-visible, button:focus-visible, select:focus-visible { outline:2px solid var(--acc); outline-offset:2px }
.row { display:flex; gap:8px; align-items:center; flex-wrap:wrap }
.btn { font:inherit; font-size:15px; min-height:44px; padding:0 18px; border-radius:10px; border:1px solid var(--line); background:var(--card); color:var(--ink); cursor:pointer }
.btn.pri { background:var(--acc); color:var(--acc-ink); border-color:var(--acc); font-weight:600 }
.btn:disabled { opacity:.5 }
.chk { font-size:14px; color:var(--ink2); display:flex; gap:8px; align-items:center; min-height:44px; cursor:pointer }
.chk input { width:18px; height:18px; margin:0 }
.err { color:var(--err); font-size:14px }
.feed { display:grid; gap:10px; margin-top:10px }
.card { display:block; text-align:left; width:100%; font:inherit; color:inherit; background:var(--card); border:1px solid var(--line);
  border-radius:12px; padding:12px 14px; cursor:pointer }
.card:hover { border-color:var(--ink2) }
.card .top { display:flex; gap:8px; justify-content:space-between; align-items:center; font-size:12px; color:var(--ink2) }
.card .t { font-weight:600; margin:4px 0 2px; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical }
.card .p { color:var(--ink2); font-size:14px; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical }
.pill { font-size:12px; font-weight:600; border-radius:999px; padding:2px 8px; white-space:nowrap }
.pill.new { background:var(--acc); color:var(--acc-ink) }
.pill.wait { background:var(--warn-bg); color:var(--warn) }
.pill.run { background:var(--me); color:var(--acc) }
.pill.bad { background:var(--warn-bg); color:var(--err) }
.seg { display:flex; gap:6px; flex-wrap:wrap; margin:16px 0 0 }
.seg button { font:inherit; font-size:14px; min-height:36px; padding:0 14px; border-radius:999px; border:1px solid var(--line); background:var(--card); color:var(--ink); cursor:pointer }
.seg button.on { background:var(--ink); color:var(--bg); border-color:var(--ink) }
.newq { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px; display:grid; gap:8px; margin-top:4px }
.newq h2 { font-size:17px; margin:0 }
.newq select { font:inherit; font-size:15px; min-height:40px; border-radius:10px; border:1px solid var(--line); background:var(--bg); color:var(--ink); padding:0 8px }
.hint { font-size:13px; color:var(--ink2); margin:0 }
.empty { color:var(--ink2); padding:24px 0; text-align:center }
@media (max-width:520px) { .thread, form.cmp { margin-left:0 } .msg.me { margin-left:16px } .act { margin-left:-8px } }
</style></head><body>
<header><div class="bar" id="bar"></div></header>
<main id="main"></main>
<script>
const I18N = {
  en: { feed:"Feed", all:"All projects", more:"More", docs:{QUESTIONS:"Questions",TODO:"Tickets",STATE:"State",LOG:"Log",DECISIONS:"Decisions",CONTEXT:"Context",PITFALLS:"Pitfalls",CONVENTIONS:"Conventions",OPERATIONS:"Operations"},
    spec:"Spec · ", review:"Review · ", ask:"Ask the agent", askHint:"The agent reads the repository and answers here, usually within a minute. The question goes to Questions, section “Questions for the agent”.",
    askHintOff:"Auto-answer is off: the question goes to Questions, the agent answers in its next working session.", askPh:"e.g. why does the September total differ from the sheet?",
    askBtn:"Ask", project:"Project", fAll:"All", fNew:"New", fWait:"Waiting", empty:"Nothing here yet. Ask a question above or comment on an item in a doc.",
    msgs:(n)=>n+(n===1?" message":" messages"), running:"agent is writing", queued:"queued", failed:"agent failed", waiting:"no answer", fresh:"new answer",
    reply:"Reply", discuss:"Discuss", sections:"Sections…", notFound:"Doc not found",
    stRun:"The agent is reading the repository and writing an answer", stQueued:"The agent is queued", stErr:"The agent did not answer: ", retry:"Retry",
    stWait:"No answer yet", askNow:"Ask the agent", phReply:"Reply", phNew:"Comment or question about this item", send:"Send", cancel:"Cancel", wantAnswer:"agent answers",
    stale:"The item changed: reload the page", offline:"Forum is not reachable", noProjects:"No agentdrop projects found. Run agentdrop in a project or add one: agentdrop forum add PATH" },
  ru: { feed:"Лента", all:"Все проекты", more:"Ещё", docs:{QUESTIONS:"Вопросы",TODO:"Задачи",STATE:"Состояние",LOG:"Журнал",DECISIONS:"Решения",CONTEXT:"Контекст",PITFALLS:"Грабли",CONVENTIONS:"Правила",OPERATIONS:"Эксплуатация"},
    spec:"ТЗ · ", review:"Ревью · ", ask:"Вопрос агенту", askHint:"Агент прочитает репозиторий и ответит здесь, обычно за минуту. Вопрос ляжет в «Вопросы», раздел «Вопросы агенту».",
    askHintOff:"Автоответ выключен: вопрос ляжет в «Вопросы», агент ответит в рабочей сессии.", askPh:"Например: почему факт сентября меньше, чем в таблице?",
    askBtn:"Спросить", project:"Проект", fAll:"Все", fNew:"Новое", fWait:"Ждут ответа", empty:"Здесь пусто. Задайте вопрос выше или обсудите пункт в документе.",
    msgs:(n)=>{const a=n%10,b=n%100;return n+(a===1&&b!==11?" сообщение":a>=2&&a<=4&&(b<12||b>14)?" сообщения":" сообщений")}, running:"агент пишет", queued:"в очереди", failed:"агент не ответил", waiting:"без ответа", fresh:"новый ответ",
    reply:"Ответить", discuss:"Обсудить", sections:"Разделы…", notFound:"Документ не найден",
    stRun:"Агент читает репозиторий и пишет ответ", stQueued:"Агент в очереди", stErr:"Агент не ответил: ", retry:"Повторить",
    stWait:"Ответа пока нет", askNow:"Спросить агента", phReply:"Ответ", phNew:"Комментарий или вопрос по этому пункту", send:"Отправить", cancel:"Отмена", wantAnswer:"ответ агента",
    stale:"Пункт изменился — обновите страницу", offline:"Нет связи с форумом", noProjects:"Проектов agentdrop не найдено. Запустите agentdrop в проекте или добавьте: agentdrop forum add ПУТЬ" } };
const TABS = ["QUESTIONS","TODO","STATE","LOG"];
const ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>';
const $ = (s, r=document) => r.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const md = (s) => marked.parse(s).replace(/<table>/g, '<div class="tbl"><table>').replace(/<\/table>/g, "</table></div>");
const strip = (s) => s.replace(/^\s*(?:[-*]|\d+\.)\s+/, "").replace(/[*_`#>]/g, "").trim();
let T = I18N.en, S = { projects:[], answer:true, author:"", agent:"" }, P = "", cur = "", filter = "all", mtime = 0, writing = false, feedSig = "";
const label = (n) => T.docs[n] || n.replace(/^specs\//, T.spec).replace(/^reviews\/inbox\//, T.review);
const seen = (() => { try { return JSON.parse(localStorage.getItem("af-seen") || "{}"); } catch { return {}; } })();
const saveSeen = () => { try { localStorage.setItem("af-seen", JSON.stringify(seen)); } catch {} };
const skey = (t) => t.stamp + "|" + t.count;
const isNew = (t) => t.last === S.agent && seen[t.p + ":" + t.tid] !== skey(t);
const proj = () => S.projects.find(p => p.id === P);
const go = (p, doc, t) => { location.hash = [p, doc].filter(Boolean).map(encodeURIComponent).join("/") + (t ? "~" + t : ""); };

function route() {
  const [path, t] = location.hash.slice(1).split("~");
  const [p, ...d] = path.split("/").map(decodeURIComponent);
  return { p: p || "", doc: d.join("/"), t: t || "" };
}
async function boot() {
  try { S = await (await fetch("/api/projects")).json(); } catch { $("#main").innerHTML = `<p class="empty">${esc(T.offline)}</p>`; return; }
  T = I18N[S.lang] || I18N.en; document.documentElement.lang = S.lang;
  if (S.projects.length === 1 && !location.hash) P = S.projects[0].id;
  window.onhashchange = show; show(); setInterval(tick, 4000);
}
function bar(unread) {
  const tab = (doc, t) => `<button data-doc="${esc(doc)}" class="${cur===doc?'on':''}">${t}</button>`;
  const pr = proj(), names = pr ? pr.docs : [];
  const more = names.filter(n => !TABS.includes(n));
  $("#bar").innerHTML = (S.projects.length > 1 ? `<select class="proj" id="proj" aria-label="${T.project}"><option value="">${T.all}</option>${S.projects.map(p => `<option value="${esc(p.id)}" ${p.id===P?'selected':''}>${esc(p.id)}</option>`).join("")}</select><span class="sep"></span>` : "")
    + tab("", T.feed + (unread ? `<span class="badge">${unread}</span>` : ""))
    + (pr ? TABS.filter(n => names.includes(n)).map(n => tab(n, label(n))).join("")
      + (more.length ? `<select id="more" aria-label="${T.more}"><option value="">${T.more}</option>${more.map(n => `<option value="${esc(n)}" ${n===cur?'selected':''}>${esc(label(n))}</option>`).join("")}</select>` : "") : "");
  const ps = $("#proj"); if (ps) ps.onchange = () => go(ps.value, "");
  const m = $("#more"); if (m) m.onchange = () => m.value && go(P, m.value);
  $("#bar").querySelectorAll("[data-doc]").forEach(b => b.onclick = () => { go(P, b.dataset.doc); if (!b.dataset.doc) show(); });
  const on = $("#bar button.on"); on && on.scrollIntoView({ block:"nearest", inline:"nearest" });
}
function show() {
  const r = route(); P = r.p || (S.projects.length === 1 ? S.projects[0].id : ""); cur = r.doc; writing = false; mtime = 0; feedSig = "";
  if (!cur) return feed(true);
  doc(true, r.t);
}
async function tick() { if (writing || document.hidden) return; cur ? (doc(false), badge()) : feed(false); }
async function getThreads() { return (await fetch("/api/threads" + (P ? "?p=" + encodeURIComponent(P) : ""))).json(); }
async function badge() { const ts = await getThreads(); bar(ts.filter(isNew).length); }

/* ---- feed ---- */
async function feed(force) {
  let ts; try { ts = await getThreads(); } catch { return; }
  const sig = JSON.stringify(ts) + filter + P;
  if (!force && sig === feedSig) return; feedSig = sig;
  bar(ts.filter(isNew).length);
  if (writing) return;
  if (!S.projects.length) { $("#main").innerHTML = `<p class="empty">${esc(T.noProjects)}</p>`; return; }
  const order = (t) => (t.status==="running"||t.status==="queued") ? 0 : isNew(t) ? 1 : t.status ? 2 : 3;
  const when = (s) => { const m = s.match(/(\d+)\.(\d+)(?: (\d+):(\d+))?/); return m ? (+m[2])*1e6 + (+m[1])*1e4 + (+(m[3]||0))*100 + (+(m[4]||0)) : 0; };
  let list = ts.slice().sort((a, b) => order(a) - order(b) || when(b.stamp) - when(a.stamp));
  if (filter === "new") list = list.filter(t => order(t) <= 1);
  if (filter === "wait") list = list.filter(t => t.status);
  const pill = (t) => t.status==="running" ? `<span class="pill run">${T.running}</span>` : t.status==="queued" ? `<span class="pill run">${T.queued}</span>`
    : t.status==="error" ? `<span class="pill bad">${T.failed}</span>` : t.status==="waiting" ? `<span class="pill wait">${T.waiting}</span>`
    : isNew(t) ? `<span class="pill new">${T.fresh}</span>` : "";
  const multi = S.projects.length > 1;
  $("#main").innerHTML = `
    <form class="newq" id="newq">
      <h2>${T.ask}</h2>
      <p class="hint">${S.answer ? T.askHint : T.askHintOff}</p>
      ${multi && !P ? `<select id="qp" aria-label="${T.project}">${S.projects.map(p => `<option ${p.id===localStorage.getItem("af-last")?"selected":""}>${esc(p.id)}</option>`).join("")}</select>` : ""}
      <textarea placeholder="${esc(T.askPh)}"></textarea>
      <div class="row"><button class="btn pri" type="submit">${T.askBtn}</button><span class="err"></span></div>
    </form>
    <div class="seg" role="group">${[["all",T.fAll],["new",T.fNew],["wait",T.fWait]].map(([k,t]) => `<button data-f="${k}" class="${filter===k?'on':''}" aria-pressed="${filter===k}">${t}</button>`).join("")}</div>
    <div class="feed">${list.map(t => `
      <button class="card" data-p="${esc(t.p)}" data-doc="${esc(t.doc)}" data-t="${t.tid}">
        <div class="top"><span>${multi && !P ? esc(t.p) + " · " : ""}${esc(label(t.doc))} · ${T.msgs(t.count)}</span>${pill(t)}</div>
        <div class="t">${esc(strip(t.title))}</div>
        <div class="p"><b>${esc(t.last)}, ${esc(t.stamp)}:</b> ${esc(strip(t.preview))}</div>
      </button>`).join("") || `<p class="empty">${T.empty}</p>`}</div>`;
  $("#main").querySelectorAll("[data-f]").forEach(b => b.onclick = () => { filter = b.dataset.f; feed(true); });
  $("#main").querySelectorAll(".card").forEach(c => c.onclick = () => go(c.dataset.p, c.dataset.doc, c.dataset.t));
  const f = $("#newq"), ta = $("textarea", f);
  ta.oninput = () => writing = !!ta.value.trim();
  ta.onkeydown = (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) f.requestSubmit(); };
  f.onsubmit = async (e) => {
    e.preventDefault(); if (!ta.value.trim()) return;
    const p = P || $("#qp")?.value || S.projects[0].id; try { localStorage.setItem("af-last", p); } catch {}
    const r = await post("/api/topic", { p, text: ta.value, ask: S.answer });
    if (r.ok) { writing = false; feed(true); } else $(".err", f).textContent = r.error;
  };
}

/* ---- doc ---- */
async function doc(force, focusT) {
  const r = await fetch("/api/doc?p=" + encodeURIComponent(P) + "&name=" + encodeURIComponent(cur)).catch(() => null);
  if (!r || !r.ok) { if (force) { $("#main").innerHTML = `<p class="empty">${T.notFound}</p>`; bar(0); } return; }
  const d = await r.json();
  if (!force && (d.mtime === mtime && !d.busy)) return;
  if (!force && writing) return;
  const y = scrollY; mtime = d.mtime;
  const heads = d.blocks.filter(b => b.kind === "heading" && /^#{2,3} /.test(b.body));
  $("#main").innerHTML = `<div class="meta"><span>${esc(P)} · ${esc(d.path)}</span>${heads.length > 3 ? `<select id="toc" aria-label="${T.sections}"><option value="">${T.sections}</option>${heads.map(b => `<option value="${b.start}">${esc(b.body.replace(/^#+\s*/, "").trim().slice(0,70))}</option>`).join("")}</select>` : ""}</div>`
    + d.blocks.map(block).join("");
  const toc = $("#toc"); if (toc) toc.onchange = () => { document.querySelector(`[data-s="${toc.value}"]`)?.scrollIntoView({ behavior:"smooth" }); toc.value = ""; };
  $("#main").querySelectorAll("[data-c]").forEach(btn => btn.onclick = () => compose(btn, d.blocks[+btn.dataset.c]));
  $("#main").querySelectorAll("[data-retry]").forEach(btn => btn.onclick = async () => { await post("/api/retry", { p: P, name: cur, head: d.blocks[+btn.dataset.retry].msgs.at(-1).head }); doc(true); });
  d.blocks.forEach(b => { if (b.msgs.length && b.msgs.at(-1).author === S.agent) seen[P + ":" + b.tid] = skey({ stamp: b.msgs.at(-1).stamp, count: b.msgs.length }); }); saveSeen();
  if (force && focusT) { const el = document.getElementById("t-" + focusT); if (el) { el.scrollIntoView({ block:"start" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600); } }
  else if (force) scrollTo(0, 0); else scrollTo(0, y);
  if (force) badge();
}
function block(b, i) {
  const can = b.kind === "item" || b.kind === "para";
  let h = `<div class="blk ${b.kind}" id="t-${b.tid}" data-s="${b.start}">${md(b.body)}`;
  if (b.msgs.length) h += `<div class="thread">${b.msgs.map(m => `<div class="msg ${m.author===S.agent?"":"me"}"><div class="who"><b>${esc(m.author)}</b><span>${esc(m.stamp)}</span></div>${md(m.md)}</div>`).join("")}${status(b, i)}</div>`;
  if (can) h += `<div class="act ${b.msgs.length ? "" : "quiet"}"><button class="lnk" data-c="${i}">${ICON}${b.msgs.length ? T.reply : T.discuss}</button></div>`;
  return h + "</div>";
}
function status(b, i) {
  if (b.status === "running") return `<div class="state" role="status"><span class="pulse"></span>${T.stRun}</div>`;
  if (b.status === "queued") return `<div class="state" role="status"><span class="pulse"></span>${T.stQueued}</div>`;
  if (b.status === "error") return `<div class="state err">${T.stErr}${esc(b.error)} <button class="lnk" data-retry="${i}">${T.retry}</button></div>`;
  if (b.status === "waiting" && S.answer) return `<div class="state">${T.stWait} <button class="lnk" data-retry="${i}">${T.askNow}</button></div>`;
  return "";
}
function compose(btn, b) {
  document.querySelectorAll("form.cmp").forEach(f => f.remove());
  writing = true;
  const f = document.createElement("form"); f.className = "cmp";
  f.innerHTML = `<textarea placeholder="${esc(b.msgs.length ? T.phReply : T.phNew)}"></textarea>
    <div class="row"><button class="btn pri" type="submit">${T.send}</button><button class="btn" type="button">${T.cancel}</button>
    ${S.answer ? `<label class="chk"><input type="checkbox" checked> ${T.wantAnswer}</label>` : ""}</div><span class="err"></span>`;
  btn.parentElement.after(f); const ta = $("textarea", f); ta.focus();
  ta.onkeydown = (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) f.requestSubmit(); };
  $("button[type=button]", f).onclick = () => { f.remove(); writing = false; };
  f.onsubmit = async (e) => {
    e.preventDefault(); if (!ta.value.trim()) return;
    const sub = $("button[type=submit]", f); sub.disabled = true;
    const r = await post("/api/comment", { p: P, name: cur, start: b.start, hash: b.hash, text: ta.value, ask: !!$("input[type=checkbox]", f)?.checked });
    if (r.ok) { writing = false; await doc(true); document.getElementById("t-" + b.tid)?.scrollIntoView({ block:"center" }); }
    else { sub.disabled = false; $(".err", f).textContent = r.error === "stale" ? T.stale : r.error; }
  };
}
async function post(url, body) {
  try {
    const r = await fetch(url, { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    return r.ok ? { ok:true } : { error: j.error || "error" };
  } catch { return { error: T.offline }; }
}
boot();
</script></body></html>
"""


# ---------- service ----------

def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.0.1", 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def cmd_url():
    print(f"This machine: http://127.0.0.1:{C['port']}")
    print(f"Phone (same Wi-Fi): http://{lan_ip()}:{C['port']}/?k={load_token()}")
    print("Open the phone link once; it sets a cookie for a year. Add it to the home screen.")


def cmd_install():
    if sys.platform != "darwin":
        raise SystemExit("install is macOS-only; elsewhere run `agentdrop forum run --lan` under your service manager")
    me = os.path.realpath(__file__)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array><string>{sys.executable}</string><string>{me}</string><string>run</string><string>--lan</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StandardOutPath</key><string>{LOGFILE}</string>
  <key>StandardErrorPath</key><string>{LOGFILE}</string>
</dict></plist>
"""
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    with open(PLIST, "w") as f:
        f.write(plist)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", PLIST], check=True)
    print(f"Forum runs as {LABEL}, log {LOGFILE}")
    cmd_url()


def cmd_uninstall():
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    if os.path.exists(PLIST):
        os.remove(PLIST)
    print("Forum service removed.")


def cmd_status():
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, text=True)
    st = re.search(r"state = (\w+)", r.stdout)
    print(f"service: {st.group(1) if st else 'not installed'}")
    for pid, root in projects().items():
        print(f"  {pid:<24} {root}")


def cmd_add(path):
    p = os.path.realpath(os.path.expanduser(path))
    if not os.path.isdir(os.path.join(p, "docs")):
        raise SystemExit(f"{p} has no docs/: run `agentdrop {p}` first")
    try:
        with open(CONF, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    lst = data.setdefault("projects", [])
    if p not in lst:
        lst.append(p)
    os.makedirs(STATE, exist_ok=True)
    with open(CONF, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Added {p}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agentdrop forum", description="Docs forum for agentdrop projects")
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "install", "uninstall", "status", "url", "logs", "add"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--lan", action="store_true", help="listen on the home network, log in via a key link")
    ap.add_argument("--port", type=int)
    ap.add_argument("--no-answer", action="store_true", help="store comments, do not run the agent")
    a = ap.parse_args(argv)
    if a.port:
        C["port"] = a.port
    if a.cmd == "install":
        return cmd_install()
    if a.cmd == "uninstall":
        return cmd_uninstall()
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "url":
        return cmd_url()
    if a.cmd == "logs":
        return os.execvp("tail", ["tail", "-n", "50", "-f", LOGFILE])
    if a.cmd == "add":
        if not a.path:
            raise SystemExit("agentdrop forum add PATH")
        return cmd_add(a.path)
    if a.no_answer:
        C["answer"] = False
    LAN.update(on=a.lan, token=load_token() if a.lan else "")
    for _ in range(2):
        threading.Thread(target=worker, daemon=True).start()
    print(f"Forum: http://127.0.0.1:{C['port']}  projects: {', '.join(projects()) or 'none'}", flush=True)
    ThreadingHTTPServer(("0.0.0.0" if a.lan else "127.0.0.1", C["port"]), H).serve_forever()


if __name__ == "__main__":
    main()
