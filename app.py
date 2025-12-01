from flask import Flask, request, jsonify
import requests
import os
import logging
from datetime import datetime
import hmac
import hashlib

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

NOTION_API_KEY = os.environ.get('NOTION_API_KEY')
CLAY_FIRM_WEBHOOK_URL = os.environ.get('CLAY_FIRM_WEBHOOK_URL')
CLAY_PERSON_WEBHOOK_URL = os.environ.get('CLAY_PERSON_WEBHOOK_URL')
RAILWAY_WEBHOOK_SECRET = os.environ.get('RAILWAY_WEBHOOK_SECRET')
RAILWAY_PUBLIC_URL = os.environ.get('RAILWAY_PUBLIC_URL', '')

# Notion Database IDs
PROSPECT_FIRMS_DB_ID = '2aec16a0-949c-802a-851e-de429d9503f4'
PROSPECTS_DB_ID = '2aec16a0-949c-8061-9fdd-daabdc22d5e2'

NOTION_HEADERS = {
    'Authorization': f'Bearer {NOTION_API_KEY}',
    'Content-Type': 'application/json',
    'Notion-Version': '2022-06-28'
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def verify_webhook_signature(request):
    """Verify the webhook signature from Notion"""
    if not RAILWAY_WEBHOOK_SECRET:
        logger.warning("No webhook secret configured, skipping verification")
        return True
    
    signature = request.headers.get('X-Webhook-Signature', '')
    if signature == RAILWAY_WEBHOOK_SECRET:
        return True
    
    logger.warning("Invalid webhook signature")
    return False

def extract_domain(website_url):
    """Extract
