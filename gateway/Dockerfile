FROM python:3.12-slim
WORKDIR /app
COPY shared /shared
COPY gateway/requirements.txt .
RUN pip install --no-cache-dir /shared -r requirements.txt
COPY gateway .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
