print("检查项目依赖...")

try:
    import pandas as pd
    import numpy as np
    from sqlalchemy import create_engine
    from src.forecasting.models import SPUProfiler
    from src.forecasting.predictors import run_all_models
    from src.database.repositories import get_data_from_db
    from src.utils.helpers import get_current_week_end, clean_series
    
    print("✓ 所有依赖导入成功")
    print("测试完成！")
    
except Exception as e:
    print(f"✗ 依赖导入失败: {e}")
    import traceback
    traceback.print_exc()
