import requests
import json

response = requests.get('http://localhost:8000/api/analysis-status')
print(json.dumps(response.json(), indent=2, ensure_ascii=False))
