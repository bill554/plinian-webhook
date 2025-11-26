# Plinian Outreach Webhook - Railway Deployment

## Files Needed

```
plinian-webhook/
├── response_detector.py      # Main webhook (use response_detector_railway.py)
├── plinian_outreach_llm.py   # LLM outreach module
├── requirements.txt          # Python dependencies
├── Procfile                  # Railway/Heroku process config
├── extract_gmail_token.py    # Helper to get Gmail token for env var
└── .gitignore
```

## Step 1: Prepare Your Repo

```bash
cd c:\NantucketHub\plinian-webhook

# Rename the Railway-compatible version
copy response_detector.py response_detector_local_backup.py
copy response_detector_railway.py response_detector.py

# Make sure all files are present
dir
```

## Step 2: Create .gitignore

Create a `.gitignore` file:
```
.env
token.json
credentials.json
__pycache__/
*.pyc
.DS_Store
```

## Step 3: Initialize Git (if not already)

```bash
git init
git add .
git commit -m "Plinian outreach webhook - Railway deployment"
```

## Step 4: Extract Gmail Token

```bash
python extract_gmail_token.py
```

Copy the output - you'll need it for Railway.

## Step 5: Create Railway Project

1. Go to https://railway.app
2. Click "New Project"
3. Choose "Deploy from GitHub repo" (or "Empty Project" then connect repo)
4. Connect your GitHub account and select the repo

## Step 6: Configure Environment Variables

In Railway dashboard → Your project → Variables tab:

| Variable | Value |
|----------|-------|
| `NOTION_API_KEY` | `secret_xxxxx` (your Notion integration token) |
| `ANTHROPIC_API_KEY` | `sk-ant-api03-xxxxx` (your Claude API key) |
| `GMAIL_TOKEN_JSON` | (paste the output from extract_gmail_token.py) |
| `OUTREACH_LOG_DB_ID` | `2b5c16a0-949c-8147-8a7f-ca839e1ae002` |

## Step 7: Deploy

Railway will auto-deploy when you push to GitHub, or click "Deploy" manually.

Watch the build logs for any errors.

## Step 8: Get Your Public URL

Once deployed:
1. Go to Settings → Networking
2. Click "Generate Domain" to get a public URL
3. Your webhook will be at: `https://your-app.railway.app/webhook/outreach`

## Step 9: Test It

```bash
curl -X POST https://your-app.railway.app/webhook/outreach \
  -H "Content-Type: application/json" \
  -d '{"firm_id": "YOUR_NOTION_FIRM_PAGE_ID"}'
```

## Step 10: Connect to Notion (Optional)

To trigger from a Notion button:
1. Use a Notion automation or 
2. Use Make.com/Zapier to watch for Notion changes and POST to your Railway URL

---

## Troubleshooting

### "Gmail service not configured"
- Make sure `GMAIL_TOKEN_JSON` is set correctly in Railway
- The token should be a single line of JSON

### "API token is invalid" (Notion)
- Check `NOTION_API_KEY` in Railway variables
- Make sure your Notion integration has access to the database

### "Rate limit" (Anthropic)
- Check your Anthropic API usage at console.anthropic.com
- The fallback template will be used if API is unavailable

### Checking Logs
- Railway dashboard → Deployments → Click on deployment → View Logs

---

## Local Development

You can still run locally with:
```bash
python response_detector.py
```

The code auto-detects whether to use file-based tokens (local) or env-based tokens (Railway).
