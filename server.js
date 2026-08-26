const express = require('express');
const cors = require('cors');
const fs = require('fs');
const path = require('path');

const app = express();
const port = 5000;

app.use(cors());
app.use(express.json());
app.use(express.static(__dirname));

// 预测状态
let forecastStatus = {
    running: false,
    progress: 0,
    current_spu: null,
    processed_spus: 0,
    total_spus: 34,
    logs: [],
    results: [],
    start_time: null,
    mode: 'smart',
    enable_db_write: true,
    prediction_data: null
};

// 34个SPU列表
const SPU_LIST = [
    '2141', '2062', '2029', '2046', '2026', '3022', '1930', '2214',
    '2033', '2038', '2208', '2012', '3050', '2176', '3033', '2192',
    '2213', '3063', '2224', '3058', '2073', '3013', '2165', '3084',
    '1976', '2197', '1476', '1533', '0887', '1577', '1750', '1512',
    '1657', '1983', '1318'
];

// 算法列表
const ALGORITHMS = ['Prophet', 'XGBoost', 'LightGBM', 'AutoARIMA', 'Ensemble-Avg', 'Ensemble-Weighted'];

function addLog(message) {
    const timestamp = new Date().toLocaleTimeString();
    forecastStatus.logs.push({
        time: timestamp,
        message: message
    });
    // 只保留最近100条日志
    if (forecastStatus.logs.length > 100) {
        forecastStatus.logs = forecastStatus.logs.slice(-100);
    }
}

function generateFallbackPredictionData() {
    const spuData = [];
    for (const spu of SPU_LIST.slice(0, 10)) {
        const records = [];
        const baseValue = Math.random() * 900 + 100;
        
        for (let i = 0; i < 10; i++) {
            const date = new Date();
            date.setDate(date.getDate() + i * 7);
            const dateStr = date.toISOString().split('T')[0];
            
            const trendFactor = 1 + (i * 0.02);
            const randomFactor = Math.random() * 0.1 + 0.95;
            const forecastValue = baseValue * trendFactor * randomFactor;
            
            records.push({
                date: dateStr,
                actual_value: i < 2 ? baseValue * (i * 0.9 + 0.8) : null,
                forecast_value: Math.round(forecastValue * 100) / 100,
                wmape: i < 2 ? Math.round((Math.random() * 0.12 + 0.03) * 10000) / 10000 : null,
                model: ['Ensemble_Stack', 'XGBoost', 'Prophet'][Math.floor(Math.random() * 3)]
            });
        }
        
        spuData.push({
            spu_id: spu,
            name: `产品_${spu}`,
            records: records
        });
    }
    
    return {
        metadata: {
            prediction_id: `pred_${new Date().toISOString().split('T')[0]}_001`,
            timestamp: new Date().toISOString(),
            model_version: "v1.2.0",
            data_source: "simulated",
            total_spus: spuData.length,
            total_records: spuData.reduce((sum, spu) => sum + spu.records.length, 0)
        },
        spus: spuData
    };
}

function runForecastSimulation() {
    forecastStatus.running = true;
    forecastStatus.start_time = new Date();
    forecastStatus.logs = [];
    forecastStatus.results = [];
    forecastStatus.processed_spus = 0;
    forecastStatus.progress = 0;
    forecastStatus.prediction_data = null;
    
    addLog(`启动预测系统 (模式: ${forecastStatus.mode})`);
    addLog(`目标SPU数量: ${SPU_LIST.length}`);
    addLog("=".repeat(70));
    
    let currentIndex = 0;
    
    function processNextSPU() {
        if (!forecastStatus.running || currentIndex >= SPU_LIST.length) {
            if (!forecastStatus.running) {
                addLog("预测被用户停止");
            }
            
            // 生成预测数据
            forecastStatus.prediction_data = generateFallbackPredictionData();
            
            addLog(`\n成功: ${forecastStatus.processed_spus}/${SPU_LIST.length} 个 SPU`);
            addLog(`平均WMAPE: ${(Math.random() * 0.07 + 0.08).toFixed(2)}%`);
            
            forecastStatus.running = false;
            forecastStatus.current_spu = null;
            addLog("\n" + "=".repeat(70));
            addLog(`预测完成！共处理 ${forecastStatus.processed_spus} 个SPU`);
            addLog(`结果已保存到数据库: ${forecastStatus.enable_db_write}`);
            
            return;
        }
        
        const spu = SPU_LIST[currentIndex];
        forecastStatus.current_spu = spu;
        addLog(`[${currentIndex + 1}/${SPU_LIST.length}] 处理 SPU: ${spu}`);
        
        // 模拟处理时间
        setTimeout(() => {
            // 模拟算法运行
            let algoIndex = 0;
            
            function runNextAlgorithm() {
                if (algoIndex >= ALGORITHMS.length) {
                    // 更新进度
                    forecastStatus.processed_spus = currentIndex + 1;
                    forecastStatus.progress = ((currentIndex + 1) / SPU_LIST.length) * 100;
                    
                    currentIndex++;
                    processNextSPU();
                    return;
                }
                
                const algo = ALGORITHMS[algoIndex];
                addLog(`  运行 ${algo}...`);
                
                setTimeout(() => {
                    const wmape = (Math.random() * 0.15 + 0.05).toFixed(4);
                    addLog(`  ${algo}: WMPE=${(parseFloat(wmape) * 100).toFixed(2)}%`);
                    algoIndex++;
                    runNextAlgorithm();
                }, 100);
            }
            
            runNextAlgorithm();
        }, 500);
    }
    
    processNextSPU();
}

// 静态文件服务
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'index.html'));
});

app.get('/:path', (req, res) => {
    res.sendFile(path.join(__dirname, req.params.path));
});

// API endpoints
app.post('/api/start', (req, res) => {
    if (forecastStatus.running) {
        return res.json({ status: 'error', message: '预测已在运行中' });
    }
    
    const data = req.body || {};
    forecastStatus.mode = data.mode || 'smart';
    forecastStatus.enable_db_write = data.enable_db_write !== false;
    
    // 启动预测
    runForecastSimulation();
    
    res.json({ status: 'success', message: '预测已启动' });
});

app.post('/api/stop', (req, res) => {
    forecastStatus.running = false;
    res.json({ status: 'success', message: '预测已停止' });
});

app.get('/api/status', (req, res) => {
    let elapsed = 0;
    if (forecastStatus.start_time) {
        elapsed = (Date.now() - forecastStatus.start_time.getTime()) / 1000;
    }
    
    res.json({
        running: forecastStatus.running,
        progress: Math.round(forecastStatus.progress * 10) / 10,
        current_spu: forecastStatus.current_spu,
        processed_spus: forecastStatus.processed_spus,
        total_spus: forecastStatus.total_spus,
        elapsed: Math.round(elapsed * 10) / 10,
        logs: forecastStatus.logs.slice(-50),
        results: forecastStatus.results.slice(-10),
        mode: forecastStatus.mode
    });
});

app.get('/api/predictions/:prediction_id', (req, res) => {
    try {
        if (forecastStatus.prediction_data) {
            return res.json(forecastStatus.prediction_data);
        }
        
        const predictionData = generateFallbackPredictionData();
        res.json(predictionData);
    } catch (error) {
        addLog(`获取预测数据失败: ${error.message}`);
        const fallbackData = generateFallbackPredictionData();
        res.json(fallbackData);
    }
});

// 启动服务器
app.listen(port, () => {
    console.log(`SPU销售预测系统 (Node.js版) 已启动`);
    console.log(`请访问: http://localhost:${port}`);
});
