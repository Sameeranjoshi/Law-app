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
    result = run_bharat_command(['bharat-courts', '--json', 'districtcourts', 'districts', '--state', '27'])
    # This endpoint may not exist; fallback to hardcoded list of common states
    states = [
        {'state_code': 27, 'state_name': 'Maharashtra'},
        {'state_code': 28, 'state_name': 'Manipur'},
        {'state_code': 29, 'state_name': 'Meghalaya'},
        {'state_code': 30, 'state_name': 'Mizoram'},
        {'state_code': 31, 'state_name': 'Nagaland'},
        {'state_code': 32, 'state_name': 'Odisha'},
        {'state_code': 33, 'state_name': 'Punjab'},
        {'state_code': 34, 'state_name': 'Rajasthan'},
    ]
    return jsonify(states)

@app.route('/api/courts/districts', methods=['GET'])
def get_districts():
    """Fetch districts for a state"""
    state = request.args.get('state')
    if not state:
        return jsonify({'error': 'state parameter required'}), 400
    result = run_bharat_command(['bharat-courts', '--json', 'districtcourts', 'districts', '--state', state])
    if 'error' in result:
        return jsonify(result), 500
    return jsonify(result)

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
    return jsonify(result)

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
    return jsonify(result)

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
    return jsonify(result)

if __name__ == '__main__':
    print(f"\n▲ Bharat-Courts Backend running → http://localhost:{FLASK_PORT}\n")
    app.run(host='localhost', port=FLASK_PORT, debug=(FLASK_ENV == 'development'))
