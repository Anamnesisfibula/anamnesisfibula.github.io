"""Fibula enemy tracker updater.

  python scripts/update.py online   -> data/status.json (who is online now)
  python scripts/update.py scan     -> refresh char info, find new alts and new guild members (data/network.json)

Data source: opentibia.info (public pages). Be polite: one request at a time with a pause.
"""
import json, re, sys, time, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

BASE = "https://opentibia.info"
ROOT = Path(__file__).resolve().parent.parent
import os
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data"))
NET = DATA / "network.json"
STATUS = DATA / "status.json"
LOG = DATA / "changes.json"
KILLS = DATA / "kills.json"
GUILDS = {"RB": "Reformed Bullies", "BW": "Bullywannabes", "CC": "Carlins Cartel", "WU": "Wyrok Ulicy"}
MIN_SCORE = 40      # new alt candidates below this are ignored
HIGH_SCORE = 100    # at or above this (and never online together) = high confidence
PAUSE = 1.0
TZ = ZoneInfo("Europe/Oslo")

def now():
    return dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M")

def session():
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (fibula-tracker)"
    s.get(f"{BASE}/index/server/fibula", timeout=30)   # selects the Fibula server (cookie)
    return s

def load(p, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

def save(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")

def all_names(net):
    out = []
    for main, _g, alts in net["clusters"]:
        out.append(main); out += [a[0] for a in alts]
    return out

def owner_of(net):
    return {n: c[0] for c in net["clusters"] for n in [c[0], *[a[0] for a in c[2]]]}

# ---------- online ----------
def online(s):
    html = s.get(f"{BASE}/stats/online", timeout=30).text
    soup = BeautifulSoup(html, "html.parser")
    names = set()
    for a in soup.select('a[href*="/stats/player/"]'):
        names.add(a.get_text(strip=True))
    return names

def run_online():
    net = load(NET, None)
    s = session()
    on = online(s)
    tracked = [n for n in all_names(net) if n in on]
    old = load(STATUS, {})
    same = sorted(old.get("online", [])) == sorted(tracked)
    save(STATUS, {"updated": old.get("updated") if same else now(), "checked": now(),
                  "server_online": len(on), "online": tracked})
    print(f"{len(tracked)} tracked online of {len(on)}")

# ---------- scan ----------
def player(s, name):
    html = s.get(f"{BASE}/stats/player/{requests.utils.quote(name)}", timeout=30).text
    soup = BeautifulSoup(html, "html.parser")
    t = soup.find("table")
    if not t: return None
    tds = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in t.find_all("td")]
    if not tds: return None
    info = tds[0]
    voc = re.search(r"Voc: (.+?) Town", info)
    guild = re.search(r"Guild: (.*?)\s*of (.+)$", info)
    level = int(tds[1]) if tds[1].isdigit() else 0
    ls = next((x for x in tds[2:6] if re.match(r"\d{4}-\d\d-\d\d \d", x)), "")
    gcode, rank = "X", ""
    if guild:
        gname = guild.group(2).strip()
        gcode = next((k for k, v in GUILDS.items() if v == gname), "X")
        rank = guild.group(1).strip() if gcode != "X" else ""
    return {"g": gcode, "r": rank, "l": level, "v": voc.group(1) if voc else "", "ls": ls[:16]}

def scanner(s, name):
    r = s.post(f"{BASE}/stats/friends/x", data={"name": name},
               headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30)
    try: return r.json()
    except Exception: return []

def guild_members(s, gname):
    html = s.get(f"{BASE}/stats/guild/{requests.utils.quote(gname)}", timeout=30).text
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables: return []
    out = []
    for tr in tables[-1].find_all("tr"):
        c = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(c) >= 5 and c[2].isdigit(): out.append(c[1])
    return out

def run_scan():
    net = load(NET, None)
    log = load(LOG, [])
    s = session()
    today = now()[:10]
    chars, clusters = net["chars"], net["clusters"]
    own = owner_of(net)

    # 1) new guild members become their own entry
    for code, gname in GUILDS.items():
        for n in guild_members(s, gname):
            if n not in own:
                log.append({"date": today, "type": "new_member", "name": n, "guild": gname})
                link_new(s, net, own, chars, clusters, log, n, f"member of {gname}", today)
        time.sleep(PAUSE)

    # 2) refresh info + look for new alts
    for n in list(own):
        p = player(s, n); time.sleep(PAUSE)
        if p:
            old = chars.get(n, {})
            if p["g"] == old.get("g") and not p["r"]: p["r"] = old.get("r", "")
            if old and p["g"] != old.get("g"):
                gname = lambda c: GUILDS.get(c, "no guild")
                log.append({"date": today, "type": "guild_change", "name": n, "owner": own[n],
                            "from": gname(old.get("g")), "to": gname(p["g"])})
            chars[n] = p  # never removed: a char stays tracked even after leaving a guild
        for e in scanner(s, n):
            other, score = e.get("name"), float(e.get("score") or 0)
            if not other or score < MIN_SCORE or other in own: continue
            shared = (e.get("overlap") or {}).get("status") == "confirmed"
            cf = "h" if score >= HIGH_SCORE and not shared else "m"
            ev = f"score {round(score)} with {n}" + (", shared online time" if shared else "") + f" (new {today})"
            main = own[n]
            cl = next(c for c in clusters if c[0] == main)
            cl[2].append([other, cf, ev, today]); own[other] = main
            chars.setdefault(other, {"g": "X", "r": "", "l": int(e.get("level") or 0), "v": "", "ls": ""})
            log.append({"date": today, "type": "new_alt", "name": other, "owner": main, "via": n, "score": round(score)})
        time.sleep(PAUSE)

    net["scanned"] = now()
    save(NET, net); save(LOG, log[-300:])
    print("scan done", len(own), "chars")

# ---------- kills / deaths ----------
LVL = re.compile(r"^(.*?)\s*\((\d+)\)\s*$")

def split_name(t):
    m = LVL.match(t.strip())
    return (m.group(1).strip(), int(m.group(2))) if m else (t.strip(), None)

def deaths_page(s, page):
    url = f"{BASE}/stats/deaths" + (f"/{page}" if page > 1 else "")
    soup = BeautifulSoup(s.get(url, timeout=30).text, "html.parser")
    out = []
    for t in soup.find_all("table"):
        heads = [th.get_text(strip=True) for th in t.find_all("th")]
        if "Via" not in heads: continue
        for tr in t.find_all("tr"):
            c = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(c) < 3: continue
            date = next((x for x in c if re.match(r"\d{4}-\d\d-\d\d \d", x)), None)
            if not date: continue
            victim, vl = split_name(c[0])
            killers = [split_name(k) for k in c[-1].split(",") if k.strip()]
            out.append({"date": date[:16], "victim": victim, "vlevel": vl,
                        "killers": [[n, l] for n, l in killers]})
    return out

def run_kills(pages=3):
    net = load(NET, None)
    own = owner_of(net)
    kills = load(KILLS, [])
    seen = {(k["date"], k["victim"]) for k in kills}
    s = session()
    added = 0
    for p in range(1, pages + 1):
        rows = deaths_page(s, p)
        new_here = 0
        for r in rows:
            key = (r["date"], r["victim"])
            if key in seen: continue
            players = [k for k in r["killers"] if k[0][:1].isupper()]
            tk = [k[0] for k in players if k[0] in own]
            if r["victim"] not in own and not tk: continue
            if not players: r["pve"] = True
            r["tracked_killers"] = tk
            r["owner_victim"] = own.get(r["victim"])
            kills.append(r); seen.add(key); added += 1; new_here += 1
        time.sleep(PAUSE)
        if pages <= 3 and rows and all((r["date"], r["victim"]) in seen for r in rows): break
    kills.sort(key=lambda k: k["date"], reverse=True)
    save(KILLS, kills[:2000])
    print("kills added", added)

def link_new(s, net, own, chars, clusters, log, name, note, today):
    """Track a new character permanently. Put it under an existing owner if the scanner links it strongly."""
    p = player(s, name); time.sleep(PAUSE)
    if p: chars[name] = p
    res = [e for e in scanner(s, name) if float(e.get("score") or 0) >= MIN_SCORE]
    time.sleep(PAUSE)
    best = next((e for e in res if e.get("name") in own), None)
    if best:
        score = float(best["score"]); shared = (best.get("overlap") or {}).get("status") == "confirmed"
        main = own[best["name"]]
        cf = "h" if score >= HIGH_SCORE and not shared else "m"
        ev = f"score {round(score)} with {best['name']}" + (", shared online time" if shared else "") + f"; {note}"
        next(c for c in clusters if c[0] == main)[2].append([name, cf, ev, today]); own[name] = main
    else:
        clusters.append([name, chars.get(name, {}).get("g", "X"), []]); own[name] = name; main = name
    log.append({"date": today, "type": "added", "name": name, "owner": main, "guild": note})
    for e in res:
        other = e.get("name")
        if not other or other in own: continue
        score = float(e["score"]); shared = (e.get("overlap") or {}).get("status") == "confirmed"
        cf = "h" if score >= HIGH_SCORE and not shared else "m"
        next(c for c in clusters if c[0] == own[name])[2].append([other, cf, f"score {round(score)} with {name}" + (", shared online time" if shared else "") + f" (new {today})", today])
        own[other] = own[name]
        chars.setdefault(other, {"g": "X", "r": "", "l": int(e.get("level") or 0), "v": "", "ls": ""})
        log.append({"date": today, "type": "new_alt", "name": other, "owner": own[name], "via": name, "score": round(score)})

def run_add(names, note):
    net = load(NET, None); log = load(LOG, [])
    s = session(); today = now()[:10]
    own = owner_of(net)
    for n in names:
        n = n.strip()
        if n and n not in own:
            link_new(s, net, own, net["chars"], net["clusters"], log, n, note, today)
    save(NET, net); save(LOG, log[-300:])

def probe_guild(gname):
    s = session()
    soup = BeautifulSoup(s.get(f"{BASE}/stats/guild/{requests.utils.quote(gname)}", timeout=30).text, "html.parser")
    out = []
    for ti, t in enumerate(soup.find_all("table")):
        out.append(f"-- table {ti}: " + " | ".join(th.get_text(" ", strip=True) for th in t.find_all("th")))
        for tr in t.find_all("tr")[:4]:
            out.append("   " + " | ".join(td.get_text(" ", strip=True) for td in tr.find_all("td")))
    for h in soup.find_all(["h1","h2","h3","h4","b","strong"]):
        tx = h.get_text(" ", strip=True)
        if "nvit" in tx: out.append("HEADING: " + tx)
    (DATA / "probe_guild.txt").write_text("\n".join(out), encoding="utf-8")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "online"
    if mode == "backfill": run_kills(20)
    elif mode == "add": run_add(sys.argv[2].split(";"), sys.argv[3] if len(sys.argv) > 3 else "added by hand")
    elif mode == "probeguild": probe_guild(sys.argv[2])
    else: {"online": run_online, "scan": run_scan, "kills": run_kills}[mode]()
