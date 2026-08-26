import pandas as pd
import datetime

def create_wbs():
    data = [
        ["3.1", "SKU Splitting", "Trend Analysis", "Analyze historical share trends for key SPUs to validate hypothesis", "High", 1, "DS", "Pending"],
        ["3.2", "SKU Splitting", "Algo Implementation", "Develop TrendWeightedShare logic to replace static mean", "High", 2, "Dev", "Pending"],
        ["3.3", "SKU Splitting", "Normalization", "Implement Softmax/Normalization to ensure sum=1", "Medium", 1, "Dev", "Pending"],
        ["3.4", "SKU Splitting", "Backtesting", "Run A/B test on validation set (New vs Old)", "High", 2, "DS", "Pending"],
        ["4.1", "Automation", "Script Hardening", "Finalize env var config and error handling in main.py", "Medium", 1, "Dev", "Pending"],
        ["4.2", "Automation", "Scheduler Setup", "Create Windows Task Scheduler script (.bat) or Python Scheduler", "High", 1, "Ops", "Pending"],
        ["4.3", "Automation", "Alerting System", "Build monitor to check WMAPE > 30% and trigger alert", "Medium", 2, "Dev", "Pending"],
        ["4.4", "Automation", "Dashboard Update", "Update SQL views to support trend analysis", "Low", 1, "BI", "Pending"]
    ]
    
    columns = ["Task ID", "Category", "Task Name", "Description", "Priority", "Estimated Days", "Owner", "Status"]
    df = pd.DataFrame(data, columns=columns)
    
    filename = "WBS_Phase2_Optimization.xlsx"
    try:
        df.to_excel(filename, index=False)
        print(f"✅ Created {filename} successfully.")
    except Exception as e:
        print(f"❌ Failed to create {filename}: {e}")

if __name__ == "__main__":
    create_wbs()
