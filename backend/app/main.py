from fastapi import FastAPI

from app.api.health import router as health_router

app = FastAPI(
    title="Enterprise AI Agent Platform",
    description=(
        "AI Agent platform for enterprise knowledge retrieval "
        "and IoT device diagnosis."
    ),
    version="0.1.0",
)

app.include_router(health_router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Enterprise AI Agent Platform API",
    }