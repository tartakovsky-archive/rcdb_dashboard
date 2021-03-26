FROM python:3.7-slim-buster
ENV PYTHONUNBUFFERED 1
RUN pip install --upgrade pip
COPY requirements.txt /app/
COPY rcdb_commons/requirements.txt /app/requirements.rcdb_commons.txt
WORKDIR /app
RUN pip install -r requirements.txt -r requirements.rcdb_commons.txt
COPY . /app/
