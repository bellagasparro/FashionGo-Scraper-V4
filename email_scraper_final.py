from flask import Flask, request, jsonify, send_file
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import os
import time
import tempfile
import logging
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')

def clean_company_name(name):
    if pd.isna(name) or name is None or str(name).strip() == '':
        return None
    
    name = str(name).strip()
    suffixes = [' LLC', ' Inc', ' Corp', ' Corporation', ' Ltd', ' Limited', ' Co', ' Company']
    for suffix in suffixes:
        if name.upper().endswith(suffix.upper()):
            name = name[:-len(suffix)].strip()
    
    return name if name else None

def find_emails_on_page(url, timeout=15):
    """Find email addresses on a given webpage with improved error handling"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        
        # Get text content
        text_content = response.text.lower()
        
        # Find emails in the HTML content
        emails = set(EMAIL_PATTERN.findall(response.text))
        
        # Filter out common false positives and improve filtering
        filtered_emails = []
        for email in emails:
            email_lower = email.lower()
            # More comprehensive filtering
            if not any(x in email_lower for x in [
                'example.com', 'test.com', 'placeholder', 'yoursite', 'yourdomain',
                'sampleemail', 'noreply', 'no-reply', 'donotreply', 'do-not-reply',
                'admin@admin', 'test@test', 'user@user', 'email@email',
                'support@example', 'info@example', 'contact@example'
            ]):
                # Check if email domain matches or is related to the website domain
                email_domain = email_lower.split('@')[1] if '@' in email_lower else ''
                website_domain = url.split('/')[2].lower() if len(url.split('/')) > 2 else ''
                
                # Accept emails that are from the same domain or look legitimate
                if email_domain and (
                    email_domain in website_domain or 
                    website_domain in email_domain or
                    len(email_domain.split('.')) >= 2  # Has proper domain structure
                ):
                    filtered_emails.append(email)
        
        return list(set(filtered_emails))
    
    except requests.exceptions.Timeout:
        logger.error(f"Timeout fetching {url}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error fetching {url}: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"Error fetching {url}: {str(e)}")
        return []

def search_company_website(company_name):
    """Search for company website using multiple search strategies"""
    try:
        if not company_name:
            return None
            
        clean_name = clean_company_name(company_name)
        if not clean_name:
            return None
            
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Try multiple search strategies
        search_queries = [
            f'"{clean_name}" website',
            f'{clean_name} official site',
            f'{clean_name} company website',
            f'{clean_name}'
        ]
        
        for query in search_queries:
            try:
                # Use DuckDuckGo Lite for better parsing
                search_url = f"https://lite.duckduckgo.com/lite/?q={query}"
                
                response = requests.get(search_url, headers=headers, timeout=15)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Look for result links in DuckDuckGo Lite format
                    links = soup.find_all('a')
                    
                    for link in links:
                        href = link.get('href', '') if hasattr(link, 'get') else ''
                        if isinstance(href, str) and href and href.startswith('http') and not any(x in href.lower() for x in ['duckduckgo.com', 'google.com', 'bing.com', 'yahoo.com', 'facebook.com', 'twitter.com', 'linkedin.com', 'instagram.com']):
                            # Validate it looks like a real website
                            domain = href.split('/')[2] if len(href.split('/')) > 2 else ''
                            if '.' in domain and len(domain) > 3:
                                logger.info(f"Found potential website for {clean_name}: {href}")
                                return href
                
                # Small delay between search attempts
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Search attempt failed for query '{query}': {str(e)}")
                continue
        
        # If no results found, try a simple Google search as fallback
        try:
            search_url = f"https://www.google.com/search?q={clean_name}+website"
            response = requests.get(search_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look for Google result links
                for link in soup.find_all('a'):
                    href = link.get('href', '') if hasattr(link, 'get') else ''
                    if isinstance(href, str) and '/url?q=' in href:
                        # Extract actual URL from Google redirect
                        actual_url = href.split('/url?q=')[1].split('&')[0]
                        if actual_url.startswith('http') and not any(x in actual_url.lower() for x in ['google.com', 'facebook.com', 'twitter.com', 'linkedin.com']):
                            logger.info(f"Found website via Google for {clean_name}: {actual_url}")
                            return actual_url
        except Exception as e:
            logger.error(f"Google search fallback failed: {str(e)}")
        
        logger.info(f"No website found for {clean_name}")
        return None
        
    except Exception as e:
        logger.error(f"Error searching for {company_name}: {str(e)}")
        return None

def find_company_email(company_name):
    """Find email for a company with improved search and error handling"""
    try:
        if not company_name:
            return None, None
            
        logger.info(f"Searching for emails for: {company_name}")
        
        # Search for company website
        website = search_company_website(company_name)
        if not website:
            logger.info(f"No website found for {company_name}")
            return None, f"No website found"
        
        logger.info(f"Found website for {company_name}: {website}")
        
        # Check main page first
        emails = find_emails_on_page(website)
        if emails:
            logger.info(f"Found email on main page for {company_name}: {emails[0]}")
            return emails[0], f"Main page: {website}"
        
        # Try common contact pages with better URL construction
        if isinstance(website, str):
            base_url = website.rstrip('/')
            
            # More comprehensive list of contact pages
            contact_pages = [
                '/contact', '/contact-us', '/contactus', '/contact_us',
                '/about', '/about-us', '/aboutus', '/about_us',
                '/team', '/staff', '/people',
                '/info', '/information',
                '/support', '/help'
            ]
            
            for page in contact_pages:
                try:
                    contact_url = base_url + page
                    logger.info(f"Checking contact page: {contact_url}")
                    emails = find_emails_on_page(contact_url)
                    if emails:
                        logger.info(f"Found email on contact page for {company_name}: {emails[0]}")
                        return emails[0], f"Contact page: {contact_url}"
                    
                    # Small delay between page requests
                    time.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"Error checking contact page {contact_url}: {str(e)}")
                    continue
        
        logger.info(f"No emails found for {company_name} on {website}")
        return None, f"No emails found on {website}"
        
    except Exception as e:
        logger.error(f"Error finding email for {company_name}: {str(e)}")
        return None, f"Error: {str(e)}"

@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html><head><title>FashionGo Email Finder</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<style>body{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh}
.main-container{background:white;border-radius:15px;box-shadow:0 10px 30px rgba(0,0,0,0.1);margin:2rem auto;max-width:800px}
.header{background:#2c5aa0;color:white;padding:2rem;border-radius:15px 15px 0 0;text-align:center}</style></head>
<body><div class="container"><div class="main-container"><div class="header">
<h1>🔍 FashionGo Email Finder</h1><p>Upload your FashionGo customer export and find email addresses</p></div>
<div class="p-4"><div class="alert alert-info"><h6>How it works:</h6><ul>
<li>Upload your FashionGo CSV or Excel file</li><li>System detects company names from 'companyName' or 'shipToCompanyName' columns</li>
<li>Searches for each company's website and extracts email addresses</li>
<li>Download enhanced file with email addresses and sources</li></ul></div>
<form id="uploadForm" enctype="multipart/form-data"><div class="mb-3">
<label class="form-label">Select FashionGo Export File:</label>
<input type="file" class="form-control" id="fileInput" name="file" accept=".csv,.xlsx,.xls" required></div>
<button type="submit" class="btn btn-primary btn-lg">🚀 Find Emails</button></form>
<div id="loading" style="display:none" class="text-center mt-4">
<div class="spinner-border text-primary"></div><h5 class="mt-3">Finding email addresses...</h5>
<p class="text-muted">This may take several minutes for large files</p></div>
<div id="results" style="display:none" class="mt-4"><div class="alert alert-success">
<h6>✅ Processing Complete!</h6><div class="row text-center mt-3">
<div class="col-md-4"><div style="font-size:2rem;font-weight:bold;color:#2c5aa0" id="totalCompanies">0</div><small>Companies</small></div>
<div class="col-md-4"><div style="font-size:2rem;font-weight:bold;color:#2c5aa0" id="emailsFound">0</div><small>Emails Found</small></div>
<div class="col-md-4"><div style="font-size:2rem;font-weight:bold;color:#2c5aa0" id="successRate">0%</div><small>Success Rate</small></div></div>
<div class="text-center mt-3"><button id="downloadBtn" class="btn btn-success btn-lg">📥 Download Results</button>
<button class="btn btn-secondary ms-2" onclick="resetForm()">🔄 Process Another File</button></div></div></div>
<div id="error" style="display:none" class="mt-4"><div class="alert alert-danger">
<h6>❌ Error</h6><p id="errorText"></p></div></div></div></div></div>
<script>document.getElementById('uploadForm').addEventListener('submit',function(e){
e.preventDefault();const file=document.getElementById('fileInput').files[0];
if(!file){alert('Please select a file');return;}const formData=new FormData();formData.append('file',file);
document.getElementById('loading').style.display='block';
document.getElementById('results').style.display='none';
document.getElementById('error').style.display='none';
fetch('/upload',{method:'POST',body:formData}).then(r=>r.json()).then(data=>{
document.getElementById('loading').style.display='none';if(data.success){
document.getElementById('totalCompanies').textContent=data.total_companies;
document.getElementById('emailsFound').textContent=data.emails_found;
document.getElementById('successRate').textContent=data.success_rate+'%';
document.getElementById('downloadBtn').onclick=()=>window.location.href=data.download_url;
document.getElementById('results').style.display='block';}else{
document.getElementById('errorText').textContent=data.error;
document.getElementById('error').style.display='block';}}).catch(e=>{
document.getElementById('loading').style.display='none';
document.getElementById('errorText').textContent='Network error: '+e.message;
document.getElementById('error').style.display='block';});});
function resetForm(){document.getElementById('results').style.display='none';
document.getElementById('error').style.display='none';document.getElementById('fileInput').value='';}
</script></body></html>'''

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'}), 200

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if not file or file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        filename = secure_filename(file.filename or 'upload.csv')
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"upload_{int(time.time())}_{filename}")
        file.save(filepath)
        
        try:
            if filename.endswith('.csv'):
                df = pd.read_csv(filepath)
            elif filename.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(filepath)
            else:
                return jsonify({'error': 'Unsupported format'}), 400
        except Exception as e:
            return jsonify({'error': f'Error reading file: {str(e)}'}), 400
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
        
        # Find company column
        company_column = None
        for col in ['companyName', 'shipToCompanyName', 'company_name', 'Company Name', 'Company', 'Name']:
            if col in df.columns:
                company_column = col
                break
        
        if not company_column:
            return jsonify({'error': f'No company column found. Available: {list(df.columns)}'}), 400
        
        # Process all companies (remove 5-company limit)
        results = []
        total_companies = len(df)
        
        for index, row in df.iterrows():
            try:
                company_name_val = row[company_column]
                if pd.isna(company_name_val) or str(company_name_val).strip() == '':
                    continue
                
                company_name = str(company_name_val).strip()
                logger.info(f"Processing: {company_name}")
                
                email, source = find_company_email(company_name)
                
                result_row = row.to_dict()
                result_row['found_email'] = email if email else 'Not found'
                result_row['email_source'] = source if source else 'N/A'
                result_row['processed_company_name'] = company_name
                
                results.append(result_row)
                time.sleep(2)  # Be respectful to websites
                
            except Exception as e:
                logger.error(f"Error processing row: {str(e)}")
                continue
        
        results_df = pd.DataFrame(results)
        
        output_filename = f"email_results_{int(time.time())}.csv"
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
        results_df.to_csv(output_path, index=False)
        
        total_processed = len(results_df)
        emails_found = len(results_df[results_df['found_email'] != 'Not found'].index) if total_processed > 0 else 0
        success_rate = (emails_found / total_processed * 100) if total_processed > 0 else 0
        
        return jsonify({
            'success': True,
            'total_companies': total_processed,
            'emails_found': emails_found,
            'success_rate': round(success_rate, 1),
            'download_url': f'/download/{output_filename}',
            'company_column_used': company_column
        })
        
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/download/<filename>')
def download_file(filename):
    try:
        filename = secure_filename(filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
            
        return send_file(filepath, as_attachment=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port) 