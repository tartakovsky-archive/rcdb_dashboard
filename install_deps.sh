#!/bin/bash

python -m pip install --upgrade "pip<20"
pip install -r requirements.txt
mkdir _req_install
cp install_github.sh _req_install/
cp requirements.github _req_install/
cd _req_install
chmod 0755 install_github.sh
export GITHUB_TOKEN=${{ secrets.RCDB_GITHUB_TOKEN }}
/bin/bash install_github.sh requirements.github
cd ..
