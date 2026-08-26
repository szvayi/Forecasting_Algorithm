2import sys
import os
import datetime
import io
import time

# 设置UTF-8编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 清屏函数
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

# 打印标题
def print_header():
    print("=" * 70)
    print("📈 SPU销售预测引擎")
    print("=" * 70)
    print(f"时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

# 打印状态
def print_status(status, progress):
    print(f"状态: {status}")
    print(f"进度: {int(progress * 100)}%")
    print("[" + "=" * int(progress * 50) + " " * (50 - int(progress * 50)) + "]")
    print()

# 打印日志
def print_logs(logs):
    print("运行日志:")
    print("-" * 70)
    for log in logs[-20:]:  # 只显示最近20条日志
        print(log)
    print("-" * 70)
    print()

# 打印结果
def print_results(results):
    print("预测结果:")
    print("-" * 70)
    print(f"{'SPU':<10} {'胜出模型':<10} {'WMAPE':<10} {'预测周数':<10}")
    print("-" * 70)
    for result in results:
        print(f"{result['SPU']:<10} {result['胜出模型']:<10} {result['WMAPE']:<10} {result['预测周数']:<10}")
    print("-" * 70)
    print()

# 彩色输出函数
def print_color(text, color='green'):
    colors = {
        'red': '\033[91m',
        'green': '\033[92m',
        'yellow': '\033[93m',
        'blue': '\033[94m',
        'purple': '\033[95m',
        'cyan': '\033[96m',
        'white': '\033[97m',
        'reset': '\033[0m'
    }
    return f"{colors.get(color, colors['white'])}{text}{colors['reset']}"

# 显示参数设置菜单
def show_param_menu():
    clear_screen()
    print_header()
    print(print_color("参数设置", "cyan"))
    print("=" * 70)
    print(print_color("1. 运行模式: ", "yellow") + "[1] fast [2] smart [3] full")
    print(print_color("2. 显示图表: ", "yellow") + "[1] 是 [2] 否")
    print(print_color("3. 保存图表: ", "yellow") + "[1] 是 [2] 否")
    print(print_color("4. 写入数据库: ", "yellow") + "[1] 是 [2] 否")
    print(print_color("5. 开始预测", "green"))
    print(print_color("6. 退出", "red"))
    print("=" * 70)

# 获取用户输入
def get_user_input(prompt, options=None):
    while True:
        try:
            choice = input(prompt)
            if options and choice not in options:
                print(f"请输入有效的选项: {', '.join(options)}")
                continue
            return choice
        except:
            print("输入错误，请重新输入")
            continue

# 主函数
def main():
    # 重定向输出到文件和控制台
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = f"run_forecast_{timestamp}.log"

    # 保存原始输出流
    original_stdout = sys.stdout

    # 自定义输出类
    class Tee:
        def __init__(self, *files):
            self.files = files
        def write(self, obj):
            for f in self.files:
                f.write(obj)
        def flush(self):
            for f in self.files:
                f.flush()

    # 打开日志文件
    with open(log_file, 'w', encoding='utf-8') as f:
        # 重定向输出到文件和控制台
        sys.stdout = Tee(sys.stdout, f)
        
        clear_screen()
        print_header()
        print("欢迎使用SPU销售预测系统")
        print()
        
        # 默认参数
        run_mode = 'smart'
        show_plots = False
        save_plots = False
        enable_db_write = True
        
        while True:
            show_param_menu()
            choice = get_user_input("请选择: ", ["1", "2", "3", "4", "5", "6"])
            
            if choice == "1":
                mode_choice = get_user_input("请选择运行模式 (1-3): ", ["1", "2", "3"])
                if mode_choice == "1":
                    run_mode = 'fast'
                elif mode_choice == "2":
                    run_mode = 'smart'
                else:
                    run_mode = 'full'
                print(f"运行模式已设置为: {run_mode}")
                input("按任意键继续...")
            
            elif choice == "2":
                plot_choice = get_user_input("是否显示图表 (1-2): ", ["1", "2"])
                show_plots = plot_choice == "1"
                print(f"显示图表已设置为: {'是' if show_plots else '否'}")
                input("按任意键继续...")
            
            elif choice == "3":
                save_choice = get_user_input("是否保存图表 (1-2): ", ["1", "2"])
                save_plots = save_choice == "1"
                print(f"保存图表已设置为: {'是' if save_plots else '否'}")
                input("按任意键继续...")
            
            elif choice == "4":
                db_choice = get_user_input("是否写入数据库 (1-2): ", ["1", "2"])
                enable_db_write = db_choice == "1"
                print(f"写入数据库已设置为: {'是' if enable_db_write else '否'}")
                input("按任意键继续...")
            
            elif choice == "5":
                clear_screen()
                print_header()
                print("预测参数")
                print("-" * 70)
                print(f"运行模式: {run_mode}")
                print(f"显示图表: {'是' if show_plots else '否'}")
                print(f"保存图表: {'是' if save_plots else '否'}")
                print(f"写入数据库: {'是' if enable_db_write else '否'}")
                print(f"日志文件: {log_file}")
                print("-" * 70)
                
                confirm = get_user_input("确认开始预测? (y/n): ", ["y", "n"])
                if confirm == "y":
                    break
            
            elif choice == "6":
                print("退出系统...")
                return
        
        logs = []
        
        try:
            # 添加路径
            sys.path.insert(0, '.')
            from src.forecasting.execution_bridge import main as forecast_main
            
            logs.append("导入main模块成功")
            logs.append("开始执行main函数...")
            clear_screen()
            print_header()
            print_status("运行中", 0)
            print_logs(logs)
            
            # 执行main函数
            # 注意：这里需要修改main函数以接受参数，或者通过环境变量传递参数
            forecast_main()
            
            logs.append(f"预测执行完成: {datetime.datetime.now()}")
            clear_screen()
            print_header()
            print_status("完成", 1.0)
            print_logs(logs)
            
        except Exception as e:
            logs.append(f"执行失败: {e}")
            import traceback
            traceback.print_exc()
            clear_screen()
            print_header()
            print_status("失败", 1.0)
            print_logs(logs)
        finally:
            # 恢复原始输出流
            sys.stdout = original_stdout
            print(f"执行完成，日志已保存到: {log_file}")
            # 读取并显示日志文件的最后50行
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if lines:
                        print("\n日志文件最后50行:")
                        for line in lines[-50:]:
                            print(line.strip())
            except Exception as e:
                print(f"读取日志文件失败: {e}")
            
            print("\n按任意键退出...")
            input()

if __name__ == "__main__":
    main()
