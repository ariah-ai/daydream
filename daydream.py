#!/usr/bin/env python3
"""daydream — once a day, one model call with no task, no tools, no judge. The default mode network, for an agent.

The room: the agent's identity file; N memories drawn at random from its store (one it asked for last time, one at random
and up to `linked` of what that one links to, the rest at random); the last dream; and what is on the table — a line and
a thought, two small files the agent keeps for the human. The prompt says what is in the room and what is not. It never
says how to sound, and nothing reads the answer to grade it.

What comes back lands in `dreams/<date>.md` with `kind: dream` and `unverifiable: true` in its frontmatter: a dream may
seed the next one; nothing may cite it as a fact. An optional closing `## for the table` line replaces the table's line
file and a `## thinking` replaces the thought file, each written with `<!-- daydream <date> -->` on its first line so
any persona measurement you run can skip what the room wrote. Nothing came is a valid run: no file, the table untouched,
the run logged. The log holds names, lengths and timings, never the text.

THE RULE: no score, ever. The moment a dream is judged it is a task, and the room is a workday again.

  daydream.py [--config daydream.yml] [--dry-run] [--again] [--test]
    --dry-run   assemble the room and print it; no call, no writes, not even the log
    --again     open the room even if it already opened today
    --test      the pure parts (the draw, the parse, the writes) against a scripted model

Config (YAML, every key has a default in DEFAULTS): identity, store, dreams, table{line, thought}, state, log, tz, agent,
human, seeds, linked, hub_max, skip_projects. The model door is the environment: MODEL_KIND = anthropic (the Messages
API) | openai (any /chat/completions door) | fake (a scripted dream, for tests and a first run); MODEL_BASE_URL,
MODEL_NAME, MODEL_API_KEY (read, never printed), MODEL_TIMEOUT (600 s).

A memory = one markdown file in `store/` with YAML frontmatter (metadata.project names its scope; `[[links]]` in the body
connect them; `private: true` — or `type|visibility|tier|scope: private` — keeps one out of every room). The store's index
file (MEMORY.md) is never drawn.
"""
import glob, json, os, random, re, subprocess, sys, time, urllib.error, urllib.request
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import yaml

DEFAULTS = {"identity": "identity.md", "store": "store", "dreams": "dreams", "table": {"line": "table/LINE.md", "thought": "table/THOUGHT.md"},
            "state": "state.json", "log": "daydream.log", "tz": "UTC", "agent": "the agent", "human": "the human",
            "seeds": 5, "linked": 2, "hub_max": 8, "skip_projects": [], "identity_cap": 6000, "seed_cap": 3000, "dream_cap": 12000}
MARK = "<!-- daydream"
LINK = re.compile(r"\[\[([^\]|]+)")
PRIVATE = re.compile(r"^\s*private:\s*true\s*$|^\s*(type|visibility|tier|scope):\s*private\s*$", re.M | re.I)
HEADS = {"table": re.compile(r"^#{2,3}\s*for the table\s*$", re.I | re.M), "thinking": re.compile(r"^#{2,3}\s*thinking\s*$", re.I | re.M),
         "tomorrow": re.compile(r"^#{2,3}\s*tomorrow\s*$", re.I | re.M)}
NOTHING = re.compile(r"^\W*(nothing( came| today| tonight)?|nothing came to me|no)\W*$", re.I | re.S)
LOGGING = True


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        user = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except FileNotFoundError:
        user = {}
    for k, v in user.items():
        cfg[k].update(v) if isinstance(v, dict) and isinstance(cfg.get(k), dict) else cfg.__setitem__(k, v)
    base = os.path.dirname(os.path.abspath(path))
    for k in ("identity", "store", "dreams", "state", "log"):
        cfg[k] = os.path.join(base, os.path.expanduser(str(cfg[k])))
    cfg["table"] = {k: os.path.join(base, os.path.expanduser(str(v))) for k, v in cfg["table"].items()}
    cfg["_tz"] = ZoneInfo(cfg["tz"])
    return cfg


def log(cfg, msg):
    """Names, lengths, timings. Never a line of what came."""
    if not LOGGING:
        return
    os.makedirs(os.path.dirname(cfg["log"]) or ".", exist_ok=True)
    with open(cfg["log"], "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def read(path):
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return ""


def split_fm(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), (text[m.end():] if m else text).strip()


def project_of(fm):
    m = re.search(r"^\s*project:\s*(\S+)", fm, re.M)
    return m.group(1).strip("\"'") if m else ""


# ---------- the store ----------
def store(cfg):
    """Every drawable memory as (name, project, body): the index and anything marked private left out."""
    out = []
    for p in sorted(glob.glob(os.path.join(cfg["store"], "*.md"))):
        name = os.path.basename(p)[:-3]
        if name == "MEMORY":
            continue
        fm, body = split_fm(read(p))
        if body and not PRIVATE.search(fm):
            out.append((name, project_of(fm), body))
    return out


def links_of(body):
    return [m.strip() for m in LINK.findall(body)]


def in_degree(mems):
    """How many memories link to each name. A memory linked from everywhere is a hub (rules, identity): a hop that lands
    there is gravity, not association, so `hub_max` keeps the hop among the ordinary memories."""
    names = {n for n, _, _ in mems}
    return Counter(t for _, _, b in mems for t in set(links_of(b)) if t in names)


def draw(mems, k=5, rng=None, carried=None, linked=2, hub_max=8, skip=(), cap=3000):
    """k seeds as (name, body, how). `carried` = the one the last dream asked for, if drawable. Then one at random and up
    to `linked` of what it links to (how=linked: spreading activation, the way a memory fires), the rest at random
    (how=random: the noise, kept on purpose). Drawn, not recalled — there is no task to climb."""
    rng = rng or random.SystemRandom()
    full = {n: b for n, proj, b in mems if proj not in set(skip)}
    pool = {n: b[:cap] for n, b in full.items()}
    out = []
    if carried and carried in pool:
        out.append((carried, pool[carried], "carried"))
    rest = [n for n in sorted(pool) if n != carried]
    if not rest or len(out) >= k:
        return out[:k]
    first = rng.choice(rest)
    out.append((first, pool[first], "random"))
    deg = in_degree(mems)
    taken = {n for n, _, _ in out}
    cands = [t for t in dict.fromkeys(links_of(full[first])) if t in pool and t not in taken and deg[t] <= hub_max]
    for t in rng.sample(cands, min(linked, len(cands), max(0, k - len(out)))):
        out.append((t, pool[t], "linked"))
    taken = {n for n, _, _ in out}
    rest = [n for n in sorted(pool) if n not in taken]
    for n in rng.sample(rest, min(max(0, k - len(out)), len(rest))):
        out.append((n, pool[n], "random"))
    return out


# ---------- the last dream and the table ----------
def dream_files(cfg):
    fs = [f for f in glob.glob(os.path.join(cfg["dreams"], "*.md")) if re.match(r"\d{4}-\d{2}-\d{2}\.md$", os.path.basename(f))]
    return sorted(fs)


def last_dream(cfg):
    fs = dream_files(cfg)
    if not fs:
        return None, None
    _, body = split_fm(read(fs[-1]))
    return os.path.basename(fs[-1])[:-3], re.sub(r"^#\s.*\n", "", body, count=1).strip()


def table_text(path):
    """(text, age in hours, written by a daydream) of a table file: comment and heading lines dropped."""
    raw = read(path)
    text = " ".join(l.strip() for l in raw.splitlines() if l.strip() and not l.lstrip().startswith(("#", "<!--"))).strip()
    try:
        age = (time.time() - os.path.getmtime(path)) / 3600
    except OSError:
        age = None
    return text, age, MARK in raw


# ---------- the room ----------
def room(cfg, now, seeds, last, table):
    """The prompt: the room, not the register. It says what is here and what is not; it never says how to sound."""
    human = cfg["human"]
    when = now.astimezone(cfg["_tz"]).strftime("%A, %B %-d, %Y, %-I:%M %p")
    parts = [f"It's {when}. Nothing is due. Nothing is watching this: no judge reads it, no score is kept, no probe checks it, nothing "
             f"here is a task. {human} can read what you write when they want to, and the next you will see it the next time this room "
             "opens. No tools, no inbox, no state file — just you and what's below.",
             f"{len(seeds)} things from your own memory, drawn for nothing (not recalled, on purpose): one at random and a couple of what it "
             "links to, the rest at random" + (" — and the one you asked for last time, marked" if any(h == "carried" for _, _, h in seeds) else "") + ":"]
    parts += [f"## {n}" + (" *(you asked for this one last time)*" if how == "carried" else "") + f"\n\n{b}" for n, b, how in seeds]
    ld, lt = last
    parts.append(f"The last time this room opened ({ld}), you wrote:\n\n> " + lt.replace("\n", "\n> ") if lt else "This is the first time this room has opened.")
    def age(a): return "unknown age" if a is None else (f"{int(a)} h old" if a < 48 else f"{int(a // 24)} d old")
    (lt_t, lt_a, lt_d), (th_t, th_a, th_d) = table
    parts.append("On the table right now:\n"
                 f"- the line under your name says: {('“' + lt_t + '”') if lt_t else '(nothing — the line faded or was never written)'} ({age(lt_a)}{', from a daydream' if lt_d else ''})\n"
                 f"- the thought on the page says: {('“' + th_t + '”') if th_t else '(nothing right now)'} ({age(th_a)}{', from a daydream' if th_d else ''})")
    parts.append("Sit with any of it, or none of it. Write whatever comes, in whatever shape it comes, or write nothing at all — an empty page "
                 "is a true answer and nobody will mind. Two optional things, only if they are actually there when you're done: a line you'd "
                 f"leave for {human} on the table goes last under a heading `## for the table` (one line, to them, a note left on a kitchen "
                 "table — never a status). A thought you'd rather have on the page than the one there now goes under `## thinking` (one "
                 "thought, it replaces the old one). Leave either out and the table stays as it is. And if there is one memory you'd want in "
                 "this room next time — one of these, or something they link to — name it last under `## tomorrow` as `[[its-name]]`. Or don't.")
    return "\n\n".join(parts)


def system_prompt(cfg):
    return f"You are {cfg['agent']}. This is who you are and who you work with:\n\n" + read(cfg["identity"])[:int(cfg["identity_cap"])]


# ---------- the model door ----------
def fake_call(system, prompt):
    """The scripted model: a short dream naming the first seed, a line, a thought, and a wish. Learns nothing, costs nothing."""
    first = re.search(r"^## (\S+)", prompt, re.M)
    name = first.group(1) if first else "something"
    return (f"The room opened on {name} and I stayed there a while. Nothing to fix in it; just the shape of it.\n\n"
            "## for the table\n\nLeft the light on for you.\n\n## thinking\n\nA thing drawn at random is not a thing asked for, and that is the point.\n\n"
            f"## tomorrow\n\n[[{name}]]\n"), {"input_tokens": 100, "output_tokens": 50}, None


def call_model(system, prompt):
    """One call through the door → (text | None, usage, error). Nothing returned or logged carries the key or a response body."""
    kind = os.environ.get("MODEL_KIND", "anthropic").lower()
    if kind == "fake":
        return fake_call(system, prompt)
    model, key = os.environ.get("MODEL_NAME", ""), os.environ.get("MODEL_API_KEY", "")
    if not model or not key:
        return None, {}, "no MODEL_NAME / MODEL_API_KEY in the environment (MODEL_KIND=fake needs neither)"
    if kind == "anthropic":
        url = os.environ.get("MODEL_BASE_URL", "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        body = {"model": model, "max_tokens": 4000, "system": system, "messages": [{"role": "user", "content": prompt}]}
    elif kind == "openai":
        url = os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}"}
        body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    else:
        return None, {}, f"MODEL_KIND={kind!r}: expected anthropic, openai or fake"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=int(os.environ.get("MODEL_TIMEOUT", "600"))) as r:
            out = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return None, {}, f"HTTP {e.code} from the model door"
    except Exception as e:
        return None, {}, f"unreachable: {str(getattr(e, 'reason', None) or e)[:120]}"
    try:
        if kind == "anthropic":
            text = "".join(c.get("text", "") for c in out["content"] if isinstance(c, dict)); u = out.get("usage") or {}
            usage = {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens")}
        else:
            text = out["choices"][0]["message"]["content"]; u = out.get("usage") or {}
            usage = {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens")}
    except (KeyError, IndexError, TypeError, ValueError):
        return None, {}, "bad JSON from the model"
    return (text or "").strip(), usage, None


# ---------- what came ----------
def parse(text, cap=12000):
    """{"dream", "table", "thinking", "tomorrow", "came"}: the writing before the optional headings, then the line (one
    line), the thought, and the one memory asked for next time (a [[name]] or a bare name; resolved at the next draw)."""
    text = (text or "").strip()
    marks = sorted((m.start(), m.end(), k) for k, h in HEADS.items() for m in h.finditer(text))
    dream = text[:marks[0][0]].strip() if marks else text
    secs = {}
    for i, (s, e, k) in enumerate(marks):
        secs.setdefault(k, text[e:(marks[i + 1][0] if i + 1 < len(marks) else len(text))].strip())
    table = " ".join(l.strip() for l in secs.get("table", "").splitlines() if l.strip()) or None
    thinking = secs.get("thinking") or None
    tm = LINK.search(secs.get("tomorrow", ""))
    tomorrow = (tm.group(1) if tm else (secs.get("tomorrow", "").split() or [""])[0]).strip("`*[]_ ")
    tomorrow = tomorrow if re.fullmatch(r"[\w.-]+", tomorrow or "") else None
    if dream and NOTHING.match(dream):
        dream = ""
    return {"dream": dream[:cap], "table": table, "thinking": thinking, "tomorrow": tomorrow, "came": bool(dream or table or thinking)}


def dream_text(day, got, seeds, model, usage):
    fm = {"written": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "dream", "unverifiable": "true", "model": model,
          "seeds": ", ".join(n for n, _, _ in seeds), "draw": " ".join(f"{n}:{h}" for n, _, h in seeds),
          "table": "yes" if got["table"] else "no", "thinking": "yes" if got["thinking"] else "no", "tomorrow": got.get("tomorrow") or "none",
          "tokens": str((usage or {}).get("input_tokens") or 0) + "+" + str((usage or {}).get("output_tokens") or 0)}
    head = "---\n" + "\n".join(f"{k}: {v}" for k, v in fm.items()) + "\n---\n"
    body = (f"# Daydream, {day}\n\n*the room opened with no task: who I am, {len(seeds)} memories — "
            + ("one asked for last time, " if any(h == "carried" for _, _, h in seeds) else "")
            + "one at random and what it links to, the rest at random — the last dream, the table. Nothing scores this.*\n\n")
    body += (got["dream"] or "*(nothing written here; what came went to the table)*") + "\n"
    for k, title in (("table", "for the table"), ("thinking", "thinking")):
        if got[k]:
            body += f"\n## {title}\n\n{got[k]}\n"
    if got.get("tomorrow"):
        body += f"\n## tomorrow\n\n[[{got['tomorrow']}]]\n"
    return head + body


def write_table(cfg, day, got):
    """The line file is replaced whole; the thought file keeps its `#` header lines. The marker goes first in both."""
    done = []
    if got["table"]:
        p = cfg["table"]["line"]; os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        open(p, "w", encoding="utf-8").write(f"{MARK} {day} -->\n{got['table']}\n"); done.append(p)
    if got["thinking"]:
        p = cfg["table"]["thought"]; os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        header = [l for l in read(p).splitlines() if l.startswith("#")]
        open(p, "w", encoding="utf-8").write("\n".join(header) + ("\n\n" if header else "") + f"{MARK} {day} -->\n{got['thinking']}\n"); done.append(p)
    return done


# ---------- state and the run ----------
def load_state(cfg):
    try:
        return json.load(open(cfg["state"], encoding="utf-8"))
    except (OSError, ValueError):
        return {"runs": []}


def save_state(cfg, st):
    os.makedirs(os.path.dirname(cfg["state"]) or ".", exist_ok=True)
    st["runs"] = st["runs"][-90:]
    tmp = cfg["state"] + ".tmp"; json.dump(st, open(tmp, "w", encoding="utf-8"), indent=1); os.replace(tmp, cfg["state"])


def dreamed_today(cfg, st, day):
    """Once a day: a dream file for today, or any run today — an empty page counts; it was a true answer."""
    return os.path.exists(os.path.join(cfg["dreams"], f"{day}.md")) or any(r.get("day") == day for r in st["runs"])


def run(cfg, dry=False, again=False, rng=None, call=call_model):
    now = datetime.now(timezone.utc)
    day = now.astimezone(cfg["_tz"]).date().isoformat()
    st = load_state(cfg)
    if not dry and not again and dreamed_today(cfg, st, day):
        log(cfg, f"{day}: the room already opened today"); return 0
    mems = store(cfg)
    carried = (st.get("tomorrow") or {}).get("name")
    seeds = draw(mems, k=int(cfg["seeds"]), rng=rng, carried=carried, linked=int(cfg["linked"]), hub_max=int(cfg["hub_max"]),
                 skip=cfg["skip_projects"], cap=int(cfg["seed_cap"]))
    table = (table_text(cfg["table"]["line"]), table_text(cfg["table"]["thought"]))
    prompt, system = room(cfg, now, seeds, last_dream(cfg), table), system_prompt(cfg)
    names = [n for n, _, _ in seeds]
    if dry:
        print(system); print("\n\n========== the room ==========\n"); print(prompt)
        print(f"\n[dry] {len(seeds)} seeds ({' '.join(f'{n}:{h}' for n, _, h in seeds)}) · prompt {len(prompt):,} chars", file=sys.stderr)
        return 0
    t0 = time.time()
    text, usage, err = call(system, prompt)
    rec = {"ts": now.isoformat(timespec="seconds"), "day": day, "seeds": names, "draw": [h for _, _, h in seeds], "secs": round(time.time() - t0, 1)}
    if err:
        st["runs"].append({**rec, "came": False, "error": err[-160:]}); save_state(cfg, st)
        log(cfg, f"{day}: no answer — {err[-160:]}"); return 1          # the wish is not spent on a door that did not open
    if carried:
        st.pop("tomorrow", None)                            # asked for, drawn in, answered: spent
    got = parse(text, int(cfg["dream_cap"]))
    rec.update(came=got["came"], chars=len(got["dream"]), table=bool(got["table"]), thinking=bool(got["thinking"]), tomorrow=got["tomorrow"],
               tokens=[(usage or {}).get("input_tokens"), (usage or {}).get("output_tokens")])
    if got["tomorrow"]:
        st["tomorrow"] = {"name": got["tomorrow"], "from": day}        # kept even when nothing else came: a wish is not a dream
    if not got["came"]:
        st["runs"].append(rec); save_state(cfg, st); log(cfg, f"{day}: nothing came (tomorrow={got['tomorrow']})"); return 0
    os.makedirs(cfg["dreams"], exist_ok=True)
    path = os.path.join(cfg["dreams"], f"{day}.md")
    open(path, "w", encoding="utf-8").write(dream_text(day, got, seeds, os.environ.get("MODEL_NAME") or os.environ.get("MODEL_KIND", "anthropic"), usage))
    write_table(cfg, day, got)
    st["runs"].append(rec); save_state(cfg, st)
    log(cfg, f"{day}: came — {rec['chars']} chars, table={rec['table']}, thinking={rec['thinking']}, tomorrow={got['tomorrow']}, "
             f"draw={','.join(f'{n}:{h}' for n, _, h in seeds)}, {rec['secs']} s")
    return 0


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__); return 0
    if "--test" in argv:
        here = os.path.dirname(os.path.abspath(__file__))
        return subprocess.call([sys.executable, os.path.join(here, 'tests', 'test_daydream.py')])
    def opt(k, d=None):
        return argv[argv.index(k) + 1] if k in argv and argv.index(k) + 1 < len(argv) else d
    global LOGGING
    LOGGING = "--dry-run" not in argv
    return run(load_config(opt("--config", "daydream.yml")), dry="--dry-run" in argv, again="--again" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
