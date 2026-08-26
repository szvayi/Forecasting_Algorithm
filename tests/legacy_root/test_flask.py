from flask import Flask

app = Flask(__name__)

@app.route('/')
def hello():
    return 'Hello, World!'

if __name__ == '__main__':
    print('Starting Flask server...')
    print('Please visit: http://localhost:5000')
    app.run(debug=True, host='0.0.0.0', port=5000)
