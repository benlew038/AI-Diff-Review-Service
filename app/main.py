from fastapi import FastAPI

from app.api.error_handlers import register_error_handlers
from app.api.routes import router
from app.workers.worker_pool import default_worker_pool

app = FastAPI(title="AI Diff Review Service")
app.include_router(router)
register_error_handlers(app)


@app.on_event("startup")
async def startup_event() -> None:
    await default_worker_pool.start()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await default_worker_pool.stop()
