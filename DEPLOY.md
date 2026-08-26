# NexusBI Repair Package - 部署说明

本文档将指导你如何部署和运行 NexusBI 修复包。

## 1. 环境准备

确保你的系统已安装：
- Python 3.7+
- pip (Python 包管理器)
- git (如果从版本控制系统获取)

## 2. 获取代码

你可以通过以下两种方式获取修复包代码：

### 方式一：直接复制文件 (推荐，适用于本交付)

1.  创建一个名为 `repair_package_v1_2_fix` 的新文件夹。
2.  将本交付中提供的所有文件（`app.py`、`templates/index.html`、`static/script.js`、`static/style.css`、`requirements.txt`、`config.example.py`、`CHANGELOG.md`、`DEPLOY.md`、`README.md` 和 `build_zip.sh`）复制到对应的子目录结构中。
    - `repair_package_v1_2_fix/app.py`
    - `repair_package_v1_2_fix/templates/index.html`
    - `repair_package_v1_2_fix/static/script.js`
    - `repair_package_v1_2_fix/static/style.css`
    - ... (其他文件在 `repair_package_v1_2_fix/` 根目录)

### 方式二：从 ZIP 包解压 (如果你已经通过 `build_zip.sh` 生成)

1.  下载 `repair_package_v1_2_fix.zip` 文件。
2.  解压到你希望部署的目录。

## 3. 安装依赖

进入修复包的根目录 (`repair_package_v1_2_fix/`)，执行以下命令：

```bash  
# 建议创建并激活虚拟环境  
python3 -m venv venv  
source venv/bin/activate  # macOS/Linux  
# venv\Scripts\activate   # Windows  

# 安装 Python 依赖  
pip install -r requirements.txt  