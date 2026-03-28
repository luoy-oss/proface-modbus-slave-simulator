#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modbus从机调试软件打包脚本
使用PyInstaller将Python脚本打包为可执行文件
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def check_pyinstaller():
    """检查PyInstaller是否安装"""
    try:
        import PyInstaller
        print("PyInstaller已安装")
        return True
    except ImportError:
        print("PyInstaller未安装，正在安装...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
            print("PyInstaller安装成功")
            return True
        except Exception as e:
            print(f"安装PyInstaller失败: {e}")
            return False

def create_spec_file():
    """创建PyInstaller spec文件"""
    spec_content = '''# -*- mode: python ; coding: utf-8 -*-

import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

a = Analysis(
    ['modbus_slave_debugger.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
    cipher=block_cipher
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ModbusSlaveDebugger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 设置为True显示控制台窗口，False不显示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico' if os.path.exists('icon.ico') else None
)

# 如果需要单文件可执行文件，取消注释下面的coll部分
# coll = COLLECT(
#     exe,
#     a.binaries,
#     a.datas,
#     strip=False,
#     upx=True,
#     upx_exclude=[],
#     name='ModbusSlaveDebugger'
# )
'''
    
    with open('modbus_slave_debugger.spec', 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print("Spec文件创建成功")

def build_executable():
    """构建可执行文件"""
    print("开始构建可执行文件...")
    
    # 使用PyInstaller构建
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=ModbusSlaveDebugger",
        "--onefile",  # 单文件可执行程序
        "--windowed",  # 不显示控制台窗口
        "--clean",  # 清理临时文件
        "--noconfirm",  # 不确认覆盖
        "--add-data=.;.",  # 添加当前目录数据
        "--icon=icon.ico" if os.path.exists("icon.ico") else "",
        "modbus_slave_debugger.py"
    ]
    
    # 移除空字符串参数
    cmd = [arg for arg in cmd if arg]
    
    try:
        print(f"执行命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("构建输出:")
        print(result.stdout)
        if result.stderr:
            print("错误输出:")
            print(result.stderr)
        
        print("可执行文件构建成功!")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"构建失败，退出码: {e.returncode}")
        print("标准输出:")
        print(e.stdout)
        print("错误输出:")
        print(e.stderr)
        return False
    except Exception as e:
        print(f"构建过程中发生错误: {e}")
        return False

def build_with_spec():
    """使用spec文件构建"""
    print("使用spec文件构建可执行文件...")
    
    try:
        cmd = [sys.executable, "-m", "PyInstaller", "modbus_slave_debugger.spec", "--clean", "--noconfirm"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("构建输出:")
        print(result.stdout)
        if result.stderr:
            print("错误输出:")
            print(result.stderr)
        
        print("使用spec文件构建成功!")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"构建失败，退出码: {e.returncode}")
        print("标准输出:")
        print(e.stdout)
        print("错误输出:")
        print(e.stderr)
        return False
    except Exception as e:
        print(f"构建过程中发生错误: {e}")
        return False

def create_icon():
    """创建默认图标文件（如果不存在）"""
    icon_path = "icon.ico"
    if not os.path.exists(icon_path):
        print("注意: 未找到icon.ico文件，将使用默认图标")
        # 这里可以添加创建默认图标的代码
        # 暂时跳过
        return False
    return True

def cleanup():
    """清理构建文件"""
    print("清理构建文件...")
    
    # 要清理的目录和文件
    cleanup_items = [
        "build",
        "__pycache__",
        "*.spec"
    ]
    
    for item in cleanup_items:
        if os.path.exists(item):
            if os.path.isdir(item):
                shutil.rmtree(item)
                print(f"已删除目录: {item}")
            else:
                # 处理通配符
                import glob
                for file in glob.glob(item):
                    os.remove(file)
                    print(f"已删除文件: {file}")

def main():
    """主函数"""
    print("=" * 60)
    print("Modbus从机调试软件打包工具")
    print("=" * 60)
    
    # 检查当前目录
    current_dir = os.getcwd()
    print(f"当前目录: {current_dir}")
    
    # 检查主程序文件是否存在
    if not os.path.exists("modbus_slave_debugger.py"):
        print("错误: 未找到modbus_slave_debugger.py文件")
        return 1
    
    print("主程序文件存在")
    
    # 检查PyInstaller
    if not check_pyinstaller():
        return 1
    
    # 创建图标（可选）
    create_icon()
    
    # 询问用户构建方式
    print("\n请选择构建方式:")
    print("1. 直接构建单文件可执行程序")
    print("2. 创建spec文件并构建")
    print("3. 清理构建文件")
    print("4. 退出")
    
    choice = input("请输入选择 (1-4): ").strip()
    
    if choice == "1":
        # 直接构建
        if build_executable():
            print("\n构建完成!")
            print(f"可执行文件位置: {os.path.join(current_dir, 'dist', 'ModbusSlaveDebugger.exe')}")
        else:
            print("\n构建失败!")
            
    elif choice == "2":
        # 创建spec文件并构建
        create_spec_file()
        if build_with_spec():
            print("\n构建完成!")
            print(f"可执行文件位置: {os.path.join(current_dir, 'dist', 'ModbusSlaveDebugger.exe')}")
        else:
            print("\n构建失败!")
            
    elif choice == "3":
        # 清理
        cleanup()
        print("清理完成!")
        
    elif choice == "4":
        print("退出")
        return 0
        
    else:
        print("无效选择")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())