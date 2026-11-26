import sys, requests
from bs4 import BeautifulSoup
s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 (fibula-tracker)"
s.get("https://opentibia.info/index/server/fibula", timeout=30)
out = []
for path in ["/stats/deaths", "/stats/killers", "/stats/player/Kopacz%20Ognia"]:
    soup = BeautifulSoup(s.get("https://opentibia.info" + path, timeout=30).text, "html.parser")
    out.append("=== " + path)
    for ti, t in enumerate(soup.find_all("table")):
        rows = t.find_all("tr")
        out.append(f"-- table {ti} rows {len(rows)} head: " + " | ".join(th.get_text(" ", strip=True) for th in t.find_all(["th"])[:10]))
        for tr in rows[:6]:
            out.append("   " + " | ".join(td.get_text(" ", strip=True) + ("{" + ",".join(a.get("href","") for a in td.find_all("a"))[:120] + "}" if td.find("a") else "") for td in tr.find_all("td")))
open(sys.argv[1], "w").write("\n".join(out))
