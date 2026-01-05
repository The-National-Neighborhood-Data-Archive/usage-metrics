# NaNDA Usage Metrics Scraper

Automated monthly scraper for NaNDA dataset usage statistics (downloads & citations) from ICPSR and openICPSR.

## How It Works

- Runs automatically on the 1st of every month at 9 AM UTC
- Scrapes download and citation counts from ICPSR and openICPSR
- Scrapes publications from NaNDA API
- Saves results as CSV files in the `data/` directory
- Commits results back to the repository

## Setup Instructions

### 1. Upload Files to GitHub

Upload these files to your repository:
- `.github/workflows/monthly-scrape.yml` - GitHub Actions workflow
- `scraper.py` - Main scraping script
- `requirements.txt` - Python dependencies
- `README.md` - This file
- `.gitignore` - Keeps Python cache out of repo

### 2. Test the Workflow

1. Go to the "Actions" tab in your repository
2. Click "NaNDA Monthly Scraper"
3. Click "Run workflow" → "Run workflow"
4. Monitor the progress
5. Check the `data/` directory for CSV files after it completes

### 3. Done!

That's it! No secrets, no Google setup needed. Just upload and run.

## Output Files

All files are saved in the `data/` directory:

**Study Metrics:**
- `nanda_usage_stats_YYYY-MM-DD.csv` - Dated snapshots
- `nanda_usage_stats_latest.csv` - Always contains most recent scrape

**Publications:**
- `nanda_publications_YYYY-MM-DD.csv` - Dated snapshots
- `nanda_publications_latest.csv` - Always contains most recent scrape

## Study Types

- **ICPSR** (5-digit IDs): Scraped from `icpsr.umich.edu`
- **openICPSR** (6-digit IDs): Scraped via DOI redirect (automatically gets latest version)

## CSV Columns

**nanda_usage_stats_*.csv:**
- `scrape_date` - Date of scrape
- `study_id` - Study ID number
- `study_type` - ICPSR or openICPSR
- `dataset_name` - Full dataset title
- `downloads` - Number of downloads
- `citations` - Number of citations
- `url` - URL scraped

**nanda_publications_*.csv:**
- `title` - Publication title
- `authors` - Authors list
- `year` - Publication year
- `journal` - Journal name
- `doi` - DOI if available
- `url` - Publication URL

## Troubleshooting

**Workflow fails:**
- Check the Actions tab for error logs
- Common issues are usually rate limiting or site changes

**403 Forbidden errors:**
- Some openICPSR studies may block automated access
- These will be marked as ERROR in the output

**Missing data:**
- Some studies may not have metrics displayed
- These will show as 'NA' in the CSV

## Manual Run (Local)

```bash
# Install dependencies
pip install -r requirements.txt

# Install Chrome/ChromeDriver (varies by OS)

# Run scraper
python scraper.py

# Results will be in data/ directory
```

## Schedule

- **Automatic:** 1st of every month at 9 AM UTC
- **Manual:** Anytime from the Actions tab

## Files Structure

```
usagemetrics/
├── .github/
│   └── workflows/
│       └── monthly-scrape.yml
├── data/
│   ├── nanda_usage_stats_YYYY-MM-DD.csv
│   ├── nanda_usage_stats_latest.csv
│   ├── nanda_publications_YYYY-MM-DD.csv
│   └── nanda_publications_latest.csv
├── scraper.py
├── requirements.txt
├── .gitignore
└── README.md
```
