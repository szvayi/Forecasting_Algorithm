import multiprocessing
from prophet import Prophet
import pandas as pd

def test_prophet():
    try:
        m = Prophet()
        df = pd.DataFrame({'ds': pd.date_range('2023-01-01', periods=10, freq='W'), 'y': range(10)})
        m.fit(df)
        return 'Prophet OK in subprocess'
    except Exception as e:
        return f'Prophet failed: {e}'

if __name__ == '__main__':
    multiprocessing.freeze_support()
    ctx = multiprocessing.get_context('spawn')
    q = ctx.Queue()
    p = ctx.Process(target=lambda: q.put(test_prophet()))
    p.start()
    p.join()
    print(q.get())
