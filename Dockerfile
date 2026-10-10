FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app/
# /data holds the SQLite database in the dev setup; owned by app so a named volume inherits it.
RUN mkdir -p /app/staticfiles /app/media /data && chown -R app:app /app /data
USER app
EXPOSE 8000
CMD ["sh","/app/start.sh"]
