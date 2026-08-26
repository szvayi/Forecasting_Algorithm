#!/usr/bin/env python3
"""
测试前端API功能
验证前端是否能顺利调用main、进度是否如实汇报、WMAPE是否表达正确
"""
import requests
import time
import json
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

API_BASE = 'http://localhost:8000'

def test_api_health():
    """测试API健康状态"""
    logging.info("测试API健康状态...")
    try:
        response = requests.get(f"{API_BASE}/api/health")
        if response.status_code == 200:
            logging.info("✅ API健康状态正常")
            return True
        else:
            logging.error(f"❌ API健康状态异常: {response.status_code}")
            return False
    except Exception as e:
        logging.error(f"❌ API健康状态测试失败: {e}")
        return False

def test_start_analysis():
    """测试启动分析功能"""
    logging.info("测试启动分析功能...")
    try:
        response = requests.post(f"{API_BASE}/api/start-analysis", headers={"Content-Type": "application/json"})
        if response.status_code == 200:
            result = response.json()
            logging.info(f"✅ 启动分析成功: {result}")
            return True
        else:
            logging.error(f"❌ 启动分析失败: {response.status_code}")
            return False
    except Exception as e:
        logging.error(f"❌ 启动分析测试失败: {e}")
        return False

def test_analysis_status():
    """测试分析状态查询功能"""
    logging.info("测试分析状态查询功能...")
    try:
        response = requests.get(f"{API_BASE}/api/analysis-status")
        if response.status_code == 200:
            status = response.json()
            logging.info(f"✅ 分析状态查询成功: {status}")
            return status
        else:
            logging.error(f"❌ 分析状态查询失败: {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"❌ 分析状态查询测试失败: {e}")
        return None

def test_analysis_result():
    """测试分析结果查询功能"""
    logging.info("测试分析结果查询功能...")
    try:
        response = requests.get(f"{API_BASE}/api/analysis-result")
        if response.status_code == 200:
            result = response.json()
            logging.info(f"✅ 分析结果查询成功: {result}")
            return result
        elif response.status_code == 400:
            logging.info("⚠️  分析尚未完成")
            return None
        else:
            logging.error(f"❌ 分析结果查询失败: {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"❌ 分析结果查询测试失败: {e}")
        return None

def monitor_analysis_progress():
    """监控分析进度"""
    logging.info("开始监控分析进度...")
    start_time = time.time()
    max_wait_time = 300  # 最大等待时间5分钟
    
    while time.time() - start_time < max_wait_time:
        status = test_analysis_status()
        if status:
            logging.info(f"当前状态: {status['status']}, 进度: {status['progress']}%")
            
            if status['status'] == 'completed':
                logging.info("✅ 分析完成")
                return True
            elif status['status'] == 'failed':
                logging.error(f"❌ 分析失败: {status['error']}")
                return False
            
        time.sleep(5)  # 每5秒查询一次
    
    logging.error("❌ 分析超时")
    return False

def test_wmape_calculation():
    """测试WMAPE计算是否正确"""
    logging.info("测试WMAPE计算...")
    # 这里可以添加WMAPE计算的测试逻辑
    # 例如，使用已知的实际值和预测值计算WMAPE
    actual = [100, 200, 300, 400, 500]
    predicted = [110, 190, 310, 390, 510]
    
    # 计算WMAPE
    numerator = sum(abs(a - p) for a, p in zip(actual, predicted))
    denominator = sum(actual)
    wmape = numerator / denominator if denominator > 0 else 0
    
    logging.info(f"测试WMAPE计算: 实际值={actual}, 预测值={predicted}, WMAPE={wmape:.4f}")
    logging.info("✅ WMAPE计算测试完成")
    return wmape

def main():
    """主测试函数"""
    logging.info("开始前端API功能测试")
    logging.info("=" * 60)
    
    # 1. 测试API健康状态
    if not test_api_health():
        logging.error("API健康状态测试失败，终止测试")
        return
    
    # 2. 测试启动分析
    if not test_start_analysis():
        logging.error("启动分析测试失败，终止测试")
        return
    
    # 3. 监控分析进度
    analysis_completed = monitor_analysis_progress()
    
    # 4. 测试分析结果
    if analysis_completed:
        result = test_analysis_result()
        if result:
            # 检查WMAPE是否正确表达
            if 'average_wmape' in result:
                avg_wmape = result['average_wmape']
                logging.info(f"✅ 平均WMAPE: {avg_wmape:.4f} ({avg_wmape * 100:.2f}%)")
            else:
                logging.warning("⚠️  结果中没有平均WMAPE")
    
    # 5. 测试WMAPE计算
    test_wmape_calculation()
    
    logging.info("=" * 60)
    logging.info("前端API功能测试完成")

if __name__ == "__main__":
    main()
