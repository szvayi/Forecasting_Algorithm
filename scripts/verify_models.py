import sys
import importlib

def check_imports():
    models = ['catboost', 'lightgbm', 'xgboost', 'prophet', 'tensorflow', 'statsmodels']
    print("🔍 Checking Model Dependencies...")
    
    all_good = True
    for model in models:
        try:
            importlib.import_module(model)
            print(f"✅ {model:<15} : Installed")
        except ImportError:
            print(f"❌ {model:<15} : MISSING")
            all_good = False
            
    if all_good:
        print("\n🎉 All model dependencies are ready!")
    else:
        print("\n⚠️ Some models are missing. They will be skipped in the arena.")

if __name__ == "__main__":
    check_imports()
