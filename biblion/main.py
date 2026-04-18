from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
from biblion.config import HOST, PORT
from biblion.core import biblion as core
from biblion.routes.biblion import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await core.initialize()
    yield


app = FastAPI(title="Biblion", description="Semantic knowledge base", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}


def run():
    uvicorn.run("biblion.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    run()
