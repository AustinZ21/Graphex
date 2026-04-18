from fastapi import FastAPI

app = FastAPI(title="ADC FastAPI Service")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
