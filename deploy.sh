#!/bin/bash

# Step 1: Pull latest code
git fetch --all
git reset --hard origin/main

chmod +x deploy.sh

# Step 2: Build Docker image
sudo docker build --no-cache -t mensa-bot .

# Step 3: Stop & remove any existing container
sudo docker stop mensa-bot-container 2>/dev/null || true
sudo docker rm mensa-bot-container 2>/dev/null || true

# Step 4: Run container in background (detached)
sudo docker run -d --restart always --name mensa-bot-container mensa-bot