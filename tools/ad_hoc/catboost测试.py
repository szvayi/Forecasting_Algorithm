# 测试 CatBoost 是否正常工作
def test_catboost():
    try:
        from catboost import CatBoostRegressor
        import numpy as np

        # 简单测试
        X = np.random.randn(100, 5)
        y = np.random.randn(100)

        model = CatBoostRegressor(iterations=10, depth=3, verbose=0)
        model.fit(X, y)
        pred = model.predict(X[:5])

        print("✅ CatBoost 安装正常!")
        print(f"   版本: {__import__('catboost').__version__}")
        print(f"   测试预测: {pred[:3]}")
        return True

    except ImportError:
        print("❌ CatBoost 未安装")
        print("   安装命令: pip install catboost")
        return False
    except Exception as e:
        print(f"❌ CatBoost 错误: {e}")
        return False


test_catboost()