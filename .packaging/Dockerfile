FROM python:3.7.5-buster

ENV PYTHONUNBUFFERED 1
RUN pip install --upgrade pip

COPY requirements.txt /app/
WORKDIR /app
RUN pip install -r requirements.txt

COPY requirements.github /app/
COPY install_github.sh /app/install_github.sh
RUN chmod 0755 install_github.sh
ARG GITHUB_TOKEN=""
ENV GITHUB_TOKEN=${GITHUB_TOKEN}
RUN /bin/bash install_github.sh requirements.github
RUN python -c "import rcdb_libs"
COPY . /app/
