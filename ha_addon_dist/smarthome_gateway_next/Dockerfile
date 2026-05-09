FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

EXPOSE 8099
CMD ["/app/run.sh"]
