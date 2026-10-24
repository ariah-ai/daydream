"""daydream — the draw, the room, the parse, the writes, the once-a-day guard, the fake door end to end, and the log that
never carries a dream. Temp dirs, the examples copied in, loopback only. Run: python tests/test_daydream.py (or pytest)."""
import importlib.util, json, os, random, shutil, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("daydream", os.path.join(ROOT, "daydream.py"))
D = importlib.util.module_from_spec(spec); spec.loader.exec_module(D)
os.environ["MODEL_KIND"] = "fake"
for k in ("MODEL_NAME", "MODEL_API_KEY", "MODEL_BASE_URL"):
    os.environ.pop(k, None)

HITS = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        HITS.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        data = json.dumps({"choices": [{"message": {"content": "A dream through the door.\n\n## for the table\n\nhello"}}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


srv = HTTPServer(("127.0.0.1", 0), Fake); threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}/v1"
KEY = "test-key-never-print"


def world(dreams=True):
    tmp = tempfile.mkdtemp()
    for d in ("store", "table") + (("dreams",) if dreams else ()):
        shutil.copytree(os.path.join(ROOT, "examples", d), os.path.join(tmp, d))
    for f in ("daydream.yml", "identity.md"):
        shutil.copy(os.path.join(ROOT, "examples", f), tmp)
    return D.load_config(os.path.join(tmp, "daydream.yml")), tmp


def test_draw():
    mems = [("a", "x", "links [[b]] [[c]] [[hub]] [[money]] [[nowhere]]"), ("b", "x", "b"), ("c", "x", "c [[a]]"), ("money", "accounts", "no"),
            ("hub", "x", "everyone links here")] + [(f"h{i}", "x", "[[hub]]") for i in range(9)]
    deg = D.in_degree(mems); assert deg["hub"] == 10 and deg["b"] == 1 and "nowhere" not in deg, deg
    d = D.draw(mems, k=4, rng=random.Random(3), carried="c", skip=["accounts"])
    assert d[0] == ("c", "c [[a]]", "carried") and d[1][2] == "random" and len(d) == 4 and len({n for n, _, _ in d}) == 4, d
    assert all(n != "money" for n, _, _ in d) and "hub" not in [n for n, _, h in d if h == "linked"]
    assert D.draw(mems, k=4, rng=random.Random(3), carried="money", skip=["accounts"])[0][2] != "carried"      # a skipped scope can't be asked for either
    d = D.draw([("a", "x", "[[b]] [[c]]"), ("b", "x", "[[a]] [[c]]"), ("c", "x", "[[a]] [[b]]")], k=3, rng=random.Random(0))
    assert [h for _, _, h in d] == ["random", "linked", "linked"], d                       # the first at random, the two it links to follow
    assert all(len(b) <= 2 for _, b, _ in D.draw(mems, k=3, rng=random.Random(1), cap=2))      # the cap applies to bodies
    assert D.draw([], k=3) == [] and len(D.draw(mems, k=50, rng=random.Random(2), skip=["accounts"])) == len(mems) - 1
    two = [D.draw(mems, k=4, rng=random.Random(7), skip=["accounts"]) for _ in range(2)]; assert two[0] == two[1]   # seeded = repeatable


def test_store_and_privacy():
    cfg, tmp = world()
    open(os.path.join(tmp, "store", "secret.md"), "w").write("---\nname: secret\nprivate: true\nmetadata:\n  project: shed\n---\nnever in a room\n")
    open(os.path.join(tmp, "store", "MEMORY.md"), "w").write("- [x](shed-key-box.md) — the index is never drawn\n")
    names = {n for n, _, _ in D.store(cfg)}
    assert "secret" not in names and "MEMORY" not in names and len(names) == 8, names
    assert {p for _, p, _ in D.store(cfg)} == {"shed", "garden"}


def test_parse():
    got = D.parse("I keep coming back to the lid.\n\n## for the table\n\nLeft the light on.\n\n## thinking\n\nWhat a draw at random does.\n")
    assert got["came"] and got["dream"] == "I keep coming back to the lid." and got["table"] == "Left the light on." and got["thinking"].startswith("What a draw") and got["tomorrow"] is None
    got = D.parse("A dream.\n\n## tomorrow\n\n[[the-rototiller]]\n\n## thinking\n\nt\n")
    assert got["dream"] == "A dream." and got["tomorrow"] == "the-rototiller" and got["thinking"] == "t", got
    assert D.parse("x\n\n## tomorrow\n\n`fuel-and-oil` — the can\n")["tomorrow"] == "fuel-and-oil"
    assert D.parse("x\n\n## tomorrow\n\nnothing in particular, honestly\n")["tomorrow"] == "nothing"   # resolved against the store later; no such memory = ignored
    got = D.parse("## thinking\n\none thought\n\n## for the table\n\na line\nin two\n")
    assert got["dream"] == "" and got["thinking"] == "one thought" and got["table"] == "a line in two" and got["came"], got
    assert not D.parse("")["came"] and not D.parse("Nothing came.")["came"] and not D.parse("  nothing  ")["came"] and D.parse("A real sentence.")["came"]
    assert len(D.parse("x" * 50, cap=10)["dream"]) == 10


def test_room():
    cfg, tmp = world()
    seeds = D.draw(D.store(cfg), k=5, rng=random.Random(1), carried="loan-log", skip=cfg["skip_projects"])
    prompt = D.room(cfg, D.datetime.now(D.timezone.utc), seeds, D.last_dream(cfg), (D.table_text(cfg["table"]["line"]), D.table_text(cfg["table"]["thought"])))
    assert "## loan-log *(you asked for this one last time)*" in prompt and prompt.count("\n## ") == 5
    assert "The last time this room opened (2026-10-20)" in prompt and "painted lid" in prompt and "Marguerite can read" in prompt
    assert "the line under your name says: “The rototiller came back" in prompt and "the thought on the page says: “Whether a tool" in prompt
    assert "from a daydream" not in prompt and "no judge reads it" in prompt
    cfg2, _ = world(dreams=False)
    assert "first time this room has opened" in D.room(cfg2, D.datetime.now(D.timezone.utc), seeds, D.last_dream(cfg2), (("", None, False), ("", None, False)))
    assert D.system_prompt(cfg).startswith("You are Fennel.") and "tool shed" in D.system_prompt(cfg)


def test_run_writes_and_the_log():
    cfg, tmp = world()
    rc = D.run(cfg, rng=random.Random(5), call=D.fake_call)
    day = D.datetime.now(cfg["_tz"]).date().isoformat()
    path = os.path.join(tmp, "dreams", f"{day}.md"); assert rc == 0 and os.path.exists(path), os.listdir(os.path.join(tmp, "dreams"))
    text = open(path).read(); fm = text.split("---\n")[1]
    assert "kind: dream\n" in fm and "unverifiable: true\n" in fm and "seeds: " in fm and "draw: " in fm and "tomorrow: " in fm and fm.startswith("written: ")
    assert "## for the table\n\nLeft the light on for you." in text and "## thinking" in text and "## tomorrow" in text
    line = open(cfg["table"]["line"]).read(); assert line.startswith(f"<!-- daydream {day} -->\n") and "Left the light on" in line
    thought = open(cfg["table"]["thought"]).read()
    assert thought.startswith("# What I'm thinking about\n\n<!-- daydream") and "drawn at random" in thought and "decoration" not in thought
    st = json.load(open(cfg["state"])); assert st["runs"][-1]["came"] and st["runs"][-1]["day"] == day and st["tomorrow"]["name"] and "text" not in st["runs"][-1]
    logtxt = open(cfg["log"]).read()
    assert "came —" in logtxt and "the shape of it" not in logtxt and "Left the light" not in logtxt and "draw=" in logtxt, logtxt
    # the table's prose is also not in the state
    assert "Left the light" not in json.dumps(st)


def test_nothing_came_and_the_guard():
    cfg, tmp = world()
    before = (open(cfg["table"]["line"]).read(), open(cfg["table"]["thought"]).read())
    calls = []
    def nothing(system, prompt): calls.append(1); return "Nothing came.\n\n## tomorrow\n\n[[winter-close]]", {}, None
    assert D.run(cfg, call=nothing) == 0 and len(calls) == 1
    day = D.datetime.now(cfg["_tz"]).date().isoformat()
    assert not os.path.exists(os.path.join(tmp, "dreams", f"{day}.md")) and (open(cfg["table"]["line"]).read(), open(cfg["table"]["thought"]).read()) == before
    st = json.load(open(cfg["state"])); assert st["runs"][-1]["came"] is False and st["tomorrow"] == {"name": "winter-close", "from": day}
    assert "nothing came" in open(cfg["log"]).read()
    assert D.run(cfg, call=nothing) == 0 and len(calls) == 1, "the room already opened today: no second call"
    assert "already opened today" in open(cfg["log"]).read()
    assert D.run(cfg, again=True, rng=random.Random(2), call=D.fake_call) == 0 and len(calls) == 1 and os.path.exists(os.path.join(tmp, "dreams", f"{day}.md"))
    fm = open(os.path.join(tmp, "dreams", f"{day}.md")).read().split("---\n")[1]
    assert "winter-close:carried" in fm, fm                                  # the wish was drawn in and spent
    assert "tomorrow" not in json.load(open(cfg["state"])) or json.load(open(cfg["state"]))["tomorrow"]["from"] == day


def test_error_is_logged_without_the_key():
    cfg, tmp = world()
    D.save_state(cfg, {"runs": [], "tomorrow": {"name": "winter-close", "from": "2026-10-20"}})       # a wish from last time
    def broken(system, prompt): return None, {}, f"unreachable: refused"
    assert D.run(cfg, call=broken) == 1
    st = json.load(open(cfg["state"])); assert st["runs"][-1]["came"] is False and "refused" in st["runs"][-1]["error"]
    assert st["tomorrow"] == {"name": "winter-close", "from": "2026-10-20"}, "a wish is not spent on a door that did not open"
    assert not os.path.exists(os.path.join(tmp, "dreams", D.datetime.now(cfg["_tz"]).date().isoformat() + ".md"))


def test_the_door():
    os.environ.update({"MODEL_KIND": "openai", "MODEL_BASE_URL": BASE, "MODEL_NAME": "door-model", "MODEL_API_KEY": KEY})
    try:
        text, usage, err = D.call_model("sys", "the room")
        assert err is None and text.startswith("A dream through the door.") and usage == {"input_tokens": 10, "output_tokens": 5}
        assert HITS[-1]["auth"] == f"Bearer {KEY}" and HITS[-1]["body"]["messages"][0]["content"] == "sys" and HITS[-1]["path"].endswith("/chat/completions")
        os.environ["MODEL_BASE_URL"] = "http://127.0.0.1:9/v1"
        text, _, err = D.call_model("sys", "x"); assert text is None and err.startswith("unreachable") and KEY not in err
        os.environ.pop("MODEL_API_KEY"); _, _, err = D.call_model("sys", "x"); assert "MODEL_API_KEY" in err
        os.environ["MODEL_KIND"] = "nope"; os.environ["MODEL_API_KEY"] = KEY; _, _, err = D.call_model("s", "x"); assert "expected anthropic" in err
    finally:
        os.environ["MODEL_KIND"] = "fake"
        for k in ("MODEL_NAME", "MODEL_API_KEY", "MODEL_BASE_URL"):
            os.environ.pop(k, None)


def test_cli_dry_run_then_fake_end_to_end():
    cfg, tmp = world()
    env = {**os.environ, "MODEL_KIND": "fake"}
    r = subprocess.run([sys.executable, os.path.join(ROOT, "daydream.py"), "--config", os.path.join(tmp, "daydream.yml"), "--dry-run"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout.startswith("You are Fennel.") and "========== the room ==========" in r.stdout and "[dry] 5 seeds" in r.stderr, r.stderr
    assert not os.path.exists(cfg["log"]) and not os.path.exists(cfg["state"]), "a dry run writes nothing, not even the log"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "daydream.py"), "--config", os.path.join(tmp, "daydream.yml")], capture_output=True, text=True, env=env)
    day = D.datetime.now(cfg["_tz"]).date().isoformat()
    assert r.returncode == 0 and os.path.exists(os.path.join(tmp, "dreams", f"{day}.md")) and os.path.exists(cfg["log"]), r.stdout + r.stderr
    assert r.stdout == "" and "the shape of it" not in r.stderr, "stdout says nothing about what came"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "daydream.py"), "--config", os.path.join(tmp, "daydream.yml")], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "already opened today" in open(cfg["log"]).read()


if __name__ == "__main__":
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)):
        fn(); print("ok ", name)
    print("test_daydream: all green")
