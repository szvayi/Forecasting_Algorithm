"""Execution bridge for the canonical forecast kernel facade.

This module keeps the runtime-facing API in one place so callers in ``src/``
do not need to scatter direct imports from the repository root ``main.py``.
The canonical import surface lives in :mod:`src.forecasting.kernel`.
"""

from src.forecasting import kernel as forecast_kernel


def get_data_from_db(db_url):
    return forecast_kernel.get_data_from_db(db_url)


def process_single_spu(*args, **kwargs):
    return forecast_kernel.process_single_spu(*args, **kwargs)


def save_to_database(*args, **kwargs):
    return forecast_kernel.save_to_database(*args, **kwargs)


def main(*args, **kwargs):
    return forecast_kernel.main(*args, **kwargs)
