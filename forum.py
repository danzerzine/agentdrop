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
import argparse, datetime as dt, glob, hashlib, json, os, queue, re, secrets, shutil, socket, subprocess, sys, textwrap, threading
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
CLOSED = {"ru": "_Ветка закрыта._", "en": "_Thread closed._"}   # last line of a closed thread


def closed(md):
    return md.rstrip().endswith(tuple(CLOSED.values()))
LOCK = threading.Lock()          # one markdown write at a time


def git_name():
    try:
        return subprocess.run(["git", "config", "--global", "user.name"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def config():
    c = {"author": git_name() or "Owner", "agent": "Agent", "lang": "en", "port": 5290,
         "roots": ["~/Projects", "~/code", "~/src", "~/Downloads"], "projects": [], "answer": True,
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
    """An agentdrop project: AGENTS.md with the managed block (kit or older layout)."""
    try:
        with open(os.path.join(d, "AGENTS.md"), encoding="utf-8") as f:
            head = f.read()
    except OSError:
        return False
    return "AGENTDROP" in head


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


def mds(d):
    return sorted(p for p in glob.glob(os.path.join(d, "*")) if p.lower().endswith(".md") and os.path.isfile(p))


SKIP = {"AGENTS", "CLAUDE", "GEMINI", "README", "LOCAL"}


def docs(root):
    """Doc name → path relative to the project. Only these files can be read or written.
    Kit docs first, then other docs/*.md, then notes in the project root (older layouts
    keep TODO.md or PITFALLS.md there), then specs and the review inbox."""
    out = {n: f"docs/{n}.md" for n in MAIN if os.path.exists(os.path.join(root, f"docs/{n}.md"))}
    for d in ("docs", ""):
        for p in mds(os.path.join(root, d)):
            stem = os.path.basename(p).rsplit(".", 1)[0]
            if stem.upper() in SKIP or os.path.relpath(p, root) in out.values():
                continue
            out[stem if stem not in out else "./" + stem] = os.path.relpath(p, root)
    for sub in ("specs", "reviews/inbox"):
        for p in mds(os.path.join(root, "docs", sub)):
            rel = os.path.relpath(p, root)
            out[rel[len("docs/"):].rsplit(".", 1)[0]] = rel
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
- if the item is already done or the question is fully answered, and nothing is left for {author} to decide
  or for anyone to do, end the answer with a separate last line `CLOSE`: the forum then closes the thread
  ({author} can reopen it by replying). Otherwise do not write it;
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
            reply = ask_agent(root, job["path"], b["md"]).rstrip()
            if reply.endswith("\nCLOSE") or reply == "CLOSE":
                reply = reply[:-len("CLOSE")].rstrip() + "\n\n" + CLOSED.get(C["lang"], CLOSED["en"])
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
        if msgs and closed(msgs[-1]["md"]):
            st = "closed"
        elif msgs and msgs[-1]["author"] != C["agent"]:
            job = JOBS.get((root, msgs[-1]["head"]))
            st, err = (job["state"], job["error"]) if job else ("waiting", "")
        out.append({"kind": b["kind"], "start": b["start"], "hash": b["hash"], "body": body,
                    "msgs": msgs, "status": st, "error": err, "tid": tid(name, body)})
    return out


# TODO and QUESTIONS are shown as a to-do list and a message board; the rest as documents.
BOARDS = ("TODO", "QUESTIONS")
# Section names (with their parents) decide what an item is: done, addressed to the owner, or
# an agent's decision the owner may revert.
DONE_RE = re.compile(r"закрыт|сделано|выполнено|архив|\bclosed\b|\bdone\b|\barchive", re.I)
REVIEW_RE = re.compile(r"решено|можно отменить|\bresolved\b|\bdecided\b|revert", re.I)
TKT = re.compile(r"^([A-Za-zА-Яа-яЁё]{1,3}-?\d+)[.:)]?\s+")
PRI = re.compile(r"^\(?(P[0-3])\)?[.:]?\s*")


def item_parts(body):
    """'- **B48 (P1). Title.** Note…' → ticket, priority, title, note (markdown)."""
    lines = body.strip("\n").splitlines()
    first = ITEM.sub("", lines[0].strip()) if lines else ""
    m = re.match(r"\*\*(.+?)\*\*[.:]?\s*(.*)", first)
    title, rest = (m.group(1), m.group(2)) if m else (first, "")
    ticket = prio = ""
    t = TKT.match(title)
    if t:
        ticket, title = t.group(1), title[t.end():]
    p = PRI.match(title)
    if p:
        prio, title = p.group(1), title[p.end():]
    note = (rest + "\n" + textwrap.dedent("\n".join(lines[1:]))).strip()
    return {"ticket": ticket, "prio": prio, "title": title.strip().rstrip(".") or first[:120], "note": note}


def board(root, name, path):
    """Sections of a doc with their items: [{title, level, path, cat, items}]."""
    a = C["author"].lower()
    stem = a[:max(3, len(a) - 1)]   # "Данияр" also matches "К Данияру"
    groups, heads = [], {}
    for b in view(root, name, path):
        if b["kind"] == "heading":
            m = re.match(r"(#+)\s*(.*)", b["body"].strip())
            lvl = len(m.group(1))
            if lvl < 2:
                continue
            heads = {k: v for k, v in heads.items() if k < lvl}
            heads[lvl] = m.group(2).strip()
            pth = " / ".join(heads[k] for k in sorted(heads))
            you = stem in pth.lower() or bool(re.search(r"\bowner\b|владельц", pth, re.I))
            cat = "done" if DONE_RE.search(pth) else "review" if you and REVIEW_RE.search(pth) else "you" if you else ""
            groups.append({"title": heads[lvl], "level": lvl, "path": pth, "cat": cat, "items": []})
        elif b["kind"] == "item":
            if not groups:
                groups.append({"title": "", "level": 2, "path": "", "cat": "", "items": []})
            g, last = groups[-1], (b["msgs"][-1] if b["msgs"] else None)
            g["items"].append({**item_parts(b["body"]), "tid": b["tid"], "start": b["start"], "hash": b["hash"],
                               "cat": g["cat"], "msgs": b["msgs"], "status": b["status"], "error": b["error"],
                               "count": len(b["msgs"]), "last": last["author"] if last else "",
                               "stamp": last["stamp"] if last else ""})
    return groups


def summary(pid, name, it):
    last = it["msgs"][-1]["md"] if it["msgs"] else it.get("note", "")
    return {"p": pid, "doc": name, "tid": it["tid"], "ticket": it["ticket"], "prio": it["prio"], "title": it["title"][:200],
            "cat": it["cat"], "count": it["count"], "last": it["last"], "stamp": it["stamp"],
            "preview": last[:220], "status": it["status"]}


def threads(only=None):
    """The forum's inbox: every thread in every doc, plus open items addressed to the owner."""
    res = []
    for pid, root in projects().items():
        if only and pid != only:
            continue
        for name, rel in docs(root).items():
            path = os.path.join(root, rel)
            try:
                if name in BOARDS:
                    its = [i for g in board(root, name, path) for i in g["items"]]
                else:
                    its = []
                    for b in view(root, name, path):
                        if b["msgs"]:
                            last = b["msgs"][-1]
                            its.append({**item_parts(b["body"]), "tid": b["tid"], "cat": "", "msgs": b["msgs"],
                                        "status": b["status"], "count": len(b["msgs"]),
                                        "last": last["author"], "stamp": last["stamp"]})
            except OSError:
                continue
            res += [summary(pid, name, i) for i in its if i["msgs"] or i["cat"] in ("you", "review")]
    return res


def todo_open(root):
    rel = docs(root).get("TODO")
    if not rel:
        return 0
    try:
        gs = board(root, "TODO", os.path.join(root, rel))
    except OSError:
        return 0
    return sum(1 for g in gs if g["cat"] != "done" for i in g["items"] if i["status"] != "closed")


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
        if secrets.compare_digest(self.headers.get("X-Forum-Key", ""), LAN["token"]):
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
        if u.path == "/":
            # The page itself holds no data; it keeps the key in localStorage and sends it as a
            # header, because privacy browsers (Cromite, Safari after a cross-site link) drop cookies.
            ck = [("Set-Cookie", f"af={LAN['token']}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax")] \
                if LAN["on"] and qs.get("k") and secrets.compare_digest(qs["k"], LAN["token"]) else []
            return self._send(200, PAGE, "text/html; charset=utf-8", ck)
        if not self._authed():
            print(f"{stamp()} 401 {self.client_address[0]} {u.path} "
                  f"cookie={'af=' in self.headers.get('Cookie', '')} header={bool(self.headers.get('X-Forum-Key'))}", flush=True)
            return self._json({"error": "key"}, 401)
        if u.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/projects":
            return self._json({"projects": [{"id": k, "docs": list(docs(v)), "todo": todo_open(v)} for k, v in projects().items()],
                               "answer": C["answer"], "lang": C["lang"], "author": C["author"], "agent": C["agent"]})
        if u.path == "/api/threads":
            return self._json(threads(qs.get("p") or None))
        if u.path == "/api/board":
            root, path = self._doc(qs)
            if not path or qs["name"] not in BOARDS:
                return self._json({"error": "no such doc"}, 404)
            return self._json({"p": qs["p"], "name": qs["name"], "path": os.path.relpath(path, root),
                               "groups": board(root, qs["name"], path)})
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
        if p == "/api/close":
            text, ask = CLOSED.get(C["lang"], CLOSED["en"]), False
        elif p != "/api/comment":
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
<meta name="theme-color" content="#f7f4ec">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Forum">
<title>Forum</title>
<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
<style>
/* Basecamp-like: warm paper, white cards, slate ink, green actions, blue links, red attention */
:root { --bg:#f7f4ec; --card:#fff; --ink:#283c46; --ink2:#6c7a82; --line:#e3ded2; --acc:#1f6fd1; --acc-ink:#fff;
  --go:#1f8a4c; --go-ink:#fff; --go-bg:#e3f4e8; --me:#eef5ff; --me-line:#cfe0f7; --ag:#fff; --warn:#8a5300; --warn-bg:#fff0c9;
  --err:#c52a1e; --hot:#e0382b; --hot-ink:#fff; --hot-bg:#fde8e5; --hl:#fff4bf; --head:#fffdf8;
  --p0:#e0382b; --p1:#c86c00; --p2:#1f6fd1; --p3:#8a949a; color-scheme:light dark }
@media (prefers-color-scheme: dark) { :root { --bg:#1b2126; --card:#242c32; --ink:#ebe8e0; --ink2:#a3aab0; --line:#36404a;
  --acc:#7ab0ff; --acc-ink:#0d1a33; --go:#4cc47a; --go-ink:#0f2418; --go-bg:#1f3a2a; --me:#22324a; --me-line:#34507a; --ag:#242c32;
  --warn:#f3c26b; --warn-bg:#3a3020; --err:#ff8a80; --hot:#ff5c4d; --hot-ink:#fff; --hot-bg:#43231f; --hl:#3d3618; --head:#20272d;
  --p0:#ff5c4d; --p1:#f3a54b; --p2:#7ab0ff; --p3:#8f989e; } }
* { box-sizing:border-box }
html { -webkit-text-size-adjust:100% }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 -apple-system,system-ui,"Segoe UI",sans-serif }
a { color:var(--acc) }
header { position:sticky; top:0; z-index:5; background:var(--head); border-bottom:1px solid var(--line); padding-top:env(safe-area-inset-top) }
.bar { display:flex; align-items:center; gap:6px; padding:8px 12px; overflow-x:auto; scrollbar-width:none; max-width:960px; margin:0 auto }
.bar::-webkit-scrollbar { display:none }
.bar button, .bar select { flex:none; font:inherit; font-size:14px; min-height:36px; border-radius:999px; cursor:pointer;
  background:none; border:1px solid var(--line); color:var(--ink); padding:0 12px; white-space:nowrap; display:inline-flex; align-items:center }
.bar button.on { background:var(--ink); color:var(--head); border-color:var(--ink); font-weight:600 }
.bar select { appearance:none; -webkit-appearance:none; background:var(--card); max-width:46vw; width:auto; text-overflow:ellipsis }
.bar select#more { max-width:120px }
.bar select.proj { font-weight:700 }
.sep { flex:none; width:1px; height:22px; background:var(--line) }
.badge { display:inline-block; min-width:20px; padding:0 6px; margin-left:6px; border-radius:10px; background:var(--hot); color:var(--hot-ink);
  font-size:12px; font-weight:700; line-height:20px; text-align:center; font-style:normal }
.bar .badge.lone { margin:0; cursor:pointer; border:0; min-height:0 }
main { max-width:860px; margin:0 auto; padding:12px 16px 96px }
h1.ph { font-size:28px; line-height:1.2; margin:14px 0 4px; text-align:center }
.lead { text-align:center; color:var(--ink2); font-size:14px; margin:0 0 14px }
.lead .btn { margin-top:8px }
h2.sh { font-size:18px; margin:26px 0 8px; display:flex; align-items:center }
.grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); margin:14px 0 }
.tile { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px 16px; display:flex; flex-direction:column; gap:8px;
  text-decoration:none; color:inherit; min-width:0; box-shadow:0 1px 2px rgba(0,0,0,.04) }
a.tile:hover { border-color:var(--ink2) }
.tile h2 { font-size:18px; margin:0; display:flex; align-items:center; text-align:center; justify-content:center }
.tile .big { font-size:30px; font-weight:700; line-height:1; text-align:center }
.tile .cap { font-size:13px; color:var(--ink2); text-align:center; display:flex; gap:6px; justify-content:center; flex-wrap:wrap; align-items:center }
.tile ul { list-style:none; padding:0; margin:4px 0 0; font-size:14px; display:grid; gap:4px; border-top:1px solid var(--line); padding-top:8px }
.tile li { white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.tile li.hot::before { content:""; display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--hot); margin-right:6px; vertical-align:1px }
.tile .docs a { text-decoration:none }
.attn { background:var(--hot-bg); border:1px solid color-mix(in srgb, var(--hot) 35%, transparent); border-radius:14px; padding:4px 14px 14px; margin:14px 0 }
.attn h2.sh { margin:10px 0 8px; color:var(--hot) }
.feed { display:grid; gap:10px }
.card { display:block; text-decoration:none; color:inherit; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 14px; min-width:0 }
.card:hover { border-color:var(--ink2) }
.card .top { display:flex; gap:8px; justify-content:space-between; align-items:flex-start; font-size:12px; color:var(--ink2) }
.card .t { font-weight:600; margin:4px 0 2px; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical }
.card .p { color:var(--ink2); font-size:14px; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical }
.pills { display:flex; gap:4px; flex-wrap:wrap; justify-content:flex-end }
.pill { font-size:12px; font-weight:600; border-radius:999px; padding:1px 8px; white-space:nowrap; line-height:18px }
.pill.new { background:var(--acc); color:var(--acc-ink) }
.pill.hot { background:var(--hot); color:var(--hot-ink) }
.pill.wait { background:var(--warn-bg); color:var(--warn) }
.pill.run { background:var(--me); color:var(--acc) }
.pill.done { background:var(--bg); color:var(--ink2); border:1px solid var(--line) }
.pill.bad { background:var(--hot-bg); color:var(--err) }
.bhead { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; margin:10px 0 4px }
.bhead h1 { font-size:26px; margin:0 }
.grp { margin:18px 0 0 }
.grp h2, .grp summary { font-size:16px; margin:0 0 8px; display:flex; align-items:center; gap:6px; color:var(--ink) }
.grp summary { cursor:pointer; min-height:40px; color:var(--ink2); font-weight:600 }
.cnt { font-size:13px; color:var(--ink2); font-weight:400 }
.list { list-style:none; padding:0; margin:0; background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden }
.list > li { display:flex; gap:6px; align-items:flex-start; border-top:1px solid var(--line) }
.list > li:first-child { border-top:0 }
.list > li.hotrow { box-shadow:inset 3px 0 0 var(--hot) }
.box { flex:none; width:44px; height:44px; display:grid; place-items:center; background:none; border:0; padding:0; cursor:pointer; margin-left:4px }
.box span { width:22px; height:22px; border:2px solid var(--ink2); border-radius:6px; display:grid; place-items:center; color:transparent }
.box span svg { width:16px; height:16px }
.box:hover span { border-color:var(--go); color:var(--go) }
.done .box span, .box:disabled span { background:var(--go); border-color:var(--go); color:var(--go-ink) }
.tl { flex:1; min-width:0; color:inherit; text-decoration:none; padding:10px 12px 10px 0; display:block }
.list > li > .tl:first-child { padding-left:14px }
.tl:hover .ttl { color:var(--acc) }
.ttl { font-weight:500 }
.ttl code { font-size:.86em }
.done .ttl { text-decoration:line-through; color:var(--ink2) }
.pv { color:var(--ink2); font-size:14px; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; margin-top:2px }
.rowmeta { display:flex; gap:6px 10px; align-items:center; font-size:13px; color:var(--ink2); margin-top:4px; flex-wrap:wrap }
.rowmeta svg { width:14px; height:14px; vertical-align:-2px; margin-right:3px }
.tk { font:600 12px ui-monospace,Menlo,monospace; color:var(--ink2); margin-right:6px; white-space:nowrap }
.pr { font-size:11px; font-weight:700; border-radius:4px; padding:0 5px; margin-right:6px; border:1px solid currentColor; vertical-align:1px; white-space:nowrap }
.pr.P0 { background:var(--p0); border-color:var(--p0); color:#fff } .pr.P1 { color:var(--p1) } .pr.P2 { color:var(--p2) } .pr.P3 { color:var(--p3) }
.back { display:inline-flex; min-height:40px; align-items:center; text-decoration:none; font-size:14px }
.crumb { font-size:13px; color:var(--ink2) }
h1.ih { font-size:22px; line-height:1.3; margin:4px 0 10px }
.note { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:6px 14px; margin:0 0 10px }
.meta { display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; color:var(--ink2); font-size:13px; margin:4px 0 8px }
.meta select { font:inherit; font-size:14px; max-width:100%; min-height:36px; padding:0 8px; border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--ink) }
.blk { padding:2px 8px; margin:0 -8px; border-radius:8px; scroll-margin-top:72px }
.blk.flash { background:var(--hl); transition:background 1.5s }
.blk h1 { font-size:24px; line-height:1.25; margin:16px 0 8px }
.blk h2 { font-size:20px; margin:24px 0 6px; padding-top:10px; border-top:1px solid var(--line) }
.blk h3 { font-size:17px; margin:18px 0 4px }
.blk ul, .blk ol { margin:4px 0; padding-left:22px }
.blk p { margin:6px 0 }
.blk code, .msg code, .ttl code { background:var(--bg); border:1px solid var(--line); border-radius:4px; padding:0 3px; font-size:.86em; overflow-wrap:anywhere }
.blk pre, .msg pre { background:var(--bg); border:1px solid var(--line); border-radius:8px; padding:10px; overflow-x:auto; font-size:13px; white-space:pre-wrap }
.blk pre code, .msg pre code { border:0; padding:0; background:none }
.tbl { overflow-x:auto; margin:6px 0 }
.blk table { border-collapse:collapse; font-size:14px }
.blk td, .blk th { border:1px solid var(--line); padding:4px 8px; vertical-align:top; text-align:left }
.blk blockquote { margin:6px 0; padding:4px 12px; border-left:3px solid var(--line); color:var(--ink2) }
.thread { margin:6px 0 10px 22px; display:grid; gap:8px }
.page .thread { margin:10px 0 }
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
  display:inline-flex; align-items:center; gap:6px; border-radius:8px; text-decoration:none }
.lnk:hover { background:var(--card) }
.lnk svg { width:16px; height:16px }
@media (hover:hover) and (pointer:fine) { .act.quiet { opacity:0 } .blk:hover .act.quiet, .act.quiet:focus-within { opacity:1 } }
form.cmp { margin:4px 0 12px 22px; display:grid; gap:8px }
.page form.cmp { margin:12px 0 }
textarea { font:inherit; font-size:16px; width:100%; min-height:96px; padding:10px; border-radius:10px; border:1px solid var(--line);
  background:var(--card); color:var(--ink); resize:vertical }
textarea:focus-visible, button:focus-visible, select:focus-visible, a:focus-visible { outline:2px solid var(--acc); outline-offset:2px }
.row { display:flex; gap:8px; align-items:center; flex-wrap:wrap }
.btn { font:inherit; font-size:15px; min-height:44px; padding:0 18px; border-radius:999px; border:1px solid var(--line); background:var(--card); color:var(--ink);
  cursor:pointer; display:inline-flex; align-items:center; gap:8px; text-decoration:none }
.btn.pri { background:var(--go); color:var(--go-ink); border-color:var(--go); font-weight:600 }
.btn.ok { color:var(--go); border-color:var(--go); font-weight:600 }
.btn svg { width:18px; height:18px }
.btn:disabled { opacity:.5 }
.chk { font-size:14px; color:var(--ink2); display:flex; gap:8px; align-items:center; min-height:44px; cursor:pointer }
.chk input { width:18px; height:18px; margin:0; accent-color:var(--go) }
.err { color:var(--err); font-size:14px }
details.thread summary { cursor:pointer; color:var(--ink2); font-size:14px; min-height:40px; display:flex; align-items:center; gap:6px }
.newq { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px; display:grid; gap:8px; margin:10px 0 }
.newq h2 { font-size:17px; margin:0 }
.hint { font-size:13px; color:var(--ink2); margin:0 }
.empty { color:var(--ink2); padding:24px 0; text-align:center }
@media (max-width:520px) { .thread, form.cmp { margin-left:0 } .msg.me { margin-left:16px } .act { margin-left:-8px } h1.ph { font-size:24px } }
</style></head><body>
<header><div class="bar" id="bar"></div></header>
<main id="main"></main>
<script>
const I18N = {
  en: { all:"All projects", more:"More", home:"Home", docs:{QUESTIONS:"Questions",TODO:"To-dos",STATE:"State",LOG:"Log",DECISIONS:"Decisions",CONTEXT:"Context",PITFALLS:"Pitfalls",CONVENTIONS:"Conventions",OPERATIONS:"Operations"},
    spec:"Spec · ", review:"Review · ", ask:"Ask the agent", askHint:"The agent reads the repository and answers here, usually within a minute. The question goes to Questions, section “Questions for the agent”.",
    askHintOff:"Auto-answer is off: the question goes to Questions, the agent answers in its next working session.", askPh:"e.g. why does the September total differ from the sheet?",
    askBtn:"Ask", project:"Project", msgs:(n)=>n+(n===1?" message":" messages"), running:"agent is writing", queued:"queued", failed:"agent failed", waiting:"no answer", fresh:"new answer",
    forYou:"Waiting for you", forYouPill:"for you", check:"check", agentDec:"Agent's decisions: check, revert if needed", recent:"Latest discussions", docsT:"Documents",
    open:(n)=>n+" open", waitN:(n)=>n+" waiting for you", topics:(n)=>n+(n===1?" topic":" topics"), allClear:"Nothing is waiting for you.", projects:"Projects",
    markDone:"Mark done", doneN:(n)=>"Done · "+n, notItem:"Item not found: the doc changed.", closedNote:"Discussion closed. A reply reopens it.",
    reply:"Reply", discuss:"Discuss", sections:"Sections…", notFound:"Doc not found", openDoc:"Open in the document",
    stRun:"The agent is reading the repository and writing an answer", stQueued:"The agent is queued", stErr:"The agent did not answer: ", retry:"Retry",
    stWait:"No answer yet", askNow:"Ask the agent", phReply:"Reply", phNew:"Comment or question about this item", send:"Send", cancel:"Cancel", wantAnswer:"agent answers",
    close:"Close", reopen:"Reopen", closedSum:"Discussion closed", closedPill:"closed", empty:"Empty.",
    stale:"The item changed: reload the page", offline:"Forum is not reachable", noProjects:"No agentdrop projects found. Run agentdrop in a project or add one: agentdrop forum add PATH" },
  ru: { all:"Все проекты", more:"Ещё", home:"Главная", docs:{QUESTIONS:"Вопросы",TODO:"Задачи",STATE:"Состояние",LOG:"Журнал",DECISIONS:"Решения",CONTEXT:"Контекст",PITFALLS:"Грабли",CONVENTIONS:"Правила",OPERATIONS:"Эксплуатация"},
    spec:"ТЗ · ", review:"Ревью · ", ask:"Вопрос агенту", askHint:"Агент прочитает репозиторий и ответит здесь, обычно за минуту. Вопрос ляжет в «Вопросы», раздел «Вопросы агенту».",
    askHintOff:"Автоответ выключен: вопрос ляжет в «Вопросы», агент ответит в рабочей сессии.", askPh:"Например: почему факт сентября меньше, чем в таблице?",
    askBtn:"Спросить", project:"Проект", msgs:(n)=>n+" "+pl(n,"сообщение","сообщения","сообщений"), running:"агент пишет", queued:"в очереди", failed:"агент не ответил", waiting:"без ответа", fresh:"новый ответ",
    forYou:"Ждёт вас", forYouPill:"ждёт вас", check:"проверьте", agentDec:"Решения агента: проверьте, при нужде отмените", recent:"Последние обсуждения", docsT:"Документы",
    open:(n)=>n+" "+pl(n,"открыта","открыты","открыто"), waitN:(n)=>n+" "+pl(n,"ждёт","ждут","ждут")+" вас", topics:(n)=>n+" "+pl(n,"тема","темы","тем"), allClear:"Сейчас ничего не ждёт вас.", projects:"Проекты",
    markDone:"Отметить сделанным", doneN:(n)=>"Сделано · "+n, notItem:"Пункт не найден — документ изменился.", closedNote:"Обсуждение закрыто. Ответ откроет его снова.",
    reply:"Ответить", discuss:"Обсудить", sections:"Разделы…", notFound:"Документ не найден", openDoc:"Открыть в документе",
    stRun:"Агент читает репозиторий и пишет ответ", stQueued:"Агент в очереди", stErr:"Агент не ответил: ", retry:"Повторить",
    stWait:"Ответа пока нет", askNow:"Спросить агента", phReply:"Ответ", phNew:"Комментарий или вопрос по этому пункту", send:"Отправить", cancel:"Отмена", wantAnswer:"ответ агента",
    close:"Закрыть", reopen:"Открыть снова", closedSum:"Обсуждение закрыто", closedPill:"закрыто", empty:"Пусто.",
    stale:"Пункт изменился — обновите страницу", offline:"Нет связи с форумом", noProjects:"Проектов agentdrop не найдено. Запустите agentdrop в проекте или добавьте: agentdrop forum add ПУТЬ" } };
function pl(n, a, b, c) { const x = n % 10, y = n % 100; return x === 1 && y !== 11 ? a : x >= 2 && x <= 4 && (y < 12 || y > 14) ? b : c; }
const TABS = ["TODO","QUESTIONS"], BOARD = ["TODO","QUESTIONS"];
const ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>';
const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
const $ = (s, r=document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const md = (s) => marked.parse(s).replace(/<table>/g, '<div class="tbl"><table>').replace(/<\/table>/g, "</table></div>");
const inl = (s) => marked.parseInline(s);
const strip = (s) => String(s || "").replace(/^\s*(?:[-*]|\d+\.)\s+/, "").replace(/[*_`#>]/g, "").replace(/\s+/g, " ").trim();
let T = I18N.en, S = { projects:[], answer:true, author:"", agent:"" }, P = "", cur = "", curT = "", TS = [], sig = {}, writing = false, askOpen = false;
const label = (n) => T.docs[n] || n.replace(/^specs\//, T.spec).replace(/^reviews\/inbox\//, T.review);
const seen = (() => { try { return JSON.parse(localStorage.getItem("af-seen") || "{}"); } catch { return {}; } })();
const saveSeen = () => { try { localStorage.setItem("af-seen", JSON.stringify(seen)); } catch {} };
const skey = (t) => t.stamp + "|" + t.count;
const isNew = (t) => t.last === S.agent && seen[(t.p || P) + ":" + t.tid] !== skey(t);
const waits = (t) => t.cat === "you" && t.status !== "closed" && t.last !== S.author;
const review = (t) => t.cat === "review" && t.status !== "closed" && t.last !== S.author;
const hot = (t) => waits(t) || isNew(t);
const nHot = (f) => TS.filter(t => hot(t) && f(t)).length;
const proj = () => S.projects.find(p => p.id === P);
const href = (p, doc, t) => "#" + [p, doc].filter(Boolean).map(encodeURIComponent).join("/") + (t ? "~" + t : "");
const go = (p, doc, t) => { location.hash = href(p, doc, t).slice(1); };
const when = (s) => { const m = String(s || "").match(/(\d+)\.(\d+)(?: (\d+):(\d+))?/); return m ? (+m[2])*1e6 + (+m[1])*1e4 + (+(m[3]||0))*100 + (+(m[4]||0)) : 0; };
const byTime = (l) => l.slice().sort((a, b) => when(b.stamp) - when(a.stamp));
const changed = (k, data, force) => { const s = JSON.stringify(data); if (!force && sig[k] === s) return false; sig[k] = s; return true; };

function route() {
  const [path, t] = location.hash.slice(1).split("~");
  const [p, ...d] = path.split("/").map(decodeURIComponent);
  return { p: p || "", doc: d.join("/"), t: t || "" };
}
const KEY = (() => {
  const k = new URLSearchParams(location.search).get("k");
  try { if (k) localStorage.setItem("af-key", k); return k || localStorage.getItem("af-key") || ""; } catch { return k || ""; }
})();
if (location.search) history.replaceState(null, "", "/" + location.hash);
const _fetch = window.fetch.bind(window);
window.fetch = (url, o = {}) => _fetch(url, { ...o, headers: { ...(o.headers || {}), "X-Forum-Key": KEY } });
function askKey(bad) {
  $("#bar").innerHTML = "";
  $("#main").innerHTML = `<form class="newq" id="keyf"><h2>Вход · Sign in</h2>
    <p class="hint">${bad ? "Ключ не подошёл. " : ""}На Mac: <code>agentdrop forum url</code>, скопируйте ключ после <code>k=</code> или всю ссылку.<br>On the Mac run <code>agentdrop forum url</code> and paste the key or the whole link.</p>
    <textarea style="min-height:60px" autocomplete="off" autocapitalize="off" spellcheck="false"></textarea>
    <div class="row"><button class="btn pri" type="submit">OK</button></div></form>`;
  $("#keyf").onsubmit = (e) => { e.preventDefault(); const v = $("#keyf textarea").value.trim(); const k = (v.match(/[?&]k=([^&#\s]+)/) || [, v])[1];
    try { localStorage.setItem("af-key", k); } catch {} location.reload(); };
}
async function boot() {
  let r; try { r = await fetch("/api/projects"); } catch { $("#main").innerHTML = `<p class="empty">${esc(T.offline)}</p>`; return; }
  if (r.status === 401) return askKey(!!KEY);
  S = await r.json();
  T = I18N[S.lang] || I18N.en; document.documentElement.lang = S.lang;
  window.onhashchange = show; show(); setInterval(tick, 4000);
}

/* ---- navigation ---- */
function bar() {
  const pr = proj(), names = pr ? pr.docs : [];
  const tab = (doc, t, n) => `<button data-doc="${esc(doc)}" class="${pr && cur.replace(/^·/, '')===doc ? 'on' : ''}">${t}${n ? `<i class="badge">${n}</i>` : ""}</button>`;
  const more = names.filter(n => !TABS.includes(n));
  const cnt = (p) => nHot(t => t.p === p);
  let h = "";
  if (S.projects.length > 1) {
    h += `<select class="proj" id="proj" aria-label="${T.project}"><option value="">${T.all}${nHot(() => true) ? " (" + nHot(() => true) + ")" : ""}</option>`
      + S.projects.map(p => `<option value="${esc(p.id)}" ${p.id===P?'selected':''}>${esc(p.id)}${cnt(p.id) ? " (" + cnt(p.id) + ")" : ""}</option>`).join("") + `</select>`;
    const others = nHot(t => t.p !== P);
    if (pr && others) h += `<button class="badge lone" data-all title="${esc(T.all)}">+${others}</button>`;
    h += `<span class="sep"></span>`;
  }
  if (pr) h += tab("", T.home, cnt(P)) + TABS.filter(n => names.includes(n)).map(n => tab(n, label(n), nHot(t => t.p === P && t.doc === n))).join("")
    + (more.length ? `<select id="more" aria-label="${T.more}"><option value="">${T.more}</option>${more.map(n => `<option value="${esc(n)}" ${n===cur?'selected':''}>${esc(label(n))}</option>`).join("")}</select>` : "");
  else h += `<button class="on" data-doc="">${T.home}${nHot(() => true) ? `<i class="badge">${nHot(() => true)}</i>` : ""}</button>`;
  $("#bar").innerHTML = h;
  const ps = $("#proj"); if (ps) ps.onchange = () => go(ps.value, "");
  const m = $("#more"); if (m) m.onchange = () => m.value && go(P, m.value);
  const a = $("[data-all]"); if (a) a.onclick = () => go("", "");
  $("#bar").querySelectorAll("[data-doc]").forEach(b => b.onclick = () => go(P, b.dataset.doc));
  const on = $("#bar button.on"); on && on.scrollIntoView({ block:"nearest", inline:"nearest" });
}
function show() {
  const r = route(); P = r.p || (S.projects.length === 1 ? S.projects[0].id : ""); cur = r.doc; curT = r.t; writing = false; sig = {};
  if (!curT) scrollTo(0, 0);
  render(true);
}
async function loadThreads() { try { TS = await (await fetch("/api/threads")).json(); } catch {} }
async function render(force) {
  await loadThreads(); bar();
  if (writing) return;
  if (!S.projects.length) { $("#main").innerHTML = `<p class="empty">${esc(T.noProjects)}</p>`; return; }
  if (!proj()) return allHome(force);
  if (!cur) return home(force);
  if (BOARD.includes(cur) && curT) return item(force);
  if (cur === "TODO") return todos(force);
  if (cur === "QUESTIONS") return qboard(force);
  return doc(force, curT);
}
function tick() { if (!document.hidden) render(false); }
async function getBoard(name) {
  const r = await fetch("/api/board?p=" + encodeURIComponent(P) + "&name=" + encodeURIComponent(name)).catch(() => null);
  return r && r.ok ? r.json() : null;
}
const items = (d, open) => d ? d.groups.filter(g => !open || g.cat !== "done").flatMap(g => g.items.map(i => ({ ...i, p:P, doc:d.name, group:g.path })))
  .filter(i => !open || i.status !== "closed") : [];

/* ---- small parts ---- */
function pills(t) {
  const out = [];
  if (t.status === "running" || t.status === "queued") out.push(`<span class="pill run">${t.status === "running" ? T.running : T.queued}</span>`);
  if (t.status === "error") out.push(`<span class="pill bad">${T.failed}</span>`);
  if (isNew(t)) out.push(`<span class="pill new">${T.fresh}</span>`);
  if (waits(t)) out.push(`<span class="pill hot">${T.forYouPill}</span>`);
  else if (review(t)) out.push(`<span class="pill wait">${T.check}</span>`);
  if (t.status === "waiting" && !S.answer) out.push(`<span class="pill wait">${T.waiting}</span>`);
  if (t.status === "closed" && !out.length) out.push(`<span class="pill done">${T.closedPill}</span>`);
  return out.join("");
}
const tag = (t) => (t.ticket ? `<span class="tk">${esc(t.ticket)}</span>` : "") + (t.prio ? `<span class="pr ${t.prio}">${t.prio}</span>` : "");
const card = (t) => `<a class="card" href="${href(t.p, t.doc, t.tid)}">
  <div class="top"><span>${!P ? esc(t.p) + " · " : ""}${esc(label(t.doc))}${t.count ? " · " + T.msgs(t.count) : ""}</span><span class="pills">${pills(t)}</span></div>
  <div class="t">${tag(t)}${esc(strip(t.title))}</div>
  ${t.preview ? `<div class="p">${t.last ? `<b>${esc(t.last)}, ${esc(t.stamp)}:</b> ` : ""}${esc(strip(t.preview))}</div>` : ""}</a>`;
const hotFirst = (l) => l.slice().sort((a, b) => (hot(b) - hot(a)) || when(b.stamp) - when(a.stamp));
function attention(list) {
  const l = hotFirst(list.filter(hot));
  return l.length ? `<section class="attn"><h2 class="sh">${T.forYou}<i class="badge">${l.length}</i></h2><div class="feed">${l.map(card).join("")}</div></section>` : "";
}

/* ---- all projects ---- */
function allHome(force) {
  if (!changed("all", [TS, S.projects], force)) return;
  $("#main").innerHTML = `<h1 class="ph">${T.projects}</h1>`
    + (attention(TS) || `<p class="lead">${T.allClear}</p>`)
    + `<div class="grid">${S.projects.map(p => { const n = nHot(t => t.p === p.id);
        return `<a class="tile" href="${href(p.id)}"><h2>${esc(p.id)}${n ? `<i class="badge">${n}</i>` : ""}</h2>
          <div class="cap">${label("TODO")}: ${T.open(p.todo)}</div></a>`; }).join("")}</div>`;
}

/* ---- project home ---- */
async function home(force) {
  const [td, qd] = await Promise.all([getBoard("TODO"), getBoard("QUESTIONS")]);
  const mine = TS.filter(t => t.p === P);
  if (writing || !changed("home", [td, qd, mine], force)) return;
  const ot = items(td, true), oq = items(qd, true);
  const qHot = oq.filter(hot).length, tHot = ot.filter(hot).length;
  const prios = ["P0","P1"].map(p => [p, ot.filter(i => i.prio === p).length]).filter(x => x[1]);
  const other = proj().docs.filter(n => !BOARD.includes(n));
  const li = (i) => `<li class="${hot(i) ? "hot" : ""}">${tag(i)}${esc(strip(i.title))}</li>`;
  const recent = byTime(mine.filter(t => t.count && !hot(t))).slice(0, 6);
  $("#main").innerHTML = `<h1 class="ph">${esc(P)}</h1>
    <p class="lead"><button class="btn pri" id="askb">${ICON}${T.ask}</button></p>
    ${attention(mine)}
    <div class="grid">
      ${td ? `<a class="tile" href="${href(P, "TODO")}"><h2>${label("TODO")}${tHot ? `<i class="badge">${tHot}</i>` : ""}</h2>
        <div class="big">${ot.length}</div><div class="cap">${T.open(ot.length)}${prios.map(([p, n]) => `<span class="pr ${p}">${p} · ${n}</span>`).join("")}</div>
        <ul>${ot.slice(0, 5).map(li).join("")}</ul></a>` : ""}
      ${qd ? `<a class="tile" href="${href(P, "QUESTIONS")}"><h2>${label("QUESTIONS")}${qHot ? `<i class="badge">${qHot}</i>` : ""}</h2>
        <div class="big">${qHot || oq.length}</div><div class="cap">${qHot ? T.waitN(qHot) : T.topics(oq.length)}</div>
        <ul>${hotFirst(oq).slice(0, 5).map(li).join("")}</ul></a>` : ""}
      <div class="tile"><h2>${T.docsT}</h2><ul class="docs">${other.map(n => `<li><a href="${href(P, n)}">${esc(label(n))}</a></li>`).join("")}</ul></div>
    </div>
    ${mine.some(review) ? `<h2 class="sh">${T.agentDec}</h2><div class="feed">${mine.filter(review).map(card).join("")}</div>` : ""}
    ${recent.length ? `<h2 class="sh">${T.recent}</h2><div class="feed">${recent.map(card).join("")}</div>` : ""}`;
  $("#askb").onclick = () => { askOpen = true; go(P, "QUESTIONS"); };
}

/* ---- to-dos and questions ---- */
function groups(d, row) {
  return d.groups.filter(g => g.items.length).map(g => {
    const its = g.items.map(i => ({ ...i, p:P, doc:d.name })), title = esc(g.path.replace(/ \/ /g, " · ")) || "—";
    const n = its.filter(hot).length, list = `<ul class="list">${its.map(row).join("")}</ul>`;
    if (g.cat === "done") return `<details class="grp"><summary>${title} <span class="cnt">${its.length}</span></summary>${list}</details>`;
    return `<section class="grp"><h2>${title} <span class="cnt">${its.length}</span>${n ? `<i class="badge">${n}</i>` : ""}</h2>${list}</section>`;
  }).join("");
}
const rowmeta = (i) => { const m = (i.count ? `<span>${ICON}${i.count}</span>` : "") + pills(i); return m ? `<div class="rowmeta">${m}</div>` : ""; };
async function todos(force) {
  const d = await getBoard("TODO");
  if (!d) { $("#main").innerHTML = `<p class="empty">${T.notFound}</p>`; return; }
  if (writing || !changed("todo", d, force)) return;
  const open = items(d, true).length, idx = {};
  d.groups.forEach(g => g.items.forEach(i => idx[i.tid] = { ...i, gcat: g.cat }));
  $("#main").innerHTML = `<div class="bhead"><h1>${label("TODO")}</h1><span class="cnt">${T.open(open)}</span></div>`
    + groups(d, (i) => { const done = i.status === "closed" || i.cat === "done";
      return `<li class="${done ? "done" : ""} ${hot(i) ? "hotrow" : ""}"><button class="box" data-box="${i.tid}" aria-label="${esc(T.markDone)}" ${i.cat === "done" ? "disabled" : ""}><span>${CHECK}</span></button>
        <a class="tl" href="${href(P, "TODO", i.tid)}"><div class="ttl">${tag(i)}${inl(i.title)}</div>${rowmeta(i)}</a></li>`; });
  $("#main").querySelectorAll("[data-box]").forEach(b => b.onclick = async () => {
    const i = idx[b.dataset.box];
    if (i.status === "closed") return go(P, "TODO", i.tid);
    b.closest("li").classList.add("done");
    await post("/api/close", { p:P, name:"TODO", start:i.start, hash:i.hash }); render(true);
  });
}
async function qboard(force) {
  const d = await getBoard("QUESTIONS");
  if (!d) { $("#main").innerHTML = `<p class="empty">${T.notFound}</p>`; return; }
  if (writing || !changed("q", d, force)) return;
  const n = items(d, true).filter(hot).length;
  $("#main").innerHTML = `<div class="bhead"><h1>${label("QUESTIONS")}${n ? `<i class="badge">${n}</i>` : ""}</h1><button class="btn pri" id="askb">${ICON}${T.ask}</button></div>
    <div id="askf"></div>`
    + groups(d, (i) => { const pv = i.msgs.length ? i.msgs.at(-1) : null;
      return `<li class="${hot(i) ? "hotrow" : ""}"><a class="tl" href="${href(P, "QUESTIONS", i.tid)}"><div class="ttl">${tag(i)}${inl(i.title)}</div>
        ${pv ? `<div class="pv"><b>${esc(pv.author)}, ${esc(pv.stamp)}:</b> ${esc(strip(pv.md))}</div>` : i.note ? `<div class="pv">${esc(strip(i.note))}</div>` : ""}${rowmeta(i)}</a></li>`; });
  $("#askb").onclick = askForm;
  if (askOpen) { askOpen = false; askForm(); }
}
function askForm() {
  const box = $("#askf"); if (!box || box.firstChild) return;
  box.innerHTML = `<form class="newq" id="newq"><h2>${T.ask}</h2><p class="hint">${S.answer ? T.askHint : T.askHintOff}</p>
    <textarea placeholder="${esc(T.askPh)}"></textarea>
    <div class="row"><button class="btn pri" type="submit">${T.askBtn}</button><button class="btn" type="button">${T.cancel}</button><span class="err"></span></div></form>`;
  const f = $("#newq"), ta = $("textarea", f); ta.focus(); writing = true;
  ta.onkeydown = (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) f.requestSubmit(); };
  $("button[type=button]", f).onclick = () => { box.innerHTML = ""; writing = false; };
  f.onsubmit = async (e) => {
    e.preventDefault(); if (!ta.value.trim()) return;
    const r = await post("/api/topic", { p:P, text:ta.value, ask:S.answer });
    if (r.ok) { writing = false; render(true); } else $(".err", f).textContent = r.error;
  };
}

/* ---- one item: its own page with the discussion ---- */
async function item(force) {
  const d = await getBoard(cur);
  const g = d && d.groups.find(g => g.items.some(i => i.tid === curT));
  const it = g && { ...g.items.find(i => i.tid === curT), p:P, doc:cur };
  if (!it) { $("#main").innerHTML = `<a class="back" href="${href(P, cur)}">← ${esc(label(cur))}</a><p class="empty">${T.notItem}</p>`; return; }
  if (writing || !changed("item", it, force)) return;
  if (it.msgs.length && it.last === S.agent) { seen[P + ":" + it.tid] = skey(it); saveSeen(); bar(); }
  const closedT = it.status === "closed", done = closedT || it.cat === "done";
  const msgs = it.msgs.map(m => `<div class="msg ${m.author === S.agent ? "" : "me"}"><div class="who"><b>${esc(m.author)}</b><span>${esc(m.stamp)}</span></div>${md(m.md)}</div>`).join("");
  $("#main").innerHTML = `<div class="page"><a class="back" href="${href(P, cur)}">← ${esc(label(cur))}</a>
    <div class="crumb">${esc(g.path.replace(/ \/ /g, " · "))}</div>
    <h1 class="ih">${tag(it)}${inl(it.title)}</h1>
    <div class="rowmeta" style="margin-bottom:10px">${pills(it)}</div>
    ${it.note ? `<div class="note blk">${md(it.note)}</div>` : ""}
    ${!done ? `<div class="row"><button class="btn ok" id="done">${CHECK}${cur === "TODO" ? T.markDone : T.close}</button></div>` : ""}
    ${it.msgs.length ? `<div class="thread">${msgs}${status(it)}</div>` : ""}
    ${closedT ? `<p class="hint">${T.closedNote}</p>` : ""}
    <form class="cmp" id="cmp"><textarea placeholder="${esc(it.msgs.length ? T.phReply : T.phNew)}"></textarea>
      <div class="row"><button class="btn pri" type="submit">${closedT ? T.reopen : T.send}</button>
      ${S.answer ? `<label class="chk"><input type="checkbox" checked> ${T.wantAnswer}</label>` : ""}</div><span class="err"></span></form>
    <p><a class="lnk" href="${href(P, "·" + cur, it.tid)}">${T.openDoc}</a></p></div>`;
  const dn = $("#done"); if (dn) dn.onclick = async () => { dn.disabled = true; await post("/api/close", { p:P, name:cur, start:it.start, hash:it.hash }); render(true); };
  $("#main").querySelectorAll("[data-retry]").forEach(b => b.onclick = async () => { await post("/api/retry", { p:P, name:cur, head:it.msgs.at(-1).head }); render(true); });
  const f = $("#cmp"), ta = $("textarea", f);
  ta.oninput = () => writing = !!ta.value.trim();
  ta.onkeydown = (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) f.requestSubmit(); };
  f.onsubmit = async (e) => {
    e.preventDefault(); if (!ta.value.trim()) return;
    const sub = $("button[type=submit]", f); sub.disabled = true;
    const r = await post("/api/comment", { p:P, name:cur, start:it.start, hash:it.hash, text:ta.value, ask:!!$("input[type=checkbox]", f)?.checked });
    if (r.ok) { writing = false; render(true); } else { sub.disabled = false; $(".err", f).textContent = r.error === "stale" ? T.stale : r.error; }
  };
  if (force) scrollTo(0, 0);
}

/* ---- any doc as a page, with threads under items ---- */
async function doc(force, focusT) {
  const name = cur.replace(/^·/, "");
  const r = await fetch("/api/doc?p=" + encodeURIComponent(P) + "&name=" + encodeURIComponent(name)).catch(() => null);
  if (!r || !r.ok) { if (force) $("#main").innerHTML = `<p class="empty">${T.notFound}</p>`; return; }
  const d = await r.json();
  if (writing || !changed("doc", [d.mtime, d.busy, d.blocks.map(b => b.status)], force)) return;
  const y = scrollY;
  const heads = d.blocks.filter(b => b.kind === "heading" && /^#{2,3} /.test(b.body));
  $("#main").innerHTML = `<div class="meta"><span>${esc(P)} · ${esc(d.path)}</span>${heads.length > 3 ? `<select id="toc" aria-label="${T.sections}"><option value="">${T.sections}</option>${heads.map(b => `<option value="${b.start}">${esc(b.body.replace(/^#+\s*/, "").trim().slice(0,70))}</option>`).join("")}</select>` : ""}</div>`
    + d.blocks.map(block).join("");
  const toc = $("#toc"); if (toc) toc.onchange = () => { document.querySelector(`[data-s="${toc.value}"]`)?.scrollIntoView({ behavior:"smooth" }); toc.value = ""; };
  $("#main").querySelectorAll("[data-c]").forEach(btn => btn.onclick = () => compose(btn, d.blocks[+btn.dataset.c], name));
  $("#main").querySelectorAll("[data-close]").forEach(btn => btn.onclick = async () => { const b = d.blocks[+btn.dataset.close]; await post("/api/close", { p:P, name, start:b.start, hash:b.hash }); render(true); });
  $("#main").querySelectorAll("[data-retry]").forEach(btn => btn.onclick = async () => { await post("/api/retry", { p:P, name, head:d.blocks[+btn.dataset.retry].msgs.at(-1).head }); render(true); });
  d.blocks.forEach(b => { if (b.msgs.length && b.msgs.at(-1).author === S.agent) seen[P + ":" + b.tid] = skey({ stamp:b.msgs.at(-1).stamp, count:b.msgs.length }); }); saveSeen();
  if (force && focusT) { const el = document.getElementById("t-" + focusT); if (el) { el.scrollIntoView({ block:"start" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600); } }
  else if (force) scrollTo(0, 0); else scrollTo(0, y);
  if (force) { await loadThreads(); bar(); }
}
function block(b, i) {
  const can = b.kind === "item" || b.kind === "para";
  let h = `<div class="blk ${b.kind}" id="t-${b.tid}" data-s="${b.start}">${md(b.body)}`;
  const msgs = b.msgs.map(m => `<div class="msg ${m.author===S.agent?"":"me"}"><div class="who"><b>${esc(m.author)}</b><span>${esc(m.stamp)}</span></div>${md(m.md)}</div>`).join("");
  if (b.status === "closed") h += `<details class="thread"><summary>${T.closedSum} · ${T.msgs(b.msgs.length)}</summary>${msgs}</details>`;
  else if (b.msgs.length) h += `<div class="thread">${msgs}${status(b, i)}</div>`;
  if (can) h += `<div class="act ${b.msgs.length ? "" : "quiet"}"><button class="lnk" data-c="${i}">${ICON}${b.status === "closed" ? T.reopen : b.msgs.length ? T.reply : T.discuss}</button>`
    + (b.msgs.length && b.status !== "closed" ? `<button class="lnk" data-close="${i}">${CHECK}${T.close}</button>` : "") + `</div>`;
  return h + "</div>";
}
function status(b, i = 0) {
  if (b.status === "running") return `<div class="state" role="status"><span class="pulse"></span>${T.stRun}</div>`;
  if (b.status === "queued") return `<div class="state" role="status"><span class="pulse"></span>${T.stQueued}</div>`;
  if (b.status === "error") return `<div class="state err">${T.stErr}${esc(b.error)} <button class="lnk" data-retry="${i}">${T.retry}</button></div>`;
  if (b.status === "waiting" && S.answer) return `<div class="state">${T.stWait} <button class="lnk" data-retry="${i}">${T.askNow}</button></div>`;
  return "";
}
function compose(btn, b, name) {
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
    const r = await post("/api/comment", { p:P, name, start:b.start, hash:b.hash, text:ta.value, ask:!!$("input[type=checkbox]", f)?.checked });
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
