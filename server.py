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

if __name__ == '__main__':
    print(f"\n▲ Bharat-Courts Backend running → http://localhost:{FLASK_PORT}\n")
    app.run(host='localhost', port=FLASK_PORT, debug=(FLASK_ENV == 'development'))
