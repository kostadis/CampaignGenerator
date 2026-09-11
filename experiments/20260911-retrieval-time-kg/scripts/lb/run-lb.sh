#!/bin/bash
# Start the load balancer. --network host so it can reach the LAN boxes directly.
docker rm -f spark-lb 2>/dev/null
docker run -d --name spark-lb --restart unless-stopped --network host \
  -v /home/kostadis/cognee-local/lb/spark-lb.conf:/etc/nginx/conf.d/default.conf:ro \
  nginx:alpine
sleep 2
curl -sS --max-time 5 http://localhost:8080/lb-health
curl -sS --max-time 10 http://localhost:8080/v1/models | head -c 200; echo
