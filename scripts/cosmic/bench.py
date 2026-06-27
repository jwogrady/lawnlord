import sys, os, json, time, base64, glob, urllib.request

BACKEND = sys.argv[1]            # 'llamacpp' or 'ollama'
HOST    = sys.argv[2]            # e.g. http://127.0.0.1:18082
MAXPX   = int(sys.argv[3])       # 0 = native render; else longest-side cap
PAGEDIR = sys.argv[4] if len(sys.argv) > 4 else r"C:\ai\bench_pages"
MODEL   = "qwen2.5vl:7b"

PROMPT = ("Transcribe this filed court document page verbatim — preserve the wording, "
 "line breaks, and reading order; do not summarize, correct, or omit anything. "
 "Return JSON with `transcription` (the full page text) and `fidelity` (0.0–1.0: "
 "your confidence the transcription is complete and accurate given how legible the image is).")
SCHEMA = {"type":"object","properties":{"transcription":{"type":"string"},
 "fidelity":{"type":"number"}},"required":["transcription","fidelity"],"additionalProperties":False}

def b64(path, maxpx):
    if not maxpx:
        return base64.standard_b64encode(open(path,'rb').read()).decode()
    from io import BytesIO
    from PIL import Image
    im = Image.open(path); longest = max(im.size)
    if longest > maxpx:
        s = maxpx/longest; im = im.resize((round(im.width*s), round(im.height*s)))
    buf = BytesIO(); im.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode()

def call(path):
    img = b64(path, MAXPX)
    if BACKEND == "llamacpp":
        url = HOST + "/v1/chat/completions"
        body = {"model":MODEL,"messages":[{"role":"user","content":[
                  {"type":"text","text":PROMPT},
                  {"type":"image_url","image_url":{"url":"data:image/png;base64,"+img}}]}],
                "temperature":0,"max_tokens":3072,"repeat_penalty":1.1,"repeat_last_n":64,
                "response_format":{"type":"json_schema","json_schema":{"name":"page","schema":SCHEMA,"strict":True}}}
    else:
        url = HOST + "/api/chat"
        body = {"model":MODEL,"messages":[{"role":"user","content":PROMPT,"images":[img]}],
                "stream":False,"format":SCHEMA,"options":{"temperature":0,"num_ctx":8192}}
    data = json.dumps(body).encode()
    t0 = time.time()
    req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        resp = json.loads(r.read())
    wall = time.time()-t0
    # extract content + timings per backend
    if BACKEND == "llamacpp":
        ch = resp["choices"][0]; content = ch["message"]["content"]
        tim = resp.get("timings",{}); usage = resp.get("usage",{})
        ptok = tim.get("prompt_n", usage.get("prompt_tokens"))
        pms  = tim.get("prompt_ms"); gtok = tim.get("predicted_n", usage.get("completion_tokens")); gms = tim.get("predicted_ms")
        finish = ch.get("finish_reason")
    else:
        content = resp["message"]["content"]
        ptok = resp.get("prompt_eval_count"); pms = resp.get("prompt_eval_duration",0)/1e6
        gtok = resp.get("eval_count"); gms = resp.get("eval_duration",0)/1e6
        finish = resp.get("done_reason")
    try:
        j = json.loads(content); text = j.get("transcription",""); fid = float(j.get("fidelity",0))
        ok = True
    except Exception:
        text = content; fid = 0.0; ok = False
    return dict(wall=wall, ptok=ptok, pms=pms, gtok=gtok, gms=gms, finish=finish,
               chars=len(text), fid=fid, ok=ok)

import concurrent.futures as cf
WORKERS = int(sys.argv[5]) if len(sys.argv) > 5 else 1
pages = sorted(glob.glob(PAGEDIR + r"\*.png"))
print(f"=== {BACKEND} @ {HOST}  maxpx={MAXPX or 'native'}  pages={len(pages)}  workers={WORKERS} ===")
# warmup (load model) on the first page; exclude it from the timed set so no
# prompt-cache hit inflates throughput.
try: call(pages[0])
except Exception as e: print("warmup err:", e)
timed = pages[1:] if len(pages) > 1 else pages
rows=[]; errs=[]
def run(p):
    try:
        r = call(p); r['name']=os.path.basename(p); return r
    except Exception as e:
        return {'err': str(e), 'name': os.path.basename(p)}
t0 = time.time()
with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
    for r in ex.map(run, timed):
        if 'err' in r: errs.append(r); print(f"{r['name']}  ERROR: {r['err']}")
        else:
            rows.append(r)
            tps = (r['gtok']/(r['gms']/1000)) if r['gtok'] and r['gms'] else 0
            print(f"{r['name']}  wall={r['wall']:.1f}s  gen={tps:.1f}t/s({r['gtok']}tok)  chars={r['chars']}  fid={r['fid']:.2f}  {'OK' if r['ok'] else 'PARSE_FAIL'}  finish={r['finish']}")
wall_total = time.time()-t0
if rows:
    n=len(rows)
    print(f"--- {n} pages in {wall_total:.1f}s wall | {n/wall_total*60:.1f} PAGES/MIN | "
          f"avg gen {sum((r['gtok'] or 0) for r in rows)/sum((r['gms'] or 1)/1000 for r in rows):.1f}t/s | "
          f"fails={len(errs)+sum(1 for r in rows if not r['ok'])} | avg fid {sum(r['fid'] for r in rows)/n:.2f}")
else:
    print(f"--- ALL FAILED ({len(errs)} errors)")
