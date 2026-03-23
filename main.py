import uvicorn

from app.config import settings


def main():
    uvicorn.run(
        "app.api:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=True,
    )


if __name__ == "__main__":
    main()
