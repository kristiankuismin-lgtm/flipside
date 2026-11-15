"""People who are building something nobody has heard of yet.

There are three cohorts in this product and they are three different moments
in the same life. "Founded before" is the person who has already done it -
the strongest signal there is, and the one every other fund can also see.
"Building in public" is the person who shipped a thing and posted it, which
is earlier and quieter. This is the one before that.

Building in private is not a mood, it is a measurable state: there is a real
artifact, it is being worked on, and almost nobody has seen it. A repository
started ten weeks ago with commits in it this week and four stars is a
person who is building something and has not told anyone. That is the moment
an investor wants, and it is the moment that is hardest to buy, because no
database sells it - it has not happened yet.

Four signals, which are the four the brief named:

  what they build      GitHub repository search. The repo is the evidence and
                       it is linked directly, so the claim can be clicked.
  hackathons           Devpost. A hackathon submission is somebody choosing to
                       build under time pressure in public, and the project
                       page names the event and usually links the repo.
  what rooms           Hacker News comments on stories in the thesis area. Not
                       who posts - who turns up in the thread.
  communities          GitHub org membership and the topic vocabulary of what
                       they build, read on drill-down.

LinkedIn is not here and will not be. It was ruled out for this product on
the first pass and routing the same data through a search engine would be
the same data by another road.

Cost, because it decides the architecture. The GitHub core API is 60 calls
an hour without a token, which is eighteen people - not a cohort. But repo
SEARCH is a separate budget, ten calls a minute, and one call returns a
hundred repositories with the owner, the description, the topics and both
timestamps. So the list is built entirely from bulk endpoints at no
per-person cost, and the core API is spent only when somebody clicks into
one person. HN and Devpost are free.

The join is on handle. A GitHub login, a Devpost member name and an HN
author are the same string often enough to be worth testing and not often
enough to assert: a handle seen in two sources is scored higher and said to
be corroborated, never silently merged.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone

import httpx

GH_SEARCH = "https://api.github.com/search/repositories"
GL_SEARCH = "https://gitlab.com/api/v4/projects"
HF_SEARCH = "https://huggingface.co/api/models"
ARXIV = "https://export.arxiv.org/api/query"
HN_SEARCH = "https://hn.algolia.com/api/v1/search"
DEVPOST = "https://devpost.com/software/search"
UA = "Flipside/0.1 (Junction hackathon; github.com/kristiankuismin-lgtm)"
DB = os.getenv("PRIVATE_DB", "private.sqlite")
TTL = 12 * 3600

# Scoring. The dominant term is sustained independent building, because that
# is the one that separates a person who is making something from a person
# who had an idea on a Saturday. Everything else adjusts it.
W_BUILDING = 34          # sustained work on a real body of code
W_DEPTH = 16             # more than one repository pointed at the same thesis
W_PRODUCT = 14           # deployed, licensed, topic-tagged: treated as a product
W_FIT = 12               # matches the thesis in the name, not just in passing
W_FRESH = 10             # still being worked on
W_QUIET = 10             # and nobody has seen it - this is the "private" part
W_HACKATHON = 14         # turned up and built under a clock
W_ROOMS = 10             # present in the conversation, not just the code
W_CORROBORATED = 8       # more than one source knows this handle
W_IDENTIFIED = 10        # Cala names the person behind the handle
W_PAPERS = 20            # publishing on the thesis, under a real name

SUSTAIN_FULL = 90        # days from first commit to last at which effort saturates
SIZE_FULL = 4000         # repository kilobytes at which "real codebase" saturates
FRESH_DAYS = 30
QUIET_STARS = 40         # above this it is not private any more
MAX_STARS = 300          # above this it is a known project, not a person starting

# A hackathon says so in the README more often than it appears on Devpost.
_HACKATHON = re.compile(r"\bhack(?:athon|s)?\b|\bjunction\b|\bhackday\b", re.I)

_NOT_A_VENTURE = re.compile(
    r"\b(awesome|tutorial|course|bootcamp|exercise|homework|assignment|"
    r"dotfiles|config|portfolio|resume|cv|blog|notes|leetcode|playground|"
    r"template|boilerplate|starter|test|demo|hello[-_ ]?world|practice|"
    r"learning|study|roadmap|cheatsheet|interview)\b", re.I)

_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "are",
         "you", "your", "our", "their", "who", "what", "how", "why", "all",
         "any", "can", "will", "has", "have", "been", "build", "building",
         "company", "companies", "startup", "startups", "founder", "founders",
         "invest", "investing", "team", "teams", "market", "markets", "new"}

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("CREATE TABLE IF NOT EXISTS p (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
_lock = threading.Lock()


class Unavailable(RuntimeError):
    """A source refused. The list degrades to the sources that answered."""


def _cached(k, ttl=TTL):
    row = _conn.execute("SELECT v, ts FROM p WHERE k=?", (k,)).fetchone()
    if row and time.time() - row[1] < ttl:
        return json.loads(row[0])
    return None


def _store(k, v):
    with _lock:
        _conn.execute("REPLACE INTO p VALUES (?,?,?)", (k, json.dumps(v), time.time()))
        _conn.commit()


def _get(url, params, *, kind, cache_only=False, timeout=12.0):
    k = kind + json.dumps(params, sort_keys=True)
    hit = _cached(k)
    if hit is not None:
        return hit
    if cache_only:
        return None
    try:
        r = httpx.get(url, params=params, headers={"User-Agent": UA},
                      timeout=timeout, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if r.status_code in (403, 429):
        raise Unavailable(f"{kind}: rate limited")
    if r.status_code != 200:
        return None
    try:
        v = r.json()
    except ValueError:
        return None
    _store(k, v)
    return v


def _get_text(url, params, *, kind, cache_only=False, timeout=15.0):
    """Same cache, for a source that answers in XML rather than JSON."""
    k = kind + json.dumps(params, sort_keys=True)
    hit = _cached(k)
    if hit is not None:
        return hit
    if cache_only:
        return None
    try:
        r = httpx.get(url, params=params, headers={"User-Agent": UA},
                      timeout=timeout, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if r.status_code in (403, 429):
        raise Unavailable(f"{kind}: rate limited")
    if r.status_code != 200:
        return None
    _store(k, r.text)
    return r.text


def queries(thesis: str, *, limit: int = 3) -> list[str]:
    """Thesis sentence -> conjunctive searches, widest last.

    This is the whole difference between a cohort and a list of strangers.
    Searching "ambient", "scribe" and "clinicians" separately returns a
    Portuguese deployment environment, a Windows dictation product and an
    account called Ancient Scribe. GitHub ANDs the words in a single query,
    so searching them together returns people building ambient clinical
    scribes - which is the question that was asked. Narrowest first, then
    progressively shorter, so a thesis nobody is working on still returns
    its neighbourhood instead of nothing.
    """
    words, seen = [], set()
    for w in re.findall(r"[a-z0-9+#.-]{3,}", (thesis or "").lower()):
        if w in _STOP or w in seen:
            continue
        seen.add(w)
        words.append(w)
    if not words:
        return ["ai agents"]
    # Never back off to a single word. "ambient AI scribe for clinicians"
    # narrowed to "ambient" put a desktop wallpaper app at the top of the
    # cohort, which is the failure this whole function exists to prevent.
    # Two words is the floor; a thesis with only one content word gets it
    # because there is nothing else, and the caller sees the query used.
    out = []
    for n in (3, 2):
        if len(words) >= n:
            q = " ".join(words[:n])
            if q not in out:
                out.append(q)
    return (out or [words[0]])[:limit]


def _fit(blob_name: str, topics: list[str], desc: str, q: str) -> float:
    """How squarely a repository sits on the thesis, 0-1.

    A match in the repository name or its topics is the author declaring the
    subject. A match in the description is weaker, and a match on one word of
    three is weaker still.
    """
    want = [w for w in q.split() if w]
    if not want:
        return 0.0
    # Whole words only. Substring matching made "ambient" a name hit inside
    # "AMBIENTE-DE-HOMOLOGACAO" and "Consultoria ambiental", which is how a
    # Portuguese staging environment ended up in a clinical-AI cohort.
    name = re.sub(r"[-_.]+", " ", blob_name.lower())
    tops = re.sub(r"[-_.]+", " ", " ".join(topics).lower())
    body = desc.lower()
    hits = 0.0
    for w in want:
        # Plurals only. A looser suffix tolerance was letting "ambient" match
        # the Portuguese "ambiente", which is the exact confusion this
        # function was rewritten to stop.
        stem = re.sub(r"(?:es|s)$", "", w)
        pat = re.compile(r"\b" + re.escape(stem) + r"(?:e?s)?\b")
        if pat.search(name) or pat.search(tops):
            hits += 1.0
        elif pat.search(body):
            hits += 0.5
    return min(1.0, hits / len(want))


# ---------------------------------------------------------------- sources

def repos(qs: list[str], *, today: date, months: int = 6,
          fetcher=None, per_query: int = 100) -> list[dict]:
    """New, live, barely-starred repositories owned by individuals."""
    since = (today - timedelta(days=30 * months)).isoformat()
    alive = (today - timedelta(days=FRESH_DAYS * 2)).isoformat()
    out, seen = [], set()
    for q in qs:
        spec = (f"{q} in:name,description,topics created:>{since} "
                f"pushed:>{alive} stars:<{MAX_STARS} fork:false")
        d = (fetcher or _get)(GH_SEARCH, {"q": spec, "sort": "updated",
                                          "per_page": min(per_query, 100)},
                              kind="gh") or {}
        for r in (d.get("items") or []):
            owner = r.get("owner") or {}
            if owner.get("type") != "User" or r.get("fork"):
                continue
            name = r.get("name") or ""
            desc = (r.get("description") or "")[:200]
            if _NOT_A_VENTURE.search(f"{name} {desc}"):
                continue
            full = r.get("full_name")
            if not full or full in seen:
                continue
            topics = (r.get("topics") or [])[:10]
            fit = _fit(name, topics, desc, q)
            if fit < 0.5:
                continue      # one word of three in a description is not a match
            seen.add(full)
            out.append({
                "handle": owner.get("login"),
                "repo": full,
                "url": r.get("html_url"),
                "description": desc[:160],
                "topics": topics,
                "language": r.get("language"),
                "stars": r.get("stargazers_count", 0),
                "size_kb": r.get("size", 0),
                "issues": r.get("open_issues_count", 0),
                "homepage": (r.get("homepage") or "").strip()[:120] or None,
                "licensed": bool(r.get("license")),
                "created": (r.get("created_at") or "")[:10],
                "pushed": (r.get("pushed_at") or "")[:10],
                "fit": round(fit, 2),
                "hack_hint": bool(_HACKATHON.search(desc)),
                "query": q,
            })
    return out


def rooms(qs: list[str], *, fetcher=None, per_query: int = 60) -> dict[str, list[dict]]:
    """handle -> the thesis-relevant threads they turned up in."""
    out: dict[str, list[dict]] = {}
    for q in qs:
        d = (fetcher or _get)(HN_SEARCH, {"tags": "comment", "query": q,
                                          "hitsPerPage": per_query},
                              kind="hn") or {}
        for h in (d.get("hits") or []):
            a = (h.get("author") or "").strip()
            if not a:
                continue
            out.setdefault(a.lower(), []).append({
                "handle": a,
                "story": (h.get("story_title") or "")[:90],
                "url": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "said": re.sub(r"<[^>]+>", " ",
                               (h.get("comment_text") or ""))[:180].strip(),
                "query": q,
            })
    return out


def hackathons(qs: list[str], *, fetcher=None, pages: int = 1) -> dict[str, list[dict]]:
    """handle -> hackathon projects they were a member of."""
    out: dict[str, list[dict]] = {}
    for q in qs:
        for pg in range(1, pages + 1):
            d = (fetcher or _get)(DEVPOST, {"query": q, "format": "json",
                                            "page": pg}, kind="dp") or {}
            for s_ in (d.get("software") or []):
                for m in (s_.get("members") or []):
                    key = (m or "").strip().lower()
                    if not key:
                        continue
                    out.setdefault(key, []).append({
                        "handle": m,
                        "project": s_.get("name"),
                        "tagline": (s_.get("tagline") or "")[:140],
                        "url": s_.get("url"),
                        "tags": (s_.get("tags") or [])[:6],
                        "winner": bool(s_.get("winner")),
                        "query": q,
                    })
    return out


_DEVPOST_SKIP = {"assets", "help", "info", "info2", "secure", "post", "blog",
                 "css", "challengepost"}


def project_page(slug: str, *, cache_only=False, timeout=10.0) -> dict:
    """A Devpost project page: which hackathon, and which repository.

    The search JSON gives a Devpost member name, and a Devpost member name
    almost never equals a GitHub login - measured across three theses, the
    overlap was zero out of thirty-five. The project page is where the two
    identities actually meet, because the submission links its own repo. It
    also names the event, which the JSON does not.
    """
    k = "dpp:" + slug
    hit = _cached(k, ttl=30 * 86400)
    if hit is not None:
        return hit
    if cache_only:
        return {}
    try:
        r = httpx.get(f"https://devpost.com/software/{slug}",
                      headers={"User-Agent": UA}, timeout=timeout,
                      follow_redirects=True)
    except httpx.HTTPError:
        return {}
    if r.status_code != 200:
        return {}
    html = r.text
    repos_ = [u for u in re.findall(r'href="(https://github\.com/[^"?#]+)"', html)
              if u.count("/") >= 4]
    events = [h for h in re.findall(r'href="https://([a-z0-9-]+)\.devpost\.com', html)
              if h not in _DEVPOST_SKIP]
    repo = sorted(set(repos_))[0] if repos_ else None
    out = {
        "repo": repo,
        "handle": repo.split("/")[3] if repo else None,
        "event": events[0].replace("-", " ") if events else None,
    }
    _store(k, out)
    return out


def enrich(hack_idx: dict, *, limit: int = 12, fetcher=None) -> dict:
    """Re-key hackathon projects onto GitHub handles wherever the page says so."""
    seen, done = set(), 0
    out: dict[str, list[dict]] = {}
    for key, projects in hack_idx.items():
        for pr in projects:
            url = pr.get("url") or ""
            slug = url.rstrip("/").split("/")[-1]
            if slug and slug not in seen and done < limit:
                seen.add(slug)
                done += 1
                extra = (fetcher or project_page)(slug)
                if extra.get("event"):
                    pr["event"] = extra["event"]
                if extra.get("repo"):
                    pr["repo"] = extra["repo"]
                if extra.get("handle"):
                    pr["github"] = extra["handle"]
            tgt = (pr.get("github") or pr["handle"]).lower()
            out.setdefault(tgt, []).append(pr)
    return out


def gitlab(qs: list[str], *, today: date, months: int = 6,
           fetcher=None, per_query: int = 50) -> list[dict]:
    """The same question asked of the other code host.

    Not everyone building something is on GitHub, and a cohort that only
    looks at one host quietly says the others do not exist.
    """
    alive = (today - timedelta(days=FRESH_DAYS * 2)).isoformat()
    out, seen = [], set()
    for q in qs:
        d = (fetcher or _get)(GL_SEARCH, {"search": q, "order_by": "last_activity_at",
                                          "sort": "desc", "per_page": per_query,
                                          "last_activity_after": alive},
                              kind="gl")
        for r in (d or []):
            if not isinstance(r, dict):
                continue
            ns = r.get("namespace") or {}
            if ns.get("kind") != "user":
                continue        # a group is a company, not a person starting one
            full = r.get("path_with_namespace") or ""
            name = (r.get("path") or "").strip()
            desc = (r.get("description") or "")[:200]
            if not full or full in seen or _NOT_A_VENTURE.search(f"{name} {desc}"):
                continue
            topics = (r.get("topics") or r.get("tag_list") or [])[:10]
            fit = _fit(name, topics, desc, q)
            if fit < 0.5:
                continue
            seen.add(full)
            stars = r.get("star_count", 0)
            if stars >= MAX_STARS:
                continue
            out.append({
                "handle": ns.get("path"), "repo": full, "host": "gitlab",
                "url": r.get("web_url") or f"https://gitlab.com/{full}",
                "description": desc[:160], "topics": topics,
                "language": None, "stars": stars, "size_kb": 0,
                "issues": r.get("open_issues_count", 0) or 0,
                "homepage": None, "licensed": False,
                "created": (r.get("created_at") or "")[:10],
                "pushed": (r.get("last_activity_at") or "")[:10],
                "fit": round(fit, 2),
                "hack_hint": bool(_HACKATHON.search(desc)), "query": q,
            })
    return out


def models(qs: list[str], *, fetcher=None, per_query: int = 30) -> list[dict]:
    """Published models. For an AI thesis this is the artifact itself."""
    out, seen = [], set()
    for q in qs:
        d = (fetcher or _get)(HF_SEARCH, {"search": q, "limit": per_query,
                                          "sort": "lastModified",
                                          "direction": -1}, kind="hf")
        for m in (d or []):
            if not isinstance(m, dict):
                continue
            mid = m.get("id") or ""
            if "/" not in mid or mid in seen:
                continue
            owner, short = mid.split("/", 1)
            fit = _fit(short, m.get("tags") or [], "", q)
            if fit < 0.5:
                continue
            seen.add(mid)
            out.append({
                "handle": owner, "repo": mid, "host": "huggingface",
                "url": f"https://huggingface.co/{mid}",
                "description": f"published model · {m.get('downloads', 0)} downloads",
                "topics": (m.get("tags") or [])[:8], "language": None,
                "stars": m.get("likes", 0) or 0, "size_kb": 0, "issues": 0,
                "homepage": None, "licensed": False,
                "created": (m.get("createdAt") or m.get("lastModified") or "")[:10],
                "pushed": (m.get("lastModified") or "")[:10],
                "fit": round(fit, 2), "hack_hint": False, "query": q,
            })
    return out


def papers(qs: list[str], *, fetcher=None, per_query: int = 25) -> dict[str, list[dict]]:
    """Researchers publishing on the thesis, keyed by their real name.

    A different identity space from the rest of this module, and a more
    useful one: arXiv prints the author's name, not a handle, so these join
    straight to a Cala Person. For a deep-tech thesis the person who will
    found the company is often publishing about it two years first.
    """
    out: dict[str, list[dict]] = {}
    for q in qs:
        raw = (fetcher or _get_text)(
            ARXIV, {"search_query": " AND ".join(f"all:{w}" for w in q.split()),
                    "max_results": per_query, "sortBy": "submittedDate",
                    "sortOrder": "descending"}, kind="ax")
        for e in re.findall(r"<entry>(.*?)</entry>", raw or "", re.S):
            ti = re.search(r"<title>(.*?)</title>", e, re.S)
            pu = re.search(r"<published>(.*?)</published>", e)
            li = re.search(r'<id>(.*?)</id>', e)
            title = re.sub(r"\s+", " ", ti.group(1)).strip() if ti else ""
            # Only the front of the author list. A six-author paper is not
            # six people about to start a company, and taking them all made
            # forty-four of sixty rows the co-authors of three papers.
            for pos, nm in enumerate(re.findall(r"<name>(.*?)</name>", e)[:3]):
                nm = nm.strip()
                if len(nm.split()) < 2:
                    continue
                bucket = out.setdefault(nm.lower(), [])
                url = li.group(1) if li else ""
                # The queries overlap by design - narrowest first, then
                # shorter - so the same paper comes back more than once.
                # Counting it twice inflates both the claim and the score.
                if any(w["url"] == url for w in bucket):
                    continue
                bucket.append({
                    "author": nm, "title": title[:120], "position": pos,
                    "when": (pu.group(1)[:10] if pu else None),
                    "url": url, "query": q,
                })
    return out


# ---------------------------------------------------------------- joining

def _days(a: str, b: str) -> int:
    try:
        return max(0, (date.fromisoformat(b) - date.fromisoformat(a)).days)
    except ValueError:
        return 0


def group(repo_rows: list[dict], room_idx: dict, hack_idx: dict, *,
          today: date, paper_idx: dict | None = None) -> list[dict]:
    """One row per handle, carrying everything the three sources said."""
    by: dict[str, dict] = {}
    for r in repo_rows:
        h = (r.get("handle") or "").strip()
        if not h:
            continue
        row = by.setdefault(h.lower(), {"handle": h, "repos": [], "sources": set()})
        row["repos"].append(r)
        row["sources"].add(r.get("host") or "github")

    # A hackathon project or a thread comment is a reason to look at someone
    # even with no repository in the window, so these create rows too.
    for key, projects in hack_idx.items():
        row = by.setdefault(key, {"handle": projects[0]["handle"],
                                  "repos": [], "sources": set()})
        row["hackathons"] = projects[:4]
        row["sources"].add("devpost")
    for key, said in room_idx.items():
        if key not in by:
            continue          # a comment alone is not evidence of building
        by[key]["rooms"] = said[:4]
        by[key]["sources"].add("hn")

    # Researchers are keyed by name rather than handle, so before they
    # become their own rows, try to land them on a handle already here. A
    # person publishing on the thesis AND pushing code for it is the
    # strongest thing this module can find, and keying on two different
    # identity spaces is the only reason it would otherwise miss them.
    for key, works in (paper_idx or {}).items():
        parts = re.findall(r"[A-Za-z]{2,}", works[0]["author"])
        target = key
        if len(parts) >= 2:
            first, last = parts[0].lower(), parts[-1].lower()
            for cand in (first + last, last + first, first + "-" + last,
                         first[0] + last, first + last[0]):
                if cand in by:
                    target = cand
                    break
        row = by.setdefault(target, {"handle": works[0]["author"],
                                     "repos": [], "sources": set()})
        row["papers"] = works[:4]
        row["sources"].add("arxiv")

    out = []
    for row in by.values():
        rs = sorted(row["repos"], key=lambda r: (-r["fit"],
                                                 -_days(r["created"], r["pushed"]),
                                                 -r["size_kb"]))
        best = rs[0] if rs else None
        out.append({
            "handle": row["handle"],
            "profile": (f"https://github.com/{row['handle']}"
                        if "github" in row["sources"]
                        else f"https://gitlab.com/{row['handle']}"
                        if "gitlab" in row["sources"]
                        else f"https://huggingface.co/{row['handle']}"
                        if "huggingface" in row["sources"] else None),
            "repos": rs[:4],
            "lead_repo": best,
            "span_days": _days(best["created"], best["pushed"]) if best else 0,
            "idle_days": _days(best["pushed"], today.isoformat()) if best else None,
            "stars": sum(r["stars"] for r in rs),
            "on_thesis": len(rs),
            "hackathons": row.get("hackathons") or [],
            "rooms": row.get("rooms") or [],
            "papers": row.get("papers") or [],
            "hosts": sorted({r.get("host") or "github" for r in rs}),
            "sources": sorted(row["sources"]),
        })
    return out


def score(row: dict) -> tuple[float, list[str]]:
    """0-100 and the reasons, in the order they contributed.

    The first version of this scored every quiet new repository at exactly
    66.0, because span, freshness and star count all saturated at once. A
    ranking where every row ties is not a ranking. What actually separates
    someone starting a company from someone with a weekend project is depth:
    how much code, over how long, how many repositories pointed at the same
    idea, and whether it has been treated as a product rather than a sketch.
    """
    why, pts = [], 0.0
    span, idle = row["span_days"], row["idle_days"]
    best = row["lead_repo"]

    if best:
        # Weeks of work and a body of code, not one of the two.
        effort = min(1.0, span / SUSTAIN_FULL)
        body = min(1.0, best["size_kb"] / SIZE_FULL)
        pts += W_BUILDING * (0.6 * effort + 0.4 * body)
        weeks = max(1, span // 7)
        why.append(f"{weeks} week{'s' if weeks != 1 else ''} of commits on "
                   f"{best['repo'].split('/')[-1]}"
                   + (f", {best['size_kb'] // 1000} MB of code"
                      if best["size_kb"] >= 1000 else ""))

        if row["on_thesis"] > 1:
            pts += W_DEPTH * min(1.0, (row["on_thesis"] - 1) / 2.0)
            why.append(f"{row['on_thesis']} repositories on this thesis, not one")

        product = sum((bool(best["homepage"]), bool(best["topics"]),
                       best["licensed"], best["issues"] > 0))
        if product:
            pts += W_PRODUCT * (product / 4.0)
            marks = []
            if best["homepage"]:
                marks.append("deployed it")
            if best["topics"]:
                marks.append("tagged it")
            if best["licensed"]:
                marks.append("licensed it")
            if best["issues"]:
                marks.append(f"{best['issues']} open issues")
            why.append("treated as a product: " + ", ".join(marks))

        pts += W_FIT * best["fit"]
        if best["fit"] >= 0.99:
            why.append("named for the thesis, not just mentioning it")

        if idle is not None and idle <= FRESH_DAYS:
            pts += W_FRESH * (1 - idle / FRESH_DAYS)
            why.append("committed today" if idle == 0 else
                       f"last commit {idle} day{'s' if idle != 1 else ''} ago")
        if row["stars"] <= QUIET_STARS:
            pts += W_QUIET * (1 - row["stars"] / (QUIET_STARS + 1))
            why.append(f"{row['stars']} star{'s' if row['stars'] != 1 else ''} "
                       "- nobody has found it yet")

    hacks = row["hackathons"]
    hinted = best and best.get("hack_hint")
    if hacks or hinted:
        won = sum(1 for h in hacks if h.get("winner"))
        pts += W_HACKATHON * min(1.0, (len(hacks) + won + (1 if hinted else 0)) / 2.0)
        if hacks:
            named = [h["event"] for h in hacks if h.get("event")]
            where = (" at " + named[0]) if named else " on Devpost"
            why.append(f"{len(hacks)} hackathon project"
                       f"{'s' if len(hacks) != 1 else ''}{where}"
                       + (f", {won} placed" if won else ""))
        elif hinted:
            why.append("built it at a hackathon, by its own description")

    if row["papers"]:
        # Volume, recency, and whose work it is. First author is the person
        # who did it; third is often the group. Without these three every
        # researcher scored an identical 20.0, which is the same tie that
        # made the first version of the repository ranking useless.
        n = min(1.0, len(row["papers"]) / 2.0)
        best = min(p.get("position", 2) for p in row["papers"])
        lead = {0: 1.0, 1: 0.7}.get(best, 0.45)
        newest = max((p.get("when") or "") for p in row["papers"])
        fresh = 1.0
        if newest:
            try:
                age = (date.today() - date.fromisoformat(newest)).days
                fresh = max(0.3, 1.0 - age / 540)
            except ValueError:
                pass
        pts += W_PAPERS * (0.45 * n + 0.35 * lead + 0.20 * fresh)
        where = ("first author" if best == 0 else
                 "second author" if best == 1 else "co-author")
        why.append(f"{len(row['papers'])} arXiv paper"
                   f"{'s' if len(row['papers']) != 1 else ''} on this, {where}"
                   + (f", latest {newest}" if newest else ""))

    if row["rooms"]:
        pts += W_ROOMS * min(1.0, len(row["rooms"]) / 3.0)
        why.append(f"arguing about this in {len(row['rooms'])} Hacker News "
                   f"thread{'s' if len(row['rooms']) != 1 else ''}")

    if len(row["sources"]) > 1:
        pts += W_CORROBORATED
        why.append("same handle in " + " and ".join(row["sources"]))

    claimed = (row.get("known_to_cala") or {}).get("claimed")
    if claimed:
        pts += W_IDENTIFIED
        why.append(f"Cala records this account as "
                   f"{row['known_to_cala']['name']}")

    return round(min(100.0, pts), 1), why


# ---------------------------------------------------------------- Cala join

def _cala_handle(e: dict) -> str | None:
    """The GitHub login Cala itself records for a person, if it records one."""
    v = (e.get("properties") or {}).get("github_url")
    v = v.get("value") if isinstance(v, dict) else v
    m = re.search(r"github\.com/([A-Za-z0-9-]+)", str(v or ""))
    return m.group(1).lower() if m else None


def _people_by_handle(index: dict) -> dict[str, dict]:
    """Cala People keyed by the handles that could be theirs.

    Two kinds of key, and the difference is the whole point. Cala stores a
    github_url on a Person, and when it does, the login in it IS the person -
    Cala is making the claim and carrying the sources for it, so the match is
    stated as fact. Everything else is a name rearranged into the shapes a
    login usually takes, which is a lead worth following and nothing more.

    The claimed ones are written last so they always win the key.
    """
    out: dict[str, dict] = {}
    for e in index.values():
        if e.get("entity_type") != "Person":
            continue
        name = (e.get("name") or "").strip()
        parts = re.findall(r"[A-Za-z]{2,}", name)
        if len(parts) < 2:
            continue
        first, last = parts[0].lower(), parts[-1].lower()
        for cand in (first + last, last + first, first + "-" + last,
                     first[0] + last, first + last[0]):
            out.setdefault(cand, dict(e, _claimed=False))
    for e in index.values():
        if e.get("entity_type") != "Person":
            continue
        h = _cala_handle(e)
        if h:
            out[h] = dict(e, _claimed=True)
    return out


def _already_founded(entity: dict) -> bool:
    rel = (entity.get("relationships") or {})
    for d in ("outgoing", "incoming"):
        if ((rel.get(d) or {}).get("FOUNDED") or []):
            return True
    return False


def rank(*, thesis: str = "", limit: int = 40, months: int = 6,
         today: date | None = None, index: dict | None = None,
         announced: set[str] | None = None, fetcher=None) -> dict:
    """The cohort, plus an honest account of which sources answered."""
    today = today or datetime.now(timezone.utc).date()
    qs = queries(thesis)
    reached, missing = [], []

    def source(name, fn, default):
        try:
            v = fn()
        except Unavailable as e:
            missing.append(f"{name}: {e}")
            return default
        reached.append(name)
        return v

    repo_rows = source("github", lambda: repos(qs, today=today, months=months,
                                               fetcher=fetcher), [])
    repo_rows += source("gitlab", lambda: gitlab(qs, today=today, months=months,
                                                 fetcher=fetcher), [])
    repo_rows += source("huggingface", lambda: models(qs, fetcher=fetcher), [])
    paper_idx = source("arxiv", lambda: papers(qs, fetcher=fetcher), {})
    hack_idx = source("devpost", lambda: enrich(hackathons(qs, fetcher=fetcher)), {})
    room_idx = source("hn", lambda: rooms(qs, fetcher=fetcher), {})

    rows = group(repo_rows, room_idx, hack_idx, today=today,
                 paper_idx=paper_idx)

    # The two subtractions that make this cohort "private" rather than just
    # "small". Someone who posted a Show HN has announced - they belong in
    # the other tab. Someone Cala already records as a founder is not before
    # anything, and belongs in the first.
    pub = {h.lower() for h in (announced or set())}
    by_handle = _people_by_handle(index or {})
    by_name = {(e.get("name") or "").strip().lower(): e
               for e in (index or {}).values()
               if e.get("entity_type") == "Person" and e.get("name")}
    out = []
    for r in rows:
        key = r["handle"].lower()
        if key in pub:
            continue
        known = by_handle.get(key) or by_name.get(key)
        if known and _already_founded(known):
            continue
        r["known_to_cala"] = ({
            "id": known.get("id"), "name": known.get("name"),
            "claimed": bool(known.get("_claimed")),
            "confidence": ("Cala records this GitHub account as theirs"
                           if known.get("_claimed")
                           else "name matches handle, unverified"),
        } if known else None)
        s, why = score(r)
        if s <= 0:
            continue
        r["score"] = s
        r["why"] = why
        out.append(r)

    out.sort(key=lambda r: -r["score"])
    shown = out[:limit]
    return {
        "rows": shown,
        "coverage": {
            "github_handles": len({r["handle"].lower() for r in rows
                                   if "github" in r["sources"]}),
            "devpost_members": len(hack_idx),
            "hn_commenters": len(room_idx),
            "researchers": len(paper_idx),
            "corroborated": sum(1 for r in rows if len(r["sources"]) > 1),
            "cala_matched": sum(1 for r in shown if r.get("known_to_cala")),
        },
        "queries": qs,
        "sources_read": reached,
        "sources_missing": missing,
        "considered": len(rows),
        "excluded_announced": sum(1 for r in rows if r["handle"].lower() in pub),
        "as_of": today.isoformat(),
    }
