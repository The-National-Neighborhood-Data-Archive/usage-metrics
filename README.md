# NaNDA Usage Metrics Scraper

Automated monthly scraper for NaNDA dataset usage statistics (downloads & citations) from ICPSR and openICPSR.

## Setup Instructions

### 1. Create GitHub Repository

1. Create a new private repository on GitHub
2. Clone it locally or upload these files:
   - `.github/workflows/monthly-scrape.yml`
   - `scraper.py`
   - `requirements.txt`
   - `README.md`

### 2. Set Up Google Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable Google Sheets API and Google Drive API
4. Create a Service Account:
   - Go to IAM & Admin → Service Accounts
   - Create service account
   - Download JSON key file
5. Share your Google Sheets with the service account email (found in the JSON)
   - Share with Editor permissions

### 3. Configure GitHub Secrets

Go to your repository → Settings → Secrets and variables → Actions

Add these secrets:

**GOOGLE_CREDENTIALS**
- Copy the entire contents of your service account JSON key file
- Paste as the secret value (entire JSON object)

**STUDY_METRICS_SHEET_ID**
- Your Google Sheet ID for study metrics
- Example: `1Iyp8Fa6XueBx1uWFaly2R0t_gpobLohu3sKyi--Ujlc`
- Found in the URL: `https://docs.google.com/spreadsheets/d/[SHEET_ID]/edit`

**PUBLICATIONS_SHEET_ID**
- Your Google Sheet ID for publications
- Example: `1RVK8YGUgJQWKS7Nwf-fv97OUVVTMj3wD1L2-xjb3YbA`

### 4. Test the Workflow

1. Go to Actions tab in your repository
2. Select "NaNDA Monthly Scraper"
3. Click "Run workflow" → "Run workflow"
4. Monitor the progress

## Schedule

- Runs automatically on the 1st of every month at 9 AM UTC
- Can be manually triggered from the Actions tab

## Output

- **CSV files**: Saved in `outputs/` directory in the repository
- **Google Sheets**: 
  - Study metrics: New tab created for each scrape date
  - Publications: Appended to existing sheet

## Study Types

- **ICPSR** (5-digit IDs): Scraped from `icpsr.umich.edu`
- **openICPSR** (6-digit IDs): Scraped via DOI redirect (auto-gets latest version)

## Troubleshooting

**"No Google credentials found"**
- Check that GOOGLE_CREDENTIALS secret is set correctly
- Ensure it's the complete JSON (starts with `{` and ends with `}`)

**403 Forbidden errors**
- Some openICPSR studies may block automated access
- These will be marked as ERROR in the output

**Workflow fails**
- Check Actions tab for error logs
- Verify secrets are set correctly
- Ensure Google Sheets are shared with service account

## Manual Run (Local)

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export GOOGLE_CREDENTIALS='{"type": "service_account", ...}'
export STUDY_METRICS_SHEET_ID='your-sheet-id'
export PUBLICATIONS_SHEET_ID='your-sheet-id'

# Run scraper
python scraper.py
```

## Files

- `.github/workflows/monthly-scrape.yml`: GitHub Actions workflow
- `scraper.py`: Main scraping script
- `requirements.txt`: Python dependencies
- `outputs/`: CSV files (gitignored by default)
