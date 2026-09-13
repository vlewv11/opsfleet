FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 MPLBACKEND=Agg

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY configs ./configs
COPY src ./src
COPY data/knowledge_base ./data/knowledge_base
COPY data/persona.md data/schema.json ./data/
COPY docs/demo/demo-questions.txt ./docs/demo/

CMD exec uvicorn src.web.app:app --host 0.0.0.0 --port ${PORT:-8080}
