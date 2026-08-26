# TEMP: 临时添加一个显式的静态文件路由，用于排查
import os # 需要在文件顶部导入 os 模块

# ... (在 app = Flask(...) 和 CORS(app) 之后) ...

@app.route('/static/<path:filename>')
def serve_static_files(filename):
    return send_from_directory(os.path.join(app.root_path, 'static'), filename)