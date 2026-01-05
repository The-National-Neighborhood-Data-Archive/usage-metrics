#!/usr/bin/env python3
"""
NaNDA Usage Metrics Scraper
Runs monthly via GitHub Actions
"""

import os
import json
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import pandas as pd
import requests
import re
import gspread
from google.oauth2.service_account import Credentials

# Configuration
SCRAPE_DATE = datetime.now().strftime('%Y-%m-%d')
OUTPUT_DIR = 'outputs'

# Study IDs
NANDA_IDS = [
    "38567", "38649", "38974", "39093", "39378", "38559", "38598", "38579",
    "38586", "38597", "38585", "38605", "38569", "38528", "38580", "38584",
    "38606", "38506", "38858", "110641", "110663", "111107", "111109", "115006",
    "115323", "115404", "115407", "115408", "115543", "115967", "115972", "115973",
    "115981", "117163", "117866", "117921", "119451", "119803", "120088", "120462",
    "120463", "120907", "121741", "123001", "123042", "123541", "123542", "123801",
    "123802", "124721", "124801", "125223", "125781", "126082", "127042", "127262",
    "127681", "127682", "128281", "128282", "128841", "128862", "130282", "130542",
    "134561", "141121", "155022", "155025", "156024", "156041", "156042", "156043",
    "156045", "159902", "159941", "159961", "159981", "160261", "160262", "190141",
    "207966", "208207", "208366", "208682", "208684", "208751", "208906", "208907",
    "209050", "209163", "209164", "209313", "209324", "210581", "220701", "222263",
    "222901", "230941", "237305"
]

# ============================================================================
# Helper Functions
# ============================================================================

def setup_driver():
    """Set up Chrome driver for GitHub Actions"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def determine_study_type(study_id):
    """Determine if study is ICPSR (5 digits) or openICPSR (6 digits)"""
    return "ICPSR" if len(study_id) == 5 else "openICPSR"

def build_study_url(study_id, study_type):
    """Build URL - DOI for openICPSR auto-redirects to latest version"""
    if study_type == "ICPSR":
        return f"https://www.icpsr.umich.edu/web/ICPSR/studies/{study_id}"
    else:
        return f"https://doi.org/10.3886/E{study_id}"

def extract_number(text):
    """Extract numeric value from text"""
    if not text:
        return 'NA'
    cleaned = re.sub(r'[^0-9]', '', text)
    return cleaned if cleaned else 'NA'

def scrape_study_metrics(study_id, driver):
    """Scrape metrics for a single study"""
    study_type = determine_study_type(study_id)
    url = build_study_url(study_id, study_type)
    
    try:
        driver.get(url)
        
        # Wait for page to load
        if study_type == "ICPSR":
            time.sleep(3)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "studyMetrics"))
            )
        else:  # openICPSR
            time.sleep(5)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "statNum"))
            )
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Extract dataset name
        if study_type == "ICPSR":
            title_elem = soup.find('h1', class_='study-title')
            dataset_name = title_elem.text.strip() if title_elem else 'Unknown'
        else:
            title_elem = soup.find('h1')
            dataset_name = title_elem.text.strip() if title_elem else 'Unknown'
        
        # Extract metrics
        downloads = 'NA'
        citations = 'NA'
        
        if study_type == "ICPSR":
            metrics_div = soup.find('div', id='studyMetrics')
            if metrics_div:
                download_elem = metrics_div.find('span', string=re.compile('Downloads'))
                if download_elem:
                    parent = download_elem.parent
                    number_elem = parent.find('strong') or parent.find('span', class_='count')
                    if number_elem:
                        downloads = extract_number(number_elem.text)
                
                citation_elem = metrics_div.find('span', string=re.compile('Citations'))
                if citation_elem:
                    parent = citation_elem.parent
                    number_elem = parent.find('strong') or parent.find('span', class_='count')
                    if number_elem:
                        citations = extract_number(number_elem.text)
        else:  # openICPSR
            stat_nums = soup.find_all('span', class_='statNum')
            stat_labels = soup.find_all('p', class_='statLabel')
            
            for i, label in enumerate(stat_labels):
                if i < len(stat_nums):
                    label_text = label.text.strip().lower()
                    if 'download' in label_text:
                        downloads = extract_number(stat_nums[i].text)
                    elif 'citation' in label_text:
                        citations = extract_number(stat_nums[i].text)
        
        return {
            'scrape_date': SCRAPE_DATE,
            'study_id': study_id,
            'study_type': study_type,
            'dataset_name': dataset_name,
            'downloads': downloads,
            'citations': citations,
            'url': url
        }
    
    except Exception as e:
        print(f"    ⚠️  Error scraping study {study_id}: {str(e)}")
        return {
            'scrape_date': SCRAPE_DATE,
            'study_id': study_id,
            'study_type': study_type,
            'dataset_name': 'ERROR',
            'downloads': 'ERROR',
            'citations': 'ERROR',
            'url': url
        }

def scrape_publications(max_pages=10):
    """Scrape publications from NaNDA API"""
    base_url = "https://nanda.isr.umich.edu/api/publications/"
    all_publications = []
    page = 1
    
    print("📚 Scraping NaNDA publications...")
    
    while page <= max_pages:
        print(f"  📄 Scraping publications page {page}...")
        
        try:
            url = f"{base_url}?page={page}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if 'results' in data and data['results']:
                publications = data['results']
                print(f"    Found {len(publications)} publications on this page")
                
                for pub in publications:
                    all_publications.append({
                        'title': pub.get('title', ''),
                        'authors': pub.get('authors', ''),
                        'year': pub.get('year', ''),
                        'journal': pub.get('journal', ''),
                        'doi': pub.get('doi', ''),
                        'url': pub.get('url', '')
                    })
                
                if not data.get('next'):
                    break
                    
                page += 1
                time.sleep(1)
            else:
                break
                
        except Exception as e:
            print(f"    ⚠️  Error on page {page}: {e}")
            break
    
    print(f"✅ Collected {len(all_publications)} total publications")
    return all_publications

def setup_google_sheets():
    """Set up Google Sheets connection using service account"""
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not creds_json:
        print("⚠️  No Google credentials found, skipping Sheets upload")
        return None
    
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 
              'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

def save_to_sheets(gc, df, sheet_id, tab_name):
    """Save dataframe to Google Sheets"""
    try:
        sheet = gc.open_by_key(sheet_id)
        
        try:
            worksheet = sheet.worksheet(tab_name)
            print(f"  ⚠️  Tab '{tab_name}' already exists, updating...")
        except gspread.exceptions.WorksheetNotFound:
            print(f"  ➕ Creating new worksheet '{tab_name}'...")
            worksheet = sheet.add_worksheet(title=tab_name, rows=len(df)+1, cols=len(df.columns))
        
        worksheet.clear()
        worksheet.update([df.columns.values.tolist()] + df.values.tolist())
        print(f"  ✅ Saved {len(df)} rows to '{tab_name}'")
        return True
    
    except Exception as e:
        print(f"  ❌ Error saving to Sheets: {e}")
        return False

# ============================================================================
# Main Execution
# ============================================================================

def main():
    print(f"🕒 Starting NaNDA scrape for {SCRAPE_DATE}")
    
    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Scrape study metrics
    print("\n🕸️ Scraping individual study metrics...")
    driver = setup_driver()
    
    results = []
    try:
        for study_id in NANDA_IDS:
            print(f"  Scraping study {study_id}...")
            result = scrape_study_metrics(study_id, driver)
            results.append(result)
            time.sleep(2)
        
        print(f"✅ Collected metrics for {len(results)} studies")
    
    finally:
        driver.quit()
        print("🔒 Browser closed")
    
    # Scrape publications
    print()
    publications = scrape_publications()
    
    # Save CSVs locally
    if results:
        studies_df = pd.DataFrame(results)
        csv_path = f"{OUTPUT_DIR}/nanda_usage_stats_{SCRAPE_DATE}.csv"
        studies_df.to_csv(csv_path, index=False)
        print(f"\n💾 Saved studies CSV: {csv_path}")
    
    if publications:
        pubs_df = pd.DataFrame(publications)
        csv_path = f"{OUTPUT_DIR}/nanda_publications_{SCRAPE_DATE}.csv"
        pubs_df.to_csv(csv_path, index=False)
        print(f"💾 Saved publications CSV: {csv_path}")
    
    # Upload to Google Sheets if credentials available
    gc = setup_google_sheets()
    if gc and results:
        print("\n📊 Uploading to Google Sheets...")
        study_sheet_id = os.environ.get('STUDY_METRICS_SHEET_ID')
        pub_sheet_id = os.environ.get('PUBLICATIONS_SHEET_ID')
        
        if study_sheet_id:
            save_to_sheets(gc, studies_df, study_sheet_id, SCRAPE_DATE)
        
        if pub_sheet_id and publications:
            save_to_sheets(gc, pubs_df, pub_sheet_id, "Sheet1")
    
    print(f"\n🎯 Scrape completed!")
    print(f"  📊 Study metrics: {len(results)} studies")
    print(f"  📚 Publications: {len(publications)} total")
    print("🎉 Done!")

if __name__ == "__main__":
    main()
