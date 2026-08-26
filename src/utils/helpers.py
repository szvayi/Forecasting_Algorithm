import os
import random
import logging
import json
import warnings
import traceback
from functools import lru_cache

DEBUG_MODE = False


def debug_print(*args, **kwargs):
    if DEBUG_MODE:
        print(*args, **kwargs)


def set_seeds(seed=42):
    os.environ['PYTHONHASHSEED'] = str(seed)
    random.seed(seed)
    import numpy as np
    np.random.seed(seed)
    try:
        import tensorflow as tf
        tf.random.set_seed(seed)
    except:
        pass

set_seeds()

# 【修复处：去掉了前缀的下划线】
@lru_cache(maxsize=1)
def get_catboost_regressor():
    try:
        from catboost import CatBoostRegressor
        return CatBoostRegressor
    except ImportError:
        return None


class suppress_stdout_stderr:
    def __init__(self):
        self.null_fds = [os.open(os.devnull, os.O_RDWR) for _ in range(2)]
        self.save_fds = [os.dup(1), os.dup(2)]
    def __enter__(self):
        os.dup2(self.null_fds[0], 1)
        os.dup2(self.null_fds[1], 2)
    def __exit__(self, *_):
        os.dup2(self.save_fds[0], 1)
        os.dup2(self.save_fds[1], 2)
        for fd in self.null_fds + self.save_fds:
            os.close(fd)


def _mp_worker(func, q):
    import os
    os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
    try:
        res = func()
        q.put((True, res))
    except Exception as e:
        q.put((False, f"{str(e)}\n{traceback.format_exc()}"))


def run_with_timeout(func, timeout_seconds, default_return=None):
    import multiprocessing
    import queue
    ctx = multiprocessing.get_context('spawn')
    q = ctx.Queue()
    p = ctx.Process(target=_mp_worker, args=(func, q))
    p.start()
    p.join(timeout_seconds)

    if p.is_alive():
        p.terminate()
        p.join()
        return default_return

    try:
        success, result = q.get_nowait()
        if success: return result
        else: return default_return
    except queue.Empty:
        return default_return


def load_config(config_path=None):
    """加载配置文件"""
    import os
    import dotenv
    dotenv.load_dotenv()
    config = {
        'DATABASE_URL': os.getenv('DATABASE_URL'),
        'SALES_FORECAST_DB_URL': os.getenv('SALES_FORECAST_DB_URL'),
        'DEEPSEEK_API_KEY': os.getenv('DEEPSEEK_API_KEY'),
        'DEBUG': os.getenv('DEBUG', 'False').lower() == 'true',
        'HOST': os.getenv('HOST', '0.0.0.0'),
        'PORT': int(os.getenv('PORT', '5000')),
    }
    return config


def ensure_directories():
    """确保必要的目录存在"""
    directories = [
        'D:/华熠/plots',
        'D:/华熠/output',
        'D:/华熠/reports',
        'logs'
    ]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)


def setup_logging():
    """设置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler('logs/app.log'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)
