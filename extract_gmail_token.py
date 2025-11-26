"""
extract_gmail_token.py
======================
Extracts your Gmail token.json contents as a single-line string
for use as a Railway environment variable.

Usage:
    python extract_gmail_token.py

This will print the token JSON that you can copy into Railway's
GMAIL_TOKEN_JSON environment variable.
"""

import json
import os

TOKEN_PATH = "token.json"

if not os.path.exists(TOKEN_PATH):
    print(f"❌ {TOKEN_PATH} not found in current directory")
    print(f"   Current directory: {os.getcwd()}")
    exit(1)

with open(TOKEN_PATH, "r") as f:
    token_data = json.load(f)

# Output as single-line JSON (for env var)
single_line = json.dumps(token_data, separators=(',', ':'))

print("=" * 60)
print("GMAIL_TOKEN_JSON value for Railway:")
print("=" * 60)
print()
print(single_line)
print()
print("=" * 60)
print("Copy the above line and paste it as the value for")
print("GMAIL_TOKEN_JSON in Railway's environment variables.")
print("=" * 60)
