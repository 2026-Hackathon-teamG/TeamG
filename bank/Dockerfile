FROM python:3.12-slim
WORKDIR /app
COPY shared /shared
COPY bank/requirements.txt .
RUN pip install --no-cache-dir /shared -r requirements.txt
COPY bank .
EXPOSE 8001
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py seed_customers --if-empty && python manage.py runserver 0.0.0.0:8001"]
