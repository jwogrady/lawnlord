import sys, os, json, base64, glob, urllib.request
HOST="http://127.0.0.1:18082"
PROMPT=("Transcribe this filed court document page verbatim — preserve the wording, line breaks, "
 "and reading order; do not summarize, correct, or omit anything. Return JSON with `transcription` "
 "and `fidelity` (0.0-1.0).")
SCHEMA={"type":"object","properties":{"transcription":{"type":"string"},"fidelity":{"type":"number"}},
 "required":["transcription","fidelity"],"additionalProperties":False}
def ask(p):
    img=base64.standard_b64encode(open(p,'rb').read()).decode()
    body={"model":"qwen2.5vl:7b","messages":[{"role":"user","content":[
        {"type":"text","text":PROMPT},
        {"type":"image_url","image_url":{"url":"data:image/png;base64,"+img}}]}],
        "temperature":0,"max_tokens":3072,"repeat_penalty":1.1,
        "response_format":{"type":"json_schema","json_schema":{"name":"page","schema":SCHEMA,"strict":True}}}
    r=urllib.request.Request(HOST+"/v1/chat/completions",data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(r,timeout=600) as resp: d=json.loads(resp.read())
    c=d["choices"][0]["message"]["content"]
    try: j=json.loads(c); return j.get("transcription",""), float(j.get("fidelity",0))
    except Exception: return c, -1
pages=sorted(glob.glob(r"C:\ai\bench_pages\*.png"))
for p in pages:
    t,f=ask(p)
    print(f"\n##### {os.path.basename(p)}  chars={len(t)} fidelity={f}")
    print(t[:280].replace(chr(10),' / '))
