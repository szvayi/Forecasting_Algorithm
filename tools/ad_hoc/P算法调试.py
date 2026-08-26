def test_prophet_directly():
    """直接测试Prophet，查看真实错误"""
    from prophet import Prophet
    import pandas as pd
    import numpy as np

    print("=" * 50)
    print("直接测试 Prophet...")
    print("=" * 50)

    try:
        # 创建简单测试数据
        dates = pd.date_range('2022-01-01', periods=100, freq='W')
        values = np.random.randint(100, 500, 100)

        df = pd.DataFrame({'ds': dates, 'y': values})

        print(f"测试数据: {df.shape}")
        print(df.head())

        m = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
        m.fit(df)

        future = m.make_future_dataframe(periods=10, freq='W')
        forecast = m.predict(future)

        print(f"✅ Prophet 正常工作!")
        print(f"预测结果: {forecast['yhat'].tail(10).values}")

    except Exception as e:
        import traceback
        print(f"❌ Prophet 错误: {e}")
        traceback.print_exc()

    print("=" * 50)
test_prophet_directly()