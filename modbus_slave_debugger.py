#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modbus TCP从机调试软件
作者：luoy-oss
功能：作为Modbus TCP从机，接收主机请求并显示通信数据
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import queue
import time
from datetime import datetime
import socket
import struct
import sys
import os

class ModbusSlaveServer:
    """Modbus TCP从机服务器类"""
    
    def __init__(self, ip='0.0.0.0', port=502, unit_id=1, message_queue=None):
        """
        初始化Modbus从机服务器
        
        参数:
            ip: 监听IP地址
            port: 监听端口
            unit_id: 从机单元ID
            message_queue: 消息队列，用于与GUI通信
        """
        self.ip = ip
        self.port = port
        self.unit_id = unit_id
        self.running = False
        self.server_socket = None
        self.client_threads = []
        
        # Modbus数据存储
        self.coils = [False] * 65536  # 线圈状态
        self.discrete_inputs = [False] * 65536  # 离散输入
        self.input_registers = [0] * 65536  # 输入寄存器
        self.holding_registers = [0] * 65536  # 保持寄存器
        
        # 消息队列
        self.message_queue = message_queue
        
        # 初始化一些测试数据
        self._init_test_data()
        
    def _init_test_data(self):
        """初始化测试数据"""
        # 初始化一些线圈状态
        for i in range(0, 100, 2):
            self.coils[i] = True
            
        # 初始化一些离散输入
        for i in range(0, 100, 3):
            self.discrete_inputs[i] = True
            
        # 初始化输入寄存器（模拟传感器数据）
        for i in range(0, 100):
            self.input_registers[i] = i * 10
            
        # 初始化保持寄存器
        for i in range(0, 100):
            self.holding_registers[i] = i * 100
    
    def start(self):
        """启动Modbus TCP服务器"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.ip, self.port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)
            self.running = True
            
            # 启动监听线程
            listen_thread = threading.Thread(target=self._listen_for_clients, daemon=True)
            listen_thread.start()
            
            return True, f"服务器已启动在 {self.ip}:{self.port}"
            
        except Exception as e:
            return False, f"启动服务器失败: {str(e)}"
    
    def stop(self):
        """停止Modbus TCP服务器"""
        self.running = False
        
        # 关闭所有客户端连接
        for thread in self.client_threads:
            if thread.is_alive():
                # 这里需要更优雅的关闭方式
                pass
        
        # 关闭服务器套接字
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        
        return True, "服务器已停止"
    
    def _listen_for_clients(self):
        """监听客户端连接"""
        while self.running:
            try:
                client_socket, client_address = self.server_socket.accept()
                client_socket.settimeout(1.0)
                
                # 为每个客户端创建处理线程
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket, client_address),
                    daemon=True
                )
                client_thread.start()
                self.client_threads.append(client_thread)
                
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"接受客户端连接时出错: {e}")
                break
    
    def _handle_client(self, client_socket, client_address):
        """处理客户端连接"""
        client_ip, client_port = client_address
        
        try:
            while self.running:
                try:
                    # 接收Modbus TCP请求
                    data = client_socket.recv(1024)
                    if not data:
                        break
                    
                    # 解析Modbus请求
                    request_info = self._parse_modbus_request(data, client_ip, client_port)
                    
                    # 处理请求并生成响应
                    response_data = self._process_modbus_request(data)
                    
                    # 发送响应
                    if response_data:
                        client_socket.send(response_data)
                    
                    # 如果有请求信息，发送到消息队列
                    if request_info and hasattr(self, 'message_queue'):
                        try:
                            self.message_queue.put(('request', request_info))
                        except:
                            pass
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"处理客户端 {client_ip}:{client_port} 时出错: {e}")
                    break
                    
        finally:
            try:
                client_socket.close()
            except:
                pass
    
    def _parse_modbus_request(self, data, client_ip, client_port):
        """解析Modbus TCP请求"""
        try:
            if len(data) < 8:  # Modbus TCP头部至少8字节
                return None
            
            # 解析Modbus TCP头部
            transaction_id = struct.unpack('>H', data[0:2])[0]
            protocol_id = struct.unpack('>H', data[2:4])[0]
            length = struct.unpack('>H', data[4:6])[0]
            unit_id = data[6]
            function_code = data[7]
            
            # 解析功能码
            function_name = self._get_function_name(function_code)
            
            # 解析地址和数量
            address = 0
            count = 0
            values = []
            
            if len(data) >= 12:
                if function_code in [1, 2, 3, 4]:  # 读操作
                    address = struct.unpack('>H', data[8:10])[0]
                    count = struct.unpack('>H', data[10:12])[0]
                elif function_code in [5, 6]:  # 写单个
                    address = struct.unpack('>H', data[8:10])[0]
                    if function_code == 5:  # 写线圈
                        value = struct.unpack('>H', data[10:12])[0]
                        values = [value == 0xFF00]
                    else:  # 写寄存器
                        value = struct.unpack('>H', data[10:12])[0]
                        values = [value]
                elif function_code in [15, 16]:  # 写多个
                    address = struct.unpack('>H', data[8:10])[0]
                    count = struct.unpack('>H', data[10:12])[0]
                    byte_count = data[12]
                    
                    if function_code == 15:  # 写多个线圈
                        values = []
                        for i in range(count):
                            byte_idx = 13 + i // 8
                            bit_idx = i % 8
                            if byte_idx < len(data):
                                byte_val = data[byte_idx]
                                values.append((byte_val >> bit_idx) & 0x01 == 0x01)
                    else:  # 写多个寄存器
                        values = []
                        for i in range(count):
                            if 13 + i*2 < len(data):
                                value = struct.unpack('>H', data[13+i*2:15+i*2])[0]
                                values.append(value)
            
            return {
                'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3],
                'client': f"{client_ip}:{client_port}",
                'transaction_id': transaction_id,
                'unit_id': unit_id,
                'function_code': function_code,
                'function_name': function_name,
                'address': address,
                'count': count,
                'values': values,
                'raw_data': data.hex().upper()
            }
            
        except Exception as e:
            print(f"解析Modbus请求时出错: {e}")
            return None
    
    def _get_function_name(self, function_code):
        """获取功能码名称"""
        function_names = {
            1: "读线圈",
            2: "读离散输入",
            3: "读保持寄存器",
            4: "读输入寄存器",
            5: "写单个线圈",
            6: "写单个寄存器",
            15: "写多个线圈",
            16: "写多个寄存器"
        }
        return function_names.get(function_code, f"未知功能码({function_code})")
    
    def _process_modbus_request(self, request_data):
        """处理Modbus请求并生成响应"""
        try:
            if len(request_data) < 8:
                return None
            
            unit_id = request_data[6]
            function_code = request_data[7]
            
            # 检查单元ID
            if self.unit_id != 0 and unit_id != self.unit_id:
                # 如果不是我们的单元ID，返回错误响应
                return self._create_error_response(request_data[0:2], unit_id, function_code, 0x0B)  # 网关路径不可用
            
            # 根据功能码处理请求
            if function_code == 1:  # 读线圈
                return self._handle_read_coils(request_data)
            elif function_code == 2:  # 读离散输入
                return self._handle_read_discrete_inputs(request_data)
            elif function_code == 3:  # 读保持寄存器
                return self._handle_read_holding_registers(request_data)
            elif function_code == 4:  # 读输入寄存器
                return self._handle_read_input_registers(request_data)
            elif function_code == 5:  # 写单个线圈
                return self._handle_write_single_coil(request_data)
            elif function_code == 6:  # 写单个寄存器
                return self._handle_write_single_register(request_data)
            elif function_code == 15:  # 写多个线圈
                return self._handle_write_multiple_coils(request_data)
            elif function_code == 16:  # 写多个寄存器
                return self._handle_write_multiple_registers(request_data)
            else:
                # 不支持的功能码
                return self._create_error_response(request_data[0:2], unit_id, function_code, 0x01)  # 非法功能
            
        except Exception as e:
            print(f"处理Modbus请求时出错: {e}")
            return self._create_error_response(request_data[0:2], unit_id, function_code, 0x04)  # 从机设备故障
    
    def _handle_read_coils(self, request_data):
        """处理读线圈请求"""
        if len(request_data) < 12:
            return None
        
        transaction_id = request_data[0:2]
        unit_id = request_data[6]
        address = struct.unpack('>H', request_data[8:10])[0]
        count = struct.unpack('>H', request_data[10:12])[0]
        
        # 检查地址范围
        if address + count > 65536:
            return self._create_error_response(transaction_id, unit_id, 1, 0x02)  # 非法数据地址
        
        # 读取线圈状态
        byte_count = (count + 7) // 8
        response_bytes = bytearray([0] * byte_count)
        
        for i in range(count):
            if address + i < len(self.coils) and self.coils[address + i]:
                byte_index = i // 8
                bit_index = i % 8
                response_bytes[byte_index] |= (1 << bit_index)
        
        # 构建响应
        response = bytearray()
        response.extend(transaction_id)  # 事务ID
        response.extend(b'\x00\x00')  # 协议ID
        response.extend(struct.pack('>H', byte_count + 3))  # 长度
        response.append(unit_id)  # 单元ID
        response.append(1)  # 功能码
        response.append(byte_count)  # 字节数
        response.extend(response_bytes)
        
        return bytes(response)
    
    def _handle_read_discrete_inputs(self, request_data):
        """处理读离散输入请求"""
        if len(request_data) < 12:
            return None
        
        transaction_id = request_data[0:2]
        unit_id = request_data[6]
        address = struct.unpack('>H', request_data[8:10])[0]
        count = struct.unpack('>H', request_data[10:12])[0]
        
        # 检查地址范围
        if address + count > 65536:
            return self._create_error_response(transaction_id, unit_id, 2, 0x02)  # 非法数据地址
        
        # 读取离散输入状态
        byte_count = (count + 7) // 8
        response_bytes = bytearray([0] * byte_count)
        
        for i in range(count):
            if address + i < len(self.discrete_inputs) and self.discrete_inputs[address + i]:
                byte_index = i // 8
                bit_index = i % 8
                response_bytes[byte_index] |= (1 << bit_index)
        
        # 构建响应
        response = bytearray()
        response.extend(transaction_id)  # 事务ID
        response.extend(b'\x00\x00')  # 协议ID
        response.extend(struct.pack('>H', byte_count + 3))  # 长度
        response.append(unit_id)  # 单元ID
        response.append(2)  # 功能码
        response.append(byte_count)  # 字节数
        response.extend(response_bytes)
        
        return bytes(response)
    
    def _handle_read_holding_registers(self, request_data):
        """处理读保持寄存器请求"""
        if len(request_data) < 12:
            return None
        
        transaction_id = request_data[0:2]
        unit_id = request_data[6]
        address = struct.unpack('>H', request_data[8:10])[0]
        count = struct.unpack('>H', request_data[10:12])[0]
        
        # 检查地址范围
        if address + count > 65536:
            return self._create_error_response(transaction_id, unit_id, 3, 0x02)  # 非法数据地址
        
        # 读取保持寄存器
        response = bytearray()
        response.extend(transaction_id)  # 事务ID
        response.extend(b'\x00\x00')  # 协议ID
        response.extend(struct.pack('>H', count * 2 + 3))  # 长度
        response.append(unit_id)  # 单元ID
        response.append(3)  # 功能码
        response.append(count * 2)  # 字节数
        
        for i in range(count):
            if address + i < len(self.holding_registers):
                value = self.holding_registers[address + i]
                response.extend(struct.pack('>H', value))
            else:
                response.extend(b'\x00\x00')
        
        return bytes(response)
    
    def _handle_read_input_registers(self, request_data):
        """处理读输入寄存器请求"""
        if len(request_data) < 12:
            return None
        
        transaction_id = request_data[0:2]
        unit_id = request_data[6]
        address = struct.unpack('>H', request_data[8:10])[0]
        count = struct.unpack('>H', request_data[10:12])[0]
        
        # 检查地址范围
        if address + count > 65536:
            return self._create_error_response(transaction_id, unit_id, 4, 0x02)  # 非法数据地址
        
        # 读取输入寄存器
        response = bytearray()
        response.extend(transaction_id)  # 事务ID
        response.extend(b'\x00\x00')  # 协议ID
        response.extend(struct.pack('>H', count * 2 + 3))  # 长度
        response.append(unit_id)  # 单元ID
        response.append(4)  # 功能码
        response.append(count * 2)  # 字节数
        
        for i in range(count):
            if address + i < len(self.input_registers):
                value = self.input_registers[address + i]
                response.extend(struct.pack('>H', value))
            else:
                response.extend(b'\x00\x00')
        
        return bytes(response)
    
    def _handle_write_single_coil(self, request_data):
        """处理写单个线圈请求"""
        if len(request_data) < 12:
            return None
        
        transaction_id = request_data[0:2]
        unit_id = request_data[6]
        address = struct.unpack('>H', request_data[8:10])[0]
        value = struct.unpack('>H', request_data[10:12])[0]
        
        # 检查地址范围
        if address >= 65536:
            return self._create_error_response(transaction_id, unit_id, 5, 0x02)  # 非法数据地址
        
        # 检查值是否有效
        if value not in [0x0000, 0xFF00]:
            return self._create_error_response(transaction_id, unit_id, 5, 0x03)  # 非法数据值
        
        # 写入线圈
        if address < len(self.coils):
            self.coils[address] = (value == 0xFF00)
        
        # 返回相同的请求作为响应（Modbus标准）
        return request_data
    
    def _handle_write_single_register(self, request_data):
        """处理写单个寄存器请求"""
        if len(request_data) < 12:
            return None
        
        transaction_id = request_data[0:2]
        unit_id = request_data[6]
        address = struct.unpack('>H', request_data[8:10])[0]
        value = struct.unpack('>H', request_data[10:12])[0]
        
        # 检查地址范围
        if address >= 65536:
            return self._create_error_response(transaction_id, unit_id, 6, 0x02)  # 非法数据地址
        
        # 写入寄存器
        if address < len(self.holding_registers):
            self.holding_registers[address] = value
        
        # 返回相同的请求作为响应（Modbus标准）
        return request_data
    
    def _handle_write_multiple_coils(self, request_data):
        """处理写多个线圈请求"""
        if len(request_data) < 13:
            return None
        
        transaction_id = request_data[0:2]
        unit_id = request_data[6]
        address = struct.unpack('>H', request_data[8:10])[0]
        count = struct.unpack('>H', request_data[10:12])[0]
        byte_count = request_data[12]
        
        # 检查地址范围
        if address + count > 65536:
            return self._create_error_response(transaction_id, unit_id, 15, 0x02)  # 非法数据地址
        
        # 检查数据长度
        expected_byte_count = (count + 7) // 8
        if byte_count != expected_byte_count or len(request_data) < 13 + byte_count:
            return self._create_error_response(transaction_id, unit_id, 15, 0x03)  # 非法数据值
        
        # 写入线圈
        for i in range(count):
            if address + i < len(self.coils):
                byte_index = 13 + i // 8
                bit_index = i % 8
                if byte_index < len(request_data):
                    byte_val = request_data[byte_index]
                    self.coils[address + i] = ((byte_val >> bit_index) & 0x01) == 0x01
        
        # 构建响应（返回地址和数量）
        response = bytearray()
        response.extend(transaction_id)  # 事务ID
        response.extend(b'\x00\x00')  # 协议ID
        response.extend(struct.pack('>H', 6))  # 长度
        response.append(unit_id)  # 单元ID
        response.append(15)  # 功能码
        response.extend(struct.pack('>H', address))  # 起始地址
        response.extend(struct.pack('>H', count))  # 数量
        
        return bytes(response)
    
    def _handle_write_multiple_registers(self, request_data):
        """处理写多个寄存器请求"""
        if len(request_data) < 13:
            return None
        
        transaction_id = request_data[0:2]
        unit_id = request_data[6]
        address = struct.unpack('>H', request_data[8:10])[0]
        count = struct.unpack('>H', request_data[10:12])[0]
        byte_count = request_data[12]
        
        # 检查地址范围
        if address + count > 65536:
            return self._create_error_response(transaction_id, unit_id, 16, 0x02)  # 非法数据地址
        
        # 检查数据长度
        if byte_count != count * 2 or len(request_data) < 13 + byte_count:
            return self._create_error_response(transaction_id, unit_id, 16, 0x03)  # 非法数据值
        
        # 写入寄存器
        for i in range(count):
            if address + i < len(self.holding_registers):
                value = struct.unpack('>H', request_data[13+i*2:15+i*2])[0]
                self.holding_registers[address + i] = value
        
        # 构建响应（返回地址和数量）
        response = bytearray()
        response.extend(transaction_id)  # 事务ID
        response.extend(b'\x00\x00')  # 协议ID
        response.extend(struct.pack('>H', 6))  # 长度
        response.append(unit_id)  # 单元ID
        response.append(16)  # 功能码
        response.extend(struct.pack('>H', address))  # 起始地址
        response.extend(struct.pack('>H', count))  # 数量
        
        return bytes(response)
    
    def _create_error_response(self, transaction_id, unit_id, function_code, error_code):
        """创建错误响应"""
        response = bytearray()
        response.extend(transaction_id)  # 事务ID
        response.extend(b'\x00\x00')  # 协议ID
        response.extend(struct.pack('>H', 3))  # 长度
        response.append(unit_id)  # 单元ID
        response.append(function_code | 0x80)  # 错误功能码
        response.append(error_code)  # 异常码
        
        return bytes(response)


class ModbusSlaveGUI:
    """Modbus从机调试软件GUI界面"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Modbus TCP从机调试软件")
        self.root.geometry("1200x800")
        
        # 设置图标（如果有）
        try:
            self.root.iconbitmap(default='icon.ico')
        except:
            pass
        
        # Modbus服务器实例
        self.modbus_server = None
        self.server_running = False
        
        # 消息队列用于线程间通信
        self.message_queue = queue.Queue()
        
        # 创建界面
        self._create_widgets()
        
        # 启动消息处理循环
        self._process_messages()
        
    def _create_widgets(self):
        """创建界面组件"""
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        # 标题
        title_label = ttk.Label(
            main_frame, 
            text="Modbus TCP从机调试软件", 
            font=("Arial", 16, "bold")
        )
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # 配置区域
        config_frame = ttk.LabelFrame(main_frame, text="服务器配置", padding="10")
        config_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)
        
        # IP地址
        ttk.Label(config_frame, text="IP地址:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.ip_var = tk.StringVar(value="0.0.0.0")
        ip_entry = ttk.Entry(config_frame, textvariable=self.ip_var, width=20)
        ip_entry.grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Label(config_frame, text="(0.0.0.0监听所有接口)").grid(row=0, column=2, sticky=tk.W)
        
        # 端口号
        ttk.Label(config_frame, text="端口号:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5))
        self.port_var = tk.StringVar(value="502")
        port_entry = ttk.Entry(config_frame, textvariable=self.port_var, width=10)
        port_entry.grid(row=1, column=1, sticky=tk.W, padx=(0, 20))
        
        # Unit ID
        ttk.Label(config_frame, text="Unit ID:").grid(row=2, column=0, sticky=tk.W, padx=(0, 5))
        self.unit_id_var = tk.StringVar(value="1")
        unit_id_entry = ttk.Entry(config_frame, textvariable=self.unit_id_var, width=10)
        unit_id_entry.grid(row=2, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Label(config_frame, text="(0表示忽略Unit ID检查)").grid(row=2, column=2, sticky=tk.W)
        
        # 控制按钮
        button_frame = ttk.Frame(config_frame)
        button_frame.grid(row=3, column=0, columnspan=3, pady=(10, 0))
        
        self.start_button = ttk.Button(
            button_frame, 
            text="启动服务器", 
            command=self._start_server,
            width=15
        )
        self.start_button.grid(row=0, column=0, padx=(0, 10))
        
        self.stop_button = ttk.Button(
            button_frame, 
            text="停止服务器", 
            command=self._stop_server,
            width=15,
            state=tk.DISABLED
        )
        self.stop_button.grid(row=0, column=1)
        
        # 状态显示
        status_frame = ttk.LabelFrame(main_frame, text="服务器状态", padding="10")
        status_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        status_frame.columnconfigure(0, weight=1)
        
        self.status_var = tk.StringVar(value="服务器未运行")
        status_label = ttk.Label(
            status_frame, 
            textvariable=self.status_var,
            font=("Arial", 10)
        )
        status_label.grid(row=0, column=0, sticky=tk.W)
        
        # 通信日志区域
        log_frame = ttk.LabelFrame(main_frame, text="通信日志", padding="10")
        log_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        # 创建带滚动条的文本区域
        self.log_text = scrolledtext.ScrolledText(
            log_frame, 
            width=100, 
            height=20,
            font=("Consolas", 9)
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置文本标签
        self.log_text.tag_config("timestamp", foreground="gray")
        self.log_text.tag_config("client", foreground="blue")
        self.log_text.tag_config("function", foreground="green")
        self.log_text.tag_config("error", foreground="red")
        self.log_text.tag_config("success", foreground="dark green")
        
        # 数据监控区域
        data_frame = ttk.LabelFrame(main_frame, text="数据监控", padding="10")
        data_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # 创建Notebook用于切换不同数据类型的显示
        self.data_notebook = ttk.Notebook(data_frame)
        self.data_notebook.grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        # 创建各数据类型的显示框架
        self._create_data_monitors()
        
        # 清空日志按钮
        clear_button = ttk.Button(
            main_frame,
            text="清空日志",
            command=self._clear_log,
            width=15
        )
        clear_button.grid(row=5, column=0, columnspan=3, pady=(10, 0))
        
    def _create_data_monitors(self):
        """创建数据监控显示"""
        # 线圈状态
        coils_frame = ttk.Frame(self.data_notebook, padding="5")
        self.data_notebook.add(coils_frame, text="线圈状态")
        
        coils_text = scrolledtext.ScrolledText(
            coils_frame,
            width=40,
            height=8,
            font=("Consolas", 9)
        )
        coils_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        coils_frame.columnconfigure(0, weight=1)
        coils_frame.rowconfigure(0, weight=1)
        
        # 离散输入
        inputs_frame = ttk.Frame(self.data_notebook, padding="5")
        self.data_notebook.add(inputs_frame, text="离散输入")
        
        inputs_text = scrolledtext.ScrolledText(
            inputs_frame,
            width=40,
            height=8,
            font=("Consolas", 9)
        )
        inputs_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        inputs_frame.columnconfigure(0, weight=1)
        inputs_frame.rowconfigure(0, weight=1)
        
        # 输入寄存器
        input_regs_frame = ttk.Frame(self.data_notebook, padding="5")
        self.data_notebook.add(input_regs_frame, text="输入寄存器")
        
        input_regs_text = scrolledtext.ScrolledText(
            input_regs_frame,
            width=40,
            height=8,
            font=("Consolas", 9)
        )
        input_regs_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        input_regs_frame.columnconfigure(0, weight=1)
        input_regs_frame.rowconfigure(0, weight=1)
        
        # 保持寄存器
        holding_regs_frame = ttk.Frame(self.data_notebook, padding="5")
        self.data_notebook.add(holding_regs_frame, text="保持寄存器")
        
        holding_regs_text = scrolledtext.ScrolledText(
            holding_regs_frame,
            width=40,
            height=8,
            font=("Consolas", 9)
        )
        holding_regs_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        holding_regs_frame.columnconfigure(0, weight=1)
        holding_regs_frame.rowconfigure(0, weight=1)
        
        # 保存引用以便更新
        self.coils_text = coils_text
        self.inputs_text = inputs_text
        self.input_regs_text = input_regs_text
        self.holding_regs_text = holding_regs_text
        
    def _start_server(self):
        """启动Modbus服务器"""
        try:
            ip = self.ip_var.get().strip()
            port = int(self.port_var.get().strip())
            unit_id = int(self.unit_id_var.get().strip())
            
            # 验证IP地址
            if not self._is_valid_ip(ip):
                messagebox.showerror("错误", "请输入有效的IPv4地址")
                return
            
            # 验证端口号
            if port < 1 or port > 65535:
                messagebox.showerror("错误", "端口号必须在1-65535之间")
                return
            
            # 验证Unit ID
            if unit_id < 0 or unit_id > 255:
                messagebox.showerror("错误", "Unit ID必须在0-255之间")
                return
            
            # 创建Modbus服务器实例
            self.modbus_server = ModbusSlaveServer(ip, port, unit_id, self.message_queue)
            
            # 启动服务器
            success, message = self.modbus_server.start()
            
            if success:
                self.server_running = True
                self.start_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.NORMAL)
                self.status_var.set(f"服务器运行中 - {ip}:{port} (Unit ID: {unit_id})")
                self._log_message(f"服务器已启动: {ip}:{port}, Unit ID: {unit_id}", "success")
                
                # 启动数据更新线程
                self._start_data_update()
                
            else:
                messagebox.showerror("启动失败", message)
                self._log_message(f"启动失败: {message}", "error")
                
        except ValueError as e:
            messagebox.showerror("输入错误", "请输入有效的数字")
        except Exception as e:
            messagebox.showerror("错误", f"启动服务器时发生错误: {str(e)}")
    
    def _stop_server(self):
        """停止Modbus服务器"""
        if self.modbus_server and self.server_running:
            success, message = self.modbus_server.stop()
            
            if success:
                self.server_running = False
                self.start_button.config(state=tk.NORMAL)
                self.stop_button.config(state=tk.DISABLED)
                self.status_var.set("服务器已停止")
                self._log_message("服务器已停止", "success")
            else:
                self._log_message(f"停止服务器时出错: {message}", "error")
    
    def _is_valid_ip(self, ip):
        """验证IPv4地址"""
        try:
            parts = ip.split('.')
            if len(parts) != 4:
                return False
            
            for part in parts:
                if not part.isdigit():
                    return False
                num = int(part)
                if num < 0 or num > 255:
                    return False
            
            return True
        except:
            return False
    
    def _log_message(self, message, tag=None):
        """添加日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        
        self.log_text.insert(tk.END, log_entry)
        if tag:
            # 为刚插入的文本添加标签
            start_index = self.log_text.index("end-2c linestart")
            end_index = self.log_text.index("end-1c")
            self.log_text.tag_add(tag, start_index, end_index)
        
        # 自动滚动到底部
        self.log_text.see(tk.END)
    
    def _clear_log(self):
        """清空日志"""
        self.log_text.delete(1.0, tk.END)
    
    def _process_messages(self):
        """处理消息队列中的消息"""
        try:
            while True:
                message = self.message_queue.get_nowait()
                if message:
                    self._log_message(message)
        except queue.Empty:
            pass
        
        # 每100ms检查一次消息队列
        self.root.after(100, self._process_messages)
    
    def _start_data_update(self):
        """启动数据更新线程"""
        if self.server_running:
            # 启动数据更新线程
            update_thread = threading.Thread(target=self._update_data_monitor, daemon=True)
            update_thread.start()
    
    def _update_data_monitor(self):
        """更新数据监控显示"""
        while self.server_running:
            try:
                # 更新线圈状态显示
                self._update_coils_display()
                
                # 更新离散输入显示
                self._update_inputs_display()
                
                # 更新输入寄存器显示
                self._update_input_registers_display()
                
                # 更新保持寄存器显示
                self._update_holding_registers_display()
                
                time.sleep(1)  # 每秒更新一次
                
            except Exception as e:
                print(f"更新数据监控时出错: {e}")
                time.sleep(5)
    
    def _update_coils_display(self):
        """更新线圈状态显示"""
        if not self.modbus_server:
            return
        
        # 获取前100个线圈状态
        coils_text = "地址\t状态\n"
        coils_text += "-" * 30 + "\n"
        
        for i in range(100):
            status = "ON" if self.modbus_server.coils[i] else "OFF"
            coils_text += f"{i:05d}\t{status}\n"
        
        # 在GUI线程中更新显示
        self.root.after(0, lambda: self._safe_update_text(self.coils_text, coils_text))
    
    def _update_inputs_display(self):
        """更新离散输入显示"""
        if not self.modbus_server:
            return
        
        # 获取前100个离散输入状态
        inputs_text = "地址\t状态\n"
        inputs_text += "-" * 30 + "\n"
        
        for i in range(100):
            status = "ON" if self.modbus_server.discrete_inputs[i] else "OFF"
            inputs_text += f"{i+10000:05d}\t{status}\n"
        
        # 在GUI线程中更新显示
        self.root.after(0, lambda: self._safe_update_text(self.inputs_text, inputs_text))
    
    def _update_input_registers_display(self):
        """更新输入寄存器显示"""
        if not self.modbus_server:
            return
        
        # 获取前50个输入寄存器值
        regs_text = "地址\t值(十进制)\t值(十六进制)\n"
        regs_text += "-" * 50 + "\n"
        
        for i in range(50):
            value = self.modbus_server.input_registers[i]
            regs_text += f"{i+30000:05d}\t{value}\t\t0x{value:04X}\n"
        
        # 在GUI线程中更新显示
        self.root.after(0, lambda: self._safe_update_text(self.input_regs_text, regs_text))
    
    def _update_holding_registers_display(self):
        """更新保持寄存器显示"""
        if not self.modbus_server:
            return
        
        # 获取前50个保持寄存器值
        regs_text = "地址\t值(十进制)\t值(十六进制)\n"
        regs_text += "-" * 50 + "\n"
        
        for i in range(50):
            value = self.modbus_server.holding_registers[i]
            regs_text += f"{i+40000:05d}\t{value}\t\t0x{value:04X}\n"
        
        # 在GUI线程中更新显示
        self.root.after(0, lambda: self._safe_update_text(self.holding_regs_text, regs_text))
    
    def _safe_update_text(self, text_widget, content):
        """安全更新文本控件内容"""
        try:
            text_widget.delete(1.0, tk.END)
            text_widget.insert(1.0, content)
        except:
            pass
    
    def run(self):
        """运行GUI应用程序"""
        self.root.mainloop()


def main():
    """主函数"""
    try:
        app = ModbusSlaveGUI()
        app.run()
    except Exception as e:
        print(f"应用程序启动失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()