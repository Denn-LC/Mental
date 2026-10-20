def main() -> None:
    """`uv run mental` starts the app on http://127.0.0.1:8000."""
    import uvicorn

    uvicorn.run("mental.web.app:app", reload=True)
