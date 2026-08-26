import psycopg2

# 数据库连接参数
db_params = {
    'host': '192.168.1.226',
    'database': 'finedatalink',
    'user': 'postgres',
    'password': 'vayiERty123',
    'port': '5432'
}

try:
    # 连接数据库
    conn = psycopg2.connect(**db_params)
    print("数据库连接成功!")
    
    # 创建游标
    cur = conn.cursor()
    
    # 检查销售预测历史表
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE  table_schema = 'finedatalink' 
            AND    table_name   = 'sales_forecast_history'
        )
    """)
    table_exists = cur.fetchone()[0]
    print(f"表是否存在: {table_exists}")
    
    # 如果表存在，检查数据量
    if table_exists:
        cur.execute("SELECT COUNT(*) FROM finedatalink.sales_forecast_history")
        count = cur.fetchone()[0]
        print(f"数据条数: {count}")
        
        # 检查表结构
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'finedatalink' AND table_name = 'sales_forecast_history'")
        columns = cur.fetchall()
        print("表结构:")
        for col in columns:
            print(f"  {col[0]}: {col[1]}")
    
    # 关闭游标和连接
    cur.close()
    conn.close()
    
    print("数据库检查完成!")
    
except Exception as e:
    print(f"数据库检查失败: {str(e)}")