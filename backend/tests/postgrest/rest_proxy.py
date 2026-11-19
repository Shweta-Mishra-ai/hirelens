"""Maps Supabase's /rest/v1/* onto a bare PostgREST, the way Supabase's gateway does."""
import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

import os

UPSTREAM = os.environ.get("E2E_UPSTREAM", "http://127.0.0.1:3001")
client = httpx.AsyncClient(base_url=UPSTREAM, timeout=30)

async def forward(request: Request):
    path = request.path_params["path"]
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length", "apikey")}
    r = await client.request(request.method, "/" + path, params=request.query_params, headers=headers, content=await request.body())
    hop = {"content-encoding", "transfer-encoding", "connection", "content-length"}
    return Response(r.content, status_code=r.status_code, headers={k: v for k, v in r.headers.items() if k.lower() not in hop})

app = Starlette(routes=[Route("/rest/v1/{path:path}", forward, methods=["GET", "POST", "PATCH", "PUT", "DELETE", "HEAD"])])
