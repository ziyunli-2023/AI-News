#!/bin/bash
set -e

echo "配置 systemd 自启动服务..."

sudo tee /etc/systemd/system/ai-news.service > /dev/null << 'EOF'
[Unit]
Description=AI News Monitor
After=network.target

[Service]
Type=simple
User=ziyun-pc
WorkingDirectory=/mnt/c/Users/liziy/Code/AI-News
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10
StandardOutput=append:/mnt/c/Users/liziy/Code/AI-News/logs/app.log
StandardError=append:/mnt/c/Users/liziy/Code/AI-News/logs/app.log
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/ai-news-tunnel.service > /dev/null << 'EOF'
[Unit]
Description=Cloudflare Tunnel - AI News
After=network.target ai-news.service

[Service]
Type=simple
User=ziyun-pc
ExecStart=/usr/local/bin/cloudflared tunnel run ai-news
Restart=always
RestartSec=10
StandardOutput=append:/mnt/c/Users/liziy/Code/AI-News/logs/tunnel.log
StandardError=append:/mnt/c/Users/liziy/Code/AI-News/logs/tunnel.log

[Install]
WantedBy=multi-user.target
EOF

# 停止手动启动的进程
pkill -f "python3 main.py" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 2

sudo systemctl daemon-reload
sudo systemctl enable ai-news ai-news-tunnel
sudo systemctl start ai-news ai-news-tunnel

sleep 3
sudo systemctl status ai-news ai-news-tunnel --no-pager
