import httpx
run = httpx.get("http://127.0.0.1:5678/api/runs/330eff22b8d84dfa92dcb1208a89d93b").json()
node = next(n for n in run["nodeRuns"] if n["nodeId"] == "summarize")
text = node["output"]["sample"]["main"][0]["json"].get("shortSummary", "")
print("repr:", repr(text[:120]))
print("codepoints:", [hex(ord(c)) for c in text[:20]])
open("tests/_summary_utf8.txt", "w", encoding="utf-8").write(text)
