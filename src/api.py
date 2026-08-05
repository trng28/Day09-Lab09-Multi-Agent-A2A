from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request

from src.coordinator import DisputeWorkflow
from src.main import ROOT


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.workflow = DisputeWorkflow(ROOT / "data")
    yield


app = FastAPI(
    title="Olist Multi-Agent Dispute Resolution",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/cases/assess")
def assess_case(case: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        output, _ = request.app.state.workflow.run(case)
        return output
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
