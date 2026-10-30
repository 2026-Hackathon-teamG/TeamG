FROM python:3.12-slim
WORKDIR /app
COPY shared /shared
COPY detector/requirements.txt .
RUN pip install --no-cache-dir /shared -r requirements.txt
COPY detector .
EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
