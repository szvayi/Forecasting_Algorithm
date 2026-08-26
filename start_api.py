#!/usr/bin/env python3
"""
使用具体IP地址启动API服务
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    
    app = FastAPI(title="预测分析API", description="提供预测分析功能的API服务")
    
    # 配置CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 全局变量用于存储分析状态
    analysis_status = {
        "status": "idle",  # idle, running, completed, failed
        "progress": 0,
        "result": None,
        "error": None
    }
    
    # 数据库连接URL
    DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    
    # 后台任务：执行预测分析
    def run_analysis():
        global analysis_status
        try:
            analysis_status.update({"status": "running", "progress": 10, "error": None})
            
            # 使用subprocess调用独立的分析脚本，避免multiprocessing冲突
            import subprocess
            import json
            import sys
            
            # 构建命令
            worker_script = os.path.join(os.path.dirname(__file__), 'src/api/analysis_worker.py')
            cmd = [sys.executable, worker_script, DB_URL]
            
            # 执行命令并捕获输出
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.path.abspath(os.path.join(os.path.dirname(__file__)))
            )
            
            # 读取输出并更新进度
            analysis_status.update({"progress": 20})
            
            result = None
            error = None
            
            for line in process.stdout:
                line = line.strip()
                if line.startswith('PROGRESS:'):
                    progress = int(line.split(':')[1])
                    analysis_status.update({"progress": progress})
                elif line.startswith('ERROR:'):
                    error = line.split(':', 1)[1]
                elif line.startswith('RESULT:'):
                    result_json = line.split(':', 1)[1]
                    result = json.loads(result_json)
            
            # 等待进程结束
            process.wait()
            
            # 处理错误
            if process.returncode != 0:
                stderr_output = process.stderr.read()
                error_message = f"分析脚本执行失败: {stderr_output}"
                analysis_status.update({"status": "failed", "error": error_message})
                return
            
            if error:
                analysis_status.update({"status": "failed", "error": error})
                return
            
            if result is None:
                analysis_status.update({"status": "failed", "error": "未获取到分析结果"})
                return
            
            # 更新完成状态
            analysis_status.update({"status": "completed", "progress": 100, "result": result})
            
        except Exception as e:
            import traceback
            error_message = f"分析失败: {str(e)}"
            analysis_status.update({"status": "failed", "error": error_message})
            print(traceback.format_exc())
    
    # API端点
    @app.post("/api/start-analysis")
    async def start_analysis():
        global analysis_status
        
        if analysis_status["status"] == "running":
            return {"message": "分析正在进行中", "status": "running"}
        
        # 重置状态
        analysis_status = {
            "status": "idle",
            "progress": 0,
            "result": None,
            "error": None
        }
        
        # 启动分析（这里简化为直接调用，实际应该使用后台任务）
        import threading
        threading.Thread(target=run_analysis, daemon=True).start()
        
        return {"message": "分析已启动", "status": "running"}
    
    @app.get("/api/analysis-status")
    async def get_analysis_status():
        return analysis_status
    
    @app.get("/api/analysis-result")
    async def get_analysis_result():
        if analysis_status["status"] != "completed":
            return {"error": "分析尚未完成"}
        
        return analysis_status["result"]
    
    @app.get("/api/health")
    async def health_check():
        return {"status": "healthy"}
    
    # 启动服务器
    if __name__ == "__main__":
        print("启动API服务...")
        uvicorn.run(app, host="192.168.210.124", port=8080, reload=False)
        
except Exception as e:
    print(f"启动失败: {e}")
    import traceback
    traceback.print_exc()
