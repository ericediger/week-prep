#!/usr/bin/env python3
"""
serve.py — tiny local server for Week Prep.

Run it from (or point it at) the folder that holds Home.html and your WO-* week
folders, and the app becomes reachable from any device on your network — phones,
tablets, other laptops — and readable by browser-based AI agents.

    python3 serve.py                 # serve this folder on port 8877
    python3 serve.py --port 9000
    python3 serve.py --root "/path/to/week folder"
    python3 serve.py --no-key        # disable the access key (LAN-trusting)

Endpoints
    /                      the app (Home.html) in HTTP mode — full read/write
    /brief                 the current week as a clean, agent-friendly page
    /brief?week=WO-260907  a specific week
    /brief.txt             same, as plain text / markdown
    /api/ls/<dir>          directory listing            (JSON)
    /api/file/<path>       read a file; PUT to save todo-state.json / projects.json

Access key
    On first run a random key is generated and stored in .serve-key next to this
    script. Every URL needs ?key=<key> once per browser (a cookie remembers it),
    or send it as an X-Key header. Delete .serve-key to rotate the key.

Python 3.8+, standard library only.
"""
import argparse, html, json, mimetypes, os, re, secrets, socket, sys, tempfile, urllib.parse
from datetime import date, datetime
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
KEY = None
WRITABLE = re.compile(r"^(projects\.json|WO-[^/]+/todo-state\.json)$")
STATIC_HTML = re.compile(r"^/[A-Za-z0-9 _.\-]+\.html$")
PLAN_OPTS = "Mon / Tue / Wed / Thu / Fri / Next wk / Done / Not doing"


# ----------------------------------------------------------------------------- helpers
def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def load_key(root, disable, explicit):
    if disable:
        return None
    if explicit:
        return explicit
    p = os.path.join(root, ".serve-key")
    try:
        k = open(p, encoding="utf-8").read().strip()
        if k:
            return k
    except FileNotFoundError:
        pass
    k = secrets.token_urlsafe(18)
    with open(p, "w", encoding="utf-8") as f:
        f.write(k + "\n")
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return k


def week_label(name):
    m = re.match(r"WO-(\d{2})(\d{2})(\d{2})$", name or "")
    if not m:
        return ""
    try:
        mon = date(2000 + int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return ""
    fri = date.fromordinal(mon.toordinal() + 4)
    if mon.month == fri.month:
        return f"Week of {mon.strftime('%B')} {mon.day}–{fri.day}"
    return f"Week of {mon.strftime('%B')} {mon.day} – {fri.strftime('%B')} {fri.day}"


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def atomic_write(path, data: bytes):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def week_dirs(root):
    out = []
    for n in os.listdir(root):
        if n.upper().startswith("WO-") and os.path.isdir(os.path.join(root, n)):
            out.append(n)
    return sorted(out, reverse=True)


# ----------------------------------------------------------------------------- brief
def due_text(d):
    if not d:
        return ""
    try:
        dt = datetime.strptime(d[:10], "%Y-%m-%d").date()
    except ValueError:
        return d
    days = (dt - date.today()).days
    s = dt.strftime("%b %-d")
    if days < 0:
        s += f" (overdue {-days}d)"
    elif days == 0:
        s += " (today)"
    elif days <= 7:
        s += f" (in {days}d)"
    return s


def unesc(s):
    return html.unescape(str(s or ""))


def build_brief(root, week_name=None, host=""):
    weeks = [w for w in week_dirs(root) if os.path.isfile(os.path.join(root, w, "todo-state.json"))]
    if not weeks:
        return "# Week Prep\n\nNo ingested weeks yet.\n"
    if week_name and week_name in weeks:
        wk = week_name
    else:
        wk = weeks[0]
    st = read_json(os.path.join(root, wk, "todo-state.json"))
    try:
        pj = read_json(os.path.join(root, "projects.json"))
    except Exception:
        pj = {}
    projects = {p["id"]: p for p in pj.get("projects", []) if "id" in p}
    themes = {t["id"]: t for t in pj.get("themes", []) if "id" in t}

    items = st.get("items", [])
    live = [i for i in items if not i.get("dismissed")]
    resolved = lambda i: i.get("done") or i.get("plan") == "Not doing"
    open_items = [i for i in live if not resolved(i)]
    done_items = [i for i in live if i.get("done")]
    not_doing = [i for i in live if i.get("plan") == "Not doing" and not i.get("done")]
    removed = [i for i in items if i.get("dismissed")]
    prio_rank = {"High": 0, "Medium": 1, "Low": 2}

    def due_key(i):
        d = i.get("due") or ""
        return d if d else "9999"

    open_items.sort(key=lambda i: (prio_rank.get(i.get("prio"), 1), due_key(i)))
    high = sum(1 for i in open_items if i.get("prio") == "High")
    soon = sum(1 for i in open_items if i.get("due") and due_text(i["due"]).find("(") >= 0)
    scheduled = sum(1 for i in open_items if i.get("plan"))
    used_projects = set()

    L = []
    L.append(f"# Week Prep — {wk} ({week_label(wk) or st.get('label','')})")
    L.append(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · state last saved {st.get('updated','?')[:16].replace('T',' ')}")
    if len(weeks) > 1:
        L.append("Other weeks available: " + ", ".join(weeks[1:6]) + (" …" if len(weeks) > 6 else "") + "  (add ?week=WO-YYMMDD)")
    L.append("")
    L.append(f"Summary: {len(live)} items · {len(open_items)} open · {high} high priority · {soon} due within 7 days or overdue · {scheduled} scheduled · {len(done_items)} done")
    L.append("")
    L.append(f"## Open items ({len(open_items)}) — sorted by priority, then due date")
    L.append("")
    for n, i in enumerate(open_items, 1):
        L.append(f"{n}. [{i.get('prio','Medium')}] {unesc(i.get('item'))}")
        det = unesc(i.get("detail"))
        if det and det != "—":
            L.append(f"   Detail: {det}")
        meta = []
        if i.get("due"):
            meta.append("Due: " + due_text(i["due"]))
        meta.append("Plan: " + (i.get("plan") or "not scheduled"))
        if i.get("theme"):
            t = themes.get(i["theme"])
            meta.append("Theme: " + i["theme"] + (f" ({t['name']})" if t and t.get("name") else ""))
        if i.get("project"):
            p = projects.get(i["project"])
            used_projects.add(i["project"])
            meta.append("Project: " + i["project"] + (f" ({p['name']})" if p and p.get("name") else ""))
        if i.get("cat"):
            meta.append("Category: " + unesc(i["cat"]))
        L.append("   " + " · ".join(meta))
        if i.get("carriedFrom"):
            age = i.get("carryAge") or 1
            L.append(f"   Carried over from {i['carriedFrom']}" + (f" ({age} weeks running)" if age > 1 else ""))
        subs = i.get("subtasks") or []
        if subs:
            d = sum(1 for s in subs if s.get("done"))
            L.append(f"   Subtasks ({d}/{len(subs)} done): " + "; ".join(("[x] " if s.get("done") else "[ ] ") + unesc(s.get("text")) for s in subs))
        if i.get("notes"):
            L.append(f"   Notes: {unesc(i['notes'])}")
        if i.get("ctx"):
            L.append(f"   Context: {unesc(i['ctx'])}")
        if i.get("source"):
            L.append(f"   Source: {unesc(i['source'])}")
        L.append("")

    if done_items:
        L.append(f"## Done this week ({len(done_items)})")
        for i in done_items:
            L.append(f"- {unesc(i.get('item'))}")
        L.append("")
    if not_doing:
        L.append(f"## Marked 'Not doing' ({len(not_doing)})")
        for i in not_doing:
            L.append(f"- {unesc(i.get('item'))}")
        L.append("")
    if removed:
        L.append(f"## Removed as not relevant ({len(removed)}) — do not resurface these")
        for i in removed:
            r = (i.get("dismissed") or {}).get("reason", "")
            L.append(f"- {unesc(i.get('item'))}" + (f" ({r})" if r else ""))
        L.append("")
    if used_projects:
        L.append("## Projects referenced above")
        for pid in sorted(used_projects):
            p = projects.get(pid, {})
            L.append(f"- {pid} — {p.get('name', pid)}" + (f": {p.get('blurb')}" if p.get("blurb") else ""))
            if p.get("llm") and (p["llm"].get("tool") or p["llm"].get("name")):
                L.append(f"  Lives in: {' / '.join(x for x in [p['llm'].get('tool'), p['llm'].get('name')] if x)}")
        L.append("")
    L.append("## How to act on this")
    base = f"http://{host}" if host else ""
    L.append(f"This page is read-only. To change items open the app at {base}/ (same key) — open the week, then:")
    L.append(f"- Plan column: {PLAN_OPTS}")
    L.append("- Priority column: High / Medium / Low · Checkbox marks done · '+ Add item' creates a task · expand a row (▸) for context, subtasks and 'Remove item'")
    L.append(f"- Raw data: {base}/api/file/{wk}/todo-state.json")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------- handler
class Handler(BaseHTTPRequestHandler):
    server_version = "WeekPrep/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s  %s  %s\n" % (datetime.now().strftime("%H:%M:%S"), self.address_string(), fmt % args))

    # --- plumbing
    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=(), head_only=False):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if not head_only and self.command != "HEAD":
            self.wfile.write(body)

    def _authed(self):
        """Returns (ok, extra_headers). Accepts ?key=, X-Key header, or the cookie set earlier."""
        if not KEY:
            return True, ()
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        if q.get("key", [None])[0] == KEY:
            return True, (("Set-Cookie", f"wpkey={KEY}; Path=/; SameSite=Lax"),)
        if self.headers.get("X-Key") == KEY:
            return True, ()
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        if "wpkey" in c and c["wpkey"].value == KEY:
            return True, ()
        return False, ()

    def _safe(self, rel):
        """Map a URL path fragment to a real path inside ROOT; refuse traversal and dotfiles."""
        rel = urllib.parse.unquote(rel).strip("/")
        parts = [p for p in rel.split("/") if p]
        if any(p.startswith(".") or p == ".." for p in parts):
            return None, None
        full = os.path.realpath(os.path.join(ROOT, *parts)) if parts else ROOT
        if full != ROOT and not full.startswith(ROOT + os.sep):
            return None, None
        return "/".join(parts), full

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    # --- routes
    def do_HEAD(self):
        self._route()

    def do_GET(self):
        self._route()

    def do_PUT(self):
        self._route()

    def _route(self):
        ok, extra = self._authed()
        if not ok:
            return self._send(403, "Forbidden — this server needs ?key=<your key> in the URL (see the terminal where serve.py is running).", extra=extra)
        url = urllib.parse.urlsplit(self.path)
        path = url.path
        q = urllib.parse.parse_qs(url.query)
        try:
            if self.command == "PUT":
                return self._put(path, extra)
            if path in ("/", "/index.html"):
                path = "/Home.html"
            if path in ("/brief", "/brief.txt"):
                text = build_brief(ROOT, q.get("week", [None])[0], self.headers.get("Host", ""))
                if path.endswith(".txt"):
                    return self._send(200, text, "text/markdown; charset=utf-8", extra)
                page = ("<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                        "<title>Week Prep brief</title>"
                        "<pre style='white-space:pre-wrap;font:14px/1.55 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:900px;margin:24px auto;padding:0 20px;color:#1c2024'>"
                        + html.escape(text) + "</pre>")
                return self._send(200, page, "text/html; charset=utf-8", extra)
            if path == "/api/ls" or path.startswith("/api/ls/"):
                rel, full = self._safe(path[len("/api/ls"):])
                if full is None or not os.path.isdir(full):
                    return self._send(404, "not a directory", extra=extra)
                out = []
                for n in sorted(os.listdir(full)):
                    if n.startswith(".") or n == ".serve-key":
                        continue
                    p = os.path.join(full, n)
                    out.append({"name": n, "kind": "directory" if os.path.isdir(p) else "file"})
                return self._send(200, json.dumps(out), "application/json; charset=utf-8", extra)
            if path.startswith("/api/file/"):
                rel, full = self._safe(path[len("/api/file/"):])
                if full is None or not os.path.isfile(full):
                    return self._send(404, "not found", extra=extra)
                ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                if full.lower().endswith(".eml"):
                    ctype = "message/rfc822"
                if ctype.startswith("text/") or ctype.endswith("json"):
                    ctype += "; charset=utf-8"
                if self.command == "HEAD":
                    return self._send(200, b"", ctype, extra, head_only=True)
                with open(full, "rb") as f:
                    return self._send(200, f.read(), ctype, extra)
            if STATIC_HTML.match(path):
                rel, full = self._safe(path)
                if full and os.path.isfile(full):
                    with open(full, "rb") as f:
                        return self._send(200, f.read(), "text/html; charset=utf-8", extra)
            return self._send(404, "not found", extra=extra)
        except Exception as e:  # never let a bad request kill the thread silently
            self.log_message("ERROR %s", e)
            return self._send(500, "server error: %s" % e, extra=extra)

    def _put(self, path, extra):
        if not path.startswith("/api/file/"):
            return self._send(405, "PUT only allowed on /api/file/…", extra=extra)
        rel, full = self._safe(path[len("/api/file/"):])
        if full is None or not WRITABLE.match(rel):
            return self._send(403, "only todo-state.json and projects.json are writable", extra=extra)
        if not os.path.isdir(os.path.dirname(full)):
            return self._send(404, "week folder does not exist", extra=extra)
        body = self._read_body()
        try:
            json.loads(body.decode("utf-8"))
        except Exception as e:
            return self._send(400, "body must be valid JSON: %s" % e, extra=extra)
        atomic_write(full, body)
        return self._send(204, b"", extra=extra)


# ----------------------------------------------------------------------------- main
def main():
    global ROOT, KEY
    ap = argparse.ArgumentParser(description="Serve the Week Prep app on your local network.")
    ap.add_argument("--port", type=int, default=8877)
    ap.add_argument("--root", default=ROOT, help="folder holding Home.html and the WO-* week folders")
    ap.add_argument("--bind", default="0.0.0.0", help="address to bind (default: all interfaces)")
    ap.add_argument("--key", default=None, help="use this access key instead of the stored/generated one")
    ap.add_argument("--no-key", action="store_true", help="disable the access key entirely")
    a = ap.parse_args()
    ROOT = os.path.realpath(a.root)
    if not os.path.isfile(os.path.join(ROOT, "Home.html")):
        print(f"warning: no Home.html in {ROOT} — the app won't load, but /brief and /api still work", file=sys.stderr)
    KEY = load_key(ROOT, a.no_key, a.key)
    qs = f"?key={KEY}" if KEY else ""
    ip = lan_ip()
    srv = ThreadingHTTPServer((a.bind, a.port), Handler)
    print(f"Week Prep server · folder: {ROOT}")
    print(f"  This machine:   http://localhost:{a.port}/{qs}")
    print(f"  Your network:   http://{ip}:{a.port}/{qs}")
    print(f"  Agent brief:    http://{ip}:{a.port}/brief{qs}")
    if KEY:
        print("  Key stored in .serve-key (delete it to generate a new one). Use --no-key to disable.")
    else:
        print("  No access key — anyone on your network can read and edit.")
    print("Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
