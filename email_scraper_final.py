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

def find_emails_on_page(url, timeout=10):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        emails = set(EMAIL_PATTERN.findall(response.text))
        
        filtered_emails = []
        for email in emails:
            email_lower = email.lower()
            if not any(x in email_lower for x in ['example.com', 'test.com', 'placeholder', 'yoursite', 'yourdomain']):
                filtered_emails.append(email)
        
        return list(set(filtered_emails))
    
    except Exception as e:
        logger.error(f"Error fetching {url}: {str(e)}")
        return []

def search_company_website(company_name):
    try:
        if not company_name:
            return None
            
        clean_name = clean_company_name(company_name)
        if not clean_name:
            return None
            
        search_query = f"{clean_name} official website"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        search_url = f"https://duckduckgo.com/html/?q={search_query}"
        
        response = requests.get(search_url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        links = soup.find_all('a', {'class': 'result__a'})
        
        for link in links[:3]:
            href = link.get('href') if hasattr(link, 'get') else None
            if href and 'http' in href:
                return href
                
        return None
        
    except Exception as e:
        logger.error(f"Error searching for {company_name}: {str(e)}")
        return None

def find_company_email(company_name):
    try:
        if not company_name:
            return None, None
            
        logger.info(f"Searching for emails for: {company_name}")
        
        website = search_company_website(company_name)
        if not website:
            logger.info(f"No website found for {company_name}")
            return None, None
        
        logger.info(f"Found website for {company_name}: {website}")
        
        emails = find_emails_on_page(website)
        if emails:
            return emails[0], f"Main page: {website}"
        
        if isinstance(website, str):
            base_url = website.rstrip('/')
            contact_pages = ['/contact', '/contact-us', '/about', '/about-us']
            
            for page in contact_pages:
                try:
                    contact_url = base_url + page
                    emails = find_emails_on_page(contact_url)
                    if emails:
                        return emails[0], f"Contact page: {contact_url}"
                except:
                    continue
        
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
<p class="text-muted">Processing first 5 companies (demo version)</p></div>
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
        
        # Process first 5 companies
        results = []
        total_companies = min(len(df), 5)
        
        for index, row in df.head(total_companies).iterrows():
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
        emails_found = len(results_df[results_df['found_email'] != 'Not found']) if total_processed > 0 else 0
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