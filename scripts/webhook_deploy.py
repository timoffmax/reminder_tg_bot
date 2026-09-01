#!/usr/bin/env python3
"""
Webhook deployment script for GitHub
Run this on your server to listen for GitHub webhooks
"""
import hashlib
import hmac
import os
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Must match the secret configured in the GitHub webhook settings.
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')
DEPLOY_SCRIPT = os.getenv('DEPLOY_SCRIPT', '/opt/reminder_tg_bot/scripts/deploy.sh')
LISTEN_HOST = os.getenv('WEBHOOK_HOST', '127.0.0.1')
LISTEN_PORT = int(os.getenv('WEBHOOK_PORT', '8080'))
REPOSITORY_NAME = os.getenv('WEBHOOK_REPOSITORY', 'reminder_tg_bot')

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/webhook':
            self.send_response(404)
            self.end_headers()
            return
            
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        # Verify GitHub signature
        signature = self.headers.get('X-Hub-Signature-256')
        if not self.verify_signature(post_data, signature):
            self.send_response(401)
            self.end_headers()
            logger.warning("Invalid signature")
            return
            
        try:
            payload = json.loads(post_data.decode('utf-8'))
            
            # Only deploy on push to master
            if (payload.get('ref') == 'refs/heads/master' and
                payload.get('repository', {}).get('name') == REPOSITORY_NAME):
                
                logger.info("Deploying bot...")
                result = subprocess.run([DEPLOY_SCRIPT], 
                                      capture_output=True, text=True)
                
                if result.returncode == 0:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'Deployment successful')
                    logger.info("Deployment successful")
                else:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'Deployment failed')
                    logger.error(f"Deployment failed: {result.stderr}")
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'Ignored')
                
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            self.send_response(500)
            self.end_headers()
            
    def verify_signature(self, payload_body, signature_header):
        if not signature_header:
            return False
            
        expected_signature = 'sha256=' + hmac.new(
            WEBHOOK_SECRET.encode('utf-8'),
            payload_body,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature_header)

if __name__ == '__main__':
    if not WEBHOOK_SECRET:
        logger.error(
            "WEBHOOK_SECRET environment variable is required. "
            "Generate one (e.g. `openssl rand -hex 32`), set it here and in the "
            "GitHub webhook settings."
        )
        sys.exit(1)

    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), WebhookHandler)
    logger.info(f"Webhook server starting on {LISTEN_HOST}:{LISTEN_PORT}...")
    server.serve_forever()
