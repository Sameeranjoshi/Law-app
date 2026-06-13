from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import os
import json
import subprocess
from datetime import datetime

load_dotenv()

app = Flask(__name__)
CORS(app)

FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
FLASK_ENV = os.getenv('FLASK_ENV', 'development')

def run_bharat_command(cmd_list):
    """
    Execute a bharat-courts CLI command and return parsed JSON output.
    cmd_list: list of command parts, e.g., ['bharat-courts', '--json', 'districtcourts', 'districts', '--state', '27']
    Returns: parsed JSON object or error dict
    """
    try:
        result = subprocess.run(cmd_list, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {'error': result.stderr or 'Command failed'}
        if not result.stdout.strip():
            return {'error': 'No output from bharat-courts'}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {'error': 'Command timed out (30s)'}
    except json.JSONDecodeError:
        return {'error': 'Invalid JSON from bharat-courts'}
    except Exception as e:
        return {'error': str(e)}

def dict_to_options(d):
    """
    Convert bharat-courts response dict {code: name} to sorted array
    of {code, name} objects for dropdown options.
    """
    if not isinstance(d, dict):
        return d  # Already a list or other format — return as-is
    return sorted(
        [{'code': code, 'name': name} for code, name in d.items()],
        key=lambda x: x['name']
    )

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# ===== COURT HIERARCHY ENDPOINTS =====

@app.route('/api/courts/states', methods=['GET'])
def get_states():
    """Fetch all states"""
    # bharat-courts 'states' command uses display codes that DON'T match the codes
    # required by 'districts'. This hardcoded list uses the codes that actually work
    # with the districts/complexes/establishments queries (verified by probing).
    states = {
        "1": "Maharashtra",
        "2": "Andhra Pradesh",
        "3": "Karnataka",
        "4": "Kerala",
        "5": "Himachal Pradesh",
        "6": "Assam",
        "7": "Delhi",
        "8": "Bihar",
        "9": "Rajasthan",
        "10": "Haryana",
        "11": "Odisha",
        "12": "Jammu and Kashmir",
        "13": "Uttar Pradesh",
        "14": "Jharkhand",
        "15": "Uttarakhand",
        "16": "West Bengal",
        "17": "Gujarat",
        "18": "Chhattisgarh",
        "20": "Tripura",
        "21": "Meghalaya",
        "22": "Punjab",
        "23": "Madhya Pradesh",
        "24": "Sikkim",
        "25": "Manipur",
        "26": "Arunachal Pradesh",
        "29": "Telangana",
        "30": "Goa",
        "31": "Puducherry",
        "33": "Ladakh",
        "34": "Mizoram",
        "35": "Lakshadweep",
        "36": "Nagaland",
    }
    return jsonify(dict_to_options(states))

@app.route('/api/courts/districts', methods=['GET'])
def get_districts():
    """Fetch districts for a state"""
    state = request.args.get('state')
    if not state:
        return jsonify({'error': 'state parameter required'}), 400
    result = run_bharat_command(['bharat-courts', '--json', 'districtcourts', 'districts', '--state', state])
    if 'error' in result:
        return jsonify(result), 500
    return jsonify(dict_to_options(result))

@app.route('/api/courts/complexes', methods=['GET'])
def get_complexes():
    """Fetch court complexes for a district"""
    state = request.args.get('state')
    dist = request.args.get('dist')
    if not state or not dist:
        return jsonify({'error': 'state and dist parameters required'}), 400
    result = run_bharat_command(['bharat-courts', '--json', 'districtcourts', 'complexes', '--state', state, '--dist', dist])
    if 'error' in result:
        return jsonify(result), 500
    return jsonify(dict_to_options(result))

@app.route('/api/courts/establishments', methods=['GET'])
def get_establishments():
    """Fetch establishments for a court complex"""
    state = request.args.get('state')
    dist = request.args.get('dist')
    complex_code = request.args.get('complex')
    if not all([state, dist, complex_code]):
        return jsonify({'error': 'state, dist, and complex parameters required'}), 400
    result = run_bharat_command(['bharat-courts', '--json', 'districtcourts', 'establishments', '--state', state, '--dist', dist, '--complex', complex_code])
    if 'error' in result:
        return jsonify(result), 500
    return jsonify(dict_to_options(result))

@app.route('/api/courts/courts', methods=['GET'])
def get_courts():
    """Fetch courts for an establishment"""
    state = request.args.get('state')
    dist = request.args.get('dist')
    complex_code = request.args.get('complex')
    est = request.args.get('est')
    if not all([state, dist, complex_code, est]):
        return jsonify({'error': 'state, dist, complex, and est parameters required'}), 400
    result = run_bharat_command(['bharat-courts', '--json', 'districtcourts', 'courts', '--state', state, '--dist', dist, '--complex', complex_code, '--est', est])
    if 'error' in result:
        return jsonify(result), 500
    return jsonify(dict_to_options(result))

# ===== CAUSE LIST ENDPOINT =====

@app.route('/api/causelist', methods=['GET'])
def get_causelist():
    """Fetch cause list for a court and date"""
    state = request.args.get('state')
    dist = request.args.get('dist')
    complex_code = request.args.get('complex')
    court_no = request.args.get('court_no')
    date_str = request.args.get('date')  # Format: DD-MM-YYYY

    if not all([state, dist, complex_code, court_no, date_str]):
        return jsonify({'error': 'state, dist, complex, court_no, and date parameters required'}), 400

    # Validate date format (basic check)
    try:
        datetime.strptime(date_str, '%d-%m-%Y')
    except ValueError:
        return jsonify({'error': 'date must be in DD-MM-YYYY format'}), 400

    result = run_bharat_command([
        'bharat-courts', '--json', 'districtcourts', 'cause-list',
        '--state', state, '--dist', dist, '--complex', complex_code, '--court-no', court_no,
        '--date', date_str
    ])

    if 'error' in result:
        return jsonify(result), 500

    return jsonify({'data': result, 'date': date_str, 'query': {'state': state, 'dist': dist, 'complex': complex_code, 'court_no': court_no}})

# ===== SEARCH BY PARTY ENDPOINT =====

@app.route('/api/search-party', methods=['GET'])
def search_by_party():
    """Search cases by party name and year"""
    state = request.args.get('state')
    dist = request.args.get('dist')
    complex_code = request.args.get('complex')
    est = request.args.get('est')
    party = request.args.get('party')
    year = request.args.get('year', str(datetime.now().year))

    if not all([state, dist, complex_code, party]):
        return jsonify({'error': 'state, dist, complex, and party parameters required'}), 400

    # Validate year
    try:
        year_int = int(year)
        if year_int < 1950 or year_int > datetime.now().year:
            return jsonify({'error': 'year must be between 1950 and current year'}), 400
    except ValueError:
        return jsonify({'error': 'year must be an integer'}), 400

    cmd = [
        'bharat-courts', '--json', 'districtcourts', 'search-by-party',
        '--state', state, '--dist', dist, '--complex', complex_code,
        '--party', party, '--year', year
    ]
    if est:
        cmd.extend(['--est', est])
    result = run_bharat_command(cmd)

    if 'error' in result:
        return jsonify(result), 500

    return jsonify({'data': result, 'query': {'party': party, 'year': year}})

# ===== CNR LOOKUP & ORDERS ENDPOINTS =====

@app.route('/api/lookup-cnr', methods=['GET'])
def lookup_cnr():
    """Lookup a case by CNR"""
    cnr = request.args.get('cnr')
    if not cnr:
        return jsonify({'error': 'cnr parameter required'}), 400

    # bharat-courts may not have a direct CNR lookup; this might return empty or error
    # Fallback: return a message that CNR lookup requires more context
    return jsonify({
        'error': 'Direct CNR lookup via bharat-courts not yet available',
        'note': 'Use search-by-party or cause-list to find cases, then get CNR from results',
        'cnr': cnr
    }), 501

@app.route('/api/orders', methods=['GET'])
def get_orders():
    """Fetch orders for a case by CNR"""
    cnr = request.args.get('cnr')
    if not cnr:
        return jsonify({'error': 'cnr parameter required'}), 400

    # This may not be directly available from bharat-courts CLI
    # Return placeholder
    return jsonify({
        'error': 'Orders retrieval via bharat-courts not yet available',
        'note': 'This endpoint is a placeholder for future bharat-courts orders integration',
        'cnr': cnr
    }), 501

if __name__ == '__main__':
    print(f"\n▲ Bharat-Courts Backend running → http://localhost:{FLASK_PORT}\n")
    app.run(host='localhost', port=FLASK_PORT, debug=(FLASK_ENV == 'development'))
