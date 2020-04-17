FROM python:3.7.5-buster

ENV PYTHONUNBUFFERED 1
RUN pip install --upgrade pip

COPY requirements.txt /app/
WORKDIR /app
RUN pip install -r requirements.txt

COPY req.github /app/
COPY github_release_install_python.sh /app/github_release_install_python.sh
RUN chmod 0755 github_release_install_python.sh
ARG GITHUB_TOKEN=""
ENV GITHUB_TOKEN=${GITHUB_TOKEN}
RUN /bin/bash github_release_install_python.sh req.github
RUN python -c "import rcdb_libs"
COPY . /app/