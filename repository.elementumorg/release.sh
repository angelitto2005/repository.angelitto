#!/bin/bash

set -e

TAG=$(git describe --tags)

git checkout master

rm -f *.zip

sudo -S true

# Install Python dependencies
pip3 install flake8

# Run linting
python3 -m flake8 || true

# Compile zip artifacts
make

# Run artifact uploads if we are on the tag
if [[ $TAG != *-* ]]
then
	make zip
    make upload
fi
