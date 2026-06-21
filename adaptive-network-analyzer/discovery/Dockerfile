FROM python:3.11-alpine

RUN apk add --no-cache iproute2 net-tools iputils

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY discover.py .

CMD ["python", "-u", "discover.py"]
