#!/usr/bin/env python3
"""
最小化API测试文件
用于测试API服务是否能正常启动
"""
import os
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="测试API", description="用于测试API服务是否能正常启动")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 健康检查端点
@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    # 禁用reload模式，避免多进程问题
    uvicorn.run("src.api.test_app:app", host="0.0.0.0", port=8000, reload=False)
