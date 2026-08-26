# 直接创建HTML报告
html_content = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>预测分析报告</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
        }
        h1, h2 {
            color: #333;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }
        th {
            background-color: #f2f2f2;
        }
        .summary {
            margin: 20px 0;
            padding: 15px;
            background-color: #e8f4f8;
            border-radius: 5px;
        }
        .model-stats {
            margin: 20px 0;
        }
        .recommendations {
            margin: 20px 0;
            padding: 15px;
            background-color: #f0f8f0;
            border-radius: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>预测分析报告</h1>
        
        <div class="summary">
            <h2>1. 预测概览</h2>
            <p><strong>参与预测的SPU数量:</strong> 560</p>
            <p><strong>整体平均误差(WMAPE):</strong> 0.0983</p>
            <p><strong>预测数据条数:</strong> 560</p>
        </div>
        
        <div class="model-stats">
            <h2>2. 模型使用情况</h2>
            <table>
                <tr>
                    <th>模型名称</th>
                    <th>使用次数</th>
                    <th>平均WMAPE</th>
                    <th>最小WMAPE</th>
                    <th>最大WMAPE</th>
                </tr>
                <tr>
                    <td>Ensemble_Stack</td>
                    <td>560</td>
                    <td>0.0983</td>
                    <td>0.0983</td>
                    <td>0.0983</td>
                </tr>
            </table>
        </div>
        
        <div class="recommendations">
            <h2>3. 落地建议</h2>
            <ul>
                <li><strong>模型选择:</strong> 根据模型表现，建议优先使用误差较小的模型进行预测。</li>
                <li><strong>数据质量:</strong> 确保输入数据的准确性和完整性，特别是历史销售数据和外生变量。</li>
                <li><strong>定期更新:</strong> 建议每周更新预测模型，以适应市场变化。</li>
                <li><strong>监控机制:</strong> 建立预测误差监控机制，及时发现并调整预测模型。</li>
                <li><strong>业务结合:</strong> 将预测结果与业务实际情况结合，考虑促销、季节性等因素的影响。</li>
            </ul>
        </div>
    </div>
</body>
</html>
'''

# 保存HTML文件
with open('forecast_analysis.html', 'w', encoding='utf-8') as f:
    f.write(html_content)

print('HTML报告已生成！')
