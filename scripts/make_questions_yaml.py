import re, yaml
tiers = {}
for ids, t in [(range(1, 10), "lookup"), ([10, 11, 12, 22, 23, 24], "conflict_or_missing"),
               ([13, 14, 15, 25, 26, 27, 33], "timeline"), ([16, 17, 18], "counting"),
               ([19, 20, 21, 28, 29, 30], "interpretation"), ([31, 32, 34, 35, 36], "synthesis")]:
    for i in ids:
        tiers[i] = t
qs = []
for line in open("data/questions_2744.txt", encoding="utf-8"):
    m = re.match(r"\s*(\d+)\.\s+(.*\S)", line)
    if m:
        n = int(m.group(1))
        qs.append({"id": f"q{n:02d}", "tier": tiers[n], "phrasings": [m.group(2)], "answer_key": None})
assert len(qs) == 36 and len(tiers) == 36
yaml.safe_dump(qs, open("data/questions_2744.yaml", "w", encoding="utf-8"), sort_keys=False, allow_unicode=True, width=200)
