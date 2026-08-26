print("测试Python基本功能...")
print(f"Python版本: {__import__('sys').version}")
print("测试导入numpy...")
import numpy
print(f"numpy版本: {numpy.__version__}")
print("测试导入pandas...")
import pandas
print(f"pandas版本: {pandas.__version__}")
print("测试导入Flask...")
import flask
print(f"Flask版本: {flask.__version__}")
print("测试导入SQLAlchemy...")
import sqlalchemy
print(f"SQLAlchemy版本: {sqlalchemy.__version__}")
print("测试完成。")