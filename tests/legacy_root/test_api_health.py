import requests
import sys

try:
    response = requests.get('http://localhost:8000/api/health', timeout=5)
    print('Status code:', response.status_code)
    print('Response:', response.json())
    sys.exit(0)
except Exception as e:
    print('Error:', str(e))
    sys.exit(1)
