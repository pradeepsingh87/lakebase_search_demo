"""Small dependency-light chat UI for the hybrid search demo."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .search import make_store

HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lakebase Search Support Demo</title>
<style>
body{font-family:Inter,system-ui,sans-serif;max-width:960px;margin:0 auto;padding:32px;background:#f7f8fa;color:#17202a}
.card{background:#fff;border:1px solid #d9dee7;border-radius:14px;padding:20px;margin:14px 0;box-shadow:0 2px 8px #10203010}
h1{margin:0 0 6px}.muted{color:#5d6b7a}.row{display:flex;gap:10px;flex-wrap:wrap}input,select,button{font:inherit;padding:10px 12px;border:1px solid #bcc6d3;border-radius:8px}input{flex:1;min-width:300px}button{background:#1b6ef3;color:white;border:0;cursor:pointer}button.secondary{background:#64748b}.result{border-top:1px solid #e5e9ef;padding:14px 0}.pill{display:inline-block;padding:3px 8px;border-radius:20px;background:#e9f1ff;color:#1558bd;font-size:12px;margin-right:6px}.answer{font-size:18px;margin:12px 0}.debug{font-family:ui-monospace,monospace;background:#f0f3f7;padding:10px;border-radius:8px;font-size:12px;white-space:pre-wrap}
</style></head><body>
<h1>Lakebase Search support assistant</h1>
<p class="muted">Search exact order IDs or describe a customer issue. The demo combines keyword and vector retrieval, then applies live-style filters.</p>
<div class="card"><div class="row"><input id="q" placeholder="Try: tracking says delivered but nothing came" autofocus><select id="customer"><option value="">All customers</option><option value="customer-a">customer-a</option><option value="customer-b">customer-b</option></select><button onclick="ask()">Search</button></div><p class="muted">Try <code>ORDER-BRAVO</code>, “shoes arrived damaged”, or “marked delivered but missing”.</p></div>
<div id="response" class="card"><div class="muted">Results will appear here.</div></div>
<script>
async function ask(){const q=document.getElementById('q').value.trim();if(!q)return;const customer=document.getElementById('customer').value;const box=document.getElementById('response');box.innerHTML='<div class="muted">Searching...</div>';const r=await fetch('/api/chat',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({query:q,customer_id:customer||null})});const data=await r.json();let html='<div class="answer">'+data.answer+'</div><div class="debug">'+JSON.stringify(data.debug,null,2)+'</div>';for(const x of data.results){html+='<div class="result"><span class="pill">'+x.match_type+'</span><b>'+x.order_id+'</b> · '+x.product_name+'<br><span class="muted">'+x.status+' · '+x.customer_id+' · '+x.order_date+'</span><p>'+x.customer_message+'</p><small>'+x.support_notes+'</small></div>'}box.innerHTML=html}
document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')ask()});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    store = None
    backend = None

    def _send(self, payload, status=200, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else (payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == "/":
            self._send(HTML, content_type="text/html; charset=utf-8")
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/chat":
            self._send({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        query = str(body.get("query", "")).strip()
        if not query:
            self._send({"error": "query is required"}, 400)
            return
        customer_id = body.get("customer_id") or None
        try:
            results = self.store.search(query, customer_id=customer_id, limit=5)
            result_dicts = [r.as_dict() for r in results]
            answer = f"I found {len(results)} matching case(s)."
            if results:
                answer += f" The strongest match is {results[0].order_id} ({results[0].status})."
            self._send({"answer": answer, "results": result_dicts, "debug": {"backend": self.backend, "keyword_and_vector": True, "customer_filter": customer_id or "none", "resolved_cases_included": False}})
        except Exception as exc:
            self._send({"error": str(exc)}, 500)


def main():
    backend = os.environ.get("SEARCH_BACKEND", "local").lower()
    store = make_store(backend)
    Handler.store = store
    Handler.backend = backend
    host = os.environ.get("DEMO_HOST", "127.0.0.1")
    port = int(os.environ.get("DEMO_PORT", "8000"))
    print(f"Lakebase Search demo listening at http://{host}:{port} (backend={backend})")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
