FROM python:3.7-slim-buster
ENV PYTHONUNBUFFERED 1
COPY .ssh/gh_rsa /root/.ssh/id_rsa
RUN chmod 600 /root/.ssh/id_rsa && \
    apt-get update && apt-get install -y git && \
    ssh-keyscan github.com >> /root/.ssh/known_hosts && \
    pip install -U pip
COPY requirements.txt /app/
COPY rcdb_commons/requirements.txt /app/requirements.rcdb_commons.txt
WORKDIR /app
RUN pip install --upgrade importlib-metadata && pip install -r requirements.txt -r requirements.rcdb_commons.txt
COPY . /app/
RUN ./manage.py collectstatic --noinput
