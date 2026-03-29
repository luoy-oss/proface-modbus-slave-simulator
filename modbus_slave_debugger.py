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
import json
import array

offset = 0

class ModbusSlaveServer:
    """Modbus TCP从机服务器类"""
    
    def __init__(self, ip='192.168.1.113', port=502, unit_id=1, message_queue=None, enabled_functions=None,
                 address_offset=0, byte_order='big'):
        """
        初始化Modbus从机服务器
        
        参数:
            ip: 监听IP地址
            port: 监听端口
            unit_id: 从机单元ID
            message_queue: 消息队列，用于与GUI通信
            enabled_functions: 启用的功能码列表，None表示启用所有
            address_offset: 地址偏移量，0表示从0开始（标准Modbus），1表示从1开始（Pro-face等设备）
            byte_order: 字节序，'big'表示大端模式（高位低字），'little'表示小端模式（低位高字）
        """
        self.ip = ip
        self.port = port
        self.unit_id = unit_id
        self.running = False
        self.server_socket = None
        self.client_threads = []
        
        # Modbus数据存储 - 使用更高效的数据结构
        # 使用array('b')存储布尔值（1字节每个），比Python列表更节省内存
        self.coils = array.array('b', [0]) * 65536  # 线圈状态，0=False, 1=True
        self.discrete_inputs = array.array('b', [0]) * 65536  # 离散输入
        # 使用array('H')存储无符号短整型（2字节每个），比Python整数列表更节省内存
        self.input_registers = array.array('H', [0]) * 65536  # 输入寄存器
        self.holding_registers = array.array('H', [0]) * 65536  # 保持寄存器
        
        # 消息队列
        self.message_queue = message_queue
        
        # 启用的功能码
        if enabled_functions is None:
            # 默认启用所有标准功能码
            self.enabled_functions = [1, 2, 3, 4, 5, 6, 15, 16]
        else:
            self.enabled_functions = enabled_functions
        
        # 地址映射和字节序配置
        self.address_offset = address_offset
        global offset
        offset = address_offset

        self.byte_order = byte_order
        
        # 初始化一些测试数据
        self._init_test_data()
        
    def _init_test_data(self):
        """初始化测试数据"""
        # 初始化一些线圈状态
        for i in range(0, 100, 2):
            self.coils[i] = 1  # True
            
        # 初始化一些离散输入
        for i in range(0, 100, 3):
            self.discrete_inputs[i] = 1  # True
            
        # 初始化输入寄存器（模拟传感器数据）
        for i in range(0, 100):
            self.input_registers[i] = i * 10
            
        # 初始化保持寄存器
        for i in range(0, 100):
            self.holding_registers[i] = i * 100

        self.coils[0] = 1  # True
        self.discrete_inputs[0] = 1  # True
        self.input_registers[0] = 233
        self.input_registers[1] = 0
        self.holding_registers[0] = 2333
        self.holding_registers[1] = 1
        self.holding_registers[2] = 1


    def _convert_address(self, address):
        """
        转换地址，考虑地址偏移
        
        参数:
            address: 原始地址
            
        返回:
            转换后的地址（考虑偏移）
        """
        if self.address_offset == 0:
            return address  # 标准Modbus，从0开始
        else:
            # Pro-face等设备，从1开始，需要减1
            if address > 0:
                return address
            else:
                # 地址为0时，返回0（虽然Pro-face通常不会使用地址0）
                return 0
    
    def _pack_value(self, value):
        """
        打包16位值，考虑字节序
        
        参数:
            value: 16位整数值
            
        返回:
            打包后的字节串
        """
        if self.byte_order == 'big':
            return struct.pack('>H', value)  # 大端模式（高位低字）
        else:
            return struct.pack('<H', value)  # 小端模式（低位高字）
    
    def _unpack_value(self, data):
        """
        解包16位值，考虑字节序
        
        参数:
            data: 2字节数据
            
        返回:
            解包后的整数值
        """
        if self.byte_order == 'big':
            return struct.unpack('>H', data)[0]  # 大端模式（高位低字）
        else:
            return struct.unpack('<H', data)[0]  # 小端模式（低位高字）
    
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
            
            # 检查功能码是否启用
            if function_code not in self.enabled_functions:
                return self._create_error_response(request_data[0:2], unit_id, function_code, 0x01)  # 非法功能
            
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
        
        # 转换地址（考虑地址偏移）
        converted_address = self._convert_address(address)
        
        # 检查地址范围
        if converted_address + count > 65536:
            return self._create_error_response(transaction_id, unit_id, 1, 0x02)  # 非法数据地址
        
        # 读取线圈状态
        byte_count = (count + 7) // 8
        response_bytes = bytearray([0] * byte_count)
        
        for i in range(count):
            if converted_address + i < len(self.coils) and self.coils[converted_address + i] == 1:
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
        
        # 转换地址（考虑地址偏移）
        converted_address = self._convert_address(address)
        
        # 检查地址范围
        if converted_address + count > 65536:
            return self._create_error_response(transaction_id, unit_id, 2, 0x02)  # 非法数据地址
        
        # 读取离散输入状态
        byte_count = (count + 7) // 8
        response_bytes = bytearray([0] * byte_count)
        
        for i in range(count):
            if converted_address + i < len(self.discrete_inputs) and self.discrete_inputs[converted_address + i] == 1:
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
        
        # 转换地址（考虑地址偏移）
        converted_address = self._convert_address(address)
        
        # 检查地址范围
        if converted_address + count > 65536:
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
            if converted_address + i < len(self.holding_registers):
                value = self.holding_registers[converted_address + i]
                response.extend(self._pack_value(value))  # 使用字节序转换
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
        
        # 转换地址（考虑地址偏移）
        converted_address = self._convert_address(address)
        
        # 检查地址范围
        if converted_address + count > 65536:
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
            if converted_address + i < len(self.input_registers):
                value = self.input_registers[converted_address + i]
                response.extend(self._pack_value(value))  # 使用字节序转换
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
        
        # 转换地址（考虑地址偏移）
        converted_address = self._convert_address(address)
        
        # 检查地址范围
        if converted_address >= 65536:
            return self._create_error_response(transaction_id, unit_id, 5, 0x02)  # 非法数据地址
        
        # 检查值是否有效
        if value not in [0x0000, 0xFF00]:
            return self._create_error_response(transaction_id, unit_id, 5, 0x03)  # 非法数据值
        
        # 写入线圈
        if converted_address < len(self.coils):
            self.coils[converted_address] = 1 if (value == 0xFF00) else 0
        
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
        
        # 转换地址（考虑地址偏移）
        converted_address = self._convert_address(address)
        
        # 检查地址范围
        if converted_address >= 65536:
            return self._create_error_response(transaction_id, unit_id, 6, 0x02)  # 非法数据地址
        
        # 写入寄存器
        if converted_address < len(self.holding_registers):
            self.holding_registers[converted_address] = value
        
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
        
        # 转换地址（考虑地址偏移）
        converted_address = self._convert_address(address)
        
        # 检查地址范围
        if converted_address + count > 65536:
            return self._create_error_response(transaction_id, unit_id, 15, 0x02)  # 非法数据地址
        
        # 检查数据长度
        expected_byte_count = (count + 7) // 8
        if byte_count != expected_byte_count or len(request_data) < 13 + byte_count:
            return self._create_error_response(transaction_id, unit_id, 15, 0x03)  # 非法数据值
        
        # 写入线圈
        for i in range(count):
            if converted_address + i < len(self.coils):
                byte_index = 13 + i // 8
                bit_index = i % 8
                if byte_index < len(request_data):
                    byte_val = request_data[byte_index]
                    self.coils[converted_address + i] = 1 if ((byte_val >> bit_index) & 0x01) == 0x01 else 0
        
        # 构建响应（返回地址和数量）
        response = bytearray()
        response.extend(transaction_id)  # 事务ID
        response.extend(b'\x00\x00')  # 协议ID
        response.extend(struct.pack('>H', 6))  # 长度
        response.append(unit_id)  # 单元ID
        response.append(15)  # 功能码
        response.extend(struct.pack('>H', address))  # 起始地址（返回原始地址）
        response.extend(struct.pack('>H', count))  # 数量
        
        return bytes(response)
    
    def _handle_write_multiple_registers(self, request_data):
        """处理写多个寄存器请求"""
        if len(request_data) < 13:
            return None
        
        '''
[23:49:45] ('request', 
{'timestamp': '23:49:45.236', 
'client': '192.168.1.100:1791', 
'transaction_id': 0, 'unit_id': 1, 
'function_code': 16, 'function_name': '写多个寄存器', 
'address': 32, 'count': 1, 'values': [7777], 
'raw_data': '000000000009011000200001021E61'})

        '''
        transaction_id = request_data[0:2]
        unit_id = request_data[6]
        address = struct.unpack('>H', request_data[8:10])[0]
        count = struct.unpack('>H', request_data[10:12])[0]
        byte_count = request_data[12]
        
        # 转换地址（考虑地址偏移）
        converted_address = self._convert_address(address)
        
        # 检查地址范围
        if converted_address + count > 65536:
            return self._create_error_response(transaction_id, unit_id, 16, 0x02)  # 非法数据地址
        
        # 检查数据长度
        if byte_count != count * 2 or len(request_data) < 13 + byte_count:
            return self._create_error_response(transaction_id, unit_id, 16, 0x03)  # 非法数据值
        
        # 写入寄存器（考虑字节序）
        for i in range(count):
            if converted_address + i < len(self.holding_registers):
                # 使用字节序转换解包值
                value = self._unpack_value(request_data[13+i*2:15+i*2])
                self.holding_registers[converted_address + i] = value
        
        # 构建响应（返回地址和数量）
        response = bytearray()
        response.extend(transaction_id)  # 事务ID
        response.extend(b'\x00\x00')  # 协议ID
        response.extend(struct.pack('>H', 6))  # 长度
        response.append(unit_id)  # 单元ID
        response.append(16)  # 功能码
        response.extend(struct.pack('>H', address))  # 起始地址（返回原始地址）
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
        self.root.title("Proface Modbus Slave v1.6")
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
        
        # 配置文件路径
        self.config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modbus_config.json")
        
        # 数据模拟管理器
        self.data_simulation_manager = None
        
        # 创建界面
        self._create_widgets()
        
        # 启动消息处理循环
        self._process_messages()
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
    def _create_widgets(self):
        """创建界面组件"""
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.columnconfigure(2, weight=1)
        # 给所有行分配权重，确保缩放时布局正确
        main_frame.rowconfigure(0, weight=0)  # 标题行，不扩展
        main_frame.rowconfigure(1, weight=0)  # 配置区域，不扩展
        main_frame.rowconfigure(2, weight=0)  # 状态区域，不扩展
        main_frame.rowconfigure(3, weight=3)  # 日志区域权重最高
        main_frame.rowconfigure(4, weight=2)  # 数据监控区域权重次高
        main_frame.rowconfigure(5, weight=0)  # 清空日志按钮，不扩展
        main_frame.rowconfigure(6, weight=0)  # 作者信息，不扩展
        
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
        self.ip_var = tk.StringVar(value="192.168.1.113")
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
        
        # 功能码配置
        ttk.Label(config_frame, text="启用功能码:").grid(row=3, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        
        # 创建功能码复选框框架
        function_frame = ttk.Frame(config_frame)
        function_frame.grid(row=3, column=1, columnspan=2, sticky=tk.W, pady=(10, 0))
        
        # 功能码映射
        self.function_codes = {
            "01 - 读线圈": 1,
            "02 - 读离散输入": 2,
            "03 - 读保持寄存器": 3,
            "04 - 读输入寄存器": 4,
            "05 - 写单个线圈": 5,
            "06 - 写单个寄存器": 6,
            "15 - 写多个线圈": 15,
            "16 - 写多个寄存器": 16
        }
        
        # 创建复选框变量
        self.function_vars = {}
        row_idx = 0
        col_idx = 0
        
        for func_name, func_code in self.function_codes.items():
            var = tk.BooleanVar(value=True)  # 默认全部启用
            self.function_vars[func_code] = var
            
            cb = ttk.Checkbutton(
                function_frame,
                text=func_name,
                variable=var
            )
            cb.grid(row=row_idx, column=col_idx, sticky=tk.W, padx=(0, 15))
            
            col_idx += 1
            if col_idx >= 2:
                col_idx = 0
                row_idx += 1
        
        # 地址映射配置
        ttk.Label(config_frame, text="地址映射:").grid(row=4, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        
        address_frame = ttk.Frame(config_frame)
        address_frame.grid(row=4, column=1, columnspan=2, sticky=tk.W, pady=(10, 0))
        
        self.address_offset_var = tk.IntVar(value=1)  # 0: 从0开始, 1: 从1开始
        
        ttk.Radiobutton(
            address_frame,
            text="标准Modbus (地址从0开始: 0-65535)",
            variable=self.address_offset_var,
            value=0,
            command=self._update_address_offset_cache
        ).grid(row=0, column=0, sticky=tk.W, padx=(0, 15))
        
        ttk.Radiobutton(
            address_frame,
            text="Pro-face等设备 (地址从1开始: 1-65536)",
            variable=self.address_offset_var,
            value=1,
            command=self._update_address_offset_cache
        ).grid(row=0, column=1, sticky=tk.W)
        
        # 字节序配置
        ttk.Label(config_frame, text="字节序:").grid(row=5, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        
        byteorder_frame = ttk.Frame(config_frame)
        byteorder_frame.grid(row=5, column=1, columnspan=2, sticky=tk.W, pady=(10, 0))
        
        self.byte_order_var = tk.StringVar(value="big")  # 'big': 大端模式, 'little': 小端模式
        
        ttk.Radiobutton(
            byteorder_frame,
            text="大端模式 (Low word first, L/H)",
            variable=self.byte_order_var,
            value="big"
        ).grid(row=0, column=0, sticky=tk.W, padx=(0, 15))
        
        ttk.Radiobutton(
            byteorder_frame,
            text="小端模式 (High word first, H/L)",
            variable=self.byte_order_var,
            value="little"
        ).grid(row=0, column=1, sticky=tk.W)
        
        # 控制按钮
        button_frame = ttk.Frame(config_frame)
        button_frame.grid(row=6, column=0, columnspan=3, pady=(10, 0))
        
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
            height=8,  # 进一步减小初始高度，让权重配置控制实际大小
            font=("Consolas", 9)
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 确保日志区域内部组件能够正确扩展
        self.log_text.configure(wrap=tk.WORD)
        
        # 配置文本标签
        self.log_text.tag_config("timestamp", foreground="gray")
        self.log_text.tag_config("client", foreground="blue")
        self.log_text.tag_config("function", foreground="green")
        self.log_text.tag_config("error", foreground="red")
        self.log_text.tag_config("success", foreground="dark green")
        
        # 数据监控区域
        data_frame = ttk.LabelFrame(main_frame, text="数据监控", padding="10")
        data_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        data_frame.columnconfigure(0, weight=1)
        data_frame.rowconfigure(0, weight=1)
        
        # 创建Notebook用于切换不同数据类型的显示
        self.data_notebook = ttk.Notebook(data_frame)
        self.data_notebook.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 确保Notebook能够正确扩展
        self.data_notebook.configure(height=200)  # 设置一个初始高度，但权重配置会控制实际大小
        
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
        
        # 作者信息和GitHub链接（右下角）
        author_frame = ttk.Frame(main_frame)
        author_frame.grid(row=6, column=0, columnspan=3, sticky=tk.E, pady=(10, 0))
        
        # 作者标签
        author_label = ttk.Label(
            author_frame,
            text="作者: luoy-oss",
            foreground="gray",
            cursor="hand2"
        )
        author_label.pack(side=tk.RIGHT, padx=(0, 10))
        
        # 绑定点击事件，跳转到GitHub页面
        author_label.bind("<Button-1>", lambda e: self._open_github_page())
        
    def _open_github_page(self):
        """打开GitHub页面"""
        import webbrowser
        webbrowser.open("https://github.com/luoy-oss/proface-modbus-slave-simulator")
        
    def _create_data_monitors(self):
        """创建数据监控显示"""
        # 线圈状态
        coils_frame = ttk.Frame(self.data_notebook, padding="5")
        self.data_notebook.add(coils_frame, text="线圈状态")
        
        # 配置线圈框架的网格权重
        coils_frame.columnconfigure(0, weight=1)
        coils_frame.rowconfigure(0, weight=1)
        coils_frame.rowconfigure(1, weight=0)  # 按钮行不扩展
        
        # 线圈状态表格
        self.coils_tree = ttk.Treeview(
            coils_frame,
            columns=("address", "status", "value"),
            show="headings",
            height=8  # 减小初始高度，让权重配置控制实际大小
        )
        self.coils_tree.heading("address", text="地址")
        self.coils_tree.heading("status", text="状态")
        self.coils_tree.heading("value", text="值")
        self.coils_tree.column("address", width=80, stretch=False)
        self.coils_tree.column("status", width=80, stretch=False)
        self.coils_tree.column("value", width=100, stretch=False)
        
        # 绑定双击事件
        self.coils_tree.bind("<Double-1>", lambda e: self._on_treeview_double_click(e, "coil"))
        
        self.coils_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 线圈操作按钮
        coils_button_frame = ttk.Frame(coils_frame)
        coils_button_frame.grid(row=1, column=0, sticky=tk.W, pady=(5, 0))
        
        ttk.Label(coils_button_frame, text="地址:").pack(side=tk.LEFT, padx=(0, 5))
        self.coil_address_var = tk.StringVar(value="0")
        ttk.Entry(coils_button_frame, textvariable=self.coil_address_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Label(coils_button_frame, text="值:").pack(side=tk.LEFT, padx=(0, 5))
        self.coil_value_var = tk.StringVar(value="ON")
        coil_value_combo = ttk.Combobox(coils_button_frame, textvariable=self.coil_value_var, width=10, values=["ON", "OFF"])
        coil_value_combo.pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            coils_button_frame,
            text="设置线圈",
            command=self._set_coil_value,
            width=10
        ).pack(side=tk.LEFT)
        
        # 离散输入
        inputs_frame = ttk.Frame(self.data_notebook, padding="5")
        self.data_notebook.add(inputs_frame, text="离散输入")
        
        # 配置离散输入框架的网格权重
        inputs_frame.columnconfigure(0, weight=1)
        inputs_frame.rowconfigure(0, weight=1)
        
        # 离散输入表格
        self.inputs_tree = ttk.Treeview(
            inputs_frame,
            columns=("address", "status"),
            show="headings",
            height=8  # 减小初始高度，让权重配置控制实际大小
        )
        self.inputs_tree.heading("address", text="地址")
        self.inputs_tree.heading("status", text="状态")
        self.inputs_tree.column("address", width=80, stretch=False)
        self.inputs_tree.column("status", width=80, stretch=False)
        
        # 绑定双击事件
        self.inputs_tree.bind("<Double-1>", lambda e: self._on_treeview_double_click(e, "discrete_input"))
        
        self.inputs_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 输入寄存器
        input_regs_frame = ttk.Frame(self.data_notebook, padding="5")
        self.data_notebook.add(input_regs_frame, text="输入寄存器")
        
        # 配置输入寄存器框架的网格权重
        input_regs_frame.columnconfigure(0, weight=1)
        input_regs_frame.rowconfigure(0, weight=1)
        input_regs_frame.rowconfigure(1, weight=0)  # 按钮行不扩展
        
        # 输入寄存器表格
        self.input_regs_tree = ttk.Treeview(
            input_regs_frame,
            columns=("address", "value"),
            show="headings",
            height=8  # 减小初始高度，让权重配置控制实际大小
        )
        self.input_regs_tree.heading("address", text="地址")
        self.input_regs_tree.heading("value", text="值")
        self.input_regs_tree.column("address", width=80, stretch=False)
        self.input_regs_tree.column("value", width=100, stretch=False)
        
        # 绑定双击事件
        self.input_regs_tree.bind("<Double-1>", lambda e: self._on_treeview_double_click(e, "input_register"))
        
        self.input_regs_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 输入寄存器操作按钮
        input_regs_button_frame = ttk.Frame(input_regs_frame)
        input_regs_button_frame.grid(row=1, column=0, sticky=tk.W, pady=(5, 0))
        
        ttk.Label(input_regs_button_frame, text="地址:").pack(side=tk.LEFT, padx=(0, 5))
        self.input_reg_address_var = tk.StringVar(value="0")
        ttk.Entry(input_regs_button_frame, textvariable=self.input_reg_address_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Label(input_regs_button_frame, text="值:").pack(side=tk.LEFT, padx=(0, 5))
        self.input_reg_value_var = tk.StringVar(value="0")
        ttk.Entry(input_regs_button_frame, textvariable=self.input_reg_value_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            input_regs_button_frame,
            text="设置寄存器",
            command=self._set_input_register_value,
            width=10
        ).pack(side=tk.LEFT)
        
        # 保持寄存器
        holding_regs_frame = ttk.Frame(self.data_notebook, padding="5")
        self.data_notebook.add(holding_regs_frame, text="保持寄存器")
        
        # 保持寄存器表格
        self.holding_regs_tree = ttk.Treeview(
            holding_regs_frame,
            columns=("address", "value"),
            show="headings",
            height=10
        )
        self.holding_regs_tree.heading("address", text="地址")
        self.holding_regs_tree.heading("value", text="值")
        self.holding_regs_tree.column("address", width=80)
        self.holding_regs_tree.column("value", width=100)
        
        # 绑定双击事件
        self.holding_regs_tree.bind("<Double-1>", lambda e: self._on_treeview_double_click(e, "holding_register"))
        
        self.holding_regs_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 保持寄存器操作按钮
        holding_regs_button_frame = ttk.Frame(holding_regs_frame)
        holding_regs_button_frame.grid(row=1, column=0, sticky=tk.W, pady=(5, 0))
        
        ttk.Label(holding_regs_button_frame, text="地址:").pack(side=tk.LEFT, padx=(0, 5))
        self.holding_reg_address_var = tk.StringVar(value="0")
        ttk.Entry(holding_regs_button_frame, textvariable=self.holding_reg_address_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Label(holding_regs_button_frame, text="值:").pack(side=tk.LEFT, padx=(0, 5))
        self.holding_reg_value_var = tk.StringVar(value="0")
        ttk.Entry(holding_regs_button_frame, textvariable=self.holding_reg_value_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            holding_regs_button_frame,
            text="设置寄存器",
            command=self._set_holding_register_value,
            width=10
        ).pack(side=tk.LEFT)
        
        holding_regs_frame.columnconfigure(0, weight=1)
        holding_regs_frame.rowconfigure(0, weight=1)
        
        # 数据模拟功能
        simulation_frame = ttk.Frame(self.data_notebook, padding="5")
        self.data_notebook.add(simulation_frame, text="数据模拟")
        
        # 创建数据模拟界面
        self._create_simulation_interface(simulation_frame)
        
    def _create_simulation_interface(self, parent_frame):
        """创建数据模拟界面"""
        # 创建Notebook用于切换不同类型的模拟功能
        simulation_notebook = ttk.Notebook(parent_frame)
        simulation_notebook.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 自增功能
        increment_frame = ttk.Frame(simulation_notebook, padding="10")
        simulation_notebook.add(increment_frame, text="自增功能")
        self._create_increment_interface(increment_frame)
        
        # 位翻转功能
        bit_flip_frame = ttk.Frame(simulation_notebook, padding="10")
        simulation_notebook.add(bit_flip_frame, text="位翻转")
        self._create_bit_flip_interface(bit_flip_frame)
        
        # 时间数据功能
        time_frame = ttk.Frame(simulation_notebook, padding="10")
        simulation_notebook.add(time_frame, text="时间数据")
        self._create_time_interface(time_frame)
        
        # 日期数据功能
        date_frame = ttk.Frame(simulation_notebook, padding="10")
        simulation_notebook.add(date_frame, text="日期数据")
        self._create_date_interface(date_frame)
        
        # 任务列表功能
        task_list_frame = ttk.Frame(simulation_notebook, padding="10")
        simulation_notebook.add(task_list_frame, text="任务列表")
        self._create_task_list_interface(task_list_frame)
        
        # 配置网格权重
        parent_frame.columnconfigure(0, weight=1)
        parent_frame.rowconfigure(0, weight=1)
        
    def _create_increment_interface(self, parent_frame):
        """创建自增功能界面"""
        # 数据类型选择
        type_frame = ttk.Frame(parent_frame)
        type_frame.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        ttk.Label(type_frame, text="数据类型:").pack(side=tk.LEFT, padx=(0, 5))
        self.increment_data_type_var = tk.StringVar(value="holding_register")
        data_type_combo = ttk.Combobox(
            type_frame,
            textvariable=self.increment_data_type_var,
            width=15,
            values=["coil", "discrete_input", "input_register", "holding_register"]
        )
        data_type_combo.pack(side=tk.LEFT, padx=(0, 10))
        
        # 地址配置
        address_frame = ttk.Frame(parent_frame)
        address_frame.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        ttk.Label(address_frame, text="地址:").pack(side=tk.LEFT, padx=(0, 5))
        self.increment_address_var = tk.StringVar(value="0")
        ttk.Entry(address_frame, textvariable=self.increment_address_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        # 自增参数配置
        params_frame = ttk.Frame(parent_frame)
        params_frame.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        # 间隔时间
        ttk.Label(params_frame, text="间隔(ms):").pack(side=tk.LEFT, padx=(0, 5))
        self.increment_interval_var = tk.StringVar(value="1000")
        ttk.Entry(params_frame, textvariable=self.increment_interval_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        # 步长
        ttk.Label(params_frame, text="步长:").pack(side=tk.LEFT, padx=(0, 5))
        self.increment_step_var = tk.StringVar(value="1")
        ttk.Entry(params_frame, textvariable=self.increment_step_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        # 最小值
        ttk.Label(params_frame, text="最小值:").pack(side=tk.LEFT, padx=(0, 5))
        self.increment_min_var = tk.StringVar(value="0")
        ttk.Entry(params_frame, textvariable=self.increment_min_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        # 最大值
        ttk.Label(params_frame, text="最大值:").pack(side=tk.LEFT, padx=(0, 5))
        self.increment_max_var = tk.StringVar(value="65535")
        ttk.Entry(params_frame, textvariable=self.increment_max_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        # 按钮
        button_frame = ttk.Frame(parent_frame)
        button_frame.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        
        ttk.Button(
            button_frame,
            text="添加自增任务",
            command=self._add_increment_task,
            width=15
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        # ttk.Button(
        #     button_frame,
        #     text="移除自增任务",
        #     command=self._remove_increment_task,
        #     width=15
        # ).pack(side=tk.LEFT)
        
        # 配置网格权重
        parent_frame.columnconfigure(0, weight=1)
        parent_frame.rowconfigure(3, weight=1)
        
    def _create_bit_flip_interface(self, parent_frame):
        """创建位翻转功能界面"""
        # 数据类型选择
        type_frame = ttk.Frame(parent_frame)
        type_frame.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        ttk.Label(type_frame, text="数据类型:").pack(side=tk.LEFT, padx=(0, 5))
        self.bit_flip_data_type_var = tk.StringVar(value="coil")
        data_type_combo = ttk.Combobox(
            type_frame,
            textvariable=self.bit_flip_data_type_var,
            width=15,
            values=["coil", "discrete_input"]
        )
        data_type_combo.pack(side=tk.LEFT, padx=(0, 10))
        
        # 地址配置
        address_frame = ttk.Frame(parent_frame)
        address_frame.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        ttk.Label(address_frame, text="地址:").pack(side=tk.LEFT, padx=(0, 5))
        self.bit_flip_address_var = tk.StringVar(value="0")
        ttk.Entry(address_frame, textvariable=self.bit_flip_address_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        # 间隔时间
        interval_frame = ttk.Frame(parent_frame)
        interval_frame.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        ttk.Label(interval_frame, text="间隔(ms):").pack(side=tk.LEFT, padx=(0, 5))
        self.bit_flip_interval_var = tk.StringVar(value="1000")
        ttk.Entry(interval_frame, textvariable=self.bit_flip_interval_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        # 按钮
        button_frame = ttk.Frame(parent_frame)
        button_frame.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        
        ttk.Button(
            button_frame,
            text="添加位翻转任务",
            command=self._add_bit_flip_task,
            width=15
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        # ttk.Button(
        #     button_frame,
        #     text="移除位翻转任务",
        #     command=self._remove_bit_flip_task,
        #     width=15
        # ).pack(side=tk.LEFT)
        
        # 配置网格权重
        parent_frame.columnconfigure(0, weight=1)
        parent_frame.rowconfigure(3, weight=1)
        
    def _create_time_interface(self, parent_frame):
        """创建时间数据功能界面"""
        # 基础地址配置
        address_frame = ttk.Frame(parent_frame)
        address_frame.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        ttk.Label(address_frame, text="基础地址:").pack(side=tk.LEFT, padx=(0, 5))
        self.time_base_address_var = tk.StringVar(value="101")
        ttk.Entry(address_frame, textvariable=self.time_base_address_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Label(address_frame, text="(占用3个地址: HH, MM, SS)").pack(side=tk.LEFT)
        
        # 间隔时间
        interval_frame = ttk.Frame(parent_frame)
        interval_frame.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        ttk.Label(interval_frame, text="更新间隔(ms):").pack(side=tk.LEFT, padx=(0, 5))
        self.time_interval_var = tk.StringVar(value="1000")
        ttk.Entry(interval_frame, textvariable=self.time_interval_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        # 当前时间显示
        time_display_frame = ttk.Frame(parent_frame)
        time_display_frame.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        ttk.Label(time_display_frame, text="当前系统时间:").pack(side=tk.LEFT, padx=(0, 5))
        self.current_time_var = tk.StringVar()
        ttk.Label(time_display_frame, textvariable=self.current_time_var, font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        
        # 更新时间显示
        self._update_time_display()
        
        # 按钮
        button_frame = ttk.Frame(parent_frame)
        button_frame.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        
        ttk.Button(
            button_frame,
            text="添加时间数据任务",
            command=self._add_time_task,
            width=15
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        # ttk.Button(
        #     button_frame,
        #     text="移除时间数据任务",
        #     command=self._remove_time_task,
        #     width=15
        # ).pack(side=tk.LEFT)
        
        # 配置网格权重
        parent_frame.columnconfigure(0, weight=1)
        parent_frame.rowconfigure(3, weight=1)
        
    def _create_date_interface(self, parent_frame):
        """创建日期数据功能界面"""
        # 基础地址配置
        address_frame = ttk.Frame(parent_frame)
        address_frame.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        ttk.Label(address_frame, text="基础地址:").pack(side=tk.LEFT, padx=(0, 5))
        self.date_base_address_var = tk.StringVar(value="201")
        ttk.Entry(address_frame, textvariable=self.date_base_address_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Label(address_frame, text="(占用4个地址: YY, MM, DD, Weekday)").pack(side=tk.LEFT)
        
        # 间隔时间
        interval_frame = ttk.Frame(parent_frame)
        interval_frame.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        ttk.Label(interval_frame, text="更新间隔(ms):").pack(side=tk.LEFT, padx=(0, 5))
        self.date_interval_var = tk.StringVar(value="1000")
        ttk.Entry(interval_frame, textvariable=self.date_interval_var, width=10).pack(side=tk.LEFT, padx=(0, 10))
        
        # 当前日期显示
        date_display_frame = ttk.Frame(parent_frame)
        date_display_frame.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        ttk.Label(date_display_frame, text="当前系统日期:").pack(side=tk.LEFT, padx=(0, 5))
        self.current_date_var = tk.StringVar()
        ttk.Label(date_display_frame, textvariable=self.current_date_var, font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        
        # 更新日期显示
        self._update_date_display()
        
        # 按钮
        button_frame = ttk.Frame(parent_frame)
        button_frame.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        
        ttk.Button(
            button_frame,
            text="添加日期数据任务",
            command=self._add_date_task,
            width=15
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        # ttk.Button(
        #     button_frame,
        #     text="移除日期数据任务",
        #     command=self._remove_date_task,
        #     width=15
        # ).pack(side=tk.LEFT)
        
        # 配置网格权重
        parent_frame.columnconfigure(0, weight=1)
        parent_frame.rowconfigure(3, weight=1)
        
    def _create_task_list_interface(self, parent_frame):
        """创建任务列表界面"""
        # 任务列表表格
        self.task_tree = ttk.Treeview(
            parent_frame,
            columns=("type", "data_type", "address", "interval", "details"),
            show="headings",
            height=15
        )
        self.task_tree.heading("type", text="任务类型")
        self.task_tree.heading("data_type", text="数据类型")
        self.task_tree.heading("address", text="地址")
        self.task_tree.heading("interval", text="间隔(ms)")
        self.task_tree.heading("details", text="详细信息")
        
        self.task_tree.column("type", width=80, stretch=False)
        self.task_tree.column("data_type", width=100, stretch=False)
        self.task_tree.column("address", width=80, stretch=False)
        self.task_tree.column("interval", width=80, stretch=False)
        self.task_tree.column("details", width=200, stretch=True)
        
        # 添加滚动条
        task_scrollbar = ttk.Scrollbar(parent_frame, orient="vertical", command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=task_scrollbar.set)
        
        self.task_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        task_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # 按钮框架
        button_frame = ttk.Frame(parent_frame)
        button_frame.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        
        # 刷新按钮
        ttk.Button(
            button_frame,
            text="刷新任务列表",
            command=self._refresh_task_list,
            width=15
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        # 删除选中任务按钮
        ttk.Button(
            button_frame,
            text="删除选中任务",
            command=self._remove_selected_task,
            width=15
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        # 删除所有任务按钮
        ttk.Button(
            button_frame,
            text="删除所有任务",
            command=self._remove_all_tasks,
            width=15
        ).pack(side=tk.LEFT)
        
        # 配置网格权重
        parent_frame.columnconfigure(0, weight=1)
        parent_frame.rowconfigure(0, weight=1)
        parent_frame.rowconfigure(1, weight=0)  # 按钮行不扩展
        
        # 启动定时刷新
        self._refresh_task_list()
        
    def _refresh_task_list(self):
        """刷新任务列表"""
        if not hasattr(self, 'task_tree'):
            return
        
        # 清空当前列表
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)
        
        # 获取所有任务
        if self.data_simulation_manager:
            tasks = self.data_simulation_manager.get_all_tasks()
            
            # 添加任务到表格
            global offset
            for task in tasks:
                task_type = task['type']
                data_type = task.get('data_type', '')
                if task_type == "日期数据" or task_type == "时间数据":
                    address = str(task.get('address', task.get('base_address', '')) + offset) 
                else:
                    address = str(task.get('address', task.get('base_address', '')) + offset)
                
                interval = str(task.get('interval', ''))
                
                # 构建详细信息
                details = ""
                if task_type == '自增':
                    details = f"步长:{task.get('step', '')} 范围:{task.get('min', '')}-{task.get('max', '')} 当前:{task.get('current', '')}"
                elif task_type == '位翻转':
                    details = f"位翻转任务"
                elif task_type == '时间数据':
                    details = f"占用3个地址: HH, MM, SS"
                elif task_type == '日期数据':
                    details = f"占用4个地址: YY, MM, DD, Weekday"
                
                self.task_tree.insert("", "end", values=(task_type, data_type, address, interval, details))
        
        # 5秒后再次刷新
        self.root.after(5000, self._refresh_task_list)
        
    def _remove_selected_task(self):
        """删除选中的任务"""
        if not hasattr(self, 'task_tree'):
            return
        
        selected_items = self.task_tree.selection()
        if not selected_items:
            messagebox.showinfo("提示", "请先选择一个任务")
            return
        
        for item in selected_items:
            values = self.task_tree.item(item, "values")
            if values and len(values) >= 5:
                task_type = values[0]
                data_type = values[1]
                address_str = values[2]
                
                # 转换地址字符串为整数
                try:
                    address = int(address_str)
                except ValueError:
                    messagebox.showerror("错误", f"无效的地址: {address_str}")
                    continue
                
                # 减去地址偏移量（因为显示时加上了offset）
                global offset
                actual_address = address - offset
                
                # 根据任务类型删除
                if self.data_simulation_manager:
                    if task_type == '自增':
                        self.data_simulation_manager.remove_increment_task(actual_address, data_type)
                    elif task_type == '位翻转':
                        self.data_simulation_manager.remove_bit_flip_task(actual_address, data_type)
                    elif task_type == '时间数据':
                        self.data_simulation_manager.remove_time_task(actual_address)
                    elif task_type == '日期数据':
                        self.data_simulation_manager.remove_date_task(actual_address)
        
        # 刷新任务列表
        self._refresh_task_list()
        
    def _remove_all_tasks(self):
        """删除所有任务"""
        if not self.data_simulation_manager:
            return
        
        # 确认对话框
        if not messagebox.askyesno("确认", "确定要删除所有任务吗？"):
            return
        
        # 移除所有任务
        with self.data_simulation_manager.lock:
            self.data_simulation_manager.increment_tasks.clear()
            self.data_simulation_manager.bit_flip_tasks.clear()
            self.data_simulation_manager.time_tasks.clear()
            self.data_simulation_manager.date_tasks.clear()
        
        self._log_message("已删除所有任务")
        
        # 刷新任务列表
        self._refresh_task_list()
        
    def _update_time_display(self):
        """更新时间显示"""
        now = datetime.now()
        self.current_time_var.set(f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}")
        # 每秒更新一次
        self.root.after(1000, self._update_time_display)
        
    def _update_date_display(self):
        """更新日期显示"""
        now = datetime.now()
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekday_names[now.isoweekday() - 1]
        self.current_date_var.set(f"{now.year%100:02d}-{now.month:02d}-{now.day:02d} ({weekday})")
        # 每分钟更新一次
        self.root.after(60000, self._update_date_display)
        
    def _start_server(self):
        """启动Modbus服务器"""
        try:
            # 调试信息：服务器启动开始
            print(f"[DEBUG] 开始启动服务器...")
            
            ip = self.ip_var.get().strip()
            port = int(self.port_var.get().strip())
            unit_id = int(self.unit_id_var.get().strip())
            
            # 调试信息：显示启动参数
            print(f"[DEBUG] 启动参数 - IP: {ip}, Port: {port}, Unit ID: {unit_id}")
            
            # 验证IP地址
            if not self._is_valid_ip(ip):
                messagebox.showerror("错误", "请输入有效的IPv4地址")
                print(f"[ERROR] 无效的IP地址: {ip}")
                return
            
            # 验证端口号
            if port < 1 or port > 65535:
                messagebox.showerror("错误", "端口号必须在1-65535之间")
                print(f"[ERROR] 无效的端口号: {port}")
                return
            
            # 验证Unit ID
            if unit_id < 0 or unit_id > 255:
                messagebox.showerror("错误", "Unit ID必须在0-255之间")
                print(f"[ERROR] 无效的Unit ID: {unit_id}")
                return
            
            # 获取启用的功能码
            enabled_functions = []
            for func_code, var in self.function_vars.items():
                if var.get():
                    enabled_functions.append(func_code)
            
            if not enabled_functions:
                messagebox.showerror("错误", "请至少启用一个功能码")
                return
            
            # 获取地址映射和字节序配置
            address_offset = self.address_offset_var.get()
            byte_order = self.byte_order_var.get()
            
            # 创建Modbus服务器实例
            self.modbus_server = ModbusSlaveServer(
                ip, port, unit_id, self.message_queue, enabled_functions,
                address_offset, byte_order
            )
            
            # 启动服务器
            success, message = self.modbus_server.start()
            
            if success:
                self.server_running = True
                self.start_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.NORMAL)
                
                # 调试信息：服务器启动成功
                print(f"[DEBUG] 服务器启动成功: {ip}:{port}, Unit ID: {unit_id}")
                
                # 显示地址映射和字节序信息
                address_mode = "标准Modbus (地址从0开始)" if address_offset == 0 else "Pro-face模式 (地址从1开始)"
                byte_order_mode = "大端模式 (高位低字)" if byte_order == "big" else "小端模式 (低位高字)"
                
                self.status_var.set(f"服务器运行中 - {ip}:{port} (Unit ID: {unit_id})")
                self._log_message(f"服务器已启动: {ip}:{port}, Unit ID: {unit_id}", "success")
                self._log_message(f"地址映射: {address_mode}", "success")
                self._log_message(f"字节序: {byte_order_mode}", "success")
                
                # 启动数据更新线程
                self._start_data_update()
                print(f"[DEBUG] 数据更新线程已启动")
                
            else:
                messagebox.showerror("启动失败", message)
                self._log_message(f"启动失败: {message}", "error")
                
        except ValueError as e:
            messagebox.showerror("输入错误", "请输入有效的数字")
        except Exception as e:
            messagebox.showerror("错误", f"启动服务器时发生错误: {str(e)}")
    
    def _add_increment_task(self):
        """添加自增任务"""
        if not self.modbus_server:
            messagebox.showerror("错误", "请先启动Modbus服务器")
            return
        
        try:
            # 获取参数
            global offset

            data_type = self.increment_data_type_var.get()
            address = int(self.increment_address_var.get()) - offset
            interval_ms = int(self.increment_interval_var.get())
            step = int(self.increment_step_var.get())
            min_value = int(self.increment_min_var.get())
            max_value = int(self.increment_max_var.get())
            
            # 验证参数
            if address < 0 or address > 65535:
                messagebox.showerror("错误", "地址必须在0-65535之间")
                return
            
            if interval_ms <= 0:
                messagebox.showerror("错误", "间隔时间必须大于0")
                return
            
            if min_value < 0 or max_value > 65535 or min_value > max_value:
                messagebox.showerror("错误", "最小值和最大值必须在0-65535之间，且最小值不能大于最大值")
                return
            
            # 创建数据模拟管理器（如果不存在）
            if not self.data_simulation_manager:
                self.data_simulation_manager = DataSimulationManager(self.modbus_server, self)
            
            # 添加任务
            self.data_simulation_manager.add_increment_task(
                address, data_type, interval_ms, step, min_value, max_value
            )
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
    
    def _remove_increment_task(self):
        """移除自增任务"""
        if not self.data_simulation_manager:
            messagebox.showerror("错误", "没有正在运行的数据模拟任务")
            return
        
        try:
            # 获取参数
            data_type = self.increment_data_type_var.get()
            address = int(self.increment_address_var.get())
            
            # 移除任务
            self.data_simulation_manager.remove_increment_task(address, data_type)
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的地址")
        except Exception as e:
            print(f"[ERROR] _set_coil_value: 设置线圈值时出错: {e}")
            import traceback
            traceback.print_exc()
            messagebox.showerror("错误", f"设置线圈值时发生错误: {str(e)}")
    
    def _add_bit_flip_task(self):
        """添加位翻转任务"""
        if not self.modbus_server:
            messagebox.showerror("错误", "请先启动Modbus服务器")
            return
        
        try:
            # 获取参数
            global offset
            data_type = self.bit_flip_data_type_var.get()
            address = int(self.bit_flip_address_var.get()) - offset
            interval_ms = int(self.bit_flip_interval_var.get())
            
            # 验证参数
            if address < 0 or address > 65535:
                messagebox.showerror("错误", "地址必须在0-65535之间")
                return
            
            if interval_ms <= 0:
                messagebox.showerror("错误", "间隔时间必须大于0")
                return
            
            # 创建数据模拟管理器（如果不存在）
            if not self.data_simulation_manager:
                self.data_simulation_manager = DataSimulationManager(self.modbus_server, self)
            
            # 添加任务
            self.data_simulation_manager.add_bit_flip_task(address, data_type, interval_ms)
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
    
    def _remove_bit_flip_task(self):
        """移除位翻转任务"""
        if not self.data_simulation_manager:
            messagebox.showerror("错误", "没有正在运行的数据模拟任务")
            return
        
        try:
            # 获取参数
            data_type = self.bit_flip_data_type_var.get()
            address = int(self.bit_flip_address_var.get())
            
            # 移除任务
            self.data_simulation_manager.remove_bit_flip_task(address, data_type)
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的地址")
    
    def _add_time_task(self):
        """添加时间数据任务"""
        if not self.modbus_server:
            messagebox.showerror("错误", "请先启动Modbus服务器")
            return
        
        try:
            # 获取参数
            global offset
            base_address = int(self.time_base_address_var.get()) - offset
            interval_ms = int(self.time_interval_var.get())
            
            # 验证参数
            if base_address < 0 or base_address > 65532:  # 需要3个连续地址
                messagebox.showerror("错误", "基础地址必须在0-65532之间（需要3个连续地址）")
                return
            
            if interval_ms <= 0:
                messagebox.showerror("错误", "间隔时间必须大于0")
                return
            
            # 创建数据模拟管理器（如果不存在）
            if not self.data_simulation_manager:
                self.data_simulation_manager = DataSimulationManager(self.modbus_server, self)
            
            # 添加任务
            self.data_simulation_manager.add_time_task(base_address, interval_ms)
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
    
    def _remove_time_task(self):
        """移除时间数据任务"""
        if not self.data_simulation_manager:
            messagebox.showerror("错误", "没有正在运行的数据模拟任务")
            return
        
        try:
            # 获取参数
            base_address = int(self.time_base_address_var.get())
            
            # 移除任务
            self.data_simulation_manager.remove_time_task(base_address)
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的基础地址")
    
    def _add_date_task(self):
        """添加日期数据任务"""
        if not self.modbus_server:
            messagebox.showerror("错误", "请先启动Modbus服务器")
            return
        
        try:
            # 获取参数
            global offset
            base_address = int(self.date_base_address_var.get()) - offset
            interval_ms = int(self.date_interval_var.get())
            
            # 验证参数
            if base_address < 0 or base_address > 65531:  # 需要4个连续地址
                messagebox.showerror("错误", "基础地址必须在0-65531之间（需要4个连续地址）")
                return
            
            if interval_ms <= 0:
                messagebox.showerror("错误", "间隔时间必须大于0")
                return
            
            # 创建数据模拟管理器（如果不存在）
            if not self.data_simulation_manager:
                self.data_simulation_manager = DataSimulationManager(self.modbus_server, self)
            
            # 添加任务
            self.data_simulation_manager.add_date_task(base_address, interval_ms)
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
    
    def _remove_date_task(self):
        """移除日期数据任务"""
        if not self.data_simulation_manager:
            messagebox.showerror("错误", "没有正在运行的数据模拟任务")
            return
        
        try:
            # 获取参数
            base_address = int(self.date_base_address_var.get())
            
            # 移除任务
            self.data_simulation_manager.remove_date_task(base_address)
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的基础地址")
    
    def _stop_server(self):
        """停止Modbus服务器"""
        try:
            if self.modbus_server and self.server_running:
                success, message = self.modbus_server.stop()
                
                if success:
                    self.server_running = False
                    self.start_button.config(state=tk.NORMAL)
                    self.stop_button.config(state=tk.DISABLED)
                    self.status_var.set("服务器已停止")
                    self._log_message("服务器已停止", "success")
                    
                    # 停止数据模拟管理器
                    if self.data_simulation_manager:
                        self.data_simulation_manager.stop()
                        self.data_simulation_manager = None
                        self._log_message("数据模拟管理器已停止", "success")
                else:
                    self._log_message(f"停止服务器时出错: {message}", "error")
        except Exception as e:
            print(f"[ERROR] _stop_server: 停止服务器时出错: {e}")
            import traceback
            traceback.print_exc()
            self._log_message(f"停止服务器时发生错误: {str(e)}", "error")
    
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
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_entry = f"[{timestamp}] {message}\n"
            
            # 限制日志长度，避免内存泄漏和GUI卡死
            max_lines = 110  # 最大保留110行日志
            current_lines = int(self.log_text.index('end-1c').split('.')[0])
            
            if current_lines >= max_lines:
                # 删除前10行，保持日志长度在合理范围内
                self.log_text.delete(1.0, "11.0")
            
            self.log_text.insert(tk.END, log_entry)
            if tag:
                # 为刚插入的文本添加标签
                start_index = self.log_text.index("end-2c linestart")
                end_index = self.log_text.index("end-1c")
                self.log_text.tag_add(tag, start_index, end_index)
            
            # 自动滚动到底部
            self.log_text.see(tk.END)
        except Exception as e:
            print(f"[ERROR] _log_message: 添加日志时出错: {e}")
    
    def _clear_log(self):
        """清空日志"""
        try:
            self.log_text.delete(1.0, tk.END)
        except Exception as e:
            print(f"[ERROR] _clear_log: 清空日志时出错: {e}")
    
    def _process_messages(self):
        """处理消息队列中的消息"""
        try:
            # 限制每次处理的消息数量，避免阻塞GUI
            max_messages = 10
            for _ in range(max_messages):
                try:
                    message = self.message_queue.get_nowait()
                    if message:
                        self._log_message(message)
                except queue.Empty:
                    break
                
        except Exception as e:
            print(f"[ERROR] 处理消息时出错: {e}")
        
        # 每500ms检查一次消息队列（进一步降低频率，减少GUI压力）
        self.root.after(500, self._process_messages)
    
    def _start_data_update(self):
        """启动数据更新线程"""
        try:
            if self.server_running:
                # 启动数据更新线程
                update_thread = threading.Thread(target=self._update_data_monitor, daemon=True)
                update_thread.start()
        except Exception as e:
            print(f"[ERROR] _start_data_update: 启动数据更新线程时出错: {e}")
    
    def _update_data_monitor(self):
        """更新数据监控显示"""
        # 记录上次更新时间，实现增量更新
        last_update_time = time.time()
        update_interval = 2  # 每2秒更新一次（降低频率）
        
        while self.server_running:
            try:
                current_time = time.time()
                
                if current_time - last_update_time >= update_interval:
                    try:
                        # 更新线圈状态显示
                        self._update_coils_display()
                        
                        # 更新离散输入显示
                        self._update_inputs_display()
                        
                        # 更新输入寄存器显示
                        self._update_input_registers_display()
                        
                        # 更新保持寄存器显示
                        self._update_holding_registers_display()
                        
                    except Exception as e:
                        print(f"[ERROR] 数据监控更新过程中出错: {e}")
                        import traceback
                        traceback.print_exc()
                    
                    last_update_time = current_time
                    print(f"[DEBUG] 数据监控更新完成")
                
                time.sleep(1.0)  # 增加休眠时间到1秒，进一步降低CPU占用
                
            except Exception as e:
                print(f"[ERROR] 更新数据监控时出错: {e}")
                time.sleep(10)  # 增加错误恢复休眠时间
    
    def _update_coils_display(self):
        """更新线圈状态显示"""
        if not self.modbus_server:
            return
        
        # 使用缓存来快速查找Treeview项
        if not hasattr(self, '_coils_item_cache'):
            self._coils_item_cache = {}
            # 初始化缓存
            for item in self.coils_tree.get_children():
                values = self.coils_tree.item(item, "values")
                if values and len(values) >= 1:
                    address = int(values[0])
                    self._coils_item_cache[address] = item
        
        # 添加数据变化检测缓存
        if not hasattr(self, '_coils_value_cache'):
            self._coils_value_cache = {}
        
        # 更新前50个线圈状态
        for i in range(50):
            try:
                display_address = self._get_display_address(i)
                coil_value = self.modbus_server.coils[i]
                
                status = "ON" if coil_value == 1 else "OFF"
                value = "1" if coil_value == 1 else "0"
                
                # 检查数据是否变化
                cache_key = display_address
                if cache_key in self._coils_value_cache:
                    cached_status, cached_value = self._coils_value_cache[cache_key]
                    if cached_status == status and cached_value == value:
                        continue  # 数据未变化，跳过更新
                
                # 更新缓存
                self._coils_value_cache[cache_key] = (status, value)
                
                # 检查是否需要更新Treeview
                if display_address in self._coils_item_cache:
                    item = self._coils_item_cache[display_address]
                    self.coils_tree.item(item, values=(display_address, status, value))
                else:
                    # 添加新项并更新缓存
                    item = self.coils_tree.insert("", "end", values=(display_address, status, value))
                    self._coils_item_cache[display_address] = item
                    
            except Exception as e:
                print(f"[ERROR] _update_coils_display: 更新地址{i}时出错: {e}")
                import traceback
                traceback.print_exc()
                continue
    
    def _update_inputs_display(self):
        """更新离散输入显示"""
        if not self.modbus_server:
            return
        
        # 使用缓存来快速查找Treeview项
        if not hasattr(self, '_inputs_item_cache'):
            self._inputs_item_cache = {}
            # 初始化缓存
            for item in self.inputs_tree.get_children():
                values = self.inputs_tree.item(item, "values")
                if values and len(values) >= 1:
                    address = int(values[0])
                    self._inputs_item_cache[address] = item
        
        # 添加数据变化检测缓存
        if not hasattr(self, '_inputs_value_cache'):
            self._inputs_value_cache = {}
        
        # 更新前50个离散输入状态
        for i in range(50):
            try:
                display_address = self._get_display_address(i)
                input_value = self.modbus_server.discrete_inputs[i]
                status = "ON" if input_value == 1 else "OFF"
                
                # 检查数据是否变化
                cache_key = display_address
                if cache_key in self._inputs_value_cache:
                    cached_status = self._inputs_value_cache[cache_key]
                    if cached_status == status:
                        continue  # 数据未变化，跳过更新
                
                # 更新缓存
                self._inputs_value_cache[cache_key] = status
                
                # 检查是否需要更新Treeview
                if display_address in self._inputs_item_cache:
                    item = self._inputs_item_cache[display_address]
                    self.inputs_tree.item(item, values=(display_address, status))
                else:
                    # 添加新项并更新缓存
                    item = self.inputs_tree.insert("", "end", values=(display_address, status))
                    self._inputs_item_cache[display_address] = item
                    
            except Exception as e:
                print(f"[ERROR] _update_inputs_display: 更新地址{i}时出错: {e}")
                continue
    
    def _update_input_registers_display(self):
        """更新输入寄存器显示"""
        try:
            if not self.modbus_server:
                return
            
            # 使用缓存来快速查找Treeview项
            if not hasattr(self, '_input_regs_item_cache'):
                self._input_regs_item_cache = {}
                # 初始化缓存
                for item in self.input_regs_tree.get_children():
                    values = self.input_regs_tree.item(item, "values")
                    if values and len(values) >= 1:
                        address = int(values[0])
                        self._input_regs_item_cache[address] = item
            
            # 添加数据变化检测缓存
            if not hasattr(self, '_input_regs_value_cache'):
                self._input_regs_value_cache = {}
            
            # 更新前50个输入寄存器值
            for i in range(50):
                try:
                    display_address = self._get_display_address(i)
                    value = self.modbus_server.input_registers[i]
                    
                    # 检查数据是否变化
                    cache_key = display_address
                    if cache_key in self._input_regs_value_cache:
                        cached_value = self._input_regs_value_cache[cache_key]
                        if cached_value == value:
                            continue  # 数据未变化，跳过更新
                    
                    # 更新缓存
                    self._input_regs_value_cache[cache_key] = value
                    
                    # 检查是否需要更新Treeview
                    if display_address in self._input_regs_item_cache:
                        item = self._input_regs_item_cache[display_address]
                        self.input_regs_tree.item(item, values=(display_address, value))
                    else:
                        # 添加新项并更新缓存
                        item = self.input_regs_tree.insert("", "end", values=(display_address, value))
                        self._input_regs_item_cache[display_address] = item
                except Exception as e:
                    print(f"[ERROR] _update_input_registers_display: 更新地址{i}时出错: {e}")
        except Exception as e:
            print(f"[ERROR] _update_input_registers_display: 更新输入寄存器显示时出错: {e}")
    
    def _update_holding_registers_display(self):
        """更新保持寄存器显示"""
        try:
            if not self.modbus_server:
                return
            
            # 使用缓存来快速查找Treeview项
            if not hasattr(self, '_holding_regs_item_cache'):
                self._holding_regs_item_cache = {}
                # 初始化缓存
                for item in self.holding_regs_tree.get_children():
                    values = self.holding_regs_tree.item(item, "values")
                    if values and len(values) >= 1:
                        address = int(values[0])
                        self._holding_regs_item_cache[address] = item
            
            # 添加数据变化检测缓存
            if not hasattr(self, '_holding_regs_value_cache'):
                self._holding_regs_value_cache = {}
            
            # 更新前50个保持寄存器值
            for i in range(50):
                try:
                    display_address = self._get_display_address(i)
                    value = self.modbus_server.holding_registers[i]
                    
                    # 检查数据是否变化
                    cache_key = display_address
                    if cache_key in self._holding_regs_value_cache:
                        cached_value = self._holding_regs_value_cache[cache_key]
                        if cached_value == value:
                            continue  # 数据未变化，跳过更新
                    
                    # 更新缓存
                    self._holding_regs_value_cache[cache_key] = value
                    
                    # 检查是否需要更新Treeview
                    if display_address in self._holding_regs_item_cache:
                        item = self._holding_regs_item_cache[display_address]
                        self.holding_regs_tree.item(item, values=(display_address, value))
                    else:
                        # 添加新项并更新缓存
                        item = self.holding_regs_tree.insert("", "end", values=(display_address, value))
                        self._holding_regs_item_cache[display_address] = item
                except Exception as e:
                    print(f"[ERROR] _update_holding_registers_display: 更新地址{i}时出错: {e}")
        except Exception as e:
            print(f"[ERROR] _update_holding_registers_display: 更新保持寄存器显示时出错: {e}")
    
    def _safe_update_text(self, text_widget, content):
        """安全更新文本控件内容"""
        try:
            text_widget.delete(1.0, tk.END)
            text_widget.insert(1.0, content)
        except:
            pass
    
    def _set_coil_value(self):
        """设置线圈值"""
        if not self.modbus_server:
            messagebox.showerror("错误", "服务器未启动")
            return
        
        try:
            display_address = int(self.coil_address_var.get())
            value_str = self.coil_value_var.get()
            
            # 将显示地址转换为内部地址
            internal_address = self._get_internal_address(display_address)
            
            if internal_address < 0 or internal_address >= 65536:
                messagebox.showerror("错误", "地址必须在0-65535之间")
                return
            
            value = 1 if value_str == "ON" else 0
            
            # 设置线圈值
            self.modbus_server.coils[internal_address] = value
            
            # 更新显示
            self._update_coils_display()
            
            # 记录日志
            self._log_message(f"设置线圈地址 {display_address} 为 {value_str}")
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的地址")
    
    def _set_input_register_value(self):
        """设置输入寄存器值"""
        if not self.modbus_server:
            messagebox.showerror("错误", "服务器未启动")
            return
        
        try:
            display_address = int(self.input_reg_address_var.get())
            value = int(self.input_reg_value_var.get())
            
            # 将显示地址转换为内部地址
            internal_address = self._get_internal_address(display_address)
            
            if internal_address < 0 or internal_address >= 65536:
                messagebox.showerror("错误", "地址必须在0-65535之间")
                return
            
            if value < 0 or value > 65535:
                messagebox.showerror("错误", "值必须在0-65535之间")
                return
            
            # 设置输入寄存器值
            self.modbus_server.input_registers[internal_address] = value
            
            # 更新显示
            self._update_input_registers_display()
            
            # 记录日志
            self._log_message(f"设置输入寄存器地址 {display_address} 为 {value}")
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的地址和值")
        except Exception as e:
            print(f"[ERROR] _set_input_register_value: 设置输入寄存器值时出错: {e}")
            import traceback
            traceback.print_exc()
            messagebox.showerror("错误", f"设置输入寄存器值时发生错误: {str(e)}")
    
    def _on_treeview_double_click(self, event, data_type):
        """
        处理Treeview双击事件
        
        参数:
            event: 事件对象
            data_type: 数据类型 ('coil', 'discrete_input', 'input_register', 'holding_register')
        """
        try:
            # 获取点击的项
            item = self._get_treeview_by_type(data_type).identify_row(event.y)
            if not item:
                return
            
            # 获取列
            column = self._get_treeview_by_type(data_type).identify_column(event.x)
            if not column:
                return
            
            # 获取当前值
            values = self._get_treeview_by_type(data_type).item(item, "values")
            if not values:
                return
            
            # 获取显示地址并转换为内部地址
            display_address = int(values[0])
            internal_address = self._get_internal_address(display_address)
            
            # 根据数据类型和列确定编辑哪个值
            if data_type == "coil":
                if column == "#2":  # 状态列
                    current_value = values[1]  # "ON" 或 "OFF"
                    new_value = "OFF" if current_value == "ON" else "ON"
                    self._update_coil_value(internal_address, new_value)
                elif column == "#3":  # 值列
                    current_value = values[2]  # "1" 或 "0"
                    new_value = "0" if current_value == "1" else "1"
                    self._update_coil_value(internal_address, "ON" if new_value == "1" else "OFF")
            
            elif data_type == "discrete_input":
                if column == "#2":  # 状态列
                    current_value = values[1]  # "ON" 或 "OFF"
                    new_value = "OFF" if current_value == "ON" else "ON"
                    self._update_discrete_input_value(internal_address, new_value)
            
            elif data_type in ["input_register", "holding_register"]:
                if column == "#2":  # 值列
                    # 创建编辑对话框
                    self._create_edit_dialog(data_type, internal_address, values[1])
        except Exception as e:
            print(f"[ERROR] _on_treeview_double_click: 处理双击事件时出错: {e}")
            import traceback
            traceback.print_exc()
    
    def _get_treeview_by_type(self, data_type):
        """根据数据类型获取对应的Treeview控件"""
        if data_type == "coil":
            return self.coils_tree
        elif data_type == "discrete_input":
            return self.inputs_tree
        elif data_type == "input_register":
            return self.input_regs_tree
        elif data_type == "holding_register":
            return self.holding_regs_tree
        return None
    
    def _update_coil_value(self, internal_address, value_str):
        """更新线圈值"""
        if not self.modbus_server:
            return
        
        value = 1 if value_str == "ON" else 0
        self.modbus_server.coils[internal_address] = value
        self._update_coils_display()
        
        # 获取显示地址
        display_address = self._get_display_address(internal_address)
        self._log_message(f"设置线圈地址 {display_address} 为 {value_str}")
    
    def _update_discrete_input_value(self, internal_address, value_str):
        """更新离散输入值"""
        if not self.modbus_server:
            return
        
        value = 1 if value_str == "ON" else 0
        self.modbus_server.discrete_inputs[internal_address] = value
        self._update_inputs_display()
        
        # 获取显示地址
        display_address = self._get_display_address(internal_address)
        self._log_message(f"设置离散输入地址 {display_address} 为 {value_str}")
    
    def _create_edit_dialog(self, data_type, internal_address, current_value):
        """创建编辑对话框"""
        # 获取显示地址
        display_address = self._get_display_address(internal_address)
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"编辑{self._get_data_type_name(data_type)}地址 {display_address}")
        dialog.geometry("300x200")
        dialog.resizable(False, False)
        
        # 使对话框模态
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 居中显示
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # 内容框架
        content_frame = ttk.Frame(dialog, padding="20")
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 当前值标签
        ttk.Label(content_frame, text=f"当前值: {current_value}").pack(pady=(0, 10))
        
        # 新值输入框
        ttk.Label(content_frame, text="新值:").pack()
        new_value_var = tk.StringVar(value=str(current_value))
        entry = ttk.Entry(content_frame, textvariable=new_value_var, width=20)
        entry.pack(pady=(0, 20))
        entry.focus_set()
        entry.select_range(0, tk.END)
        
        # 按钮框架
        button_frame = ttk.Frame(content_frame)
        button_frame.pack()
        
        def on_ok():
            try:
                new_value = int(new_value_var.get())
                if data_type == "input_register":
                    self.modbus_server.input_registers[internal_address] = new_value
                    self._update_input_registers_display()
                    self._log_message(f"设置输入寄存器地址 {display_address} 为 {new_value}")
                elif data_type == "holding_register":
                    self.modbus_server.holding_registers[internal_address] = new_value
                    self._update_holding_registers_display()
                    self._log_message(f"设置保持寄存器地址 {display_address} 为 {new_value}")
                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "请输入有效的整数值", parent=dialog)
        
        def on_cancel():
            dialog.destroy()
        
        # 绑定回车和ESC键
        entry.bind("<Return>", lambda e: on_ok())
        entry.bind("<Escape>", lambda e: on_cancel())
        
        ttk.Button(button_frame, text="确定", command=on_ok, width=10).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="取消", command=on_cancel, width=10).pack(side=tk.LEFT)
    
    def _get_data_type_name(self, data_type):
        """获取数据类型的显示名称"""
        names = {
            "coil": "线圈",
            "discrete_input": "离散输入",
            "input_register": "输入寄存器",
            "holding_register": "保持寄存器"
        }
        return names.get(data_type, "数据")
    
    def _get_display_address(self, internal_address):
        """
        根据地址映射模式获取显示地址
        
        参数:
            internal_address: 内部地址（从0开始）
        
        返回:
            显示地址（根据地址映射模式调整）
        """
        try:
            # 使用缓存的地址偏移值，避免在非GUI线程中访问tkinter变量
            if not hasattr(self, '_cached_address_offset'):
                # 第一次调用时，从tkinter变量获取并缓存
                try:
                    self._cached_address_offset = self.address_offset_var.get()
                except Exception as e:
                    print(f"[WARNING] _get_display_address: 无法获取地址偏移，使用默认值1: {e}")
                    self._cached_address_offset = 1  # 默认值
            
            address_offset = self._cached_address_offset
            
            if address_offset == 0:
                # 标准Modbus模式：从0开始
                result = internal_address
            else:
                # Pro-face模式：从1开始
                result = internal_address + 1
            
            return result
            
        except Exception as e:
            print(f"[ERROR] _get_display_address: 出错: {e}")
            import traceback
            traceback.print_exc()
            return internal_address  # 出错时返回原地址
    def _update_address_offset_cache(self):
        """
        更新地址偏移缓存值
        
        当用户在GUI中更改地址偏移设置时调用此方法
        """
        try:
            if hasattr(self, 'address_offset_var'):
                self._cached_address_offset = self.address_offset_var.get()
        except Exception as e:
            print(f"[ERROR] _update_address_offset_cache: 更新缓存失败: {e}")
    
    def _get_internal_address(self, display_address):
        """
        根据显示地址获取内部地址
        
        参数:
            display_address: 显示地址（根据地址映射模式调整）
        
        返回:
            内部地址（从0开始）
        """
        try:
            # 使用缓存的地址偏移值
            if not hasattr(self, '_cached_address_offset'):
                # 如果缓存不存在，尝试获取
                try:
                    self._cached_address_offset = self.address_offset_var.get()
                except:
                    self._cached_address_offset = 1  # 默认值
            
            address_offset = self._cached_address_offset
            if address_offset == 0:
                # 标准Modbus模式：从0开始
                return display_address
            else:
                # Pro-face模式：从1开始
                if display_address > 0:
                    return display_address - 1
                else:
                    return 0
        except Exception as e:
            print(f"[ERROR] _get_internal_address: 出错: {e}")
            import traceback
            traceback.print_exc()
            return display_address  # 出错时返回原地址
    
    def _save_config(self):
        """保存当前配置到文件"""
        try:
            config = {
                # 服务器配置
                "ip_address": self.ip_var.get(),
                "port": self.port_var.get(),
                "unit_id": self.unit_id_var.get(),
                
                # 地址映射模式
                "address_offset": self.address_offset_var.get(),
                
                # 字节序
                "byte_order": self.byte_order_var.get(),
                
                # 功能码配置
                "enabled_functions": {}
            }
            
            # 保存功能码配置
            for func_code, var in self.function_vars.items():
                config["enabled_functions"][str(func_code)] = var.get()
            
            # 保存到JSON文件
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            print(f"配置已保存到: {self.config_file}")
            
        except Exception as e:
            print(f"保存配置时出错: {e}")
    
    def _on_closing(self):
        """窗口关闭事件处理"""
        # 保存当前配置
        self._save_config()
        
        # 停止数据模拟管理器（如果存在）
        if self.data_simulation_manager:
            self.data_simulation_manager.stop()
        
        # 停止服务器（如果正在运行）
        if self.server_running and self.modbus_server:
            self._stop_server()
        
        # 关闭窗口
        self.root.destroy()
    
    def _set_holding_register_value(self):
        """设置保持寄存器值"""
        if not self.modbus_server:
            messagebox.showerror("错误", "服务器未启动")
            return
        
        try:
            display_address = int(self.holding_reg_address_var.get())
            value = int(self.holding_reg_value_var.get())
            
            # 将显示地址转换为内部地址
            internal_address = self._get_internal_address(display_address)
            
            if internal_address < 0 or internal_address >= 65536:
                messagebox.showerror("错误", "地址必须在0-65535之间")
                return
            
            if value < 0 or value > 65535:
                messagebox.showerror("错误", "值必须在0-65535之间")
                return
            
            # 设置保持寄存器值
            self.modbus_server.holding_registers[internal_address] = value
            
            # 更新显示
            self._update_holding_registers_display()
            
            # 记录日志
            self._log_message(f"设置保持寄存器地址 {display_address} 为 {value}")
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的地址和值")
    
    def run(self):
        """运行GUI应用程序"""
        self.root.mainloop()


class DataSimulationManager:
    """数据模拟管理器类"""
    
    def __init__(self, modbus_server, gui_instance):
        """
        初始化数据模拟管理器
        
        参数:
            modbus_server: Modbus服务器实例
            gui_instance: GUI实例，用于日志记录
        """
        self.modbus_server = modbus_server
        self.gui = gui_instance
        
        # 自增任务列表
        self.increment_tasks = []
        
        # 位翻转任务列表
        self.bit_flip_tasks = []
        
        # 时间数据任务列表
        self.time_tasks = []
        
        # 日期数据任务列表
        self.date_tasks = []
        
        # 运行标志
        self.running = False
        
        # 线程锁
        self.lock = threading.Lock()
        
        # 启动模拟线程
        self.simulation_thread = threading.Thread(target=self._simulation_loop, daemon=True)
        self.simulation_thread.start()
    
    def add_increment_task(self, address, data_type, interval_ms=1000, step=1, min_value=0, max_value=65535):
        """
        添加自增任务
        
        参数:
            address: 地址
            data_type: 数据类型 ('coil', 'discrete_input', 'input_register', 'holding_register')
            interval_ms: 自增间隔（毫秒），默认1000ms（1秒）
            step: 每次自增值，默认1
            min_value: 最小值，默认0
            max_value: 最大值，默认65535
        """
        with self.lock:
            task = {
                'address': address,
                'data_type': data_type,
                'interval_ms': interval_ms,
                'step': step,
                'min_value': min_value,
                'max_value': max_value,
                'last_update': time.time() * 1000,  # 转换为毫秒
                'current_value': self._get_current_value(address, data_type)
            }
            self.increment_tasks.append(task)
            
            # 记录日志
            self.gui._log_message(f"添加自增任务: {data_type}地址{address}, 间隔{interval_ms}ms, 步长{step}")
    
    def add_bit_flip_task(self, address, data_type, interval_ms=1000):
        """
        添加位翻转任务
        
        参数:
            address: 地址
            data_type: 数据类型 ('coil', 'discrete_input')
            interval_ms: 翻转间隔（毫秒），默认1000ms（1秒）
        """
        with self.lock:
            task = {
                'address': address,
                'data_type': data_type,
                'interval_ms': interval_ms,
                'last_update': time.time() * 1000  # 转换为毫秒
            }
            self.bit_flip_tasks.append(task)
            
            # 记录日志
            self.gui._log_message(f"添加位翻转任务: {data_type}地址{address}, 间隔{interval_ms}ms")
    
    def add_time_task(self, base_address, interval_ms=1000):
        """
        添加时间数据任务
        
        参数:
            base_address: 基础地址，将占用3个连续地址：HH, MM, SS
            interval_ms: 更新时间间隔（毫秒），默认1000ms（1秒）
        """
        with self.lock:
            task = {
                'base_address': base_address,
                'interval_ms': interval_ms,
                'last_update': time.time() * 1000  # 转换为毫秒
            }
            self.time_tasks.append(task)
            
            # 记录日志
            self.gui._log_message(f"添加时间数据任务: 基础地址{base_address}, 间隔{interval_ms}ms")
    
    def add_date_task(self, base_address, interval_ms=60000):
        """
        添加日期数据任务
        
        参数:
            base_address: 基础地址，将占用4个连续地址：YY, MM, DD, Weekday
            interval_ms: 更新时间间隔（毫秒），默认60000ms（1分钟）
        """
        with self.lock:
            task = {
                'base_address': base_address,
                'interval_ms': interval_ms,
                'last_update': time.time() * 1000  # 转换为毫秒
            }
            self.date_tasks.append(task)
            
            # 记录日志
            self.gui._log_message(f"添加日期数据任务: 基础地址{base_address}, 间隔{interval_ms}ms")
    
    def _get_current_value(self, address, data_type):
        """获取当前值"""
        if data_type == 'coil':
            return 1 if self.modbus_server.coils[address] else 0
        elif data_type == 'discrete_input':
            return 1 if self.modbus_server.discrete_inputs[address] else 0
        elif data_type == 'input_register':
            return self.modbus_server.input_registers[address]
        elif data_type == 'holding_register':
            return self.modbus_server.holding_registers[address]
        return 0
    
    def _set_value(self, address, data_type, value):
        """设置值"""
        if data_type == 'coil':
            self.modbus_server.coils[address] = 1 if value else 0
            # 更新显示
            self.gui._update_coils_display()
        elif data_type == 'discrete_input':
            self.modbus_server.discrete_inputs[address] = 1 if value else 0
            # 更新显示
            self.gui._update_inputs_display()
        elif data_type == 'input_register':
            self.modbus_server.input_registers[address] = value
            # 更新显示
            self.gui._update_input_registers_display()
        elif data_type == 'holding_register':
            self.modbus_server.holding_registers[address] = value
            # 更新显示
            self.gui._update_holding_registers_display()
    
    def _update_time_data(self, base_address):
        """更新时间数据"""
        now = datetime.now()
        
        # 设置小时、分钟、秒
        self.modbus_server.holding_registers[base_address] = now.hour
        self.modbus_server.holding_registers[base_address + 1] = now.minute
        self.modbus_server.holding_registers[base_address + 2] = now.second
        
        # 更新显示
        self.gui._update_holding_registers_display()
    
    def _update_date_data(self, base_address):
        """更新日期数据"""
        now = datetime.now()
        
        # 设置年（后两位）、月、日、星期（1=星期一，7=星期日）
        self.modbus_server.holding_registers[base_address] = now.year % 100
        self.modbus_server.holding_registers[base_address + 1] = now.month
        self.modbus_server.holding_registers[base_address + 2] = now.day
        self.modbus_server.holding_registers[base_address + 3] = now.isoweekday()  # 1=星期一，7=星期日
        
        # 更新显示
        self.gui._update_holding_registers_display()
    
    def _simulation_loop(self):
        """模拟循环"""
        self.running = True
        
        # 动态休眠时间，根据任务数量调整
        base_sleep_time = 0.05  # 50ms基础休眠时间
        
        while self.running:
            try:
                current_time_ms = time.time() * 1000
                has_tasks = False
                
                with self.lock:
                    # 检查是否有任务需要处理
                    has_tasks = (len(self.increment_tasks) > 0 or 
                               len(self.bit_flip_tasks) > 0 or 
                               len(self.time_tasks) > 0 or 
                               len(self.date_tasks) > 0)
                
                if has_tasks:
                    # 处理自增任务
                    for task in self.increment_tasks[:]:
                        if current_time_ms - task['last_update'] >= task['interval_ms']:
                            # 执行自增
                            new_value = task['current_value'] + task['step']
                            
                            # 检查边界
                            if new_value > task['max_value']:
                                new_value = task['min_value']
                            elif new_value < task['min_value']:
                                new_value = task['max_value']
                            
                            # 设置新值
                            self._set_value(task['address'], task['data_type'], new_value)
                            
                            # 更新任务状态
                            task['current_value'] = new_value
                            task['last_update'] = current_time_ms
                    
                    # 处理位翻转任务
                    for task in self.bit_flip_tasks[:]:
                        if current_time_ms - task['last_update'] >= task['interval_ms']:
                            # 执行位翻转
                            current_value = self._get_current_value(task['address'], task['data_type'])
                            new_value = 0 if current_value else 1
                            
                            # 设置新值
                            self._set_value(task['address'], task['data_type'], new_value)
                            
                            # 更新任务状态
                            task['last_update'] = current_time_ms
                    
                    # 处理时间数据任务
                    for task in self.time_tasks[:]:
                        if current_time_ms - task['last_update'] >= task['interval_ms']:
                            # 更新时间数据
                            self._update_time_data(task['base_address'])
                            
                            # 更新任务状态
                            task['last_update'] = current_time_ms
                    
                    # 处理日期数据任务
                    for task in self.date_tasks[:]:
                        if current_time_ms - task['last_update'] >= task['interval_ms']:
                            # 更新日期数据
                            self._update_date_data(task['base_address'])
                            
                            # 更新任务状态
                            task['last_update'] = current_time_ms
            
                # 动态调整休眠时间
                if has_tasks:
                    # 有任务时使用较短的休眠时间
                    time.sleep(0.05)  # 50ms（从20ms增加到50ms，减少CPU占用）
                else:
                    # 没有任务时使用较长的休眠时间
                    time.sleep(0.2)  # 200ms（从100ms增加到200ms，进一步减少CPU占用）
                    
            except Exception as e:
                print(f"[ERROR] _simulation_loop: 模拟循环出错: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.5)  # 出错时休眠更长时间
    
    def remove_increment_task(self, address, data_type):
        """移除自增任务"""
        with self.lock:
            self.increment_tasks = [t for t in self.increment_tasks 
                                   if not (t['address'] == address and t['data_type'] == data_type)]
            self.gui._log_message(f"移除自增任务: {data_type}地址{address}")
    
    def remove_bit_flip_task(self, address, data_type):
        """移除位翻转任务"""
        with self.lock:
            self.bit_flip_tasks = [t for t in self.bit_flip_tasks 
                                  if not (t['address'] == address and t['data_type'] == data_type)]
            self.gui._log_message(f"移除位翻转任务: {data_type}地址{address}")
    
    def remove_time_task(self, base_address):
        """移除时间数据任务"""
        with self.lock:
            self.time_tasks = [t for t in self.time_tasks if t['base_address'] != base_address]
            self.gui._log_message(f"移除时间数据任务: 基础地址{base_address}")
    
    def remove_date_task(self, base_address):
        """移除日期数据任务"""
        with self.lock:
            self.date_tasks = [t for t in self.date_tasks if t['base_address'] != base_address]
            self.gui._log_message(f"移除日期数据任务: 基础地址{base_address}")
    
    def stop(self):
        """停止模拟管理器"""
        self.running = False
        if self.simulation_thread.is_alive():
            self.simulation_thread.join(timeout=1)
    
    def get_all_tasks(self):
        """获取所有任务列表"""
        tasks = []
        with self.lock:
            # 自增任务
            for task in self.increment_tasks:
                tasks.append({
                    'type': '自增',
                    'data_type': task['data_type'],
                    'address': task['address'],
                    'interval': task.get('interval_ms', 1000),
                    'step': task.get('step', 1),
                    'min': task.get('min_value', 0),
                    'max': task.get('max_value', 65535),
                    'current': task.get('current_value', 0)
                })
            
            # 位翻转任务
            for task in self.bit_flip_tasks:
                tasks.append({
                    'type': '位翻转',
                    'data_type': task['data_type'],
                    'address': task['address'],
                    'interval': task.get('interval_ms', 1000)
                })
            
            # 时间数据任务
            for task in self.time_tasks:
                tasks.append({
                    'type': '时间数据',
                    'base_address': task['base_address'],
                    'interval': task.get('interval_ms', 1000)
                })
            
            # 日期数据任务
            for task in self.date_tasks:
                tasks.append({
                    'type': '日期数据',
                    'base_address': task['base_address'],
                    'interval': task.get('interval_ms', 60000)
                })
        
        return tasks
    
    def remove_task_by_index(self, task_type, index):
        """根据索引移除任务"""
        with self.lock:
            if task_type == '自增':
                if 0 <= index < len(self.increment_tasks):
                    task = self.increment_tasks.pop(index)
                    self.gui._log_message(f"移除自增任务: {task['data_type']}地址{task['address']}")
                    return True
            
            elif task_type == '位翻转':
                if 0 <= index < len(self.bit_flip_tasks):
                    task = self.bit_flip_tasks.pop(index)
                    self.gui._log_message(f"移除位翻转任务: {task['data_type']}地址{task['address']}")
                    return True
            
            elif task_type == '时间数据':
                if 0 <= index < len(self.time_tasks):
                    task = self.time_tasks.pop(index)
                    self.gui._log_message(f"移除时间数据任务: 基础地址{task['base_address']}")
                    return True
            
            elif task_type == '日期数据':
                if 0 <= index < len(self.date_tasks):
                    task = self.date_tasks.pop(index)
                    self.gui._log_message(f"移除日期数据任务: 基础地址{task['base_address']}")
                    return True
        
        return False


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