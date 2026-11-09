import os
from fastapi import Depends, FastAPI, Header, HTTPException, Response

from db import insert_calls, ping
from models import CallIn

app = FastAPI(title="llmops-collector")

MAX_BATCH = 100


def require_token(authorization: str = Header(default="")) -> None:
    expected = os.environ.get("LLMOPS_TOKEN", "")
    if not expected or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="bad token")


@app.get("/health")
def health():
    ping()
    return {"status": "ok"}


@app.post("/v1/calls", status_code=202, dependencies=[Depends(require_token)])
def post_call(call: CallIn):
    insert_calls([call.model_dump()])
    return Response(status_code=202)


@app.post("/v1/calls/batch", status_code=202, dependencies=[Depends(require_token)])
def post_batch(calls: list[CallIn]):
    if len(calls) > MAX_BATCH:
        raise HTTPException(status_code=413, detail=f"max {MAX_BATCH} per batch")
    insert_calls([c.model_dump() for c in calls])
    return Response(status_code=202)
