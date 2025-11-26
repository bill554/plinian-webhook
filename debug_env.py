import os
from dotenv import load_dotenv

# Print current directory
print(f"Current dir: {os.getcwd()}")

# Check if .env exists
print(f".env exists: {os.path.exists('.env')}")

# Load and check
load_dotenv()
key = os.getenv("ANTHROPIC_API_KEY")
print(f"Key found: {key[:20] if key else 'NOT FOUND'}...")