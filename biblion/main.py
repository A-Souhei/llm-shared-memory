from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
from biblion.config import HOST, PORT
from biblion.core import biblion as core
from biblion.routes.biblion import router
from indexer.routes.indexer import router as indexer_router
from indexer.core import indexer as indexer_core


@asynccontextmanager
async def lifespan(app: FastAPI):
    await core.initialize()
    await indexer_core.initialize()
    yield


app = FastAPI(title="Biblion", description="Semantic knowledge base", lifespan=lifespan)
app.include_router(router)
app.include_router(indexer_router)


@app.get("/health")
def health():
    return {"status": "ok"}


def run():
    uvicorn.run("biblion.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    run()
