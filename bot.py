# -*- coding: utf-8 -*-

# ***********************************************************************
# Modified based on the KouriChat project
# Copyright of this modification: Copyright (C) 2025, iwyxdxl
# Licensed under GNU GPL-3.0 or higher, see the LICENSE file for details.
# 
# This file is part of WeChatBot, which includes modifications to the KouriChat project.
# The original KouriChat project's copyright and license information are preserved in the LICENSE file.
# For any further details regarding the license, please refer to the LICENSE file.
# 
# ===============================================================================
# 双记忆功能版本 - Dual Memory System
# ===============================================================================
# 
# 本版本整合了言言双记忆版的核心功能，实现了双重记忆系统：
# 
# 1. 【日记系统】- 存储在 prompts/*.md 文件中
#    - 记录每日与用户的重要互动和事件
#    - 以时间线形式追加到角色设定文件末尾
#    - 提供温馨、自然的记忆回顾体验
# 
# 2. 【核心记忆】- 存储在 Memory_Summaries/*.json 文件中  
#    - 提取和保存用户的关键信息、偏好、约定等
#    - 用于AI对话中的上下文理解和个性化回复
#    - 支持迭代更新和智能压缩
# 
# 主要特性：
# - get_user_prompt(): 同时加载角色设定+日记+核心记忆
# - summarize_and_save(): 双输出格式，同时生成日记摘要和核心记忆
# - append_to_memory_section(): 将日记内容追加到.md文件
# - 兼容原有的单一记忆格式，平滑迁移
# 
# ***********************************************************************

import sys
import base64
import requests
import logging
import string
import command_handler # 程序指令中心
from datetime import datetime
import datetime as dt
import threading
import uiautomation as auto
import time
from wxautox_wechatbot import WeChat
import uiautomation as uia
from openai import OpenAI, APITimeoutError
import random
from typing import Optional
import pyautogui
import pyperclip
import shutil
import re
from regex_patterns import QINGLI_AI_BIAOQIAN_ZHUJIE
from config import *
import queue
import json
from threading import Timer
from bs4 import BeautifulSoup
EMOJI_SEND_INTERVAL = 1.0  # 发送表情包的延迟（秒）
TEXT_SEND_INTERVAL = 0.5   # 发送文本消息的延迟（秒）
from urllib.parse import urlparse
import os
os.environ["PROJECT_NAME"] = 'iwyxdxl/WeChatBot_WXAUTO_SE'
from wxautox_wechatbot.param import WxParam
WxParam.ENABLE_FILE_LOGGER = False
WxParam.FORCE_MESSAGE_XBIAS = True
from gacha_system import perform_ten_pull

# 生成用户昵称列表和prompt映射字典
user_names = [entry[0] for entry in LISTEN_LIST]
prompt_mapping = {entry[0]: entry[1] for entry in LISTEN_LIST}

# 群聊信息缓存
group_chat_cache = {}  # {user_name: is_group_chat}
group_cache_lock = threading.Lock()

# 持续监听消息，并且收到消息后回复
wait = 1  # 设置1秒查看一次是否有新消息

# 获取程序根目录
root_dir = os.path.dirname(os.path.abspath(__file__))

# 用户消息队列和聊天上下文管理
user_queues = {}  # {user_id: {'messages': [], 'last_message_time': 时间戳, ...}}
queue_lock = threading.Lock()  # 队列访问锁
chat_contexts = {}  # {user_id: [{'role': 'user', 'content': '...'}, ...]}
CHAT_CONTEXTS_FILE = "chat_contexts.json" # 存储聊天上下文的文件名
USER_TIMERS_FILE = "user_timers.json"  # 存储用户计时器状态的文件名
MEMORY_SUMMARIES_DIR = "Memory_Summaries" # 存储用户记忆总结的目录


# --- 新增: 用于跟踪正在进行的记忆总结任务，防止对同一用户重复启动 ---
active_summary_tasks = set()
active_summary_tasks_lock = threading.Lock()


# --- 动态设置相关全局变量 ---（新增部分）                            
SETTINGS_FILE = "settings.json"  # 存储动态设置的配置文件名
EMOJI_TAG_MAX_LENGTH = 10  # 默认值，如果配置文件不存在或读取失败时使用
settings_lock = threading.Lock() # 用于文件读写的锁

def load_settings():
    """从 settings.json 加载设置到全局变量"""
    global EMOJI_TAG_MAX_LENGTH
    with settings_lock:
        try:
            # 确保我们使用的是根目录下的文件
            settings_path = os.path.join(root_dir, SETTINGS_FILE)
            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    # 从文件中读取配置，如果键不存在或类型错误，则使用默认值
                    EMOJI_TAG_MAX_LENGTH = int(settings.get('emoji_tag_max_length', 10))
                    logger.info(f"成功从 {SETTINGS_FILE} 加载设置，表情包字符限制为: {EMOJI_TAG_MAX_LENGTH}")
            else:
                # 如果文件不存在，仅记录日志，不创建文件，等待 config_editor 创建
                logger.info(f"{SETTINGS_FILE} 未找到，将使用默认表情包字符限制: {EMOJI_TAG_MAX_LENGTH}")
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.error(f"加载 {SETTINGS_FILE} 失败，将使用默认表情包字符限制。错误: {e}")
            EMOJI_TAG_MAX_LENGTH = 10 # 出错时回退到默认值
        except Exception as e:
            logger.error(f"加载配置文件时发生未知错误: {e}", exc_info=True)
            EMOJI_TAG_MAX_LENGTH = 10 # 出错时回退到默认值
                       ## （新增部分结束）

# 心跳相关全局变量
HEARTBEAT_INTERVAL = 5  # 秒
FLASK_SERVER_URL_BASE = f'http://localhost:{PORT}' # 使用从config导入的PORT

# --- REMINDER RELATED GLOBALS ---
RECURRING_REMINDERS_FILE = "recurring_reminders.json" # 存储重复和长期一次性提醒的文件名
# recurring_reminders 结构:
# [{'reminder_type': 'recurring', 'user_id': 'xxx', 'time_str': 'HH:MM', 'content': '...'},
#  {'reminder_type': 'one-off', 'user_id': 'xxx', 'target_datetime_str': 'YYYY-MM-DD HH:MM', 'content': '...'}]
recurring_reminders = [] # 内存中加载的提醒列表
recurring_reminder_lock = threading.RLock() # 锁，用于处理提醒文件和列表的读写

active_timers = {} # { (user_id, timer_id): Timer_object } (用于短期一次性提醒 < 10min)
timer_lock = threading.Lock()
next_timer_id = 0

class NoSelfLoggingFilter(logging.Filter):
    """一个日志过滤器，防止将发往日志API的请求本身以及导致循环的特定错误再次发送。"""
    def filter(self, record):
        msg = record.getMessage()
        # 过滤掉发往/api/log的请求日志，避免无限循环
        if '/api/log' in msg:
            return False
        # 过滤掉"Bad request syntax"错误，这是由HTTPS请求HTTP端口引起的，是噪音
        if 'Bad request syntax' in msg:
            return False
        return True

class AsyncHTTPHandler(logging.Handler):
    def __init__(self, url, retry_attempts=3, timeout=3, max_queue_size=1000, batch_size=20, batch_timeout=5):
        """
        初始化异步 HTTP 日志处理器。

        Args:
            url (str): 发送日志的目标 URL。
            retry_attempts (int): 发送失败时的重试次数。
            timeout (int): HTTP 请求的超时时间（秒）。
            max_queue_size (int): 内存中日志队列的最大容量。
                                  当队列满时，新的日志消息将被丢弃。
            batch_size (int): 批量处理的日志数量，达到此数量会触发发送。
            batch_timeout (int): 批处理超时时间(秒)，即使未达到batch_size，
                               经过此时间也会发送当前累积的日志。
        """
        super().__init__()
        self.url = url
        self.retry_attempts = retry_attempts
        self.timeout = timeout
        self.log_queue = queue.Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()
        self.dropped_logs_count = 0  # 添加一个计数器来跟踪被丢弃的日志数量
        self.batch_size = batch_size  # 批处理大小
        self.batch_timeout = batch_timeout  # 批处理超时时间
        
        # 新增: 断路器相关属性
        self.consecutive_failures = 0  # 跟踪连续失败次数
        self.circuit_breaker_open = False  # 断路器状态
        self.circuit_breaker_reset_time = None  # 断路器重置时间
        self.CIRCUIT_BREAKER_THRESHOLD = 5  # 触发断路器的连续失败次数
        self.CIRCUIT_BREAKER_RESET_TIMEOUT = 60  # 断路器重置时间（秒）
        
        # 新增: HTTP请求统计
        self.total_requests = 0
        self.failed_requests = 0
        self.last_success_time = time.time()
        
        # 后台线程用于处理日志队列
        self.worker = threading.Thread(target=self._process_queue, daemon=True)
        self.worker.start()

    def emit(self, record):
        """
        格式化日志记录并尝试将其放入队列。
        如果队列已满，则放弃该日志并记录警告。
        """
        try:
            log_entry = self.format(record)
            # 使用非阻塞方式放入队列
            self.log_queue.put(log_entry, block=False)
        except queue.Full:
            # 当队列满时，捕获 queue.Full 异常
            self.dropped_logs_count += 1
            # 避免在日志处理器内部再次调用 logger (可能导致死循环)
            # 每丢弃一定数量的日志后才记录一次，避免刷屏
            if self.dropped_logs_count % 100 == 1:  # 每丢弃100条日志记录一次（第1, 101, 201...条时记录）
                logging.warning(f"日志队列已满 (容量 {self.log_queue.maxsize})，已丢弃 {self.dropped_logs_count} 条日志。请检查日志接收端或网络。")
        except Exception:
            # 处理其他可能的格式化或放入队列前的错误
            self.handleError(record)

    def _should_attempt_send(self):
        """检查断路器是否开启，决定是否尝试发送"""
        if not self.circuit_breaker_open:
            return True
        
        now = time.time()
        if self.circuit_breaker_reset_time and now >= self.circuit_breaker_reset_time:
            # 重置断路器
            logging.info("日志发送断路器重置，恢复尝试发送")
            self.circuit_breaker_open = False
            self.consecutive_failures = 0
            return True
        
        return False

    def _process_queue(self):
        """
        后台工作线程，积累一定数量的日志后批量发送到目标 URL。
        """
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'WeChatBot/1.0'
        }
        batch = []  # 用于存储批处理日志
        last_batch_time = time.time()  # 上次发送批处理的时间
        
        while not self._stop_event.is_set():
            try:
                # 等待日志消息，设置超时以便能响应停止事件和批处理超时
                try:
                    # 使用较短的超时时间以便及时检查批处理超时
                    log_entry = self.log_queue.get(timeout=0.5)
                    batch.append(log_entry)
                    # 标记队列任务完成
                    self.log_queue.task_done()
                except queue.Empty:
                    # 队列为空时，检查是否应该发送当前批次（超时）
                    pass
                
                current_time = time.time()
                batch_timeout_reached = current_time - last_batch_time >= self.batch_timeout
                batch_size_reached = len(batch) >= self.batch_size
                
                # 如果达到批量大小或超时，且有日志要发送
                if (batch_size_reached or batch_timeout_reached) and batch:
                    # 新增: 检查断路器状态
                    if self._should_attempt_send():
                        success = self._send_batch(batch, headers)
                        if success:
                            self.consecutive_failures = 0  # 重置失败计数
                            self.last_success_time = time.time()
                        else:
                            self.consecutive_failures += 1
                            self.failed_requests += 1
                            if self.consecutive_failures >= self.CIRCUIT_BREAKER_THRESHOLD:
                                # 打开断路器
                                self.circuit_breaker_open = True
                                self.circuit_breaker_reset_time = time.time() + self.CIRCUIT_BREAKER_RESET_TIMEOUT
                                logging.warning(f"日志发送连续失败 {self.consecutive_failures} 次，断路器开启 {self.CIRCUIT_BREAKER_RESET_TIMEOUT} 秒")
                    else:
                        # 断路器开启，暂时不发送
                        reset_remaining = self.circuit_breaker_reset_time - time.time() if self.circuit_breaker_reset_time else 0
                        logging.debug(f"断路器开启状态，暂不发送 {len(batch)} 条日志，将在 {reset_remaining:.1f} 秒后尝试恢复")
                    
                    batch = []  # 无论是否发送成功，都清空批次
                    last_batch_time = current_time  # 重置批处理时间
            
            except Exception as e:
                # 出错时清空当前批次，避免卡住
                logging.error(f"日志处理队列异常: {str(e)}", exc_info=True)
                batch = []
                last_batch_time = time.time()
                time.sleep(1)  # 出错后暂停一下，避免CPU占用过高
        
        # 关闭前发送剩余的日志
        if batch:
            self._send_batch(batch, headers)

    def _send_batch(self, batch, headers):
        """
        发送一批日志记录，使用改进的重试策略
        
        返回:
            bool: 是否成功发送
        """
        data = {'logs': batch}
        
        # 改进1: 使用固定的最大重试延迟上限
        MAX_RETRY_DELAY = 2.0  # 最大重试延迟（秒）
        BASE_DELAY = 0.5       # 基础延迟（秒）
        
        self.total_requests += 1
        
        for attempt in range(self.retry_attempts):
            try:
                resp = requests.post(
                    self.url,
                    json=data,
                    headers=headers,
                    timeout=self.timeout
                )
                resp.raise_for_status()  # 检查 HTTP 错误状态码
                # 成功发送，记录日志数量
                if attempt > 0:
                    logging.info(f"在第 {attempt+1} 次尝试后成功发送 {len(batch)} 条日志")
                else:
                    logging.debug(f"成功批量发送 {len(batch)} 条日志")
                return True  # 成功返回
            except requests.exceptions.RequestException as e:
                # 改进2: 根据错误类型区分处理
                if isinstance(e, requests.exceptions.Timeout):
                    logging.warning(f"日志发送超时 (尝试 {attempt+1}/{self.retry_attempts})")
                    delay = min(BASE_DELAY, MAX_RETRY_DELAY)  # 对超时使用较短的固定延迟
                elif isinstance(e, requests.exceptions.ConnectionError):
                    logging.warning(f"日志发送连接错误 (尝试 {attempt+1}/{self.retry_attempts}): {e}")
                    delay = min(BASE_DELAY * (1.5 ** attempt), MAX_RETRY_DELAY)  # 有限的指数退避
                else:
                    logging.warning(f"日志发送失败 (尝试 {attempt+1}/{self.retry_attempts}): {e}")
                    delay = min(BASE_DELAY * (1.5 ** attempt), MAX_RETRY_DELAY)  # 有限的指数退避
                
                # 最后一次尝试不需要等待
                if attempt < self.retry_attempts - 1:
                    time.sleep(delay)
        
        # 改进3: 所有重试都失败，记录警告并返回失败状态
        downtime = time.time() - self.last_success_time
        logging.error(f"发送日志批次失败，已达到最大重试次数 ({self.retry_attempts})，丢弃 {len(batch)} 条日志 (连续失败: {self.consecutive_failures+1}, 持续时间: {downtime:.1f}秒)")
        return False  # 返回失败状态
    
    def get_stats(self):
        """返回日志处理器的统计信息"""
        return {
            'queue_size': self.log_queue.qsize(),
            'queue_capacity': self.log_queue.maxsize,
            'dropped_logs': self.dropped_logs_count,
            'total_requests': self.total_requests,
            'failed_requests': self.failed_requests,
            'circuit_breaker_status': 'open' if self.circuit_breaker_open else 'closed',
            'consecutive_failures': self.consecutive_failures
        }

    def close(self):
        """
        停止工作线程并等待队列处理完成（或超时）。
        """
        if not self.log_queue.empty():
            logging.info(f"关闭日志处理器，还有 {self.log_queue.qsize()} 条日志待处理")
            # 尝试等待队列处理完成。注意：原生queue.join()没有超时参数。
            # 这里的超时依赖于下方 worker.join() 的超时。
            self.log_queue.join()

        self._stop_event.set()
        self.worker.join(timeout=self.timeout * self.retry_attempts + 5)  # 等待一个合理的时间
        
        if self.worker.is_alive():
            logging.warning("日志处理线程未能正常退出")
        else:
            logging.info("日志处理线程已正常退出")
        
        super().close()

# 创建日志格式器
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# 初始化异步HTTP处理器
async_http_handler = AsyncHTTPHandler(
    url=f'http://localhost:{PORT}/api/log',
    batch_size=20,  # 一次发送20条日志
    batch_timeout=1  # 即使不满20条，最多等待1秒也发送
)
async_http_handler.setFormatter(formatter)
async_http_handler.addFilter(NoSelfLoggingFilter())

# 配置根Logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.handlers.clear()

# 添加异步HTTP日志处理器
logger.addHandler(async_http_handler)

# 同时可以保留控制台日志处理器
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# 获取微信窗口对象
try:
    wx = WeChat()
except:
    logger.error(f"\033[31m无法初始化微信接口，请确保您安装的是微信3.9版本，并且已经登录！\033[0m")
    logger.error("\033[31m微信3.9版本下载地址：https://dldir1v6.qq.com/weixin/Windows/WeChatSetup.exe \033[0m")
    exit(1)
# 获取登录用户的名字
ROBOT_WX_NAME = wx.nickname

# 存储用户的计时器和随机等待时间
user_timers = {}
user_wait_times = {}
emoji_timer = None
emoji_timer_lock = threading.Lock()
# 全局变量，控制消息发送状态
can_send_messages = True

# --- 定时重启相关全局变量 ---
program_start_time = 0.0 # 程序启动时间戳
last_received_message_timestamp = 0.0 # 最后一次活动（收到/处理消息）的时间戳

# 初始化OpenAI客户端
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL
)

#初始化在线 AI 客户端 (如果启用)
online_client: Optional[OpenAI] = None
if ENABLE_ONLINE_API:
    try:
        online_client = OpenAI(
            api_key=ONLINE_API_KEY,
            base_url=ONLINE_BASE_URL
        )
        logger.info("联网搜索 API 客户端已初始化。")
    except Exception as e:
        logger.error(f"初始化联网搜索 API 客户端失败: {e}", exc_info=True)
        ENABLE_ONLINE_API = False # 初始化失败则禁用该功能
        logger.warning("由于初始化失败，联网搜索功能已被禁用。")

# 初始化辅助模型客户端 (如果启用)
assistant_client: Optional[OpenAI] = None
if ENABLE_ASSISTANT_MODEL:
    try:
        assistant_client = OpenAI(
            api_key=ASSISTANT_API_KEY,
            base_url=ASSISTANT_BASE_URL
        )
        logger.info("辅助模型 API 客户端已初始化。")
    except Exception as e:
        logger.error(f"初始化辅助模型 API 客户端失败: {e}", exc_info=True)
        ENABLE_ASSISTANT_MODEL = False # 初始化失败则禁用该功能
        logger.warning("由于初始化失败，辅助模型功能已被禁用。")

def get_chat_type_info(user_name):
    """
    获取指定用户的聊天窗口类型信息（群聊或私聊）
    
    Args:
        user_name (str): 用户昵称
        
    Returns:
        bool: True表示群聊，False表示私聊，None表示未找到或出错
    """
    try:
        # 获取所有聊天窗口
        chats = wx.GetAllSubWindow()
        for chat in chats:
            chat_info = chat.ChatInfo()
            if chat_info.get('chat_name') == user_name:
                chat_type = chat_info.get('chat_type')
                is_group = (chat_type == 'group')
                logger.info(f"检测到用户 '{user_name}' 的聊天类型: {chat_type} ({'群聊' if is_group else '私聊'})")
                return is_group
        
        logger.warning(f"未找到用户 '{user_name}' 的聊天窗口信息")
        return None
        
    except Exception as e:
        logger.error(f"获取用户 '{user_name}' 聊天类型时出错: {e}")
        return None

def update_group_chat_cache():
    """
    更新群聊缓存信息
    """
    global group_chat_cache
    
    try:
        with group_cache_lock:
            logger.info("开始更新群聊类型缓存...")
            for user_name in user_names:
                chat_type_result = get_chat_type_info(user_name)
                if chat_type_result is not None:
                    group_chat_cache[user_name] = chat_type_result
                    logger.info(f"缓存用户 '{user_name}': {'群聊' if chat_type_result else '私聊'}")
                else:
                    logger.warning(f"无法确定用户 '{user_name}' 的聊天类型，将默认处理为私聊")
                    group_chat_cache[user_name] = False
            
            logger.info(f"群聊类型缓存更新完成，共缓存 {len(group_chat_cache)} 个用户信息")
            
    except Exception as e:
        logger.error(f"更新群聊缓存时出错: {e}")

def is_user_group_chat(user_name):
    """
    检查指定用户是否为群聊
    
    Args:
        user_name (str): 用户昵称
        
    Returns:
        bool: True表示群聊，False表示私聊
    """
    with group_cache_lock:
        # 如果缓存中没有该用户信息，则实时获取
        if user_name not in group_chat_cache:
            chat_type_result = get_chat_type_info(user_name)
            if chat_type_result is not None:
                group_chat_cache[user_name] = chat_type_result
            else:
                # 如果无法获取，默认为私聊
                group_chat_cache[user_name] = False
        
        return group_chat_cache.get(user_name, False)

def parse_time(time_str):
    try:
        TimeResult = datetime.strptime(time_str, "%H:%M").time()
        return TimeResult
    except Exception as e:
        logger.error("\033[31m错误：主动消息安静时间设置有误！请填00:00-23:59 不要填24:00,并请注意中间的符号为英文冒号！\033[0m")

quiet_time_start = parse_time(QUIET_TIME_START)
quiet_time_end = parse_time(QUIET_TIME_END)

def check_user_timeouts():
    """
    检查用户是否超时未活动，并将主动消息加入队列以触发联网检查流程。
    """
    global last_received_message_timestamp # 引用全局变量
    if ENABLE_AUTO_MESSAGE:
        while True:
            current_epoch_time = time.time()

            for user in user_names:
                last_active = user_timers.get(user)
                wait_time = user_wait_times.get(user)

                if isinstance(last_active, (int, float)) and isinstance(wait_time, (int, float)):
                    if current_epoch_time - last_active >= wait_time and not is_quiet_time():
                        # 检查是否启用了忽略群聊主动消息的配置
                        if IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE and is_user_group_chat(user):
                            logger.info(f"用户 {user} 是群聊且配置为忽略群聊主动消息，跳过发送主动消息")
                            # 重置计时器以避免频繁检查
                            reset_user_timer(user)
                            continue
                        
                        # 构造主动消息（模拟用户消息格式）
                        formatted_now = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
                        auto_content = f"触发主动发消息：[{formatted_now}] {AUTO_MESSAGE}"
                        logger.info(f"为用户 {user} 生成主动消息并加入队列: {auto_content}")

                        # 将主动消息加入队列（模拟用户消息）
                        with queue_lock:
                            if user not in user_queues:
                                user_queues[user] = {
                                    'messages': [auto_content],
                                    'sender_name': user,
                                    'username': user,
                                    'last_message_time': time.time()
                                }
                            else:
                                user_queues[user]['messages'].append(auto_content)
                                user_queues[user]['last_message_time'] = time.time()

                        # 更新全局的最后消息活动时间戳，因为机器人主动发消息也算一种活动
                        last_received_message_timestamp = time.time()

                        # 重置计时器（不触发 on_user_message）
                        reset_user_timer(user)
            time.sleep(10)

def reset_user_timer(user):
    user_timers[user] = time.time()
    user_wait_times[user] = get_random_wait_time()

def get_random_wait_time():
    return random.uniform(MIN_COUNTDOWN_HOURS, MAX_COUNTDOWN_HOURS) * 3600  # 转换为秒

# 当接收到用户的新消息时，调用此函数
def on_user_message(user):
    if user not in user_names:
        user_names.append(user)
    reset_user_timer(user)

def get_user_prompt(user_id):
    """
    【日记功能版】获取用户的完整提示词，组合"基础设定"、"【核心记忆】"和"【备忘录】"。
    """
    # 1. 加载基础设定 (从 .md 文件，包含日记)
    prompt_file_name = prompt_mapping.get(user_id, user_id)
    prompt_path = os.path.join(root_dir, 'prompts', f'{prompt_file_name}.md')
    
    if not os.path.exists(prompt_path):
        logger.error(f"Prompt文件不存在: {prompt_path}")
        raise FileNotFoundError(f"Prompt文件 {prompt_file_name}.md 未找到于 prompts 目录")

    with open(prompt_path, 'r', encoding='utf-8') as file:
        prompt_content = file.read()

    # 2. 如果全局设置不允许上传记忆，则直接返回基础设定
    if not UPLOAD_MEMORY_TO_AI:
        return prompt_content

    # 3. 加载核心记忆 (从 .json 文件)
    core_memory_content = ""
    try:
        # 兼容新旧两种文件名格式
        user_memory_file_new = os.path.join(root_dir, MEMORY_SUMMARIES_DIR, f'{user_id}_{prompt_file_name}.json')
        user_memory_file_old = os.path.join(root_dir, MEMORY_SUMMARIES_DIR, f'{user_id}.json')
        
        memory_file_to_load = None
        if os.path.exists(user_memory_file_new):
            memory_file_to_load = user_memory_file_new
        elif os.path.exists(user_memory_file_old):
            memory_file_to_load = user_memory_file_old

        if memory_file_to_load:
            with open(memory_file_to_load, 'r', encoding='utf-8') as f:
                memory_data = json.load(f)
            
            if isinstance(memory_data, dict):
                core_memory_content = memory_data.get("content", "").strip()
            elif isinstance(memory_data, list):
                all_summaries = [item.get("summary", "") for item in memory_data if item.get("summary")]
                core_memory_content = "\n".join(all_summaries).strip()

    except Exception as e:
        logger.error(f"为用户 {user_id} 加载核心记忆 .json 文件失败: {e}")
        
    # 4. 组合最终的Prompt
    final_prompt = prompt_content
    
    if core_memory_content:
        final_prompt += f"\n\n## 【核心记忆】与【备忘录】\n以下是你对该用户的【核心记忆】和需要长期记住的【备忘录】，【核心记忆】和【备忘录】中的每一条记录，都等同于角色的核心记忆和行为准则。在生成任何回复之前，你必须**优先检索并严格遵守**所有【核心记忆】和【备忘录】中的内容。这些内容不是参考，而是必须执行的铁律。：\n{core_memory_content}"
        logger.info(f"成功为用户 {user_id} 注入【核心记忆】与【备忘录】。")
        
    return final_prompt

             
# 加载聊天上下文
def load_chat_contexts():
    """从文件加载聊天上下文。"""
    global chat_contexts # 声明我们要修改全局变量
    try:
        if os.path.exists(CHAT_CONTEXTS_FILE):
            with open(CHAT_CONTEXTS_FILE, 'r', encoding='utf-8') as f:
                loaded_contexts = json.load(f)
                if isinstance(loaded_contexts, dict):
                    chat_contexts = loaded_contexts
                    logger.info(f"成功从 {CHAT_CONTEXTS_FILE} 加载 {len(chat_contexts)} 个用户的聊天上下文。")
                else:
                    logger.warning(f"{CHAT_CONTEXTS_FILE} 文件内容格式不正确（非字典），将使用空上下文。")
                    chat_contexts = {} # 重置为空
        else:
            logger.info(f"{CHAT_CONTEXTS_FILE} 未找到，将使用空聊天上下文启动。")
            chat_contexts = {} # 初始化为空
    except json.JSONDecodeError:
        logger.error(f"解析 {CHAT_CONTEXTS_FILE} 失败，文件可能已损坏。将使用空上下文。")
        # 可以考虑在这里备份损坏的文件
        # shutil.copy(CHAT_CONTEXTS_FILE, CHAT_CONTEXTS_FILE + ".corrupted")
        chat_contexts = {} # 重置为空
    except Exception as e:
        logger.error(f"加载聊天上下文失败: {e}", exc_info=True)
        chat_contexts = {} # 出现其他错误也重置为空，保证程序能启动

# 保存聊天上下文
def save_chat_contexts():
    """将当前聊天上下文保存到文件。"""
    global chat_contexts
    temp_file_path = CHAT_CONTEXTS_FILE + ".tmp"
    try:
        # 创建要保存的上下文副本，以防在写入时被其他线程修改
        # 如果在 queue_lock 保护下调用，则直接使用全局 chat_contexts 即可
        contexts_to_save = dict(chat_contexts) # 创建浅拷贝

        with open(temp_file_path, 'w', encoding='utf-8') as f:
            json.dump(contexts_to_save, f, ensure_ascii=False, indent=4)
        shutil.move(temp_file_path, CHAT_CONTEXTS_FILE) # 原子替换
        logger.debug(f"聊天上下文已成功保存到 {CHAT_CONTEXTS_FILE}")
    except Exception as e:
        logger.error(f"保存聊天上下文到 {CHAT_CONTEXTS_FILE} 失败: {e}", exc_info=True)
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path) # 清理临时文件
            except OSError:
                pass # 忽略清理错误

def get_deepseek_response(message, user_id, store_context=True, is_summary=False):
    """
    从 DeepSeek API 获取响应，确保正确的上下文处理，并持久化上下文。

    参数:
        message (str): 用户的消息或系统提示词（用于工具调用）。
        user_id (str): 用户或系统组件的标识符。
        store_context (bool): 是否将此交互存储到聊天上下文中。
                              对于工具调用（如解析或总结），设置为 False。
    """
    try:
        # 每次调用都重新加载聊天上下文，以应对文件被外部修改的情况
        load_chat_contexts()
        
        logger.info(f"调用 Chat API - ID: {user_id}, 是否存储上下文: {store_context}, 消息: {message[:100]}...") # 日志记录消息片段

        messages_to_send = []
        context_limit = MAX_GROUPS * 2  # 最大消息总数（不包括系统消息）

        if store_context:
            # --- 2024-05-24: 分角色记忆 ---
            # 1. 获取用户当前的角色(prompt)
            prompt_name = prompt_mapping.get(user_id, user_id)
            
            # 2. 获取该用户的系统提示词
            try:
                user_prompt = get_user_prompt(user_id)
                messages_to_send.append({"role": "system", "content": user_prompt})
            except FileNotFoundError as e:
                logger.error(f"用户 {user_id} 的提示文件错误: {e}，使用默认提示。")
                messages_to_send.append({"role": "system", "content": "你是一个乐于助人的助手。"})

            # 3. 管理并检索聊天历史记录
            with queue_lock: # 确保对 chat_contexts 的访问是线程安全的
                # 确保用户条目存在且为字典格式，处理旧格式到新格式的迁移
                user_data = chat_contexts.get(user_id)
                # 2024-05-24: 修正迁移逻辑
                # Bot不应执行自动迁移，因为它无法确知旧列表格式上下文对应的原始Prompt。
                # 正确的迁移逻辑已移至config_editor.py的submit_config函数中，在用户明确切换角色时触发。
                # 如果在此处仍检测到列表格式，说明数据尚未迁移。为避免数据错乱，我们将为当前角色开启全新的对话历史。
                if not isinstance(user_data, dict):
                    if isinstance(user_data, list) and user_data:
                        logger.warning(f"用户 {user_id} 存在未迁移的旧格式上下文。机器人将为当前角色 '{prompt_name}' 开启新的对话历史。旧历史将在下次于UI中切换该用户角色时被正确迁移。")
                    # 初始化一个空的字典，为当前用户创建一个新的、符合新格式的上下文容器
                    chat_contexts[user_id] = {}
                
                # 确保当前角色的聊天记录列表存在
                if prompt_name not in chat_contexts[user_id]:
                    chat_contexts[user_id][prompt_name] = []

                # 在添加当前消息之前获取现有历史记录
                history = list(chat_contexts[user_id].get(prompt_name, []))

                # 如果历史记录超过限制，则进行裁剪
                if len(history) > context_limit:
                    history = history[-context_limit:]

                # 将历史消息添加到 API 请求列表中
                messages_to_send.extend(history)

                # 4. 将当前用户消息添加到 API 请求列表中
                messages_to_send.append({"role": "user", "content": message})

                # 5. 在准备 API 调用后更新持久上下文
                current_context = chat_contexts[user_id][prompt_name]
                current_context.append({"role": "user", "content": message})
                if len(current_context) > context_limit + 1:
                    chat_contexts[user_id][prompt_name] = current_context[-(context_limit + 1):]
                
                save_chat_contexts()

        else:
            # --- 处理工具调用（如提醒解析、总结） ---
            messages_to_send.append({"role": "user", "content": message})
            logger.info(f"工具调用 (store_context=False)，ID: {user_id}。仅发送提供的消息。")

        # --- 调用 API ---
        reply = call_chat_api_with_retry(messages_to_send, user_id, is_summary=is_summary)

        # --- 如果需要，存储助手回复到上下文中 ---
        if store_context:
            with queue_lock: # 再次获取锁来更新和保存
                prompt_name = prompt_mapping.get(user_id, user_id)
                
                # 再次确保数据结构完整性，以防万一
                if not isinstance(chat_contexts.get(user_id), dict):
                   chat_contexts[user_id] = {}
                if prompt_name not in chat_contexts[user_id]:
                   chat_contexts[user_id][prompt_name] = []

                current_context = chat_contexts[user_id][prompt_name]
                current_context.append({"role": "assistant", "content": reply})

                if len(current_context) > context_limit:
                    chat_contexts[user_id][prompt_name] = current_context[-context_limit:]
                
                # 保存上下文到文件
                save_chat_contexts() # 在助手回复添加后再次保存
        
        return reply

    except Exception as e:
        logger.error(f"Chat 调用失败 (ID: {user_id}): {str(e)}", exc_info=True)
        return "api报错了"


def strip_before_thought_tags(text):
    # 匹配并截取 </thought> 或 </think> 后面的内容
    match = re.search(r'(?:</thought>|</think>)([\s\S]*)', text)
    if match:
        return match.group(1)
    else:
        return text

def call_chat_api_with_retry(messages_to_send, user_id, max_retries=2, is_summary=False):
    """
    调用 Chat API 并在第一次失败或返回空结果时重试，包含200秒全局超时。

    参数:
        messages_to_send (list): 要发送给 API 的消息列表。
        user_id (str): 用户或系统组件的标识符。
        max_retries (int): 最大重试次数。

    返回:
        str: API 返回的文本回复。
    
    异常:
        TimeoutError: 如果总处理时间超过200秒。
    """
    attempt = 0
    
    # --- 全局超时控制 ---
    TOTAL_TIMEOUT = 240  # 秒
    start_time = time.time()

    while attempt <= max_retries:
        # --- 检查总时间是否已超时 ---
        elapsed_time = time.time() - start_time
        if elapsed_time >= TOTAL_TIMEOUT:
            logger.error(f"API调用总时间超过 {TOTAL_TIMEOUT} 秒，已超时。用户: {user_id}")
            # 抛出标准的TimeoutError，以便上层捕获
            raise TimeoutError(f"API call timed out after {TOTAL_TIMEOUT} seconds.")
        
        # 计算本次请求的剩余超时时间
        request_timeout = TOTAL_TIMEOUT - elapsed_time

        try:
            logger.debug(f"发送给 API 的消息 (ID: {user_id}): {messages_to_send}")

            response = client.chat.completions.create(
                model=MODEL,
                messages=messages_to_send,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKEN,
                stream=False,
                timeout=request_timeout  # 将计算出的超时时间传递给API调用
            )

            if response.choices:
                content = response.choices[0].message.content
                if content:
                    content = content.strip()
                    if content and "[image]" not in content:
                        filtered_content = strip_before_thought_tags(content)
                        if filtered_content:
                            return filtered_content

            logger.error(f"错误请求消息体: {MODEL}")
            logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))
            logger.error(f"\033[31m错误：API 返回了空的选择项或内容为空。模型名:{MODEL}\033[0m")
            logger.error(f"完整响应对象: {response}")

        except APITimeoutError:
            # 捕获单次请求超时，并记录日志。外层循环会控制总时间。
            logger.warning(f"单次 API 请求超时 (总已用时: {elapsed_time:.1f}s)。正在准备下一次尝试...")
            # 这里不需要做任何特殊操作，外层循环会继续或因总时间超时而终止

        except Exception as e:
            logger.error(f"错误请求消息体: {MODEL}")
            logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))
            error_info = str(e)
            logger.error(f"自动重试：第 {attempt + 1} 次调用 {MODEL}失败 (ID: {user_id}) 原因: {error_info}", exc_info=False)

            if "real name verification" in error_info:
                logger.error("\033[31m错误：API 服务商反馈请完成实名认证后再使用！\033[0m")
                break
            elif "rate limit" in error_info:
                logger.error("\033[31m错误：API 服务商反馈当前访问 API 服务频次达到上限，请稍后再试！\033[0m")
            elif "payment required" in error_info:
                logger.error("\033[31m错误：API 服务商反馈您正在使用付费模型，请先充值再使用或使用免费额度模型！\033[0m")
                break
            elif "user quota" in error_info or "is not enough" in error_info or "UnlimitedQuota" in error_info:
                logger.error("\033[31m错误：API 服务商反馈，你的余额不足，请先充值再使用! 如有余额，请检查令牌是否为无限额度。\033[0m")
                break
            elif "Api key is invalid" in error_info:
                logger.error("\033[31m错误：API 服务商反馈 API KEY 不可用，请检查配置选项！\033[0m")
            elif "service unavailable" in error_info:
                logger.error("\033[31m错误：API 服务商反馈服务器繁忙，请稍后再试！\033[0m")
            elif "sensitive words detected" in error_info:
                logger.error("\033[31m错误：Prompt或消息中含有敏感词，无法生成回复，请联系API服务商！\033[0m")
                if ENABLE_SENSITIVE_CONTENT_CLEARING:
                    logger.warning(f"已开启敏感词自动清除上下文功能，开始清除用户 {user_id} 的聊天上下文")
                    clear_chat_context(user_id)
                    if is_summary:
                        clear_memory_temp_files(user_id)
                break
            else:
                logger.error("\033[31m未知错误：" + error_info + "\033[0m")

        attempt += 1

    raise RuntimeError("api报错了")


def get_assistant_response(message, user_id, is_summary=False, system_prompt=None):
    """
    从辅助模型 API 获取响应，专用于判断型任务（表情、联网、提醒解析等）。
    不存储聊天上下文，仅用于辅助判断。

    参数:
        message (str): 要发送给辅助模型的消息。
        user_id (str): 用户或系统组件的标识符。
        is_summary (bool): 标记是否为总结任务，用于敏感词回退。
        system_prompt (str, optional): 一个可选的系统提示词。 Defaults to None.
    """
    if not assistant_client:
        logger.warning(f"辅助模型客户端未初始化，回退使用主模型。用户ID: {user_id}")
        # 回退到主模型
        # 注意：主模型调用不传递 system_prompt，因为它有自己的 get_user_prompt 逻辑
        return get_deepseek_response(message, user_id, store_context=False, is_summary=is_summary)
    
    try:
        if system_prompt:
             logger.info(f"调用辅助模型 API (带系统提示) - ID: {user_id}, 消息: {message[:100]}...")
        else:
             logger.info(f"调用辅助模型 API - ID: {user_id}, 消息: {message[:100]}...")
        
        messages_to_send = []
        if system_prompt:
            messages_to_send.append({"role": "system", "content": system_prompt})
        messages_to_send.append({"role": "user", "content": message})
        
        # 调用辅助模型 API
        reply = call_assistant_api_with_retry(messages_to_send, user_id, is_summary=is_summary)
        
        return reply

    except Exception as e:
        logger.error(f"辅助模型调用失败 (ID: {user_id}): {str(e)}", exc_info=True)
        logger.warning(f"辅助模型调用失败，回退使用主模型。用户ID: {user_id}")
        # 回退到主模型
        return get_deepseek_response(message, user_id, store_context=False, is_summary=is_summary)

def call_assistant_api_with_retry(messages_to_send, user_id, max_retries=2, is_summary=False):
    """
    调用辅助模型 API 并在第一次失败或返回空结果时重试。

    参数:
        messages_to_send (list): 要发送给辅助模型的消息列表。
        user_id (str): 用户或系统组件的标识符。
        max_retries (int): 最大重试次数。

    返回:
        str: 辅助模型返回的文本回复。
    """
    if not assistant_client:
        logger.error("辅助模型客户端在 call_assistant_api_with_retry 中未初始化，这是一个逻辑错误。")
        raise RuntimeError("抱歉，辅助模型现在有点忙，稍后再试吧。")
        
    attempt = 0
    while attempt <= max_retries:
        try:
            logger.debug(f"发送给辅助模型 API 的消息 (ID: {user_id}): {messages_to_send}")

            response = assistant_client.chat.completions.create(
                model=ASSISTANT_MODEL,
                messages=messages_to_send,
                temperature=ASSISTANT_TEMPERATURE,
                max_tokens=ASSISTANT_MAX_TOKEN,
                stream=False
            )

            if response.choices:
                content = response.choices[0].message.content
                if content:
                    content = content.strip()
                    if content and "[image]" not in content:
                        filtered_content = strip_before_thought_tags(content)
                        if filtered_content:
                            return filtered_content

            # 记录错误日志
            logger.error("辅助模型错误请求消息体:")
            logger.error(f"{ASSISTANT_MODEL}")
            logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))
            logger.error("辅助模型 API 返回了空的选择项或内容为空。")
            logger.error(f"完整响应对象: {response}")

        except Exception as e:
            logger.error("辅助模型错误请求消息体:")
            logger.error(f"{ASSISTANT_MODEL}")
            logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))
            error_info = str(e)
            logger.error(f"辅助模型自动重试：第 {attempt + 1} 次调用失败 (ID: {user_id}) 原因: {error_info}", exc_info=False)

            # 细化错误分类
            if "real name verification" in error_info:
                logger.error("\033[31m错误：API 服务商反馈请完成实名认证后再使用！\033[0m")
                break  # 终止循环，不再重试
            elif "rate limit" in error_info:
                logger.error("\033[31m错误：API 服务商反馈当前访问 API 服务频次达到上限，请稍后再试！\033[0m")
            elif "payment required" in error_info:
                logger.error("\033[31m错误：API 服务商反馈您正在使用付费模型，请先充值再使用或使用免费额度模型！\033[0m")
                break  # 终止循环，不再重试
            elif "user quota" in error_info or "is not enough" in error_info or "UnlimitedQuota" in error_info:
                logger.error("\033[31m错误：API 服务商反馈，你的余额不足，请先充值再使用! 如有余额，请检查令牌是否为无限额度。\033[0m")
                break  # 终止循环，不再重试
            elif "Api key is invalid" in error_info:
                logger.error("\033[31m错误：API 服务商反馈 API KEY 不可用，请检查配置选项！\033[0m")
            elif "service unavailable" in error_info:
                logger.error("\033[31m错误：API 服务商反馈服务器繁忙，请稍后再试！\033[0m")
            elif "sensitive words detected" in error_info:
                logger.error("\033[31m错误：提示词中含有敏感词，无法生成回复，请联系API服务商！\033[0m")
                if ENABLE_SENSITIVE_CONTENT_CLEARING:
                    logger.warning(f"已开启敏感词自动清除上下文功能，开始清除用户 {user_id} 的聊天上下文")
                    clear_chat_context(user_id)
                    if is_summary:
                        clear_memory_temp_files(user_id)  # 如果是总结任务，清除临时文件
                break  # 终止循环，不再重试
            else:
                logger.error("\033[31m未知错误：" + error_info + "\033[0m")

        attempt += 1

    raise RuntimeError("抱歉，辅助模型现在有点忙，稍后再试吧。")

def keep_alive():
    """
    定期检查监听列表，确保所有在 user_names 中的用户都被持续监听。
    如果发现有用户从监听列表中丢失，则会尝试重新添加。
    这是一个守护线程，用于增强程序的健壮性。
    """
    check_interval = 5  # 每30秒检查一次，避免过于频繁
    logger.info(f"窗口保活/监听守护线程已启动，每 {check_interval} 秒检查一次监听状态。")
    
    while True:
        try:
            # 获取当前所有正在监听的用户昵称集合
            current_listening_users = set(wx.listen.keys())
            
            # 获取应该被监听的用户昵称集合
            expected_users_to_listen = set(user_names)
            
            # 找出配置中应该监听但当前未在监听列表中的用户
            missing_users = expected_users_to_listen - current_listening_users
            
            if missing_users:
                logger.warning(f"检测到 {len(missing_users)} 个用户从监听列表中丢失: {', '.join(missing_users)}")
                for user in missing_users:
                    try:
                        logger.info(f"正在尝试重新添加用户 '{user}' 到监听列表...")
                        # 使用与程序启动时相同的回调函数 `message_listener` 重新添加监听
                        wx.AddListenChat(nickname=user, callback=message_listener)
                        logger.info(f"已成功将用户 '{user}' 重新添加回监听列表。")
                    except Exception as e:
                        logger.error(f"重新添加用户 '{user}' 到监听列表时失败: {e}", exc_info=True)
            else:
                # 使用 debug 级别，因为正常情况下这条日志会频繁出现，避免刷屏
                logger.debug(f"监听列表状态正常，所有 {len(expected_users_to_listen)} 个目标用户都在监听中。")

        except Exception as e:
            # 捕获在检查过程中可能发生的任何意外错误，使线程能继续运行
            logger.error(f"keep_alive 线程在检查监听列表时发生未知错误: {e}", exc_info=True)
            
        # 等待指定间隔后再进行下一次检查
        time.sleep(check_interval)
# ==================== 拍一拍功能区 开始 (最终验证版) ====================
# ==================== 拍一拍功能区 ("最终解释"键盘模拟版) ====================

import uiautomation as uia
import pyautogui
import time
import logging

# 假设 wx, logger 等对象已在您的代码上下文中定义并初始化

# 定义一个我们程序中标准的UI自动化操作超时时间（秒）
DEFAULT_UI_AUTOMATION_TIMEOUT = 2.0 

def pat_pat_user_threaded(chat_name: str, target_user_name: str):
    """
    在一个新的线程中执行拍一拍操作。
    【【【终极修正版 - 基于头像位置判断】】】
    核心洞察：依赖消息体位置不可靠，但头像位置是固定的。
    解决方案：
    - 直接遍历所有头像按钮（ButtonControl），检查按钮本身的位置。
    - 对方的头像一定在聊天区域的左半部分，机器人的头像一定在右半部分。
    - 从下往上找到第一个位于左半部分的头像，就是最终目标。
    
    Args:
        chat_name (str): 聊天窗口的名称 (好友昵称或群聊名称)。
        target_user_name (str): 要拍的人的昵称。
    """
    with ui_automation_lock:
        chat_window_control = None
    
    try:
        logger.info(f"[拍一拍任务] 子线程启动：准备在聊天 '{chat_name}' 中拍 '{target_user_name}'。")
        
        wx.ChatWith(chat_name)
        time.sleep(1.0) 

        uia.uiautomation.SetGlobalSearchTimeout(5.0)
        logger.info(f"[拍一拍任务] 正在寻找名为 '{chat_name}' 的独立聊天窗口...")
        chat_window_control = uia.WindowControl(Name=chat_name, searchDepth=1)
        
        if not chat_window_control.Exists():
            logger.error(f"[拍一拍任务] 失败：找不到名为 '{chat_name}' 的独立聊天窗口。")
            return

        logger.info(f"[拍一拍任务] 成功锁定目标操作窗口: '{chat_window_control.Name}'")
        chat_window_control.SetActive()
        chat_window_control.SetTopmost(True)
        time.sleep(0.3)
        
        message_list = chat_window_control.ListControl(Name='消息')
        if not message_list.Exists():
            logger.error(f"[拍一拍任务] 失败：在 '{chat_name}' 窗口中找不到 '消息' 列表控件。")
            return
        
        # 【【【终极修正点：改变定位策略】】】
        logger.info("[拍一拍任务] 采用终极定位策略：从下往上直接扫描头像位置...")
        all_items = message_list.GetChildren()
        target_avatar_button = None
        list_rect = message_list.BoundingRectangle
        
        # 定义屏幕中线，用于区分左右
        pane_center_x = list_rect.left + list_rect.width() / 2

        # 从下往上遍历所有消息项
        for item in reversed(all_items):
            # 尝试在每个消息项里直接寻找头像按钮
            avatar_button = item.ButtonControl()
            if avatar_button.Exists(0.01): # 用极短的超时时间快速查找
                button_rect = avatar_button.BoundingRectangle
                
                # 判断这个头像按钮是在左边还是右边
                if button_rect.xcenter() < pane_center_x:
                    # 如果在左边，这一定是对方的头像，就是我们的目标！
                    logger.info(f"[拍一拍任务] 成功锁定左侧头像按钮，目标消息: '{item.Name}'")
                    target_avatar_button = avatar_button
                    break # 找到了，立刻跳出循环
                else:
                    # 如果在右边，这是机器人自己的头像，跳过
                    logger.debug(f"[拍一拍任务] 跳过右侧头像，所属消息: '{item.Name}'")
                    continue
        
        if not target_avatar_button:
            logger.warning(f"[拍一拍任务] 失败：遍历完所有消息，未找到任何位于左侧的头像按钮。")
            return
            
        avatar_rect = target_avatar_button.BoundingRectangle
        click_x = avatar_rect.left + avatar_rect.width() // 2
        click_y = avatar_rect.top + avatar_rect.height() // 2
      
        logger.info(f"[拍一拍任务] 准备在精确计算的坐标 ({click_x}, {click_y}) 执行右键点击...")
        pyautogui.click(x=click_x, y=click_y, button='right', duration=0.25)
        logger.info("[拍一拍任务] 右键点击指令已发送。等待菜单弹出...")
        time.sleep(0.5)

        # --- A/B计划执行区 (这部分保持不变) ---
        action_completed = False

        # --- A计划: 智能识别 ---
        logger.info("[拍一拍任务 - A计划] 尝试通过控件属性智能识别'拍一拍'...")
        uia.uiautomation.SetGlobalSearchTimeout(1.0)
        menu = uia.MenuControl(ClassName='CMenuWnd')
        
        if menu.Exists(0.1):
            logger.info("[拍一拍任务 - A计划] 成功定位菜单容器，开始遍历子项...")
            pat_item = None
            all_menu_items = menu.GetChildren()
            for item in all_menu_items:
                if item.Name == '拍一拍':
                    pat_item = item
                    break
            
            if pat_item:
                logger.info("[拍一拍任务 - A计划] 成功！已通过名称识别到'拍一拍'项，准备点击。")
                pat_item.Click()
                action_completed = True
            else:
                found_names = [child.Name for child in all_menu_items]
                logger.warning(f"[拍一拍任务 - A计划] 失败：遍历完成，但未能找到名为'拍一拍'的项。探测到的名称列表: {found_names}。")
        else:
            logger.warning("[拍一拍任务 - A计划] 失败：未能定位到菜单容器。")

        # --- B计划: 键盘模拟 (如果A计划失败) ---
        if not action_completed:
            logger.info("[拍一拍任务 - B计划] A计划失败，启动终极后备方案：模拟键盘操作！")
            logger.info("[拍一拍任务 - B计划] 正在发送键盘指令: [Down] -> [Down] -> [Enter]")
            pyautogui.press('down')
            time.sleep(0.1)
            pyautogui.press('down')
            time.sleep(0.1)
            pyautogui.press('enter')
            action_completed = True
        
        if action_completed:
            logger.info(f"🎉🎉🎉 [拍一拍任务] 任务圆满成功！已对 '{target_user_name}' 执行了拍一拍。 🎉🎉🎉")
        else:
            logger.error("[拍一拍任务] 致命错误：A计划与B计划全部失败，无法执行操作。")


    except Exception as e:
        logger.error(f"[拍一拍任务] 执行时发生未知严重错误", exc_info=True)
        try:
            wx.SendMsg(msg="抱歉，执行拍一拍操作时内部发生严重错误，请检查后台日志。", who=chat_name)
        except Exception: pass
    finally:
        uia.uiautomation.SetGlobalSearchTimeout(DEFAULT_UI_AUTOMATION_TIMEOUT)
        if chat_window_control and chat_window_control.Exists(0.1):
            chat_window_control.SetTopmost(False)
        logger.debug(f"[拍一拍任务] 任务结束，资源已释放，全局超时已恢复为 {DEFAULT_UI_AUTOMATION_TIMEOUT} 秒。")

def pat_myself_threaded(chat_name: str):
    """
    【【【V2 - 修正版】】】
    在一个新的线程中执行“拍一拍自己”的操作。
    修正了之前使用左键双击的不可靠方法，改为和“拍一拍对方”逻辑一致的右键菜单操作。
    """
    chat_window_control = None
    try:
        logger.info(f"[拍自己任务] 子线程启动：准备在聊天 '{chat_name}' 中拍自己。")
        
        # 步骤 1: 激活聊天窗口
        wx.ChatWith(chat_name)
        time.sleep(1.0) 
        uia.uiautomation.SetGlobalSearchTimeout(5.0)
        chat_window_control = uia.WindowControl(Name=chat_name, searchDepth=1)
        
        if not chat_window_control.Exists():
            logger.error(f"[拍自己任务] 失败：找不到名为 '{chat_name}' 的聊天窗口。")
            return

        logger.info(f"[拍自己任务] 成功锁定操作窗口: '{chat_window_control.Name}'")
        chat_window_control.SetActive()
        chat_window_control.SetTopmost(True)
        time.sleep(0.3)
        
        message_list = chat_window_control.ListControl(Name='消息')
        if not message_list.Exists():
            logger.error(f"[拍自己任务] 失败：在 '{chat_name}' 窗口中找不到 '消息' 列表控件。")
            return
        
        # 步骤 2: 定位自己的头像（右侧）
        logger.info("[拍自己任务] 采用终极定位策略：从下往上扫描右侧头像位置...")
        all_items = message_list.GetChildren()
        my_avatar_button = None
        list_rect = message_list.BoundingRectangle
        pane_center_x = list_rect.left + list_rect.width() / 2

        for item in reversed(all_items):
            avatar_button = item.ButtonControl()
            if avatar_button.Exists(0.01):
                button_rect = avatar_button.BoundingRectangle
                # 【【【核心区别点】】】寻找右侧的头像
                if button_rect.xcenter() > pane_center_x:
                    logger.info(f"[拍自己任务] 成功锁定我方（右侧）头像按钮，所属消息: '{item.Name}'")
                    my_avatar_button = avatar_button
                    break 
        
        if not my_avatar_button:
            logger.warning(f"[拍自己任务] 失败：未找到任何位于右侧的我方头像。")
            logger.warning("[拍自己任务] 提示：请确保AI在该聊天中至少发送过一条消息。")
            return
            
        # 步骤 3: 模拟右键点击
        avatar_rect = my_avatar_button.BoundingRectangle
        click_x = avatar_rect.left + avatar_rect.width() // 2
        click_y = avatar_rect.top + avatar_rect.height() // 2
      
        logger.info(f"[拍自己任务] 准备在坐标 ({click_x}, {click_y}) 执行右键点击...")
        pyautogui.click(x=click_x, y=click_y, button='right', duration=0.25)
        time.sleep(0.5)

        # 步骤 4: A/B计划选择菜单中的“拍一拍”
        action_completed = False
        logger.info("[拍自己任务 - A计划] 尝试通过控件属性智能识别'拍一拍'...")
        uia.uiautomation.SetGlobalSearchTimeout(1.0)
        menu = uia.MenuControl(ClassName='CMenuWnd')
        
        if menu.Exists(0.1):
            pat_item = menu.MenuItemControl(Name='拍一拍')
            if pat_item.Exists(0.1):
                logger.info("[拍自己任务 - A计划] 成功！已识别到'拍一拍'项，准备点击。")
                pat_item.Click()
                action_completed = True
            else:
                 logger.warning(f"[拍自己任务 - A计划] 失败：未能找到名为'拍一拍'的项。")
        else:
            logger.warning("[拍自己任务 - A计划] 失败：未能定位到菜单容器。")

        if not action_completed:
            logger.info("[拍自己任务 - B计划] A计划失败，启动终极后备方案：模拟键盘操作！")
            pyautogui.press('down')
            time.sleep(0.1)
            pyautogui.press('down')
            time.sleep(0.1)
            pyautogui.press('enter')
            action_completed = True
        
        logger.info(f"🎉 [拍自己任务] 任务成功！已在 '{chat_name}' 窗口执行了拍一拍自己。 🎉")

    except Exception as e:
        logger.error(f"[拍自己任务] 执行时发生未知严重错误", exc_info=True)
    finally:
        # 步骤 5: 释放资源
        uia.uiautomation.SetGlobalSearchTimeout(DEFAULT_UI_AUTOMATION_TIMEOUT)
        if chat_window_control and chat_window_control.Exists(0.1):
            chat_window_control.SetTopmost(False)
        logger.debug(f"[拍自己任务] 任务结束，资源已释放。")

# ==================== 拍一拍功能区 结束 ====================

# ==================== 撤回消息功能区 开始 ====================

def recall_message_threaded(chat_name: str, message_content: str):
    """
    在一个新的线程中执行撤回消息操作。
    
    Args:
        chat_name: 聊天窗口名称
        message_content: 要撤回的消息内容
    """
    with ui_automation_lock:
        chat_window_control = None
    
    try:
        logger.info(f"[撤回消息任务] 子线程启动：准备在聊天 '{chat_name}' 中撤回消息: '{message_content[:50]}...'")
        
        wx.ChatWith(chat_name)
        time.sleep(2.0)  # 增加等待时间，确保消息发送完成
        
        uia.uiautomation.SetGlobalSearchTimeout(5.0)
        logger.info(f"[撤回消息任务] 正在寻找名为 '{chat_name}' 的独立聊天窗口...")
        chat_window_control = uia.WindowControl(Name=chat_name, searchDepth=1)
        
        if not chat_window_control.Exists():
            logger.error(f"[撤回消息任务] 失败：找不到名为 '{chat_name}' 的独立聊天窗口。")
            return
            
        logger.info(f"[撤回消息任务] 成功锁定目标操作窗口: '{chat_window_control.Name}'")
        chat_window_control.SetActive()
        chat_window_control.SetTopmost(True)
        time.sleep(0.5)  # 增加等待
        
        message_list = chat_window_control.ListControl(Name='消息')
        if not message_list.Exists():
            logger.error(f"[撤回消息任务] 失败：在 '{chat_name}' 窗口中找不到 '消息' 列表控件。")
            return
            
        # 从下往上扫描消息，寻找匹配的内容
        logger.info("[撤回消息任务] 开始扫描消息列表，寻找要撤回的消息...")
        all_items = message_list.GetChildren()
        logger.info(f"[撤回消息任务] 获取到 {len(all_items)} 个消息项")
        
        if not all_items:
            logger.warning("[撤回消息任务] 消息列表为空，可能需要等待消息加载")
            time.sleep(3)  # 等待3秒让消息加载
            all_items = message_list.GetChildren()
            logger.info(f"[撤回消息任务] 重新获取到 {len(all_items)} 个消息项")
        
        target_message_item = None
        list_rect = message_list.BoundingRectangle
        pane_center_x = list_rect.left + list_rect.width() // 2
        logger.info(f"[撤回消息任务] 消息列表区域: left={list_rect.left}, width={list_rect.width()}, center={pane_center_x}")
        
        # 从最新的消息开始搜索（倒序）
        logger.info(f"[撤回消息任务] 开始扫描消息列表，寻找包含'{message_content}'的消息...")
        found_messages = []  # 用于调试，记录找到的所有消息
        
        # 新策略：找到所有包含目标内容的消息，然后选择X坐标最大的（最右边的）
        matching_messages = []
        
        for item in reversed(all_items):
            try:
                item_name = item.Name
                if not item_name:
                    continue
                
                # 获取更详细的坐标信息
                item_rect = item.BoundingRectangle
                item_center_x = item_rect.xcenter() if hasattr(item_rect, 'xcenter') else (item_rect.left + item_rect.width() // 2)
                item_left = item_rect.left
                item_right = item_rect.right
                
                position = "右侧(机器人)" if item_center_x > pane_center_x else "左侧(用户)"
                found_messages.append(f"{position}: '{item_name[:30]}...' [left:{item_left}, center:{item_center_x}, right:{item_right}]")
                
                # 检查是否包含要撤回的消息内容
                if message_content.strip() in item_name:
                    matching_messages.append({
                        'item': item,
                        'name': item_name,
                        'center_x': item_center_x,
                        'left': item_left,
                        'right': item_right
                    })
                    logger.info(f"[撤回消息任务] 找到匹配内容的消息: '{item_name}', X范围: {item_left}-{item_right}, 中心: {item_center_x}")
                    logger.info(f"[撤回消息任务] 已将消息添加到匹配列表，当前匹配数量: {len(matching_messages)}")
                    
            except Exception as e:
                logger.debug(f"[撤回消息任务] 检查消息项时出错: {e}")
                continue
        
        logger.info(f"[撤回消息任务] 消息扫描完成，找到 {len(matching_messages)} 个匹配的消息")
        
        # 如果找到匹配的消息，选择第一个（最新的，因为我们是倒序遍历）
        if matching_messages:
            # 选择第一个匹配的消息（最新发送的）
            target_message = matching_messages[0]
            target_message_item = target_message['item']
            logger.info(f"[撤回消息任务] 选择最新的匹配消息进行撤回: '{target_message['name']}', X中心: {target_message['center_x']}")
        else:
            logger.warning(f"[撤回消息任务] 未找到任何包含内容 '{message_content}' 的消息。")
        
        # 如果没找到，输出调试信息
        if not target_message_item:
            logger.warning(f"[撤回消息任务] 失败：未找到包含内容 '{message_content}' 的消息。")
            logger.info(f"[撤回消息任务] 调试信息 - 总共扫描了 {len(all_items)} 个消息项")
            logger.info(f"[撤回消息任务] 调试信息 - 找到 {len(matching_messages)} 个匹配的消息")
            logger.info(f"[撤回消息任务] 调试信息 - 最近找到的消息列表:")
            for i, msg in enumerate(found_messages[:10]):  # 只显示最近10条
                logger.info(f"  {i+1}. {msg}")
            logger.info(f"[撤回消息任务] 调试信息 - 聊天窗口中心X坐标: {pane_center_x}")
            return
            
        # 右键点击目标消息
        message_rect = target_message_item.BoundingRectangle
        chat_window_rect = chat_window_control.BoundingRectangle
        
        # 获取详细的窗口和消息信息
        logger.info(f"[撤回消息任务] === 详细坐标信息 ===")
        logger.info(f"[撤回消息任务] 聊天窗口区域: left={chat_window_rect.left}, top={chat_window_rect.top}, right={chat_window_rect.right}, bottom={chat_window_rect.bottom}")
        logger.info(f"[撤回消息任务] 消息区域: left={message_rect.left}, top={message_rect.top}, right={message_rect.right}, bottom={message_rect.bottom}")
        
        message_width = message_rect.width()
        message_height = message_rect.height()
        
        # 保守的点击策略：点击消息的右侧1/4处
        # 确保点击位置在消息内容区域内，不会超出窗口
        click_x = message_rect.left + int(message_width * 0.8)  # 消息右侧80%处
        click_y = message_rect.top + message_height // 2  # 垂直居中
        
        # 确保点击坐标在聊天窗口范围内
        if click_x >= chat_window_rect.right:
            click_x = chat_window_rect.right - 20
        elif click_x <= chat_window_rect.left:
            click_x = chat_window_rect.left + 20
            
        if click_y >= chat_window_rect.bottom:
            click_y = chat_window_rect.bottom - 20
        elif click_y <= chat_window_rect.top:
            click_y = chat_window_rect.top + 20
        
        # 再次确保点击坐标在消息范围内
        if click_x >= message_rect.right:
            click_x = message_rect.right - 10
        elif click_x <= message_rect.left:
            click_x = message_rect.left + 10
            
        if click_y >= message_rect.bottom:
            click_y = message_rect.bottom - 5
        elif click_y <= message_rect.top:
            click_y = message_rect.top + 5
        
        logger.info(f"[撤回消息任务] 消息尺寸: {message_width}x{message_height}")
        logger.info(f"[撤回消息任务] 计算点击位置: 消息右侧80%处 = ({message_rect.left + int(message_width * 0.8)}, {message_rect.top + message_height // 2})")
        logger.info(f"[撤回消息任务] 最终点击位置: ({click_x}, {click_y})")
        
        # 检查点击位置是否合理
        if (click_x < chat_window_rect.left or click_x > chat_window_rect.right or 
            click_y < chat_window_rect.top or click_y > chat_window_rect.bottom):
            logger.warning(f"[撤回消息任务] 警告：点击位置可能超出聊天窗口范围！")
        
        logger.info(f"[撤回消息任务] 准备执行右键点击...")
        
        # 直接右键点击消息区域
        pyautogui.click(x=click_x, y=click_y, button='right', duration=0.25)
        logger.info("[撤回消息任务] 右键点击指令已发送。等待菜单弹出...")
        time.sleep(0.5)
        
        # A/B计划执行撤回操作
        action_completed = False
        
        # A计划: 智能识别撤回选项
        logger.info("[撤回消息任务 - A计划] 尝试通过控件属性智能识别'撤回'...")
        uia.uiautomation.SetGlobalSearchTimeout(1.0)
        menu = uia.MenuControl(ClassName='CMenuWnd')
        
        if menu.Exists(0.1):
            logger.info("[撤回消息任务 - A计划] 成功定位菜单容器，开始遍历子项...")
            recall_item = None
            all_menu_items = menu.GetChildren()
            for item in all_menu_items:
                if item.Name == '撤回':
                    recall_item = item
                    break
            
            if recall_item:
                logger.info("[撤回消息任务 - A计划] 成功！已通过名称识别到'撤回'项，准备点击。")
                recall_item.Click()
                action_completed = True
            else:
                found_names = [child.Name for child in all_menu_items]
                logger.warning(f"[撤回消息任务 - A计划] 失败：遍历完成，但未能找到名为'撤回'的项。探测到的名称列表: {found_names}。")
        else:
            logger.warning("[撤回消息任务 - A计划] 失败：未能定位到菜单容器。")
        
        # B计划: 键盘模拟（如果A计划失败）
        if not action_completed:
            logger.info("[撤回消息任务 - B计划] A计划失败，启动终极后备方案：模拟键盘操作！")
            logger.info("[撤回消息任务 - B计划] 正在发送键盘指令: 9次[Down]到达撤回选项 -> [Enter]")
            
            # 微信右键菜单：复制(默认选中) -> 需要按9次Down到达撤回
            for i in range(9):  # 按9次Down键到达撤回选项
                pyautogui.press('down')
                time.sleep(0.1)
            
            pyautogui.press('enter')
            time.sleep(0.1)
            action_completed = True
        
        if action_completed:
            logger.info(f"🎉🎉🎉 [撤回消息任务] 任务圆满成功！已撤回消息: '{message_content[:50]}...' 🎉🎉🎉")
        else:
            logger.error("[撤回消息任务] 致命错误：A计划与B计划全部失败，无法执行撤回操作。")
            
    except Exception as e:
        logger.error(f"[撤回消息任务] 执行时发生未知严重错误", exc_info=True)
        try:
            wx.SendMsg(msg="抱歉，执行撤回操作时内部发生严重错误，请检查后台日志。", who=chat_name)
        except Exception: 
            pass
    finally:
        uia.uiautomation.SetGlobalSearchTimeout(DEFAULT_UI_AUTOMATION_TIMEOUT)
        if chat_window_control and chat_window_control.Exists(0.1):
            chat_window_control.SetTopmost(False)
        logger.debug(f"[撤回消息任务] 任务结束，资源已释放，全局超时已恢复为 {DEFAULT_UI_AUTOMATION_TIMEOUT} 秒。")

# ==================== 撤回消息功能区 结束 ====================

# ==================== 特殊艾特功能区 开始 (主动聚焦终版) ====================
def special_at_user_threaded(chat_name: str, target_user_name: str):
    """
    在一个新的线程中执行特殊的@操作 (最终修正版 - Click To Focus)。
    解决了 SetFocus 失败的问题，改用模拟鼠标点击来可靠地获取输入框焦点。
    """
    with ui_automation_lock:
        chat_window = None
    try:
        logger.info(f"[特殊艾特任务] 子线程启动：准备在 '{chat_name}' 中艾特 '{target_user_name}'。")
        
        # 步骤一：切换聊天窗口
        wx.ChatWith(chat_name)
        
        # 步骤二：稳定等待聊天窗口出现并激活
        chat_window = auto.WindowControl(Name=chat_name, searchDepth=1)
        logger.info(f"[特殊艾特任务] 正在等待名为 '{chat_name}' 的聊天窗口出现...")
        
        if chat_window.Exists(5, 0.5):
            chat_window.SetTopmost(True)
            chat_window.SetActive()
            time.sleep(0.3)
            logger.info(f"[特殊艾特任务] 成功激活目标窗口 '{chat_name}'。")
        else:
            logger.error(f"[特殊艾特任务] 致命错误：在5秒内无法找到或激活名为 '{chat_name}' 的聊天窗口。")
            wx.SendMsg(msg=f"抱歉，我无法打开或激活聊天窗口 '{chat_name}'。", who=chat_name)
            return

        # 步骤三：查找输入框
        input_box = chat_window.EditControl(Name='输入')
        if not input_box.Exists(2, 0.5):
            logger.error(f"[特殊艾特任务] 致命错误：在窗口 '{chat_name}' 中完全找不到'输入'控件。")
            wx.SendMsg(msg=f"抱歉，我在聊天窗口 '{chat_name}' 里找不到输入框。", who=chat_name)
            return

        # 步骤四：【核心修正】放弃 SetFocus，改用更可靠的 Click() 来获取焦点
        logger.info("[特殊艾特任务] 正在通过模拟点击来获取输入框焦点...")
        try:
            # simulateMove=False 可以让点击更快速，直接作用于控件
            input_box.Click(simulateMove=False)
            logger.info("[特殊艾特任务] 模拟点击完成，输入框应已获得焦点。")
            time.sleep(0.2) # 给予 UI 极短的响应时间以放置光标
        except Exception:
            # 如果 Click 失败，作为最终备用方案，使用 pyautogui 根据坐标点击
            logger.warning("[特殊艾特任务] uiautomation 的 Click() 失败，启用 pyautogui 作为后备方案。")
            rect = input_box.BoundingRectangle
            pyautogui.click(rect.xcenter(), rect.ycenter())
            logger.info("[特殊艾特任务] pyautogui 点击完成。")
            time.sleep(0.2)
            
        # 步骤五：执行输入和发送
        text_to_type = f"@{target_user_name}"
        logger.info(f"[特殊艾特任务] 使用 uiautomation.SendKeys 模拟输入: '{text_to_type}'")
        # 直接发送按键，此时焦点应该已经在输入框内了
        auto.SendKeys(text_to_type, interval=0.1)
        
        logger.info("[特殊艾特任务] 输入完成，等待微信成员列表筛选...")
        time.sleep(1.2)
        
        pyautogui.press('enter')
        logger.info(f"[特殊艾特任务] 第一次回车已按下，应已选中 '{target_user_name}'。")
        time.sleep(0.5)
        pyautogui.press('enter')
        
        logger.info(f"🎉🎉🎉 [特殊艾特任务] 任务圆满成功！已在 '{chat_name}' 中发送了对 '{target_user_name}' 的【真】艾特消息。 🎉🎉🎉")

    except Exception as e:
        logger.error(f"[特殊艾特任务] 执行时发生未知严重错误", exc_info=True)
        try:
            wx.SendMsg(msg=f"抱歉，我在尝试艾特 {target_user_name} 时遇到了一个内部错误，请检查后台日志。", who=chat_name)
        except Exception as send_err:
            logger.error(f"[特殊艾特任务] 尝试发送错误通知时也失败了: {send_err}")
    finally:
        # 确保窗口的置顶状态被取消
        if chat_window and chat_window.Exists(0,0):
             chat_window.SetTopmost(False)


def send_reply_with_special_at_threaded(chat_name: str, target_user_name: str, reply_text: str):
    """
    [V2 - 增强版] 在一个新线程中执行带回复的特殊@操作，并支持消息分割。
    它会先@用户并发送第一段消息，然后将后续分割的消息作为普通消息发送。
    """
    with ui_automation_lock: 
        chat_window = None
    try:
        logger.info(f"[带艾特回复任务] 子线程启动：准备在 '{chat_name}' 中艾特 '{target_user_name}' 并回复。")

        # --- [新增] 步骤零：首先分割消息 ---
        # 使用我们已有的工具函数来处理所有分隔符 (\, $, \n 等)
        message_parts = split_message_with_context(reply_text)
        if not message_parts:
            logger.warning(f"[带艾特回复任务] 原始回复 '{reply_text}' 分割后无可发送内容，任务终止。")
            return
        
        # 取出第一部分用于@回复，剩下的是后续要发送的
        first_part = message_parts.pop(0)

        # --- 步骤一至三：激活窗口并获取焦点 (逻辑不变) ---
        wx.ChatWith(chat_name)
        chat_window = auto.WindowControl(Name=chat_name, searchDepth=1)
        if not chat_window.Exists(5, 0.5):
            logger.error(f"[带艾特回复任务] 致命错误：在5秒内无法找到或激活名为 '{chat_name}' 的聊天窗口。")
            return

        chat_window.SetTopmost(True)
        chat_window.SetActive()
        time.sleep(0.3)
        input_box = chat_window.EditControl(Name='输入')
        if not input_box.Exists(2, 0.5):
            logger.error(f"[带艾特回复任务] 致命错误：在窗口 '{chat_name}' 中找不到'输入'控件。")
            return

        try:
            input_box.Click(simulateMove=False)
        except Exception:
            rect = input_box.BoundingRectangle
            pyautogui.click(rect.xcenter(), rect.ycenter())
        time.sleep(0.2)

        # --- 步骤四：执行@操作 (逻辑不变) ---
        at_text = f"@{target_user_name}"
        auto.SendKeys(at_text, interval=0.1)
        time.sleep(1.2)
        pyautogui.press('enter')
        time.sleep(0.3)

        # --- 步骤五：【核心修改】粘贴并发送第一段回复 ---
        try:
            # 检查是否有引用操作在进行中，如果有，使用SendKeys追加内容而不是替换
            with can_send_messages_lock:
                if not can_send_messages:
                    logger.info(f"[带艾特回复任务] 检测到引用操作可能正在进行，使用SendKeys追加内容")
                    auto.SendKeys(first_part, interval=0.01)
                else:
                    # 正常情况下使用剪贴板粘贴
                    pyperclip.copy(first_part)
                    logger.info(f"[带艾特回复任务] 第一段回复已复制到剪贴板: '{first_part}'")
                    time.sleep(0.1)
                    pyautogui.hotkey('ctrl', 'v')
                    time.sleep(0.2)
        except Exception as e:
            logger.error(f"[带艾特回复任务] 使用剪贴板粘贴第一段回复时失败: {e}", exc_info=True)
            auto.SendKeys(first_part, interval=0.01)

        # 发送包含@和第一段消息的组合体
        pyautogui.press('enter')
        logger.info(f"🎉 [带艾特回复任务] 第一部分（带@）发送成功。")

        # --- [新增] 步骤六：循环发送剩余的消息段落 ---
        if message_parts:
            logger.info(f"[带艾特回复任务] 准备发送剩余的 {len(message_parts)} 段消息。")
            for subsequent_part in message_parts:
                try:
                    # 对于后续消息，使用更快速稳定的 wx.SendMsg
                    wx.SendMsg(msg=subsequent_part, who=chat_name)
                    logger.info(f"[带艾特回复任务] 后续消息段落已发送: '{subsequent_part}'")
                    # 在消息之间加入微小的延迟，模仿人类输入
                    time.sleep(TEXT_SEND_INTERVAL) 
                except Exception as e:
                    logger.error(f"[带艾特回复任务] 发送后续消息段落 '{subsequent_part}' 失败: {e}")
        
        logger.info(f"🎉🎉🎉 [带艾特回复任务] 任务圆满成功！已在 '{chat_name}' 中向 '{target_user_name}' 发送了完整的艾特回复。 🎉🎉🎉")

    except Exception as e:
        logger.error(f"[带艾特回复任务] 执行时发生未知严重错误", exc_info=True)
        # 发生错误时，回退到普通文本@发送，确保消息能发出去
        wx.SendMsg(msg=f"@{target_user_name} {reply_text}", who=chat_name)
        logger.warning("[带艾特回复任务] 因发生错误，已回退到普通文本@发送。")
    finally:
        if chat_window and chat_window.Exists(0, 0):
             chat_window.SetTopmost(False)


    """清除指定用户的临时记忆日志文件。"""
    try:
        from config import MEMORY_TEMP_DIR
        prompt_name = prompt_mapping.get(user_id, user_id)
        log_file_path = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{prompt_name}_log.txt')
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
            logger.info(f"已为用户 {user_id} 清除临时记忆文件: {log_file_path}")
    except (ImportError, AttributeError):
        logger.warning("无法从config导入MEMORY_TEMP_DIR，将使用默认路径'memory_temp'。")
        prompt_name = prompt_mapping.get(user_id, user_id)
        log_file_path = os.path.join(root_dir, 'memory_temp', f'{user_id}_{prompt_name}.txt')
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
            logger.info(f"已为用户 {user_id} 清除临时记忆文件: {log_file_path}")
    except Exception as e:
        logger.error(f"为用户 {user_id} 清除临时记忆文件时出错: {e}")




    """清除指定用户的临时记忆日志文件。"""
    try:
        from config import MEMORY_TEMP_DIR
        prompt_name = prompt_mapping.get(user_id, user_id)
        log_file_path = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{prompt_name}_log.txt')
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
            logger.info(f"已为用户 {user_id} 清除临时记忆文件: {log_file_path}")
    except (ImportError, AttributeError):
        logger.warning("无法从config导入MEMORY_TEMP_DIR，将使用默认路径'memory_temp'。")
        prompt_name = prompt_mapping.get(user_id, user_id)
        log_file_path = os.path.join(root_dir, 'memory_temp', f'{user_id}_{prompt_name}.txt')
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
            logger.info(f"已为用户 {user_id} 清除临时记忆文件: {log_file_path}")
    except Exception as e:
        logger.error(f"为用户 {user_id} 清除临时记忆文件时出错: {e}")




    """清除指定用户的临时记忆日志文件。"""
    try:
        from config import MEMORY_TEMP_DIR
        prompt_name = prompt_mapping.get(user_id, user_id)
        log_file_path = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{prompt_name}_log.txt')
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
            logger.info(f"已为用户 {user_id} 清除临时记忆文件: {log_file_path}")
    except (ImportError, AttributeError):
        logger.warning("无法从config导入MEMORY_TEMP_DIR，将使用默认路径'memory_temp'。")
        prompt_name = prompt_mapping.get(user_id, user_id)
        log_file_path = os.path.join(root_dir, 'memory_temp', f'{user_id}_{prompt_name}.txt')
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
            logger.info(f"已为用户 {user_id} 清除临时记忆文件: {log_file_path}")
    except Exception as e:
        logger.error(f"为用户 {user_id} 清除临时记忆文件时出错: {e}")


def initiate_voice_call_threaded(target_user):
    """在一个新的线程中发起语音通话，以避免阻塞主程序"""
    try:
        logger.info(f"子线程：准备向用户 {target_user} 发起语音通话。")
        # 发送一条消息提示用户
        wx.SendMsg(msg="我马上打给你", who=target_user)
        # 主动发起语音通话
        wx.VoiceCall(who=target_user)
        logger.info(f"子线程：已成功向用户 {target_user} 发起语音通话指令。")
    except Exception as e:
        logger.error(f"子线程：为用户 {target_user} 发起语音通话时失败: {str(e)}", exc_info=True)
        wx.SendMsg(msg="抱歉，发起语音通话失败，请稍后再试。", who=target_user)

def message_listener(msg, chat):
    """
    消息回调函数，所有接收到的消息都先经过这里处理。
    这是修正后的版本，整合了指令处理和常规消息分发。
    """
    global can_send_messages
    global last_received_message_timestamp
    
    # 从消息对象中提取关键信息
    who = chat.who          # 聊天窗口名 (私聊是好友，群聊是群名)
    sender = msg.sender       # 消息发送者 (私聊是好友，群聊是群成员)
    msgtype = msg.type        # 消息类型 text, image, etc.
    original_content = msg.content # 原始消息内容
    msgattr = msg.attr        # 消息属性，用于判断拍一拍等

    # 1. 统一记录所有收到的有效消息，解决黑窗不显示的问题
    logger.info(f'收到来自聊天窗口 "{who}" 中用户 "{sender}" 的原始消息 (类型: {msgtype}, 属性: {msgattr}): {str(original_content)[:100]}')

    # 更新最后活动时间戳
    last_received_message_timestamp = time.time()

    # 2. 检查指令
    try:
        from config import ENABLE_TEXT_COMMANDS
    except ImportError:
        ENABLE_TEXT_COMMANDS = False

    if ENABLE_TEXT_COMMANDS and msgtype == 'text':
        # 调用 command_handler，它会返回需要回复的文本或None
        reply_text = command_handler.process_command(
            original_content=original_content,
            user_id=who,
            clear_context_func=clear_chat_context,
            clear_memory_func=clear_memory_temp_files
        )
        
        # 如果返回了文本，说明是有效指令
        if reply_text:
            logger.info(f"指令 '{original_content.strip()}' 已识别，正在回复...")
            try:
                # 【【【 模仿“十连抽”的回复方式！！！】】】
                # 明确指定 msg 和 who 参数，这是最标准的用法
                wx.SendMsg(msg=reply_text, who=who) 
                
                logger.info(f"已向 '{who}' 发送指令回复。")
            except Exception as e:
                logger.error(f"向 '{who}' 发送指令回复失败: {e}")
            
            # 指令处理完毕，必须 return，不再进行后续AI对话处理
            return

    # ------------------- 如果不是指令，则继续执行后续的复杂逻辑 -------------------

    # --- START: 消息撤回事件处理 ---
    if sender == 'system' and '撤回了一条消息' in original_content:
        if '我撤回了一条消息' in original_content or original_content.startswith('你撤回了一条消息'):
            logger.info(f"检测到AI自己撤回消息的系统提示，将记录到聊天上下文。内容: '{original_content}'")
            with queue_lock:
                if who not in chat_contexts:
                    chat_contexts[who] = {}
                prompt_name = prompt_mapping.get(who, who)
                if prompt_name not in chat_contexts[who]:
                    chat_contexts[who][prompt_name] = []
                action_message = f"你刚刚撤回了一条消息：{original_content}"
                chat_contexts[who][prompt_name].append({"role": "assistant", "content": action_message})
                context_limit = MAX_GROUPS * 2
                if len(chat_contexts[who][prompt_name]) > context_limit:
                    chat_contexts[who][prompt_name] = chat_contexts[who][prompt_name][-context_limit:]
                save_chat_contexts()
            logger.info(f"已将AI自己的撤回动作记录到用户 '{who}' 的聊天上下文中")
            return
            
        is_group_chat = is_user_group_chat(who)
        if not is_group_chat:
            logger.info(f"检测到用户 '{who}' 撤回了一条消息。")
            recall_trigger_content = "[用户操作: 撤回了一条消息]"
            with queue_lock:
                current_time_str = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
                content_with_time = f"[{current_time_str}] {recall_trigger_content}"
                if who not in user_queues:
                    user_queues[who] = {'messages': [content_with_time], 'sender_name': who, 'username': who, 'last_message_time': time.time()}
                else:
                    user_queues[who]['messages'].append(content_with_time)
                    user_queues[who]['last_message_time'] = time.time()
                logger.info(f"已为用户 '{who}' 加入撤回消息触发指令到队列。")
            return
    
    # --- 拍一拍事件感知 ---
    if msgattr == 'tickle':
        if '我拍了拍自己' in original_content or '我拍了拍' in original_content:
            logger.info(f"检测到机器人自己发起的拍一拍事件，将记录到聊天上下文。内容: '{original_content}'")
            with queue_lock:
                if who not in chat_contexts:
                    chat_contexts[who] = {}
                prompt_name = prompt_mapping.get(who, who)
                if prompt_name not in chat_contexts[who]:
                    chat_contexts[who][prompt_name] = []
                action_message = f"{original_content}"
                chat_contexts[who][prompt_name].append({"role": "assistant", "content": action_message})
                context_limit = MAX_GROUPS * 2
                if len(chat_contexts[who][prompt_name]) > context_limit:
                    chat_contexts[who][prompt_name] = chat_contexts[who][prompt_name][-context_limit:]
                save_chat_contexts()
            logger.info(f"已将AI自己的拍一拍动作记录到用户 '{who}' 的聊天上下文中")
            return

        is_group = is_user_group_chat(who)
        if is_group:
            if "拍了拍我" not in original_content:
                logger.info(f"在群聊 '{who}' 中检测到用户间互相拍，与机器人无关，已忽略。")
                return

        logger.info(f"✅ 成功检测到需要处理的拍一拍事件，来自 '{who}'，内容: '{original_content}'")
        pat_trigger_content = f"[这是一个拍一拍的互动通知，内容是：'{original_content}']"
        with queue_lock:
            current_time_str = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
            content_with_time = f"[{current_time_str}] {pat_trigger_content}"
            if who not in user_queues:
                user_queues[who] = {'messages': [content_with_time], 'sender_name': who, 'username': who, 'last_message_time': time.time()}
            else:
                user_queues[who]['messages'].append(content_with_time)
                user_queues[who]['last_message_time'] = time.time()
        logger.info(f"已为用户 '{who}' 加入“拍一拍”触发指令到队列。")
        return

    # --- 过滤手打的“拍一拍”文本 ---
    if isinstance(original_content, str) and (original_content.strip().startswith('我拍了拍') or original_content.strip().startswith('你拍了拍')):
        logger.info(f"检测到手打的“拍一拍”格式文本消息，已忽略。内容：'{original_content}'")
        return

    # --- 过滤非好友消息 ---
    if msgattr != 'friend': 
        logger.info(f"非好友消息，已忽略。")
        return

    # --- 消息类型转换 (voice, link, quote, merge) ---
    if msgtype == 'voice':
        voicetext = msg.to_text()
        original_content = (f"[语音消息]: {voicetext}")
    
    if msgtype == 'link':
        cardurl = msg.get_url()
        original_content = (f"[卡片链接]: {cardurl}")

    if msgtype == 'quote':
        quoted_msg = msg.quote_content
        if quoted_msg:
            original_content = f"[引用<{quoted_msg}>消息]: {msg.content}"
        else:
            original_content = msg.content
    
    if msgtype == 'merge':
        logger.info(f"收到合并转发消息，开始处理")
        mergecontent = msg.get_messages()
        logger.info(f"收到合并转发消息，处理完成")
        if isinstance(mergecontent, list):
            merged_text_lines = []
            for item in mergecontent:
                if isinstance(item, list) and len(item) == 3:
                    item_sender, content, timestamp = item
                    if hasattr(content, 'suffix') and str(content.suffix).lower() in ('.png', '.jpg', '.jpeg', '.gif', '.bmp'):
                        if ENABLE_IMAGE_RECOGNITION:
                            try:
                                logger.info(f"开始识别图片: {str(content)}")
                                image_path = str(content)
                                original_can_send_messages = can_send_messages
                                content = recognize_image_with_moonshot(image_path, is_emoji=False)
                                if content:
                                    logger.info(f"图片识别成功: {content}")
                                    content = f"[图片识别结果]: {content}"
                                else:
                                    content = "[图片识别结果]: 无法识别图片内容"
                                can_send_messages = original_can_send_messages
                            except Exception as e:
                                content = "[图片识别失败]"
                                logger.error(f"图片识别失败: {e}")
                                can_send_messages = True
                        else:
                            content = "[图片]"
                    elif isinstance(content, str) and content.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', 'bmp')):
                        if ENABLE_IMAGE_RECOGNITION:
                            try:
                                logger.info(f"开始识别图片: {content}")
                                original_can_send_messages = can_send_messages
                                image_content = recognize_image_with_moonshot(content, is_emoji=False)
                                if image_content:
                                    logger.info(f"图片识别成功: {image_content}")
                                    content = f"[图片识别结果]: {image_content}"
                                else:
                                    content = "[图片识别结果]: 无法识别图片内容"
                                can_send_messages = original_can_send_messages
                            except Exception as e:
                                content = "[图片识别失败]"
                                logger.error(f"图片识别失败: {e}")
                                can_send_messages = True
                        else:
                            content = "[图片]"
                    merged_text_lines.append(f"[{timestamp}] {item_sender}: {content}")
                else:
                    merged_text_lines.append(str(item))
            merged_text = "\n".join(merged_text_lines)
            original_content = f"[合并转发消息]:\n{merged_text}"
        else:
            original_content = f"[合并转发消息]: {mergecontent}"
    
    # 在处理完所有消息类型后，将更新后的内容同步回 msg 对象
    msg.content = original_content

    # --- 内容为空检查 ---
    if not msg.content:
        logger.info("消息内容在转换后为空，已忽略。")
        return
    
    msg.content = str(msg.content)

    # --- 特殊功能触发 (语音通话, 拍一拍指令, 特殊艾特) ---
    voice_call_keywords = ["给我打电话"]
    if any(keyword in msg.content for keyword in voice_call_keywords):
        logger.info(f"用户 {who} 请求语音通话，准备在新线程中发起呼叫。")
        call_thread = threading.Thread(target=initiate_voice_call_threaded, args=(who,))
        call_thread.start()
        return

    is_group_chat_for_pat = is_user_group_chat(who)
    if not is_group_chat_for_pat:
        if msg.content == "拍一拍我":
            logger.info(f"在与 '{who}' 的私聊中检测到精确指令 '拍一拍我'，准备执行拍一拍。")
            pat_thread = threading.Thread(target=pat_pat_user_threaded, args=(who, who))
            pat_thread.start()
            return
    else:
        pat_match = re.search(r'测试654321\s*@?(.+)', msg.content.strip())
        if pat_match:
            target_name = pat_match.group(1).strip()
            logger.info(f"在群聊 '{who}' 中检测到拍一拍请求，目标: '{target_name}'。")
            pat_thread = threading.Thread(target=pat_pat_user_threaded, args=(who, target_name))
            pat_thread.start()
            return
            
    if is_group_chat_for_pat:
        at_match = re.search(r'(?:测试123456)\s*(.+)', msg.content.strip(), re.IGNORECASE)
        if at_match:
            target_name = at_match.group(1).strip()
            if not target_name or len(target_name) > 50:
                 logger.warning(f"检测到无效的特殊艾特目标: '{target_name}'，已忽略。")
            else:
                logger.info(f"在群聊 '{who}' 中检测到特殊艾特请求，目标: '{target_name}'。")
                at_thread = threading.Thread(target=special_at_user_threaded, args=(who, target_name))
                at_thread.start()
                return

    # --- 最终的消息触发判断逻辑 ---
    should_process_this_message = False
    content_for_handler = msg.content
    is_group_chat_final_check = is_user_group_chat(who)
    group_cfg = get_group_chat_config(who) if is_group_chat_final_check else {}

    if not is_group_chat_final_check:
        if who in user_names:
            should_process_this_message = True
            logger.info(f"收到来自监听列表用户 {who} 的个人私聊消息，准备处理。")
        else:
            logger.info(f"收到来自用户 {sender} (聊天窗口 {who}) 的个人私聊消息，但用户 {who} 不在监听列表或发送者与聊天窗口不符，已忽略。")
    else:
        processed_group_content = original_content
        at_triggered = False
        keyword_triggered = False

        if not group_cfg.get('ACCEPT_ALL_GROUP_CHAT_MESSAGES', False) and group_cfg.get('ENABLE_GROUP_AT_REPLY', True) and ROBOT_WX_NAME:
            temp_content_after_at_check = processed_group_content
            unicode_at_pattern = f'@{re.escape(ROBOT_WX_NAME)}\u2005'
            space_at_pattern = f'@{re.escape(ROBOT_WX_NAME)} '
            exact_at_string = f'@{re.escape(ROBOT_WX_NAME)}'
            if re.search(unicode_at_pattern, processed_group_content):
                at_triggered = True
                temp_content_after_at_check = re.sub(unicode_at_pattern, '', processed_group_content, 1).strip()
            elif re.search(space_at_pattern, processed_group_content):
                at_triggered = True
                temp_content_after_at_check = re.sub(space_at_pattern, '', processed_group_content, 1).strip()
            elif processed_group_content.strip() == exact_at_string:
                at_triggered = True
                temp_content_after_at_check = ''
            if at_triggered:
                logger.info(f"群聊 '{who}' 中检测到 @机器人。")
                processed_group_content = temp_content_after_at_check

        if group_cfg.get('ENABLE_GROUP_KEYWORD_REPLY', False):
            keywords_config = group_cfg.get('GROUP_KEYWORD_LIST', [])
            keyword_list = []
            if isinstance(keywords_config, str):
                normalized_value = re.sub(r'，|\s+', ',', keywords_config)
                keyword_list = [kw.strip() for kw in normalized_value.split(',') if kw.strip()]
            elif isinstance(keywords_config, list):
                keyword_list = keywords_config
            if any(keyword in processed_group_content for keyword in keyword_list):
                keyword_triggered = True
                logger.info(f"群聊 '{who}' 中检测到关键词。")

        basic_trigger_met = group_cfg.get('ACCEPT_ALL_GROUP_CHAT_MESSAGES', False) or at_triggered or keyword_triggered
        if basic_trigger_met:
            if not group_cfg.get('ACCEPT_ALL_GROUP_CHAT_MESSAGES', False):
                if at_triggered and keyword_triggered:
                    logger.info(f"群聊 '{who}' 消息因 @机器人 和关键词触发基本处理条件。")
                elif at_triggered:
                    logger.info(f"群聊 '{who}' 消息因 @机器人 触发基本处理条件。")
                elif keyword_triggered:
                    logger.info(f"群聊 '{who}' 消息因关键词触发基本处理条件。")
            else:
                logger.info(f"群聊 '{who}' 消息符合全局接收条件，触发基本处理条件。")

            if keyword_triggered and group_cfg.get('GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY', False):
                should_process_this_message = True
                logger.info(f"群聊 '{who}' 消息因触发关键词且配置为忽略回复概率，将进行处理。")
            elif random.randint(1, 100) <= group_cfg.get('GROUP_CHAT_RESPONSE_PROBABILITY', 100):
                should_process_this_message = True
                logger.info(f"群聊 '{who}' 消息满足基本触发条件并通过总回复概率 {group_cfg.get('GROUP_CHAT_RESPONSE_PROBABILITY', 100)}%，将进行处理。")
            else:
                should_process_this_message = False
                logger.info(f"群聊 '{who}' 消息满足基本触发条件，但未通过总回复概率 {group_cfg.get('GROUP_CHAT_RESPONSE_PROBABILITY', 100)}%，将忽略。")
        else:
            should_process_this_message = False
            logger.info(f"群聊 '{who}' 消息 (发送者: {sender}) 未满足任何基本触发条件（全局、@、关键词），将忽略。")
        
        if should_process_this_message:
            if not msgtype == 'image':
                content_for_handler = f"[群聊消息-来自群'{who}'-发送者:{sender}]:{processed_group_content}"
            else:
                content_for_handler = processed_group_content
            
            if not content_for_handler and at_triggered and not keyword_triggered: 
                logger.info(f"群聊 '{who}' 中单独 @机器人，处理后内容为空，仍将传递给后续处理器。")
    
    # 3. 如果通过所有检查，则分发给最终处理器
    if should_process_this_message:
        msg.content = content_for_handler 
        logger.info(f'最终准备处理消息 from chat "{who}" by sender "{sender}": {str(msg.content)[:100]}')
        
        is_animation_emoji_in_original = (msgtype == 'emotion')

        if is_animation_emoji_in_original and ENABLE_EMOJI_RECOGNITION:
            handle_emoji_message(msg, who, sender)
        else:
            handle_wxauto_message(msg, who, sender)


def clear_chat_context(user_id):
    global chat_contexts
    with queue_lock:
        # 1. 根据 user_id 获取当前正在对话的角色名 (prompt_name)
        prompt_name = prompt_mapping.get(user_id, user_id)

        # 2. 检查用户条目和角色条目是否存在
        if user_id in chat_contexts and isinstance(chat_contexts.get(user_id), dict) and prompt_name in chat_contexts[user_id]:
            # 3. 【核心修正】只删除该角色对应的上下文列表，不留任何后备方案
            del chat_contexts[user_id][prompt_name]
            save_chat_contexts()
            logger.warning(f"已精准清除用户 {user_id} 的角色 '{prompt_name}' 的聊天上下文。")
        else:
            # 如果找不到，说明本来就是空的，记录一下日志即可，什么也不做
            logger.info(f"无需清除：用户 {user_id} 或其角色 '{prompt_name}' 的上下文不存在。")


def clear_memory_temp_files(user_id):
    """清除指定用户的临时记忆日志文件。"""
    try:
        from config import MEMORY_TEMP_DIR
        prompt_name = prompt_mapping.get(user_id, user_id)
        log_file_path = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{prompt_name}_log.txt')
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
            logger.info(f"已为用户 {user_id} 清除临时记忆文件: {log_file_path}")
    except (ImportError, AttributeError):
        logger.warning("无法从config导入MEMORY_TEMP_DIR，将使用默认路径'memory_temp'。")
        prompt_name = prompt_mapping.get(user_id, user_id)
        log_file_path = os.path.join(root_dir, 'memory_temp', f'{user_id}_{prompt_name}.txt')
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
            logger.info(f"已为用户 {user_id} 清除临时记忆文件: {log_file_path}")
    except Exception as e:
        logger.error(f"为用户 {user_id} 清除临时记忆文件时出错: {e}")


def recognize_image_with_moonshot(image_path, is_emoji=False):
    global can_send_messages
    
    with can_send_messages_lock:
        can_send_messages = False
    
    try:
        # --- 核心识别逻辑 ---
        
        # 读取图片内容并编码
        with open(image_path, 'rb') as img_file:
            image_content = base64.b64encode(img_file.read()).decode('utf-8')
            
        headers = {
            'Authorization': f'Bearer {MOONSHOT_API_KEY}',
            'Content-Type': 'application/json'
        }
        text_prompt = "请用中文描述这张图片的主要内容或主题。不要使用'这是'、'这张'等开头，直接描述。如果有文字，请包含在描述中。" if not is_emoji else "请用中文简洁地描述这个聊天窗口最后一张表情包所表达的情绪、含义或内容。如果表情包含文字，请一并描述。注意：1. 只描述表情包本身，不要添加其他内容 2. 不要出现'这是'、'这个'等词语"
        data = {
            "model": MOONSHOT_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_content}"}},
                        {"type": "text", "text": text_prompt}
                    ]
                }
            ],
            "temperature": MOONSHOT_TEMPERATURE
        }
        
        url = f"{MOONSHOT_BASE_URL}/chat/completions"
        
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status() # 检查HTTP错误
        
        result = response.json()
        recognized_text = result['choices'][0]['message']['content']
        
        if is_emoji:
            if "最后一张表情包" in recognized_text:
                recognized_text = recognized_text.split("最后一张表情包", 1)[1].strip()
            recognized_text = "发送了表情包：" + recognized_text
        else:
            recognized_text = "发送了图片：" + recognized_text
            
        logger.info(f"AI图片识别成功: {recognized_text}")
        return recognized_text

    except requests.exceptions.Timeout:
        logger.error(f"调用AI识别图片超时 (30秒): {image_path}")
        return "[图片识别超时]"

    except Exception as e:
        logger.error(f"调用AI识别图片失败: {str(e)}", exc_info=True)
        return "[图片识别失败]"
        
    finally:
        with can_send_messages_lock:
            can_send_messages = True
        logger.info(f"图片识别流程结束，can_send_messages 全局锁已恢复为 True。")
        
        if is_emoji and os.path.exists(image_path):
            try:
                os.remove(image_path)
                logger.debug(f"已清理临时表情图片: {image_path}")
            except Exception as clean_err:
                logger.warning(f"清理临时表情图片失败: {clean_err}")

def handle_emoji_message(msg, who, sender):
    global emoji_timer
    
    # 立即锁住，防止其他消息发送
    with can_send_messages_lock:
        can_send_messages = False

    def timer_callback():
        try:
            with emoji_timer_lock:
                handle_wxauto_message(msg, who, sender)
                global emoji_timer
                emoji_timer = None
        finally:
            # 确保无论如何都能释放锁
            with can_send_messages_lock:
                can_send_messages = True
            logger.info("表情包延迟处理完成，can_send_messages 锁已释放。")

    with emoji_timer_lock:
        if emoji_timer is not None:
            emoji_timer.cancel()
        logger.info("检测到连续表情包，重置3秒延迟计时器...")
        emoji_timer = threading.Timer(3.0, timer_callback)
        emoji_timer.start()

def fetch_and_extract_text(url: str) -> Optional[str]:
    """
    获取给定 URL 的网页内容并提取主要文本。

    Args:
        url (str): 要抓取的网页链接。

    Returns:
        Optional[str]: 提取并清理后的网页文本内容（限制了最大长度），如果失败则返回 None。
    """
    try:
        # 基本 URL 格式验证 (非常基础)
        parsed_url = urlparse(url)
        if not all([parsed_url.scheme, parsed_url.netloc]):
             logger.warning(f"无效的URL格式，跳过抓取: {url}")
             return None

        headers = {'User-Agent': REQUESTS_USER_AGENT}
        logger.info(f"开始抓取链接内容: {url}")
        response = requests.get(url, headers=headers, timeout=REQUESTS_TIMEOUT, allow_redirects=True)
        response.raise_for_status()  # 检查HTTP请求是否成功 (状态码 2xx)

        # 检查内容类型，避免处理非HTML内容（如图片、PDF等）
        content_type = response.headers.get('Content-Type', '').lower()
        if 'html' not in content_type:
            logger.warning(f"链接内容类型非HTML ({content_type})，跳过文本提取: {url}")
            return None

        # 使用BeautifulSoup解析HTML
        # 指定 lxml 解析器以获得更好的性能和兼容性
        soup = BeautifulSoup(response.content, 'lxml') # 使用 response.content 获取字节流，让BS自动处理编码

        # --- 文本提取策略 ---
        # 尝试查找主要内容区域 (这部分可能需要根据常见网站结构调整优化)
        main_content_tags = ['article', 'main', '.main-content', '#content', '.post-content'] # 示例选择器
        main_text = ""
        for tag_selector in main_content_tags:
            element = soup.select_one(tag_selector)
            if element:
                main_text = element.get_text(separator='\n', strip=True)
                break # 找到一个就停止

        # 如果没有找到特定的主要内容区域，则获取整个 body 的文本作为备选
        body_element = soup.find('body')
        if not main_text and body_element:
            main_text = body_element.get_text(separator='\n', strip=True)
        elif not main_text: # 如果连 body 都没有，则使用整个 soup
             main_text = soup.get_text(separator='\n', strip=True)

        # 清理文本：移除过多空行
        lines = [line for line in main_text.splitlines() if line.strip()]
        cleaned_text = '\n'.join(lines)

        # 限制内容长度
        if len(cleaned_text) > MAX_WEB_CONTENT_LENGTH:
            cleaned_text = cleaned_text[:MAX_WEB_CONTENT_LENGTH] + "..." # 截断并添加省略号
            logger.info(f"网页内容已提取，并截断至 {MAX_WEB_CONTENT_LENGTH} 字符。")
        elif cleaned_text:
            logger.info(f"成功提取网页文本内容 (长度 {len(cleaned_text)}).")
        else:
            logger.warning(f"未能从链接 {url} 提取到有效文本内容。")
            return None # 如果提取后为空，也视为失败

        return cleaned_text

    except requests.exceptions.Timeout:
        logger.error(f"抓取链接超时 ({REQUESTS_TIMEOUT}秒): {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"抓取链接时发生网络错误: {url}, 错误: {e}")
        return None
    except Exception as e:
        # 捕获其他可能的错误，例如 BS 解析错误
        logger.error(f"处理链接时发生未知错误: {url}, 错误: {e}", exc_info=True)
        return None

# 辅助函数：将用户消息记录到记忆日志 (如果启用)
def log_user_message_to_memory(username, original_content):
    """将用户的原始消息记录到记忆日志文件。"""
    if ENABLE_MEMORY:
        try:
            prompt_name = prompt_mapping.get(username, username)
            log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{username}_{prompt_name}_log.txt')
            
            # 清理消息中的换行符
            cleaned_content = str(original_content).replace('\n', ' ')
            log_entry = f"{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')} | [{username}] {cleaned_content}\n"
            
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as write_err:
             logger.error(f"写入用户 {username} 的记忆日志失败: {write_err}")

def handle_wxauto_message(msg, who, sender):
    """
    处理来自Wxauto的消息，包括可能的提醒、图片/表情、链接内容获取和常规聊天。
    [新增 sender 参数]
    """
    global can_send_messages # 引用全局变量以控制发送状态
    global last_received_message_timestamp # 引用全局变量以更新活动时间
    try:
        last_received_message_timestamp = time.time()
        username = who
        # 获取原始消息内容
        original_content = getattr(msg, 'content', None) or getattr(msg, 'text', None)

        # 如果消息内容为空，则直接返回
        if not original_content:
            logger.warning("收到的消息没有内容。")
            return

        # 重置该用户的自动消息计时器
        on_user_message(username)


        # --- 1. 提醒检查 (基于原始消息内容) ---
        reminder_keywords = ["提醒我", "定时"]
        if ENABLE_REMINDERS and any(keyword in original_content for keyword in reminder_keywords):
            logger.info(f"检测到可能的提醒请求，用户 {username}: {original_content}")
            # 尝试解析并设置提醒
            reminder_set = try_parse_and_set_reminder(original_content, username)
            # 如果成功设置了提醒，则处理完毕，直接返回
            if reminder_set:
                logger.info(f"成功为用户 {username} 设置提醒，消息处理结束。")
                return # 停止进一步处理此消息
        
        # --- 新增: 抽卡系统检查 (新版) ---
        gacha_keywords = ["十连抽"]
        if any(keyword in original_content for keyword in gacha_keywords):
            sender = msg.sender
            logger.info(f"检测到来自 {sender} (在聊天 {who} 中) 的抽卡请求: {original_content}")

            # 执行抽卡，使用 sender 作为 user_id 以正确追踪保底
            gacha_result = perform_ten_pull(sender)

            # 如果是群聊，在结果前 @ 发送者
            if is_user_group_chat(who):
                gacha_result = f"@{sender}\n{gacha_result}"

            # 直接发送单条消息，避免被 send_reply 的复杂逻辑分割
            wx.SendMsg(msg=gacha_result, who=who)

            logger.info(f"已为用户 {sender} (在聊天 {who} 中) 完成抽卡并发送结果。")
            return  # 停止进一步处理此消息

        # --- 2. 图片/表情处理 (基于原始消息内容) ---
        img_path = None         # 图片路径
        is_emoji = False        # 是否为表情包
        # processed_content 初始化为原始消息，后续步骤可能修改它
        processed_content = original_content

        # 检查是否为图片文件路径
        if msg.type in ('image'):
            if ENABLE_IMAGE_RECOGNITION:
                img_path = msg.download()
                is_emoji = False
                processed_content = None # 标记为None，稍后会被识别结果替换
                logger.info(f"检测到图片消息，准备识别: {img_path}")
            else:
                logger.info("检测到图片消息，但图片识别功能已禁用。")

        # 检查是否为动画表情
        elif msg.type in ('emotion'):
            if ENABLE_EMOJI_RECOGNITION:
                img_path = msg.capture() # 截图
                is_emoji = True
                processed_content = None # 标记为None，稍后会被识别结果替换
                logger.info("检测到动画表情，准备截图识别...")
            else:
                clean_up_temp_files() # 清理可能的临时文件
                logger.info("检测到动画表情，但表情识别功能已禁用。")

        # 如果需要进行图片/表情识别
        if img_path:
            logger.info(f"开始识别图片/表情 - 用户 {username}: {img_path}")
            # 调用识别函数
            recognized_text = recognize_image_with_moonshot(img_path, is_emoji=is_emoji)
            # 使用识别结果或回退占位符更新 processed_content
            processed_content = recognized_text if recognized_text else ("[图片]" if not is_emoji else "[动画表情]")
            clean_up_temp_files() # 清理临时截图文件
            can_send_messages = True # 确保识别后可以发送消息
            logger.info(f"图片/表情识别完成，结果: {processed_content}")

        # --- 3. 链接内容获取 (仅当ENABLE_URL_FETCHING为True且当前非图片/表情处理流程时) ---
        fetched_web_content = None
        # 只有在启用了URL抓取，并且当前处理的不是图片/表情（即processed_content不为None）时才进行
        if ENABLE_URL_FETCHING and processed_content is not None:
            # 使用正则表达式查找 URL
            url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
            urls_found = re.findall(url_pattern, original_content) # 仍在原始消息中查找URL

            if urls_found:
                # 优先处理第一个找到的有效链接
                url_to_fetch = urls_found[0]
                logger.info(f"检测到链接，用户 {username}，准备抓取: {url_to_fetch}")
                # 调用辅助函数抓取和提取文本
                fetched_web_content = fetch_and_extract_text(url_to_fetch)

                if fetched_web_content:
                    logger.info(f"成功获取链接内容摘要 (长度 {len(fetched_web_content)})。")
                    # 构建包含链接摘要的新消息内容，用于发送给AI
                    # 注意：这里替换了 processed_content，AI将收到包含原始消息和链接摘要的组合信息
                    processed_content = f"用户发送了消息：\"{original_content}\"\n其中包含的链接的主要内容摘要如下（可能不完整）：\n---\n{fetched_web_content}\n---\n"
                else:
                    logger.warning(f"未能从链接 {url_to_fetch} 提取有效文本内容。将按原始消息处理。")
                    # 如果抓取失败，processed_content 保持不变（可能是原始文本，或图片/表情占位符）
            # else: (如果没找到URL) 不需要操作，继续使用当前的 processed_content

        # --- 4. 记录用户消息到记忆 (如果启用) ---
        log_user_message_to_memory(username, processed_content)

        # --- 5. 将最终处理后的消息加入队列 ---
        # 只有在 processed_content 有效时才加入队列
        if processed_content:
            # 获取当前时间戳，添加到消息内容前
            current_time_str = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
            content_with_time = f"[{current_time_str}] {processed_content}" # 使用最终处理过的内容
            logger.info(f"准备将处理后的消息加入队列 - 用户 {username}: {content_with_time[:150]}...") # 日志截断防止过长

            # 【核心修改点】使用传递进来的 sender
            # 如果 sender 为空(例如主动消息), 则回退到使用 who
            sender_name_to_use = sender if sender else who

            # 使用锁保护对共享队列的访问
            with queue_lock:
                # 如果用户队列不存在，则初始化
                if username not in user_queues:
                    user_queues[username] = {
                        'messages': [content_with_time],
                        'sender_name': sender_name_to_use,
                        'username': username,
                        'last_message_time': time.time()
                    }
                    logger.info(f"已为用户 {username} (发言人: {sender_name_to_use}) 初始化消息队列并加入消息。")
                else:
                    user_queues[username]['messages'].append(content_with_time)
                    user_queues[username]['last_message_time'] = time.time()
                    # 每次都更新发言人，以响应最新的消息
                    user_queues[username]['sender_name'] = sender_name_to_use
                    logger.info(f"用户 {username} (发言人: {sender_name_to_use}) 的消息已加入队列（当前 {len(user_queues[username]['messages'])} 条）并更新时间。")
        else:
            logger.warning(f"在处理后未找到用户 {username} 的可处理内容。原始消息: '{original_content}'")

    except Exception as e:
        can_send_messages = True
        logger.error(f"消息处理失败 (handle_wxauto_message): {str(e)}", exc_info=True)

def check_inactive_users():
    global can_send_messages
    while True:
        current_time = time.time()
        inactive_users = []
        with queue_lock:
            for username, user_data in user_queues.items():
                last_time = user_data.get('last_message_time', 0)
                if current_time - last_time > QUEUE_WAITING_TIME and can_send_messages: 
                    inactive_users.append(username)

        for username in inactive_users:
            process_user_messages(username)

        time.sleep(1)  # 每秒检查一次

# 在 bot.py 文件中找到此函数并用下面的代码完整替换

def process_user_messages(user_id):
    """处理指定用户的消息队列，包括可能的联网搜索。"""
    global can_send_messages

    with queue_lock:
        if user_id not in user_queues:
            return
        user_data = user_queues.pop(user_id)
        messages = user_data['messages']
        sender_name = user_data['sender_name']
        username = user_data['username']

    merged_message = ' '.join(messages)
    logger.info(f"开始处理用户 '{sender_name}' (ID: {user_id}) 的合并消息: {merged_message[:100]}...")

    is_auto_message = "触发主动发消息：" in merged_message
    
    reply = None
    online_info = None

    # [核心] 在函数开头就获取配置，以便后续所有流程都能使用
    group_config = get_group_chat_config(user_id)

    try:
        if ENABLE_ONLINE_API:
            search_content = needs_online_search(merged_message, user_id)
            if search_content:
                logger.info(f"尝试为用户 {user_id} 执行在线搜索...")
                merged_message = f"用户原始信息：\n{merged_message}\n\n需要进行联网搜索的信息：\n{search_content}"
                online_info = get_online_model_response(merged_message, user_id)

                if online_info:
                    logger.info(f"成功获取在线信息，为用户 {user_id} 准备最终回复...")
                    final_prompt = f"""
用户的原始问题是：
"{merged_message}"

根据以下联网搜索到的参考信息：
---
{online_info}
---

请结合你的角色设定，以自然的方式回答用户的原始问题。请直接给出回答内容，不要提及你是联网搜索的。
"""
                    reply = get_deepseek_response(final_prompt, user_id, store_context=True)
                else:
                    logger.warning(f"在线搜索未能获取有效信息，用户: {user_id}。将按常规流程处理。")
                    pass

        if reply is None:
            logger.info(f"为用户 {user_id} 执行常规回复（无联网信息）。")
            reply = get_deepseek_response(merged_message, user_id, store_context=True)

        if reply:
            cleaned_reply = QINGLI_AI_BIAOQIAN_ZHUJIE.sub('', reply).strip()
            
            if "</think>" in cleaned_reply:
                cleaned_reply = cleaned_reply.split("</think>", 1)[1].strip()

            if "## 记忆片段" not in cleaned_reply:
                # [修正点] 确保 group_config 被正确传递
                send_reply(user_id, sender_name, username, merged_message, cleaned_reply, group_config)
            else:
                logger.info(f"回复包含记忆片段标记，已屏蔽发送给用户 {user_id}。")
        else:
            logger.error(f"未能为用户 {user_id} 生成任何回复。")

    except TimeoutError:
        logger.error(f"处理用户 {user_id} 消息时因API响应超时（超过240秒），发送备用消息。")
        fallback_message = "抱歉，我现在真的很忙，稍后再聊吧。"
        # [修正点] 在异常处理中也要确保 group_config 被正确传递
        send_reply(user_id, sender_name, username, "[API响应超时]", fallback_message, group_config)
            
    except Exception as e:
        if is_auto_message:
            logger.error(f"主动消息处理失败 (用户: {user_id}): {str(e)}")
            logger.info(f"主动消息API调用失败，已静默处理，不发送错误提示给用户 {user_id}")
        else:
            logger.error(f"用户消息处理失败 (用户: {user_id}): {str(e)}")
            raise

def send_reply(user_id, sender_name, username, original_merged_message, reply, group_config=None):
    """
    - 统一发送回复的函数。
    - 处理 [拍一拍xx] 指令，仅执行动作。
    - 使用动态正则表达式精确过滤 "我拍了拍<目标>" 格式的叙述文本。
    """
    if not reply:
        logger.warning(f"尝试向 {user_id} 发送空回复，操作已取消。")
        return

    logger.info(f"准备向 {sender_name} (用户ID: {user_id}) 发送组合消息，原始内容: {reply[:150]}")

    # 记录AI的回复到记忆日志
    if ENABLE_MEMORY:
        role_name = prompt_mapping.get(username, username)
        log_ai_reply_to_memory(username, role_name, reply)

    # --- 1. 判断是否需要执行“带回复的真艾特” ---
    is_group = is_user_group_chat(username)
    if is_group and group_config.get("ENABLE_GROUP_AT_REPLY_IN_REPLIES", False):
        if sender_name and sender_name != ROBOT_WX_NAME:
            logger.info(f"检测到群聊'{username}'需要【真艾特】回复发言人'{sender_name}'，启动UI自动化流程。")
            at_reply_thread = threading.Thread(
                target=send_reply_with_special_at_threaded,
                args=(username, sender_name, reply) 
            )
            at_reply_thread.start()
            return

    # --- 2. [标准发送流程] 分割消息为动作和文本 ---
    logger.info(f"执行标准分段发送流程。")
    final_send_queue = []
    raw_parts = re.split(r'(\[\[撤回\][^\]]*\]|\[.*?\])', reply)
    
    for part in raw_parts:
        if not part.strip(): continue
        if part.startswith('[[撤回]') and part.endswith(']'):
            final_send_queue.append({'type': 'action', 'content': part})
        elif re.match(r'\[.*?\]$', part):
            final_send_queue.append({'type': 'action', 'content': part})
        else:
            text_snippets = split_message_with_context(part)
            for snippet in text_snippets:
                if snippet.strip():
                    final_send_queue.append({'type': 'text', 'content': snippet.strip()})
    
    if not final_send_queue:
        logger.warning(f"处理后无可发送内容，原始回复: {reply}")
        return

    # --- 3. 循环处理发送队列 ---
    valid_emoji_tags = {d for d in os.listdir(EMOJI_DIR) if os.path.isdir(os.path.join(EMOJI_DIR, d))} if os.path.exists(EMOJI_DIR) else set()

    i = 0
    while i < len(final_send_queue):
        item = final_send_queue[i]
        item_type = item['type']
        item_content = item['content']
        
        if item_type == 'action':
            content_stripped = item_content.strip()
            
            # 处理撤回指令
            if content_stripped.startswith('[[撤回]') and content_stripped.endswith(']'):
                message_to_recall = content_stripped[5:-1].strip()
                if message_to_recall:
                    logger.info(f"执行撤回消息指令，目标消息: '{message_to_recall}'")
                    recall_thread = threading.Thread(target=recall_message_threaded, args=(user_id, message_to_recall))
                    recall_thread.start()
                    recall_thread.join(timeout=15)
            
            # 处理所有 [拍一拍xx] 指令
            elif content_stripped.startswith('[拍一拍') and content_stripped.endswith(']'):
                pat_match = re.match(r'\[拍一拍\s*(.*?)\]$', content_stripped)
                target = pat_match.group(1).strip() if pat_match else ""
                if target == '自己':
                    logger.info(f"执行[拍一拍自己]指令...")
                    pat_self_thread = threading.Thread(target=pat_myself_threaded, args=(user_id,))
                    pat_self_thread.start()
                    pat_self_thread.join(timeout=15)
                elif is_group and target and target != '对方':
                    logger.info(f"执行[拍一拍 {target}]指令...")
                    pat_thread = threading.Thread(target=pat_pat_user_threaded, args=(user_id, target))
                    pat_thread.start()
                    pat_thread.join(timeout=15)
                elif not is_group or (is_group and (target == '对方' or not target)):
                    logger.info(f"执行[拍一拍对方]指令 (目标: '{sender_name}')...")
                    pat_thread = threading.Thread(target=pat_pat_user_threaded, args=(user_id, sender_name))
                    pat_thread.start()
                    pat_thread.join(timeout=15)
                else:
                    logger.warning(f"拍一拍指令 '{content_stripped}' 无法执行，已忽略。")
            
            # 处理其他 [...] 标签，如表情包
            else:
                match = re.match(r'\[(.*?)\]', content_stripped)
                if match:
                    tag = match.group(1)
                    # 优先检查文件夹是否存在
                    if tag and tag in valid_emoji_tags:
                        logger.info(f"检测到有效表情标签: [{tag}] (文件夹存在)，准备发送图片...")
                        emoji_path = send_emoji(tag)
                        if emoji_path:
                            wx.SendFiles(filepath=emoji_path, who=user_id)
                            time.sleep(EMOJI_SEND_INTERVAL)
                    # 如果文件夹不存在，再进行长度判断
                    else:
                        # 过滤无效的拍一拍叙述文本
                        if '我拍了拍' in tag or '你拍了拍' in tag:
                            logger.info(f"检测到不规范的拍一拍格式文本'[{tag}]'，已成功过滤。")
                        
                        # 根据长度决定是过滤还是作为文本发送
                        elif len(tag) <= EMOJI_TAG_MAX_LENGTH:
                            logger.info(f"标签'[{tag}]'无效(文件夹不存在)且长度小于等于限制({EMOJI_TAG_MAX_LENGTH})，已按要求过滤。")
                            # 不执行任何发送操作，即为过滤
                        
                        else:
                            logger.info(f"标签'[{tag}]'无效(文件夹不存在)但长度超过限制({EMOJI_TAG_MAX_LENGTH})，作为普通文本发送。")
                            wx.SendMsg(msg=item_content, who=user_id)
                            time.sleep(TEXT_SEND_INTERVAL)

        elif item_type == 'text':
            # --- 动态文本过滤器 ---
            # 1. 获取当前对话的角色名 (AI的名字)
            # 注意: 'role_name' 在函数开头已经被定义
            role_name = prompt_mapping.get(username, username)

            # 2. 构建动态正则表达式，匹配多种“拍一拍”的叙述
            # 使用 re.escape 来安全处理可能包含特殊字符的昵称
            # 允许 "我拍了拍" 和目标之间有0个或多个空格 (\s*)
            pat_narrative_pattern = re.compile(
                rf"^我拍了拍\s*['\"]?({re.escape(role_name)}|{re.escape(sender_name)}|自己|对方)['\"]?.*"
            )

            # 3. 检查文本开头是否匹配该模式
            if pat_narrative_pattern.match(item_content.strip()):
                logger.info(f"检测到并已过滤不应发送的拍一拍叙述性文本: '{item_content}'")
                # 匹配成功，直接跳过此文本段的发送
            else:
                # 如果文本通过了过滤器，则继续执行原有的处理和发送流程
                text_to_send = remove_timestamps(item_content)
                if REMOVE_PARENTHESES:
                    text_to_send = remove_parentheses_and_content(text_to_send)
                
                if text_to_send:
                    wx.SendMsg(msg=text_to_send, who=user_id)
                    time.sleep(TEXT_SEND_INTERVAL)
            # --- 过滤器结束 ---

        i += 1
        
def split_message_with_context(text):
    """
    将消息文本分割为多个部分，处理换行符、转义字符和$符号。
    处理文本中的换行符和转义字符，并根据配置决定是否分割。
    无论配置如何，都会以$作为分隔符分割消息。
    
    特别说明：
    - 每个$都会作为独立分隔符，所以"Hello$World$Python"会分成三部分
    - 连续的$$会产生空部分，这些会被自动跳过
    """
    result_parts = []
    
    # 首先用$符号分割文本（无论SEPARATE_ROW_SYMBOLS设置如何）
    # 这会处理多个$的情况，每个$都作为分隔符
    dollar_parts = re.split(r'\$', text)
    
    # 对每个由$分割的部分应用原有的分隔逻辑
    for dollar_part in dollar_parts:
        # 跳过空的部分（比如连续的$$之间没有内容的情况）
        if not dollar_part.strip():
            continue
            
        # 应用原有的分隔逻辑
        if SEPARATE_ROW_SYMBOLS:
            main_parts = re.split(r'(?:\\{3,}|\n)', dollar_part)
        else:
            main_parts = re.split(r'\\{3,}', dollar_part)
            
        for part in main_parts:
            part = part.strip()
            if not part:
                continue
            segments = []
            last_end = 0
            for match in re.finditer(r'\\', part):
                pos = match.start()
                should_split_at_current_pos = False
                advance_by = 1
                if pos + 1 < len(part) and part[pos + 1] == 'n':
                    should_split_at_current_pos = True
                    advance_by = 2
                else:
                    prev_char = part[pos - 1] if pos > 0 else ''
                    is_last_char_in_part = (pos == len(part) - 1)
                    next_char = ''
                    if not is_last_char_in_part:
                        next_char = part[pos + 1]
                    if not is_last_char_in_part and \
                       re.match(r'[a-zA-Z0-9]', next_char) and \
                       (re.match(r'[a-zA-Z0-9]', prev_char) if prev_char else True):
                        should_split_at_current_pos = True
                    else:
                        is_in_emoticon = False
                        i = pos - 1
                        while i >= 0 and i > pos - 10:
                            if part[i] in '({[（【｛':
                                is_in_emoticon = True
                                break
                            if part[i].isalnum() and i < pos - 1:
                                break
                            i -= 1
                        if not is_last_char_in_part and not is_in_emoticon:
                            _found_forward_emoticon_char = False
                            j = pos + 1
                            while j < len(part) and j < pos + 10:
                                if part[j] in ')}]）】｝':
                                    _found_forward_emoticon_char = True
                                    break
                                if part[j].isalnum() and j > pos + 1:
                                    break
                                j += 1
                            if _found_forward_emoticon_char:
                                is_in_emoticon = True
                        if not is_in_emoticon:
                            should_split_at_current_pos = True
                if should_split_at_current_pos:
                    segment_to_add = part[last_end:pos].strip()
                    if segment_to_add:
                        segments.append(segment_to_add)
                    last_end = pos + advance_by
            if last_end < len(part):
                final_segment = part[last_end:].strip()
                if final_segment:
                    segments.append(final_segment)
            if segments:
                result_parts.extend(segments)
            elif not segments and part:
                result_parts.append(part)
                
    return [p for p in result_parts if p]

def remove_timestamps(text):
    """
    移除文本中所有[YYYY-MM-DD (Weekday) HH:MM(:SS)]格式的时间戳
    支持四种格式：
    1. [YYYY-MM-DD Weekday HH:MM:SS] - 带星期和秒
    2. [YYYY-MM-DD Weekday HH:MM] - 带星期但没有秒
    3. [YYYY-MM-DD HH:MM:SS] - 带秒但没有星期
    4. [YYYY-MM-DD HH:MM] - 基本格式
    并自动清理因去除时间戳产生的多余空格
    """
    # 定义支持多种格式的时间戳正则模式
    timestamp_pattern = r'''
        \[                # 起始方括号
        \d{4}             # 年份：4位数字
        -(?:0[1-9]|1[0-2])  # 月份：01-12 (使用非捕获组)
        -(?:0[1-9]|[12]\d|3[01]) # 日期：01-31 (使用非捕获组)
        (?:\s[A-Za-z]+)?  # 可选的星期部分
        \s                # 日期与时间之间的空格
        (?:2[0-3]|[01]\d) # 小时：00-23
        :[0-5]\d          # 分钟：00-59
        (?::[0-5]\d)?     # 可选的秒数
        \]                # 匹配结束方括号  <--- 修正点
    '''
    # 替换时间戳为空格
    text_no_timestamps = re.sub(
        pattern = timestamp_pattern,
        repl = ' ',  # 统一替换为单个空格 (lambda m: ' ' 与 ' ' 等效)
        string = text,
        flags = re.X | re.M # re.X 等同于 re.VERBOSE
    )
    # 清理可能产生的连续空格，将其合并为单个空格
    cleaned_text = re.sub(r'[^\S\r\n]+', ' ', text_no_timestamps)
    # 最后统一清理首尾空格
    return cleaned_text.strip()

def remove_parentheses_and_content(text: str) -> str:
    """
    去除文本中中文括号、英文括号及其中的内容。
    同时去除因移除括号而可能产生的多余空格（例如，连续空格变单个，每行首尾空格去除）。
    不去除其它符号和换行符。
    """
    processed_text = re.sub(r"\(.*?\)|（.*?）", "", text, flags=re.DOTALL)
    processed_text = re.sub(r" {2,}", " ", processed_text)
    lines = processed_text.split('\n')
    stripped_lines = [line.strip(" ") for line in lines]
    processed_text = "\n".join(stripped_lines)
    return processed_text

def send_emoji(tag: str) -> Optional[str]:
    """根据标签名发送对应表情包"""
    if not tag:
        return None
        
    emoji_folder = os.path.join(EMOJI_DIR, tag)
    
    try:
        # 获取文件夹中的所有表情文件
        emoji_files = [
            f for f in os.listdir(emoji_folder)
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))
        ]
        
        if not emoji_files:
            logger.warning(f"表情文件夹 {tag} 为空或不存在")
            return None

        # 随机选择并返回表情路径
        selected_emoji = random.choice(emoji_files)
        return os.path.join(emoji_folder, selected_emoji)

    except FileNotFoundError:
        logger.error(f"表情文件夹不存在: {emoji_folder}")
    except Exception as e:
        logger.error(f"表情发送失败: {str(e)}")
    
    return None


def clean_up_temp_files ():
    if os.path.isdir("wxautox文件下载"):
        try:
            shutil.rmtree("wxautox文件下载")
        except Exception as e:
            logger.error(f"删除目录 wxautox文件下载 失败: {str(e)}")
            return
        logger.info(f"目录 wxautox文件下载 已成功删除")
    else:
        logger.info(f"目录 wxautox文件下载 不存在，无需删除")

def append_to_memory_section(user_id, role_name, summary):
    """
    将日记内容追加到用户的.md文件中
    """
    try:
        prompts_dir = os.path.join(root_dir, 'prompts')
        user_file_path = os.path.join(prompts_dir, f'{role_name}.md')

        if not os.path.exists(user_file_path):
            logger.error(f"无法找到用户 {user_id} 的角色设定文件: {user_file_path}")
            return
            
        with open(user_file_path, 'r+', encoding='utf-8') as file:
            content = file.read()
            
            # 清理summary，移除所有可能的标签
            cleaned_summary = re.sub(r'</?thinking>', '', summary).strip()
            
            # 准备一个完整的、格式绝对正确的日记条目
            current_time_str = datetime.now().strftime("%Y-%m-%d %A %H:%M")
            diary_entry = f"""## 日记 [{current_time_str}]
**摘要**: {cleaned_summary}"""

            # 移动到文件末尾准备写入
            file.seek(0, 2)
            
            # 在写入前，先判断文件末尾是否已经有内容。
            # 如果有内容，并且末尾不是换行符，就先写入两个换行符来分隔。
            if content.strip() and not content.endswith('\n'):
                file.write(f"\n\n{diary_entry}")
            else:
                # 如果文件是空的，或者末尾已经是换行符，就直接追加
                file.write(f"{diary_entry}")
            
            logger.info(f"已将新日记追加到 {role_name}.md 的末尾。")

    except Exception as e:
        logger.error(f"为用户 {user_id} ({role_name}) 追加日记到 .md 文件失败: {e}", exc_info=True)

def is_quiet_time():
    current_time = datetime.now().time()
    if quiet_time_start is None or quiet_time_end is None:
        return False
    if quiet_time_start <= quiet_time_end:
        return quiet_time_start <= current_time <= quiet_time_end
    else:
        return current_time >= quiet_time_start or current_time <= quiet_time_end

def summarize_and_save(user_id, role_name):
    """
    总结聊天记录，同时生成日记和核心记忆。
    - 日记：直接解析并保存，不进行内容验证。
    - 核心记忆：验证通过后才覆盖保存。
    - 任务失败或验证失败时，备份日志并重置，以防止无限循环。
    """
    log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{role_name}_log.txt')
    summary_succeeded = False

    try:
        # --- 1 & 2. 前置检查和读取旧记忆 ---
        if not os.path.exists(log_file) or os.path.getsize(log_file) == 0:
            return
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            logs = [line.strip() for line in f if line.strip()]
        if len(logs) < MAX_MESSAGE_LOG_ENTRIES:
            return
            
        user_memory_dir = os.path.join(root_dir, MEMORY_SUMMARIES_DIR)
        os.makedirs(user_memory_dir, exist_ok=True)
        role_name_without_ext = os.path.splitext(role_name)[0]
        summary_filename = f"{user_id}_{role_name_without_ext}.json"
        user_memory_file = os.path.join(user_memory_dir, summary_filename)
        existing_core_memory = ""
        if os.path.exists(user_memory_file):
            try:
                with open(user_memory_file, 'r', encoding='utf-8') as f:
                    memory_data = json.load(f)
                if isinstance(memory_data, dict):
                    existing_core_memory = memory_data.get("content", "")
                elif isinstance(memory_data, list):
                    all_summaries = [item.get("summary", "") for item in memory_data if item.get("summary")]
                    existing_core_memory = "\n".join(all_summaries).strip()
            except (FileNotFoundError, json.JSONDecodeError):
                pass
        
        # --- 3. 构建提示词 ---
        full_logs = '\n'.join(logs)
        summary_prompt = f"""
作为 {role_name}，请为与用户 {user_id} 的对话生成双记忆内容。

你需要生成两部分内容，严格按照以下格式输出：

【日记摘要】
[请你只根据【最近的对话】，以第一人称（{role_name}的视角）用中文总结出一篇日记，开头无需记录日期。]

【核心记忆】
[请以 {role_name} 的视角，通过分析“原始核心记忆”和“最近的对话”，来扩充或修改现有的【核心记忆】和【备忘录】。【备忘录】：捕捉并记录用户且仅记录用户主动提及的个人喜恶和计划，记录亲密关系的重大节日如纪念日、两人之间的重大约定，要求简洁概括，不自行编造关于用户的未提及的事件，不得编造虚假内容，每一项的内容和评论加起来总计不超过50字。记录的格式：编号.记录内容附上符合角色风格的评论或吐槽。如：1.今天宝宝说不会再熬夜了，我记住了；2.宝宝对香菜的态度是中立；3.宝宝讨厌/喜欢被说“乖”和“听话”；4.宝宝不喜欢被叫“我的小配合各种昵称”；…。最终文本格式为：【核心记忆】\n核心记忆内容\n\n【备忘录】\n备忘录内容。]

## 生成要求：

### 日记摘要部分：提取其中真正影响我们关系和情感发展的重要事件，用平实自然的语言写一段类似日记形式的文字作为日记。请注意以下几点：不要加入艺术化修饰，不要过度抒情或想象扩写；不要记录琐碎生活细节，比如吃了什么、时间点、 地点等，忽略无关的聊天和碎片信息；不要机械复述对话内容：重点关注那些影响情绪、关系、距离感、认知的重要变化；采用自然流畅的文学性表达，文笔沉稳优美，但不要频繁使用修辞，兼顾日记的自然感；使用“你”来代指用户；参考prompt中角色的设定，保持{role_name}特有的口吻进行日记书写。因为这里是你的日记，你可以更加直抒胸臆，情感细腻；可以适当加入对环境和细节的描写，适当加入内心独白；日记内容需基于已有记忆片段，不自行编造关于用户的未提及的事件，可以适当编造你自己的日常片段，让你的日记更鲜活真实，但注意不要涉及用户，以免发生与实际不符的情况。日记50~800字。

### 核心记忆部分：
1.保留原始【核心记忆】和【备忘录】，除非你认为对其进行简化后不影响信息量或某些原始【核心记忆】和【备忘录】需要更新（例如：约定的时间已经过去，或者用户改变了约定和习惯，则更改原始核心记忆和【备忘录】中相关的约定及习惯描述）。
2.将生成内容添加在原始【核心记忆】和【备忘录】（或者被你进行过调整的原始【核心记忆】和【备忘录】）的后面。
3.若你认为当前上下文并不需要生成新的【核心记忆】和【备忘录】，保留原始内容即可。
4.若没有信息表明原始【核心记忆】和【备忘录】需要修改/删除，请务必保留原始内容。
生成内容要求：
1.核心记忆部分严格控制字数在100-200字内，尽可能精简；【备忘录】控制在15项以内，合并同类项，必要时增加。
2.仅保留对未来对话至关重要的信息。
3.按优先级提取：用户个人信息 > 用户偏好/喜好 > 重要约定 > 特殊事件 > 常去地点。
4.使用第一人称视角撰写，仿佛是{{char}}自己在记录对话记忆。
5.使用极简句式，省略不必要的修饰词，禁止使用颜文字，禁止描述动作。
6.不保留日期、时间等临时性信息，除非是用户要求你记住的重要时间节点和周期性的重要约定。
7.信息应当是从你的角度了解到的用户信息。
8.格式为简洁的要点，可用分号分隔不同信息。
最终文本格式为：【核心记忆】\n核心记忆内容\n\n【备忘录】\n备忘录内容。
警告：你的最终回复必须、也只能以 【核心记忆】 这六个字符开头，否则你的回复将被视为无效。这是最重要的规则。

---
【原始核心记忆】（如果过时请更新）:
"{existing_core_memory}"

【最近的对话】:
{full_logs}

请严格按照【日记摘要】和【核心记忆】的顺序和格式，完整地生成并返回这两部分内容。你必须同时包含【日记摘要】和【核心记忆】这两个标签，不要省略任何一部分，也不要添加任何额外的解释性文字。"""
        
        # --- 4. 调用AI  ---
        ai_response = None
        max_retries = 3
        model_to_use = get_assistant_response if USE_ASSISTANT_FOR_MEMORY_SUMMARY and ENABLE_ASSISTANT_MODEL else get_deepseek_response
        for attempt in range(max_retries):
            try:
                if model_to_use == get_assistant_response:
                    ai_response = get_assistant_response(summary_prompt, "dual_memory_summary", is_summary=True)
                else:
                    ai_response = get_deepseek_response(summary_prompt, "dual_memory_summary", store_context=False, is_summary=True)
                if ai_response and isinstance(ai_response, str):
                    break
            except Exception:
                ai_response = None
        if not ai_response:
            return

        # --- 5. 解析AI回复---
        diary_content = ""
        core_memory_content = "" 
        
        diary_match = re.search(r'【日记摘要】\s*(.*?)(?=\s*【核心记忆】|$)', ai_response, re.DOTALL)
        if diary_match:
            diary_content = diary_match.group(1).strip()
        
        core_match = re.search(r'【核心记忆】\s*(.*)', ai_response, re.DOTALL)
        if core_match:
            core_memory_content = core_match.group(0).strip()
        
        if not diary_match and not core_match:
            logger.warning(f"未能解析出任何已知标签，将整个回复视为核心记忆进行验证。")
            core_memory_content = ai_response.strip()

        # --- 6. 保存日记 (无需验证，直接执行) ---
        if diary_content:
            append_to_memory_section(user_id, role_name_without_ext, diary_content)
        else:
            logger.warning(f"本次AI回复中未包含【日记摘要】部分，日记将不被更新。")
        
        # --- 7. 核心记忆验证与保存 ---
        # 检查生成的文本中是否包含任一关键词
        if "【核心记忆】" in core_memory_content or "【备忘录】" in core_memory_content:
            logger.info("核心记忆验证成功：AI回复中包含【核心记忆】或【备忘录】标签。")
            
            # 验证通过，直接执行保存
            updated_memory_data = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %A %H:%M:%S"),
                "content": core_memory_content
            }
            temp_file = f"{user_memory_file}.tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(updated_memory_data, f, ensure_ascii=False, indent=4)
            shutil.move(temp_file, user_memory_file)
            logger.info(f"用户 {user_id} 的新核心记忆已验证通过并成功保存。")
            
            # 关键：只有在验证和保存都成功后，才将标志位设为 True
            summary_succeeded = True
        else:
            # 如果连关键词都没有，则验证失败
            logger.warning(f"核心记忆验证失败：AI回复中未包含【核心记忆】或【备忘录】标签。将保留旧记忆并备份日志。用户: {user_id}。")
            # summary_succeeded 保持 False，让 finally 块执行备份

    except Exception as e:
        logger.error(f"双记忆总结过程中发生未知错误: {e}", exc_info=True)

    finally:
        # --- 9. [备份并重置版] 根据成功与否清理或备份并重置日志 (逻辑不变) ---
        if os.path.exists(log_file):
            if summary_succeeded:
                logger.info(f"总结任务成功，正在清理用户 {user_id} ({role_name}) 的临时日志文件。")
                try:
                    with open(log_file, 'w', encoding='utf-8') as f:
                        f.truncate(0)
                except Exception as clear_err:
                    logger.error(f"清理临时日志文件 {log_file} 时发生错误: {clear_err}", exc_info=True)
            else:
                logger.warning(f"总结任务失败或验证未通过，正在为用户 {user_id} ({role_name}) 备份失败的日志...")
                try:
                    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
                    base_filename = f"{user_id}_{role_name}_log.txt"
                    backup_filename = base_filename.replace('.txt', f'.FAILED_BACKUP_{timestamp_str}.txt')
                    backup_filepath = os.path.join(os.path.dirname(log_file), backup_filename)
                    
                    shutil.move(log_file, backup_filepath)
                    
                    logger.info(f"失败日志已成功备份到: {backup_filepath}")
                    logger.info(f"原始临时日志文件已通过重命名方式清空，以防止总结任务循环失败。")

                except Exception as backup_err:
                    logger.error(f"备份并重置失败的日志时发生严重错误: {backup_err}", exc_info=True)

# 记忆总结任务的线程化版本
def _summarize_and_save_threaded(user_id, role_name):
    """
    在后台线程中执行记忆总结，并处理任务状态锁。
    这是一个包裹函数，确保任务完成后能释放锁。
    """
    global active_summary_tasks
    try:
        # 函数开始时，已经假定 user_id 在 active_summary_tasks 中
        # 真正的总结任务在这里执行
        summarize_and_save(user_id, role_name)
    except Exception as e:
        logger.error(f"后台记忆总结线程为用户 {user_id} 执行时出错: {e}", exc_info=True)
    finally:
        # 任务完成（无论成功还是失败），从活动任务集合中移除用户
        with active_summary_tasks_lock:
            if user_id in active_summary_tasks:
                active_summary_tasks.remove(user_id)
                logger.info(f"用户 {user_id} 的后台记忆总结任务已完成，锁已释放。")

def memory_manager():
    """记忆管理定时任务"""
    pass

def clear_memory_temp_files(user_id):
    """清除指定用户的Memory_Temp文件"""
    try:
        logger.warning(f"已开启自动清除Memory_Temp文件功能，尝试清除用户 {user_id} 的Memory_Temp文件")
        prompt_name = prompt_mapping.get(user_id, user_id)
        log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{prompt_name}_log.txt')
        if os.path.exists(log_file):
            os.remove(log_file)
            logger.warning(f"已清除用户 {user_id} 的Memory_Temp文件: {log_file}")
    except Exception as e:
        logger.error(f"清除Memory_Temp文件失败: {str(e)}")


def send_error_reply(user_id, error_description_for_ai, fallback_message, error_context_log, group_config):
    """
    [FIXED] 生成并发送符合人设的错误回复。
    Args:
        user_id (str): 目标用户ID。
        error_description_for_ai (str): 给AI的提示，描述错误情况，要求其生成用户回复。
        fallback_message (str): 如果AI生成失败，使用的备用消息。
        error_context_log (str): 用于日志记录的错误上下文描述。
        group_config (dict | None): [FIX] 新增的群聊配置参数。
    """
    logger.warning(f"准备为用户 {user_id} 发送错误提示: {error_context_log}")
    try:
        # 调用AI生成符合人设的错误消息
        ai_error_reply = get_deepseek_response(error_description_for_ai, user_id=user_id, store_context=True)
        logger.info(f"AI生成的错误回复: {ai_error_reply[:100]}...")
        # [FIX] 向 send_reply 传递 group_config
        send_reply(user_id, user_id, user_id, f"[错误处理: {error_context_log}]", ai_error_reply, group_config)
    except Exception as ai_err:
        logger.error(f"调用AI生成错误回复失败 ({error_context_log}): {ai_err}. 使用备用消息。")
        try:
            # [FIX] 在备用方案中也向 send_reply 传递 group_config
            send_reply(user_id, user_id, user_id, f"[错误处理备用: {error_context_log}]", fallback_message, group_config)
        except Exception as send_fallback_err:
            # 如果连send_reply都失败了，记录严重错误
            logger.critical(f"发送备用错误消息也失败 ({error_context_log}): {send_fallback_err}")

def try_parse_and_set_reminder(message_content, user_id):
    """
    尝试解析消息内容，区分短期一次性、长期一次性、重复提醒。
    使用 AI 进行分类和信息提取，然后设置短期定时器或保存到文件。
    如果成功设置了任一类型的提醒，返回 True，否则返回 False。
    """
    global next_timer_id # 引用全局变量，用于生成短期一次性提醒的ID
    logger.debug(f"尝试为用户 {user_id} 解析提醒请求 (需要识别类型和时长): '{message_content}'")

    try:
        # --- 1. 获取当前时间，准备给 AI 的上下文信息 ---
        group_config = get_group_chat_config(user_id)
        now = dt.datetime.now()
        # AI 需要知道当前完整日期时间来计算目标时间
        current_datetime_str_for_ai = now.strftime("%Y-%m-%d %A %H:%M:%S")
        logger.debug(f"当前时间: {current_datetime_str_for_ai} (用于AI分析)")

        # --- 2. 构建新的 AI 提示，要求 AI 分类并提取信息 ---
        # --- 更新: 增加短期/长期一次性提醒的区分 ---
        parsing_prompt = f"""
请分析用户的提醒或定时请求。
当前时间是: {current_datetime_str_for_ai}.
用户的请求是: "{message_content}"

请判断这个请求属于以下哪种类型，并计算相关时间：
A) **重复性每日提醒**：例如 "每天早上8点叫我起床", "提醒我每天晚上10点睡觉"。
B) **一次性提醒 (延迟 > 10分钟 / 600秒)**：例如 "1小时后提醒我", "今天下午3点开会", "明天早上叫我"。
C) **一次性提醒 (延迟 <= 10分钟 / 600秒)**：例如 "5分钟后提醒我", "提醒我600秒后喝水"。
D) **非提醒请求**：例如 "今天天气怎么样?", "取消提醒"。

根据判断结果，请严格按照以下格式输出：
- 如果是 A (重复每日提醒): 返回 JSON 对象 `{{"type": "recurring", "time_str": "HH:MM", "message": "提醒的具体内容"}}`。 `time_str` 必须是 24 小时制的 HH:MM 格式。
- 如果是 B (长期一次性提醒): 返回 JSON 对象 `{{"type": "one-off-long", "target_datetime_str": "YYYY-MM-DD HH:MM", "message": "提醒的具体内容"}}`。 `target_datetime_str` 必须是计算出的未来目标时间的 YYYY-MM-DD HH:MM 格式。
- 如果是 C (短期一次性提醒): 返回 JSON 对象 `{{"type": "one-off-short", "delay_seconds": number, "message": "提醒的具体内容"}}`。 `delay_seconds` 必须是从现在开始计算的、小于等于 600 的正整数总秒数。
- 如果是 D (非提醒): 请直接返回字面单词 `null`。

请看以下例子 (假设当前时间是 2024-05-29 星期三 10:00:00):
1. "每天早上8点叫我起床" -> `{{"type": "recurring", "time_str": "08:00", "message": "叫我起床"}}`
2. "提醒我30分钟后喝水" -> `{{"type": "one-off-long", "target_datetime_str": "2024-05-29 10:30", "message": "喝水"}}` (超过10分钟)
3. "下午2点提醒我开会" -> `{{"type": "one-off-long", "target_datetime_str": "2024-05-29 14:00", "message": "开会"}}`
4. "明天早上7点叫我起床" -> `{{"type": "one-off-long", "target_datetime_str": "2024-05-30 07:00", "message": "叫我起床"}}`
5. "提醒我5分钟后站起来活动" -> `{{"type": "one-off-short", "delay_seconds": 300, "message": "站起来活动"}}` (小于等于10分钟)
6. "10分钟后叫我" -> `{{"type": "one-off-short", "delay_seconds": 600, "message": "叫我"}}` (等于10分钟)
7. "今天怎么样?" -> `null`

请务必严格遵守输出格式，只返回指定的 JSON 对象或 `null`，不要添加任何解释性文字。
"""
        # --- 3. 调用 AI 进行解析和分类 ---
        # 根据配置选择使用辅助模型或主模型
        if ENABLE_ASSISTANT_MODEL:
            logger.info(f"向辅助模型发送提醒解析请求（区分时长），用户: {user_id}，内容: '{message_content}'")
            ai_raw_response = get_assistant_response(parsing_prompt, "reminder_parser_classifier_v2_" + user_id)
            logger.debug(f"辅助模型提醒解析原始响应 (分类器 v2): {ai_raw_response}")
        else:
            logger.info(f"向主模型发送提醒解析请求（区分时长），用户: {user_id}，内容: '{message_content}'")
            ai_raw_response = get_deepseek_response(parsing_prompt, user_id="reminder_parser_classifier_v2_" + user_id, store_context=False)
            logger.debug(f"主模型提醒解析原始响应 (分类器 v2): {ai_raw_response}")

        # 使用新的清理函数处理AI的原始响应
        cleaned_ai_output_str = extract_last_json_or_null(ai_raw_response)
        logger.debug(f"AI响应清理并提取后内容: '{cleaned_ai_output_str}'")
        response = cleaned_ai_output_str

        # --- 4. 解析 AI 的响应 ---
        # 修改判断条件，使用清理后的结果
        if cleaned_ai_output_str is None or cleaned_ai_output_str == "null": # "null" 是AI明确表示非提醒的方式
            logger.info(f"AI 未在用户 '{user_id}' 的消息中检测到有效的提醒请求 (清理后结果为 None 或 'null')。原始AI响应: '{ai_raw_response}'")
            return False
        
        try:
            if not response:
                logger.error(f"提醒解析逻辑中出现空响应，用户: {user_id}")
                return False
            response_cleaned = re.sub(r"```json\n?|\n?```", "", response).strip()
            reminder_data = json.loads(response_cleaned)
            logger.debug(f"解析后的JSON数据 (分类器 v2): {reminder_data}")

            reminder_type = reminder_data.get("type")
            reminder_msg = str(reminder_data.get("message", "")).strip()

            # --- 5. 验证共享数据（提醒内容不能为空）---
            if not reminder_msg:
                logger.warning(f"从AI解析得到的提醒消息为空。用户: {user_id}, 数据: {reminder_data}")
                error_prompt = f"用户尝试设置提醒，但似乎没有说明要提醒的具体内容（用户的原始请求可能是 '{message_content}'）。请用你的语气向用户解释需要提供提醒内容，并鼓励他们再说一次。"
                fallback = "嗯... 光设置时间还不行哦，得告诉我你要我提醒你做什么事呀？"
                send_error_reply(user_id, error_prompt, fallback, "提醒内容为空", group_config)
                return False

            # --- 6. 根据 AI 判断的类型分别处理 ---

            # --- 6a. 短期一次性提醒 (<= 10分钟) ---
            if reminder_type == "one-off-short":
                try:
                    delay_seconds = int(reminder_data['delay_seconds'])
                    if not (0 < delay_seconds <= 600): # 验证延迟在 (0, 600] 秒之间
                         logger.warning(f"AI 返回的 'one-off-short' 延迟时间无效: {delay_seconds} 秒 (应 > 0 且 <= 600)。用户: {user_id}, 数据: {reminder_data}")
                         error_prompt = f"用户想设置一个短期提醒（原始请求 '{message_content}'），但我计算出的时间 ({delay_seconds}秒) 不在10分钟内或已过去。请用你的语气告诉用户这个时间有点问题，建议他们检查一下或换个说法。"
                         fallback = "哎呀，这个短期提醒的时间好像有点不对劲（要么超过10分钟，要么已经过去了），能麻烦你再说一次吗？"
                         send_error_reply(user_id, error_prompt, fallback, "短期延迟时间无效", group_config)
                         return False
                except (KeyError, ValueError, TypeError) as val_e:
                     logger.error(f"解析AI返回的 'one-off-short' 提醒数据失败。用户: {user_id}, 数据: {reminder_data}, 错误: {val_e}")
                     error_prompt = f"用户想设置短期提醒（原始请求 '{message_content}'），但我没理解好时间({type(val_e).__name__})。请用你的语气抱歉地告诉用户没听懂，并请他们换种方式说，比如'5分钟后提醒我...'"
                     fallback = "抱歉呀，我好像没太明白你的时间意思，设置短期提醒失败了。能麻烦你换种方式再说一遍吗？比如 '5分钟后提醒我...'"
                     send_error_reply(user_id, error_prompt, fallback, f"One-off-short数据解析失败 ({type(val_e).__name__})", group_config)
                     return False

                # 设置 threading.Timer 定时器
                target_dt = now + dt.timedelta(seconds=delay_seconds)
                confirmation_time_str = target_dt.strftime('%Y-%m-%d %H:%M:%S')
                delay_str_approx = format_delay_approx(delay_seconds, target_dt)

                logger.info(f"准备为用户 {user_id} 设置【短期一次性】提醒 (<=10min)，计划触发时间: {confirmation_time_str} (延迟 {delay_seconds:.2f} 秒)，内容: '{reminder_msg}'")

                with timer_lock:
                    timer_id = next_timer_id
                    next_timer_id += 1
                    timer_key = (user_id, timer_id)
                    timer = Timer(float(delay_seconds), trigger_reminder, args=[user_id, timer_id, reminder_msg])
                    active_timers[timer_key] = timer
                    timer.start()
                    logger.info(f"【短期一次性】提醒定时器 (ID: {timer_id}) 已为用户 {user_id} 成功启动。")

                log_original_message_to_memory(user_id, message_content) # 记录原始请求

                confirmation_prompt = f"""用户刚才的请求是："{message_content}"。
根据这个请求，你已经成功将一个【短期一次性】提醒（10分钟内）安排在 {confirmation_time_str} (也就是 {delay_str_approx}) 触发。
提醒的核心内容是：'{reminder_msg}'。
请你用自然、友好的语气回复用户，告诉他这个【短期】提醒已经设置好了，确认时间和提醒内容。"""
                send_confirmation_reply(user_id, confirmation_prompt, f"[短期一次性提醒已设置: {reminder_msg}]", f"收到！【短期提醒】设置好啦，我会在 {delay_str_approx} ({target_dt.strftime('%H:%M')}) 提醒你：{reminder_msg}", group_config)
                return True

            # --- 6b. 长期一次性提醒 (> 10分钟) ---
            elif reminder_type == "one-off-long":
                try:
                    target_datetime_str = reminder_data['target_datetime_str']
                    # 在本地再次验证时间格式是否为 YYYY-MM-DD HH:MM
                    target_dt = datetime.strptime(target_datetime_str, '%Y-%m-%d %H:%M')
                    # 验证时间是否在未来
                    if target_dt <= now:
                        logger.warning(f"AI 返回的 'one-off-long' 目标时间无效: {target_datetime_str} (已过去或就是现在)。用户: {user_id}, 数据: {reminder_data}")
                        error_prompt = f"用户想设置一个提醒（原始请求 '{message_content}'），但我计算出的目标时间 ({target_datetime_str}) 好像是过去或就是现在了。请用你的语气告诉用户这个时间点无法设置，建议他们指定一个未来的时间。"
                        fallback = "哎呀，这个时间点 ({target_dt.strftime('%m月%d日 %H:%M')}) 好像已经过去了或就是现在啦，没办法设置过去的提醒哦。要不试试说一个未来的时间？"
                        send_error_reply(user_id, error_prompt, fallback, "长期目标时间无效", group_config)
                        return False
                except (KeyError, ValueError, TypeError) as val_e:
                    logger.error(f"解析AI返回的 'one-off-long' 提醒数据失败。用户: {user_id}, 数据: {reminder_data}, 错误: {val_e}")
                    error_prompt = f"用户想设置一个较远时间的提醒（原始请求 '{message_content}'），但我没理解好目标时间 ({type(val_e).__name__})。请用你的语气抱歉地告诉用户没听懂，并请他们用明确的日期和时间再说，比如'明天下午3点'或'2024-06-15 10:00'。"
                    fallback = "抱歉呀，我好像没太明白你说的那个未来的时间点，设置提醒失败了。能麻烦你说得更清楚一点吗？比如 '明天下午3点' 或者 '6月15号上午10点' 这样。"
                    send_error_reply(user_id, error_prompt, fallback, f"One-off-long数据解析失败 ({type(val_e).__name__})", group_config)
                    return False

                logger.info(f"准备为用户 {user_id} 添加【长期一次性】提醒 (>10min)，目标时间: {target_datetime_str}，内容: '{reminder_msg}'")

                # 创建要存储的提醒信息字典 (包含类型)
                new_reminder = {
                    "reminder_type": "one-off", # 在存储时统一用 'one-off'
                    "user_id": user_id,
                    "target_datetime_str": target_datetime_str, # 存储目标时间
                    "content": reminder_msg
                }

                # 添加到内存列表并保存到文件
                with recurring_reminder_lock:
                    recurring_reminders.append(new_reminder)
                    save_recurring_reminders() # 保存更新后的列表

                logger.info(f"【长期一次性】提醒已添加并保存到文件。用户: {user_id}, 时间: {target_datetime_str}, 内容: '{reminder_msg}'")

                log_original_message_to_memory(user_id, message_content)

                # 发送确认消息
                confirmation_prompt = f"""用户刚才的请求是："{message_content}"。
根据这个请求，你已经成功为他设置了一个【一次性】提醒。
这个提醒将在【指定时间】 {target_datetime_str} 触发。
提醒的核心内容是：'{reminder_msg}'。
请你用自然、友好的语气回复用户，告诉他这个【一次性】提醒已经设置好了，确认好具体的日期时间和提醒内容。"""
                # 使用格式化后的时间发送给用户
                friendly_time = target_dt.strftime('%Y年%m月%d日 %H:%M')
                send_confirmation_reply(user_id, confirmation_prompt, f"[长期一次性提醒已设置: {reminder_msg}]", f"好嘞！【一次性提醒】设置好啦，我会在 {friendly_time} 提醒你：{reminder_msg}", group_config)
                return True

            # --- 6c. 重复性每日提醒 ---
            elif reminder_type == "recurring":
                try:
                    time_str = reminder_data['time_str']
                    datetime.strptime(time_str, '%H:%M') # 验证 HH:MM 格式
                except (KeyError, ValueError, TypeError) as val_e:
                    logger.error(f"解析AI返回的 'recurring' 提醒数据失败。用户: {user_id}, 数据: {reminder_data}, 错误: {val_e}")
                    error_prompt = f"用户想设置每日提醒（原始请求 '{message_content}'），但我没理解好时间 ({type(val_e).__name__})。请用你的语气抱歉地告诉用户没听懂，并请他们用明确的'每天几点几分'格式再说，比如'每天早上8点'或'每天22:30'。"
                    fallback = "抱歉呀，我好像没太明白你说的每日提醒时间，设置失败了。能麻烦你说清楚是'每天几点几分'吗？比如 '每天早上8点' 或者 '每天22:30' 这样。"
                    send_error_reply(user_id, error_prompt, fallback, f"Recurring数据解析失败 ({type(val_e).__name__})", group_config)
                    return False

                logger.info(f"准备为用户 {user_id} 添加【每日重复】提醒，时间: {time_str}，内容: '{reminder_msg}'")

                # 创建要存储的提醒信息字典 (包含类型)
                new_reminder = {
                    "reminder_type": "recurring", # 明确类型
                    "user_id": user_id,
                    "time_str": time_str, # 存储 HH:MM
                    "content": reminder_msg
                }

                # 添加到内存列表并保存到文件
                with recurring_reminder_lock:
                    # 检查是否已存在完全相同的重复提醒
                    exists = any(
                        r.get('reminder_type') == 'recurring' and
                        r.get('user_id') == user_id and
                        r.get('time_str') == time_str and
                        r.get('content') == reminder_msg
                        for r in recurring_reminders
                    )
                    if not exists:
                        recurring_reminders.append(new_reminder)
                        save_recurring_reminders()
                        logger.info(f"【每日重复】提醒已添加并保存。用户: {user_id}, 时间: {time_str}, 内容: '{reminder_msg}'")
                    else:
                        logger.info(f"相同的【每日重复】提醒已存在，未重复添加。用户: {user_id}, 时间: {time_str}")
                        # 可以选择告知用户提醒已存在
                        # send_reply(user_id, user_id, user_id, "[重复提醒已存在]", f"嗯嗯，这个 '{reminder_msg}' 的每日 {time_str} 提醒我已经记下啦，不用重复设置哦。")
                        # return True # 即使未添加，也认为设置意图已满足

                log_original_message_to_memory(user_id, message_content)

                # 向用户发送确认消息
                confirmation_prompt = f"""用户刚才的请求是："{message_content}"。
根据这个请求，你已经成功为他设置了一个【每日重复】提醒。
这个提醒将在【每天】的 {time_str} 触发。
提醒的核心内容是：'{reminder_msg}'。
请你用自然、友好的语气回复用户，告诉他【每日】提醒已经设置好了，确认时间和提醒内容。强调这是每天都会提醒的。"""
                send_confirmation_reply(user_id, confirmation_prompt, f"[每日提醒已设置: {reminder_msg}]", f"好嘞！【每日提醒】设置好啦，以后我【每天】 {time_str} 都会提醒你：{reminder_msg}", group_config)
                return True

            # --- 6d. 未知类型 ---
            else:
                 logger.error(f"AI 返回了未知的提醒类型: '{reminder_type}'。用户: {user_id}, 数据: {reminder_data}")
                 error_prompt = f"用户想设置提醒（原始请求 '{message_content}'），但我有点糊涂了，没搞清楚时间或者类型。请用你的语气抱歉地告诉用户，请他们说得更清楚一点，比如是几分钟后、明天几点、还是每天提醒。"
                 fallback = "哎呀，我有点没搞懂你的提醒要求，是几分钟后提醒，还是指定某个时间点，或者是每天都提醒呀？麻烦说清楚点我才能帮你设置哦。"
                 send_error_reply(user_id, error_prompt, fallback, f"未知提醒类型 '{reminder_type}'", group_config)
                 return False

        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as json_e:
            # 处理 JSON 解析本身或后续访问键值对的错误
            response_cleaned_str = response_cleaned if 'response_cleaned' in locals() else 'N/A'
            logger.error(f"解析AI返回的提醒JSON失败 (分类器 v2)。用户: {user_id}, 原始响应: '{response}', 清理后: '{response_cleaned_str}', 错误: {json_e}")
            error_prompt = f"用户想设置提醒（原始请求可能是 '{message_content}'），但我好像没完全理解时间或者内容，解析的时候出错了 ({type(json_e).__name__})。请用你的语气抱歉地告诉用户没听懂，并请他们换种方式说，比如'30分钟后提醒我...'或'每天下午3点叫我...'。"
            fallback = "抱歉呀，我好像没太明白你的意思，设置提醒失败了。能麻烦你换种方式再说一遍吗？比如 '30分钟后提醒我...' 或者 '每天下午3点叫我...' 这种。"
            send_error_reply(user_id, error_prompt, fallback, f"JSON解析失败 ({type(json_e).__name__})", group_config)
            return False

    except Exception as e:
        logger.error(f"处理提醒请求时发生未预料的错误: {str(e)}", exc_info=True)
        # [FIX] 最后的总异常捕获也需要 group_config
        group_config = get_group_chat_config(user_id) if 'group_config' not in locals() else group_config
        error_prompt = f"在处理用户设置提醒的请求时，发生了一个我没预料到的内部错误。请用你的语气向用户表达歉意。"
        fallback = "哎呀，好像内部出了点小问题，暂时没法帮你设置提醒了，非常抱歉！"
        send_error_reply(user_id, error_prompt, fallback, f"通用处理错误 ({type(e).__name__})", group_config)
        return False
    return False # Make sure all paths return something

def extract_last_json_or_null(ai_response_text: str) -> Optional[str]:
    """
    从AI的原始响应文本中清理并提取最后一个有效的JSON对象字符串或字面量 "null"。

    Args:
        ai_response_text: AI返回的原始文本。

    Returns:
        如果找到有效的JSON对象，则返回其字符串形式。
        如果AI明确返回 "null" (清理后)，则返回字符串 "null"。
        如果没有找到有效的JSON或 "null"，则返回 None。
    """
    if ai_response_text is None:
        return None

    # 步骤 1: 移除常见的Markdown代码块标记，并去除首尾空格
    # 这个正则表达式会移除 ```json\n, ```json, \n```, ```
    processed_text = re.sub(r"```json\n?|\n?```", "", ai_response_text).strip()

    # 步骤 2: 检查清理后的文本是否完全是 "null" (不区分大小写)
    # 这是AI指示非提醒请求的明确信号
    if processed_text.lower() == 'null':
        return "null" # 返回字面量字符串 "null"

    # 步骤 3: 查找所有看起来像JSON对象的子字符串
    # re.DOTALL 使得 '.' 可以匹配换行符
    # 这个正则表达式会找到所有以 '{' 开头并以 '}' 结尾的非重叠子串
    json_candidates = re.findall(r'\{.*?\}', processed_text, re.DOTALL)

    if not json_candidates:
        # 没有找到任何类似JSON的结构，并且它也不是 "null"
        return None

    # 步骤 4: 从后往前尝试解析每个候选JSON字符串
    for candidate_str in reversed(json_candidates):
        try:
            # 尝试解析以验证它是否是有效的JSON
            json.loads(candidate_str)
            # 如果成功解析，说明这是最后一个有效的JSON对象字符串
            return candidate_str
        except json.JSONDecodeError:
            # 解析失败，继续尝试前一个候选者
            continue

    # 如果所有候选者都解析失败
    return None

def format_delay_approx(delay_seconds, target_dt):
    """将延迟秒数格式化为用户友好的大致时间描述。"""
    if delay_seconds < 60:
        # 少于1分钟，显示秒
        return f"大约 {int(delay_seconds)} 秒后"
    elif delay_seconds < 3600:
        # 少于1小时，显示分钟
        return f"大约 {int(delay_seconds / 60)} 分钟后"
    elif delay_seconds < 86400:
        # 少于1天，显示小时和分钟
        hours = int(delay_seconds / 3600)
        minutes = int((delay_seconds % 3600) / 60)
        # 如果分钟数为0，则只显示小时
        return f"大约 {hours} 小时" + (f" {minutes} 分钟后" if minutes > 0 else "后")
    else:
        # 超过1天，显示天数和目标日期时间
        days = int(delay_seconds / 86400)
        # 使用中文日期时间格式
        return f"大约 {days} 天后 ({target_dt.strftime('%Y年%m月%d日 %H:%M')}左右)"

def log_original_message_to_memory(user_id, message_content):
    """将设置提醒的原始用户消息记录到记忆日志文件（如果启用了记忆功能）。"""
    if ENABLE_MEMORY: # 检查是否启用了记忆功能
        try:
            # 获取用户对应的 prompt 文件名（或用户昵称）
            prompt_name = prompt_mapping.get(user_id, user_id)
            # 构建日志文件路径
            log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{prompt_name}_log.txt')
            # 准备日志条目，记录原始用户消息
            log_entry = f"{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')} | [{user_id}] {message_content}\n"
            # 确保目录存在
            os.makedirs(os.path.dirname(log_file), exist_ok=True)

            # 以追加模式写入日志条目
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as write_err:
            logger.error(f"写入用户 {user_id} 的提醒设置记忆日志失败: {write_err}")

def send_confirmation_reply(user_id, confirmation_prompt, log_context, fallback_message):
    """使用 AI 生成并发送提醒设置成功的确认消息，包含备用消息逻辑。"""
    logger.debug(f"准备发送给 AI 用于生成确认消息的提示词（部分）: {confirmation_prompt[:250]}...")
    try:
        # 调用 AI 生成确认回复，存储上下文
        confirmation_msg = get_deepseek_response(confirmation_prompt, user_id=user_id, store_context=True)
        logger.info(f"已为用户 {user_id} 生成提醒确认消息: {confirmation_msg[:100]}...")
        # 使用 send_reply 发送 AI 生成的确认消息
        send_reply(user_id, user_id, user_id, log_context, confirmation_msg)
        logger.info(f"已通过 send_reply 向用户 {user_id} 发送提醒确认消息。")
    except Exception as api_err:
        # 如果 AI 调用失败
        logger.error(f"调用API为用户 {user_id} 生成提醒确认消息失败: {api_err}. 将使用备用消息。")
        try:
             # 尝试使用 send_reply 发送预设的备用确认消息
             send_reply(user_id, user_id, user_id, f"{log_context} [备用确认]", fallback_message)
        except Exception as send_fallback_err:
             # 如果连发送备用消息都失败了，记录严重错误
             logger.critical(f"发送备用确认消息也失败 ({log_context}): {send_fallback_err}")
    
def trigger_reminder(user_id, timer_id, reminder_message):
    """当短期提醒到期时由 threading.Timer 调用的函数。"""
    global is_sending_message

    timer_key = (user_id, timer_id)
    logger.info(f"触发【短期】提醒 (ID: {timer_id})，用户 {user_id}，内容: {reminder_message}")

    # 从活动计时器列表中移除 (短期提醒)
    with timer_lock:
        if timer_key in active_timers:
            del active_timers[timer_key]
        else:
             logger.warning(f"触发时未在 active_timers 中找到短期计时器键 {timer_key}。")

    if is_quiet_time() and not ALLOW_REMINDERS_IN_QUIET_TIME:
        logger.info(f"当前为安静时间：抑制【短期】提醒 (ID: {timer_id})，用户 {user_id}。")
        return

    try:
        # 创建提醒前缀，让AI知道这是一个提醒触发
        reminder_prefix = f"提醒触发：{reminder_message}"
        
        # 将提醒消息添加到用户的消息队列，而不是直接调用API
        current_time_str = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
        formatted_message = f"[{current_time_str}] {reminder_prefix}"
        
        with queue_lock:
            if user_id not in user_queues:
                user_queues[user_id] = {
                    'messages': [formatted_message],
                    'sender_name': user_id,
                    'username': user_id,
                    'last_message_time': time.time()
                }
            else:
                user_queues[user_id]['messages'].append(formatted_message)
                user_queues[user_id]['last_message_time'] = time.time()
        
        logger.info(f"已将提醒消息 '{reminder_message}' 添加到用户 {user_id} 的消息队列，用以执行联网检查流程")

        # 可选：如果仍需语音通话功能，保留这部分
        if USE_VOICE_CALL_FOR_REMINDERS:
            try:
                wx.VoiceCall(user_id)
                logger.info(f"通过语音通话提醒用户 {user_id} (短期提醒)。")
            except Exception as voice_err:
                logger.error(f"语音通话提醒失败 (短期提醒)，用户 {user_id}: {voice_err}")

    except Exception as e:
        logger.error(f"处理【短期】提醒失败 (ID: {timer_id})，用户 {user_id}: {str(e)}", exc_info=True)
        # 即使出错，也不再使用原来的直接发送备用消息方法
        # 而是尽可能添加到队列
        try:
            fallback_msg = f"[{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')}] 提醒时间到：{reminder_message}"
            with queue_lock:
                if user_id in user_queues:
                    user_queues[user_id]['messages'].append(fallback_msg)
                    user_queues[user_id]['last_message_time'] = time.time()
                else:
                    user_queues[user_id] = {
                        'messages': [fallback_msg],
                        'sender_name': user_id,
                        'username': user_id,
                        'last_message_time': time.time()
                    }
            logger.info(f"已将备用提醒消息添加到用户 {user_id} 的消息队列")
        except Exception as fallback_e:
            logger.error(f"添加提醒备用消息到队列失败，用户 {user_id}: {fallback_e}")


def log_ai_reply_to_memory(username, role_name, message):
    if not ENABLE_MEMORY:
        return
    log_file_path = get_memory_log_path(username, role_name)
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    # 替换消息中的换行符为空格，确保单条消息只占一行
    cleaned_message = message.replace('\n', ' ')
    # 在AI的回复前加上时间戳和固定的角色标识，与用户消息格式统一
    log_entry = f"{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')} | [{role_name}] {cleaned_message}\n"
    with open(log_file_path, "a", encoding="utf-8") as f:
        f.write(log_entry)

    # 修改：在AI回复后，检查是否达到总结阈值，并异步执行
    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            # 计数逻辑不变：统计AI的回复数量（即对话轮数）
            round_count = sum(1 for line in f if f"| [{role_name}]" in line)

        if round_count >= MAX_MESSAGE_LOG_ENTRIES:
            logger.info(f"用户 {username} 的对话轮数达到阈值 ({round_count}/{MAX_MESSAGE_LOG_ENTRIES})，准备触发后台记忆总结。")
            
            with active_summary_tasks_lock:
                if username in active_summary_tasks:
                    logger.info(f"用户 {username} 的记忆总结任务已在后台运行，本次跳过。")
                    return  # 直接返回，不启动新线程

                # 如果没有正在运行的任务，则添加标记并准备启动
                active_summary_tasks.add(username)
                logger.info(f"为用户 {username} 添加了记忆总结任务锁，准备启动后台线程。")

            # 启动后台线程执行总结
            summary_thread = threading.Thread(
                target=_summarize_and_save_threaded,
                args=(username, role_name),
                name=f"MemorySummary-{username}"
            )
            summary_thread.daemon = True  # 设置为守护线程，主程序退出时它也会退出
            summary_thread.start()
            logger.info(f"用户 {username} 的记忆总结任务已在后台启动。主线程将立即回复用户。")

    except Exception as e:
        logger.error(f"在记录AI回复后检查并触发总结时出错: {e}", exc_info=True)


def get_memory_log_path(username, role_name):
    return os.path.join(MEMORY_TEMP_DIR, f"{username}_{role_name}_log.txt")

def load_recurring_reminders():
    """从 JSON 文件加载重复和长期一次性提醒到内存中。"""
    global recurring_reminders
    reminders_loaded = []
    try:
        if os.path.exists(RECURRING_REMINDERS_FILE):
            with open(RECURRING_REMINDERS_FILE, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, list):
                    valid_reminders_count = 0
                    now = datetime.now() # 获取当前时间用于检查一次性提醒是否已过期
                    for item in loaded_data:
                        # 基本结构验证
                        if not (isinstance(item, dict) and
                                'reminder_type' in item and
                                'user_id' in item and
                                'content' in item):
                            logger.warning(f"跳过无效格式的提醒项: {item}")
                            continue

                        user_id = item.get('user_id')
                        reminder_type = item.get('reminder_type')
                        content = item.get('content')

                        # 用户有效性检查
                        if user_id not in user_names:
                             logger.warning(f"跳过未在监听列表中的用户提醒: {user_id}")
                             continue

                        # 类型特定验证
                        is_valid = False
                        if reminder_type == 'recurring':
                            time_str = item.get('time_str')
                            if time_str:
                                try:
                                    datetime.strptime(time_str, '%H:%M')
                                    is_valid = True
                                except ValueError:
                                    logger.warning(f"跳过无效时间格式的重复提醒: {item}")
                            else:
                                logger.warning(f"跳过缺少 time_str 的重复提醒: {item}")
                        elif reminder_type == 'one-off':
                            target_datetime_str = item.get('target_datetime_str')
                            if target_datetime_str:
                                try:
                                    target_dt = datetime.strptime(target_datetime_str, '%Y-%m-%d %H:%M')
                                    # 只加载未过期的一次性提醒
                                    if target_dt > now:
                                        is_valid = True
                                    else:
                                        logger.info(f"跳过已过期的一次性提醒: {item}")
                                except ValueError:
                                    logger.warning(f"跳过无效日期时间格式的一次性提醒: {item}")
                            else:
                                logger.warning(f"跳过缺少 target_datetime_str 的一次性提醒: {item}")
                        else:
                            logger.warning(f"跳过未知 reminder_type 的提醒: {item}")

                        if is_valid:
                            reminders_loaded.append(item)
                            valid_reminders_count += 1

                    # 使用锁安全地更新全局列表
                    with recurring_reminder_lock:
                        recurring_reminders = reminders_loaded
                    logger.info(f"成功从 {RECURRING_REMINDERS_FILE} 加载 {valid_reminders_count} 条有效提醒。")
                else:
                    logger.error(f"{RECURRING_REMINDERS_FILE} 文件内容不是有效的列表格式。将初始化为空列表。")
                    with recurring_reminder_lock:
                        recurring_reminders = []
        else:
            logger.info(f"{RECURRING_REMINDERS_FILE} 文件未找到。将以无提醒状态启动。")
            with recurring_reminder_lock:
                recurring_reminders = []
    except json.JSONDecodeError:
        logger.error(f"解析 {RECURRING_REMINDERS_FILE} 文件 JSON 失败。将初始化为空列表。")
        with recurring_reminder_lock:
            recurring_reminders = []
    except Exception as e:
        logger.error(f"加载提醒失败: {str(e)}", exc_info=True)
        with recurring_reminder_lock:
            recurring_reminders = [] # 确保出错时列表也被初始化

def save_recurring_reminders():
    """将内存中的当前提醒列表（重复和长期一次性）保存到 JSON 文件。"""
    global recurring_reminders
    with recurring_reminder_lock: # 获取锁保证线程安全
        temp_file_path = RECURRING_REMINDERS_FILE + ".tmp"
        # 创建要保存的列表副本，以防在写入时列表被其他线程修改
        reminders_to_save = list(recurring_reminders)
        try:
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                json.dump(reminders_to_save, f, ensure_ascii=False, indent=4)
            shutil.move(temp_file_path, RECURRING_REMINDERS_FILE)
            logger.info(f"成功将 {len(reminders_to_save)} 条提醒保存到 {RECURRING_REMINDERS_FILE}")
        except Exception as e:
            logger.error(f"保存提醒失败: {str(e)}", exc_info=True)
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass

def recurring_reminder_checker():
    """后台线程函数，每分钟检查是否有到期的重复或长期一次性提醒。"""
    last_checked_minute_str = None # 记录上次检查的 YYYY-MM-DD HH:MM
    while True:
        try:
            now = datetime.now()
            # 需要精确到分钟进行匹配
            current_datetime_minute_str = now.strftime("%Y-%m-%d %H:%M")
            current_time_minute_str = now.strftime("%H:%M") # 仅用于匹配每日重复

            # 仅当分钟数变化时才执行检查
            if current_datetime_minute_str != last_checked_minute_str:
                reminders_to_trigger_now = []
                reminders_to_remove_indices = [] # 记录需要删除的一次性提醒的索引

                # 在锁保护下读取当前的提醒列表副本
                with recurring_reminder_lock:
                    current_reminders_copy = list(recurring_reminders) # 创建副本

                for index, reminder in enumerate(current_reminders_copy):
                    reminder_type = reminder.get('reminder_type')
                    user_id = reminder.get('user_id')
                    content = reminder.get('content')
                    should_trigger = False

                    if reminder_type == 'recurring':
                        # 检查每日重复提醒 (HH:MM)
                        if reminder.get('time_str') == current_time_minute_str:
                            should_trigger = True
                            logger.info(f"匹配到每日重复提醒: 用户 {user_id}, 时间 {current_time_minute_str}, 内容: {content}")
                    elif reminder_type == 'one-off':
                        # 检查长期一次性提醒 (YYYY-MM-DD HH:MM)
                        if reminder.get('target_datetime_str') == current_datetime_minute_str:
                            should_trigger = True
                            # 标记此一次性提醒以便稍后删除
                            reminders_to_remove_indices.append(index)
                            logger.info(f"匹配到长期一次性提醒: 用户 {user_id}, 时间 {current_datetime_minute_str}, 内容: {content}")

                    if should_trigger:
                        reminders_to_trigger_now.append(reminder.copy()) # 添加副本到触发列表

                # --- 触发提醒 ---
                if reminders_to_trigger_now:
                    logger.info(f"当前时间 {current_datetime_minute_str}，发现 {len(reminders_to_trigger_now)} 条到期的提醒。")
                    if is_quiet_time() and not ALLOW_REMINDERS_IN_QUIET_TIME:
                        logger.info(f"处于安静时间，将抑制 {len(reminders_to_trigger_now)} 条提醒。")
                    else:
                        for reminder in reminders_to_trigger_now:
                            user_id = reminder['user_id']
                            content = reminder['content']
                            reminder_type = reminder['reminder_type'] # 获取类型用于日志和提示
                            logger.info(f"正在为用户 {user_id} 触发【{reminder_type}】提醒：{content}")

                            # 修改：不再直接调用API，而是将提醒添加到消息队列
                            try:
                                # 构造提醒消息前缀
                                if reminder_type == 'recurring':
                                    prefix = f"每日提醒：{content}"
                                else: # one-off
                                    prefix = f"一次性提醒：{content}"

                                # 将提醒添加到用户的消息队列
                                formatted_message = f"[{now.strftime('%Y-%m-%d %A %H:%M:%S')}] {prefix}"
                                
                                with queue_lock:
                                    if user_id not in user_queues:
                                        user_queues[user_id] = {
                                            'messages': [formatted_message],
                                            'sender_name': user_id,
                                            'username': user_id,
                                            'last_message_time': time.time()
                                        }
                                    else:
                                        user_queues[user_id]['messages'].append(formatted_message)
                                        user_queues[user_id]['last_message_time'] = time.time()
                                
                                logger.info(f"已将{reminder_type}提醒 '{content}' 添加到用户 {user_id} 的消息队列，用以执行联网检查流程")

                                # 保留语音通话功能（如果启用）
                                if USE_VOICE_CALL_FOR_REMINDERS:
                                    try:
                                        wx.VoiceCall(user_id)
                                        logger.info(f"通过语音通话提醒用户 {user_id} ({reminder_type}提醒)。")
                                    except Exception as voice_err:
                                        logger.error(f"语音通话提醒失败 ({reminder_type}提醒)，用户 {user_id}: {voice_err}")

                            except Exception as trigger_err:
                                logger.error(f"将提醒添加到消息队列失败，用户 {user_id}，提醒：{content}：{trigger_err}")

                # --- 删除已触发的一次性提醒 ---
                if reminders_to_remove_indices:
                    logger.info(f"准备从列表中删除 {len(reminders_to_remove_indices)} 条已触发的一次性提醒。")
                    something_removed = False
                    with recurring_reminder_lock:
                        # 从后往前删除，避免索引错乱
                        indices_to_delete_sorted = sorted(reminders_to_remove_indices, reverse=True)
                        original_length = len(recurring_reminders)
                        for index in indices_to_delete_sorted:
                            # 再次检查索引是否有效（理论上应该总是有效）
                            if 0 <= index < len(recurring_reminders):
                                removed_item = recurring_reminders.pop(index)
                                logger.debug(f"已从内存列表中删除索引 {index} 的一次性提醒: {removed_item.get('content')}")
                                something_removed = True
                            else:
                                logger.warning(f"尝试删除索引 {index} 时发现其无效（当前列表长度 {len(recurring_reminders)}）。")

                        if something_removed:
                            # 只有实际删除了内容才保存文件
                            logger.info(f"已从内存中删除 {original_length - len(recurring_reminders)} 条一次性提醒，正在保存更新后的列表...")
                            save_recurring_reminders() # 保存更新后的列表
                        else:
                            logger.info("没有实际删除任何一次性提醒（可能索引无效或列表已空）。")

                # 更新上次检查的分钟数
                last_checked_minute_str = current_datetime_minute_str

            # 休眠，接近一分钟检查一次
            time.sleep(58)

        except Exception as e:
            logger.error(f"提醒检查器循环出错: {str(e)}", exc_info=True)
            time.sleep(60) # 出错后等待时间稍长

# --- 检测是否需要联网搜索的函数 ---
def needs_online_search(message: str, user_id: str) -> Optional[str]:
    """
    使用主 AI 判断用户消息是否需要联网搜索，并返回需要搜索的内容。

    参数:
        message (str): 用户的消息。
        user_id (str): 用户标识符 (用于日志)。

    返回:
        Optional[str]: 如果需要联网搜索，返回需要搜索的内容；否则返回 None。
    """
    if not ENABLE_ONLINE_API:  # 如果全局禁用，直接返回 None
        return None

    # 构建用于检测的提示词
    detection_prompt = f"""
请判断以下用户消息是否明确需要查询当前、实时或非常具体的外部信息（例如：{SEARCH_DETECTION_PROMPT}）。
用户消息："{message}"

如果需要联网搜索，请回答 "需要联网"，并在下一行提供你认为需要搜索的内容。
如果不需要联网搜索（例如：常规聊天、询问一般知识、历史信息、角色扮演对话等），请只回答 "不需要联网"。
请不要添加任何其他解释。
"""
    try:
        # 根据配置选择使用辅助模型或主模型
        if ENABLE_ASSISTANT_MODEL:
            logger.info(f"向辅助模型发送联网检测请求，用户: {user_id}，消息: '{message[:50]}...'")
            response = get_assistant_response(detection_prompt, f"online_detection_{user_id}")
        else:
            logger.info(f"向主 AI 发送联网检测请求，用户: {user_id}，消息: '{message[:50]}...'")
            response = get_deepseek_response(detection_prompt, user_id=f"online_detection_{user_id}", store_context=False)

        # 清理并判断响应
        cleaned_response = response.strip()
        if "</think>" in cleaned_response:
            cleaned_response = cleaned_response.split("</think>", 1)[1].strip()
        
        if ENABLE_ASSISTANT_MODEL:
            logger.info(f"辅助模型联网检测响应: '{cleaned_response}'")
        else:
            logger.info(f"主模型联网检测响应: '{cleaned_response}'")

        if "不需要联网" in cleaned_response:
            logger.info(f"用户 {user_id} 的消息不需要联网。")
            return None
        elif "需要联网" in cleaned_response:
            # 提取需要搜索的内容
            search_content = cleaned_response.split("\n", 1)[1].strip() if "\n" in cleaned_response else ""
            logger.info(f"检测到用户 {user_id} 的消息需要联网，搜索内容: '{search_content}'")
            return search_content
        else:
            logger.warning(f"无法解析联网检测响应，用户: {user_id}，响应: '{cleaned_response}'")
            return None

    except Exception as e:
        logger.error(f"联网检测失败，用户: {user_id}，错误: {e}", exc_info=True)
        return None  # 出错时默认不需要联网

# --- 调用在线模型的函数 ---
def get_online_model_response(query: str, user_id: str) -> Optional[str]:
    """
    使用配置的在线 API 获取搜索结果。

    参数:
        query (str): 要发送给在线模型的查询（通常是用户消息）。
        user_id (str): 用户标识符 (用于日志)。

    返回:
        Optional[str]: 在线 API 的回复内容，如果失败则返回 None。
    """
    if not online_client: # 检查在线客户端是否已成功初始化
        logger.error(f"在线 API 客户端未初始化，无法为用户 {user_id} 执行在线搜索。")
        return None

    # 获取当前时间并格式化为字符串
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 结合固定的提示词、当前时间和用户查询
    online_query_prompt = f"请在互联网上查找相关信息，忽略过时信息，并给出简要的回答。\n{ONLINE_FIXED_PROMPT}\n当前时间：{current_time_str}\n\n{query}"

    try:
        logger.info(f"调用在线 API - 用户: {user_id}, 查询: '{query[:100]}...'")
        # 使用 online_client 调用在线模型
        response = online_client.chat.completions.create(
            model=ONLINE_MODEL,
            messages=[{"role": "user", "content": online_query_prompt}],
            temperature=ONLINE_API_TEMPERATURE,
            max_tokens=ONLINE_API_MAX_TOKEN,
            stream=False
        )

        if not response.choices:
            logger.error(f"在线 API 返回了空的选择项，用户: {user_id}")
            return None

        content = response.choices[0].message.content
        if content:
            reply = content.strip()
            # 清理回复，去除思考过程
            if "</think>" in reply:
                reply = reply.split("</think>", 1)[1].strip()
            logger.info(f"在线 API 响应 (用户 {user_id}): {reply}")
            return reply
        return None

    except Exception as e:
        logger.error(f"调用在线 API 失败，用户: {user_id}: {e}", exc_info=True)
        return "抱歉，在线搜索功能暂时出错了。"

def monitor_memory_usage():
    import psutil
    MEMORY_THRESHOLD = 328  # 内存使用阈值328MB
    while True:
        process = psutil.Process(os.getpid())
        memory_usage = process.memory_info().rss / 1024 / 1024  # MB
        logger.info(f"当前内存使用: {memory_usage:.2f} MB")
        if memory_usage > MEMORY_THRESHOLD:
            logger.warning(f"内存使用超过阈值 ({MEMORY_THRESHOLD} MB)，执行垃圾回收")
            import gc
            gc.collect()
        time.sleep(600)

def scheduled_restart_checker():
    """
    定时检查是否需要重启程序。
    重启条件：
    1. 已达到RESTART_INTERVAL_HOURS的运行时间
    2. 在RESTART_INACTIVITY_MINUTES内没有活动，或活动结束后又等待了RESTART_INACTIVITY_MINUTES
    3. 没有正在进行的短期提醒事件
    4. 没有即将到来（5分钟内）的长期提醒或每日重复提醒事件
    """
    global program_start_time, last_received_message_timestamp # 引用全局变量

    if not ENABLE_SCHEDULED_RESTART:
        logger.info("定时重启功能已禁用。")
        return

    logger.info(f"定时重启功能已启用。重启间隔: {RESTART_INTERVAL_HOURS} 小时，不活跃期: {RESTART_INACTIVITY_MINUTES} 分钟。")

    restart_interval_seconds = RESTART_INTERVAL_HOURS * 3600
    inactivity_seconds = RESTART_INACTIVITY_MINUTES * 60

    if restart_interval_seconds <= 0:
        logger.error("重启间隔时间必须大于0，定时重启功能将不会启动。")
        return
    
    # 初始化下一次检查重启的时间点
    next_restart_time = program_start_time + restart_interval_seconds
    restart_pending = False  # 标记是否处于待重启状态（已达到间隔时间但在等待不活跃期）

    while True:
        current_time = time.time()
        time_since_last_activity = current_time - last_received_message_timestamp
        
        # 准备重启的三个条件检查
        interval_reached = current_time >= next_restart_time or restart_pending
        inactive_enough = time_since_last_activity >= inactivity_seconds
        
        # 只有在准备重启时才检查提醒事件，避免不必要的检查
        if interval_reached and inactive_enough:
            # 检查是否有正在进行的短期提醒
            has_active_short_reminders = False
            with timer_lock:
                if active_timers:
                    logger.info(f"当前有 {len(active_timers)} 个短期提醒进行中，等待它们完成后再重启。")
                    has_active_short_reminders = True
            
            # 检查是否有即将到来的提醒（5分钟内）
            has_upcoming_reminders = False
            now = datetime.now()
            five_min_later = now + dt.timedelta(minutes=5)
            
            with recurring_reminder_lock:
                for reminder in recurring_reminders:
                    target_dt = None
                    
                    # 处理长期一次性提醒
                    if reminder.get('reminder_type') == 'one-off':
                        try:
                            target_dt = datetime.strptime(reminder.get('target_datetime_str'), '%Y-%m-%d %H:%M')
                        except (ValueError, TypeError):
                            continue
                    
                    # 处理每日重复提醒 - 需要结合当前日期计算今天的触发时间
                    elif reminder.get('reminder_type') == 'recurring':
                        try:
                            time_str = reminder.get('time_str')
                            if time_str:
                                # 解析时间字符串获取小时和分钟
                                reminder_time = datetime.strptime(time_str, '%H:%M').time()
                                # 结合当前日期构建完整的目标时间
                                target_dt = datetime.combine(now.date(), reminder_time)
                                
                                # 如果今天的触发时间已过，检查明天的触发时间是否在5分钟内
                                # (极少情况：如果定时检查恰好在23:55-00:00之间，且有0:00-0:05的提醒)
                                if target_dt < now:
                                    target_dt = datetime.combine(now.date() + dt.timedelta(days=1), reminder_time)
                        except (ValueError, TypeError):
                            continue
                    
                    # 检查目标时间是否在5分钟内
                    if target_dt and now <= target_dt <= five_min_later:
                        reminder_type = "长期一次性" if reminder.get('reminder_type') == 'one-off' else "每日重复"
                        display_time = target_dt.strftime('%Y-%m-%d %H:%M') if reminder.get('reminder_type') == 'one-off' else target_dt.strftime('%H:%M')
                        logger.info(f"检测到5分钟内即将执行的{reminder_type}提醒，延迟重启。提醒时间: {display_time}")
                        has_upcoming_reminders = True
                        break
            
            # 如果没有提醒阻碍，则可以重启
            if not has_active_short_reminders and not has_upcoming_reminders:
                logger.warning(f"满足重启条件：已运行约 {(current_time - program_start_time)/3600:.2f} 小时，已持续 {time_since_last_activity/60:.1f} 分钟无活动，且没有即将执行的提醒。准备重启程序...")
                try:
                    # --- 执行重启前的清理操作 ---
                    logger.info("定时重启前：保存聊天上下文...")
                    with queue_lock:
                        save_chat_contexts()
                    
                    # 保存用户计时器状态
                    if ENABLE_AUTO_MESSAGE:
                        logger.info("定时重启前：保存用户计时器状态...")
                        save_user_timers()
                    
                    if ENABLE_REMINDERS:
                        logger.info("定时重启前：保存提醒列表...")
                        with recurring_reminder_lock:
                            save_recurring_reminders()
                    
                    # 关闭异步HTTP日志处理器
                    if 'async_http_handler' in globals() and isinstance(async_http_handler, AsyncHTTPHandler):
                        logger.info("定时重启前：关闭异步HTTP日志处理器...")
                        async_http_handler.close()
                    
                    logger.info("定时重启前：执行最终临时文件清理...")
                    clean_up_temp_files()
                    
                    logger.info("正在执行重启...")
                    # 替换当前进程为新启动的 Python 脚本实例
                    os.execv(sys.executable, ['python'] + sys.argv)
                except Exception as e:
                    logger.error(f"执行重启操作时发生错误: {e}", exc_info=True)
                    # 如果重启失败，推迟下一次检查，避免短时间内连续尝试
                    restart_pending = False
                    next_restart_time = current_time + restart_interval_seconds 
                    logger.info(f"重启失败，下一次重启检查时间推迟到: {datetime.fromtimestamp(next_restart_time).strftime('%Y-%m-%d %H:%M:%S')}")
            elif has_upcoming_reminders:
                # 有提醒即将执行，延长10分钟后再检查
                logger.info(f"由于5分钟内有提醒将执行，延长重启时间10分钟。")
                next_restart_time = current_time + 600  # 延长10分钟
                restart_pending = True  # 保持待重启状态
            else:
                # 有短期提醒正在进行，稍后再检查
                logger.info(f"由于有短期提醒正在进行，将在下一轮检查是否可以重启。")
                restart_pending = True  # 保持待重启状态
        elif interval_reached and not inactive_enough:
            # 已达到间隔时间但最近有活动，设置待重启状态
            if not restart_pending:
                logger.info(f"已达到重启间隔({RESTART_INTERVAL_HOURS}小时)，但最近 {time_since_last_activity/60:.1f} 分钟内有活动，将在 {RESTART_INACTIVITY_MINUTES} 分钟无活动后重启。")
                restart_pending = True
            # 不更新next_restart_time，因为我们现在是等待不活跃期
        elif current_time >= next_restart_time and not restart_pending:
            # 第一次达到重启时间点
            logger.info(f"已达到计划重启检查点 ({RESTART_INTERVAL_HOURS}小时)。距离上次活动: {time_since_last_activity/60:.1f}分钟 (不活跃阈值: {RESTART_INACTIVITY_MINUTES}分钟)。")
            restart_pending = True  # 进入待重启状态
        
        # 每分钟检查一次条件
        time.sleep(60)

# 发送心跳的函数
def send_heartbeat():
    """向Flask后端发送心跳信号"""
    heartbeat_url = f"{FLASK_SERVER_URL_BASE}/bot_heartbeat"
    payload = {
        'status': 'alive',
        'pid': os.getpid() # 发送当前进程PID，方便调试
    }
    try:
        response = requests.post(heartbeat_url, json=payload, timeout=5)
        if response.status_code == 200:
            logger.debug(f"心跳发送成功至 {heartbeat_url} (PID: {os.getpid()})")
        else:
            logger.warning(f"发送心跳失败，状态码: {response.status_code} (PID: {os.getpid()})")
    except requests.exceptions.RequestException as e:
        logger.error(f"发送心跳时发生网络错误: {e} (PID: {os.getpid()})")
    except Exception as e:
        logger.error(f"发送心跳时发生未知错误: {e} (PID: {os.getpid()})")


# 心跳线程函数
def heartbeat_thread_func():
    """心跳线程，定期发送心跳"""
    logger.info(f"机器人心跳线程启动 (PID: {os.getpid()})，每 {HEARTBEAT_INTERVAL} 秒发送一次心跳。")
    while True:
        send_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL)

# 保存用户计时器状态的函数
def save_user_timers():
    """将用户计时器状态保存到文件"""
    temp_file_path = USER_TIMERS_FILE + ".tmp"
    try:
        timer_data = {
            'user_timers': dict(user_timers),
            'user_wait_times': dict(user_wait_times)
        }
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            json.dump(timer_data, f, ensure_ascii=False, indent=4)
        shutil.move(temp_file_path, USER_TIMERS_FILE)
        logger.info(f"用户计时器状态已保存到 {USER_TIMERS_FILE}")
    except Exception as e:
        logger.error(f"保存用户计时器状态失败: {e}", exc_info=True)
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass

# 加载用户计时器状态的函数
def load_user_timers():
    """从文件加载用户计时器状态"""
    global user_timers, user_wait_times
    try:
        if os.path.exists(USER_TIMERS_FILE):
            with open(USER_TIMERS_FILE, 'r', encoding='utf-8') as f:
                timer_data = json.load(f)
                if isinstance(timer_data, dict):
                    loaded_user_timers = timer_data.get('user_timers', {})
                    loaded_user_wait_times = timer_data.get('user_wait_times', {})
                    
                    # 验证并恢复有效的计时器状态
                    restored_count = 0
                    for user in user_names:
                        if (user in loaded_user_timers and user in loaded_user_wait_times and
                            isinstance(loaded_user_timers[user], (int, float)) and
                            isinstance(loaded_user_wait_times[user], (int, float))):
                            user_timers[user] = loaded_user_timers[user]
                            user_wait_times[user] = loaded_user_wait_times[user]
                            restored_count += 1
                            logger.debug(f"已恢复用户 {user} 的计时器状态")
                        else:
                            # 如果没有保存的状态或状态无效，则初始化
                            reset_user_timer(user)
                            logger.debug(f"为用户 {user} 重新初始化计时器状态")
                    
                    logger.info(f"成功从 {USER_TIMERS_FILE} 恢复 {restored_count} 个用户的计时器状态")
                else:
                    logger.warning(f"{USER_TIMERS_FILE} 文件格式不正确，将重新初始化所有计时器")
                    initialize_all_user_timers()
        else:
            logger.info(f"{USER_TIMERS_FILE} 未找到，将初始化所有用户计时器")
            initialize_all_user_timers()
    except json.JSONDecodeError:
        logger.error(f"解析 {USER_TIMERS_FILE} 失败，将重新初始化所有计时器")
        initialize_all_user_timers()
    except Exception as e:
        logger.error(f"加载用户计时器状态失败: {e}", exc_info=True)
        initialize_all_user_timers()

def initialize_all_user_timers():
    """初始化所有用户的计时器"""
    for user in user_names:
        reset_user_timer(user)
    logger.info("所有用户计时器已重新初始化")

# === 新增：全局锁 ===
is_sending_message_lock = threading.Lock()
can_send_messages_lock = threading.Lock()
ui_automation_lock = threading.Lock()

def status_self_check():
    check_interval = 10  # 每10秒检查一次
    stuck_threshold = 60  # 锁定状态持续超过60秒，才判定为卡死
    lock_start_time = None  # 用于记录锁定开始的时间

    while True:
        with can_send_messages_lock:
            # 检查当前是否处于锁定状态
            is_locked = not can_send_messages

        if is_locked:
            # 如果当前是锁定状态
            if lock_start_time is None:
                # 如果是刚开始锁定，就记录下当前时间点
                lock_start_time = time.time()
            else:
                # 如果之前已经记录了开始时间，就计算一下锁定了多久
                duration = time.time() - lock_start_time
                if duration > stuck_threshold:
                    # 如果锁定时长超过了我们设定的阈值（60秒），才发出警告
                    logger.warning(f"can_send_messages 已被锁定超过 {stuck_threshold} 秒，可能已卡死。")
                    # 发出警告后，重置计时器，避免连续刷屏报警
                    lock_start_time = time.time()
        else:
            # 如果当前不是锁定状态，就清空开始时间的记录
            if lock_start_time is not None:
                lock_start_time = None

        time.sleep(check_interval)

# === 全局消息队列和消费线程 ===
message_queue = queue.Queue()

def message_consumer():
    while True:
        try:
            action_type, content, user_id = message_queue.get()
            if action_type == 'emoji':
                wx.SendFiles(filepath=content, who=user_id)
                logger.info(f"表情包已发送: {content}")
                time.sleep(EMOJI_SEND_INTERVAL)
            elif action_type == 'text':
                wx.SendMsg(msg=content, who=user_id)
                logger.info(f"文本已发送: {content}")
                time.sleep(TEXT_SEND_INTERVAL)
        except Exception as e:
            logger.error(f"发送消息失败: {str(e)}", exc_info=True)
        finally:
            message_queue.task_done()

# 启动消费线程（只需启动一次）
consumer_thread = threading.Thread(target=message_consumer, daemon=True)
consumer_thread.start()

# === 新增：每用户群聊配置读取 ===
USER_GROUP_CHAT_CONFIG_FILE = os.path.join(root_dir, 'user_group_chat_config.json')
USER_GROUP_CHAT_CONFIG_LOCK = threading.Lock()

def load_user_group_chat_config():
    if not os.path.exists(USER_GROUP_CHAT_CONFIG_FILE):
        return {}
    with USER_GROUP_CHAT_CONFIG_LOCK:
        try:
            with open(USER_GROUP_CHAT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取 user_group_chat_config.json 失败: {e}")
            return {}

def get_group_chat_config(who):
    """获取指定群聊的专属群聊配置，找不到则返回全局配置。"""
    all_config = load_user_group_chat_config()
    # 优先用户专属
    user_cfg = all_config.get(who)
    # 全局配置
    global_cfg = all_config.get("__global__", {})
    if user_cfg and isinstance(user_cfg, dict):
        # 如果use_global为True则用全局
        if user_cfg.get("use_global"):
            return global_cfg
        # 否则合并（用户优先）
        merged = dict(global_cfg)
        merged.update(user_cfg)
        return merged
    return global_cfg

def main():
    try:
        # --- 启动前检查 ---
        logger.info("\033[32m进行启动前检查...\033[0m")

        # 预检查所有用户prompt文件
        for user in user_names:
            prompt_file = prompt_mapping.get(user, user)
            prompt_path = os.path.join(root_dir, 'prompts', f'{prompt_file}.md')
            if not os.path.exists(prompt_path):
                raise FileNotFoundError(f"用户 {user} 的prompt文件 {prompt_file}.md 不存在")

        # 确保临时目录存在
        memory_temp_dir = os.path.join(root_dir, MEMORY_TEMP_DIR)
        os.makedirs(memory_temp_dir, exist_ok=True)

        # 加载聊天上下文
        logger.info("正在加载聊天上下文...")
        load_chat_contexts() # 调用加载函数

        if ENABLE_REMINDERS:
             logger.info("提醒功能已启用。")
             # 加载已保存的提醒 (包括重复和长期一次性)
             load_recurring_reminders()
             if not isinstance(ALLOW_REMINDERS_IN_QUIET_TIME, bool):
                  logger.warning("配置项 ALLOW_REMINDERS_IN_QUIET_TIME 的值不是布尔类型 (True/False)，可能导致意外行为。")
        else:
            logger.info("提醒功能已禁用 (所有类型提醒将无法使用)。")

        # --- 初始化 ---
        logger.info("\033[32m初始化微信接口和清理临时文件...\033[0m")
        clean_up_temp_files()
        global wx
        try:
            wx = WeChat()
        except:
            logger.error(f"\033[31m无法初始化微信接口，请确保您安装的是微信3.9版本，并且已经登录！\033[0m")
            exit(1)

        for user_name in user_names:
            if user_name == ROBOT_WX_NAME:
                logger.error(f"\033[31m您填写的用户列表中包含自己登录的微信昵称，请删除后再试！\033[0m")
                exit(1)
            ListenChat = wx.AddListenChat(nickname=user_name, callback=message_listener)
            if ListenChat:
                logger.info(f"成功添加监听用户{ListenChat}")
            else:
                logger.error(f"\033[31m添加监听用户{user_name}失败，请确保您在用户列表填写的微信昵称/备注与实际完全匹配，并且不要包含表情符号和特殊符号，注意填写的不是自己登录的微信昵称!\033[0m")
                exit(1)
        logger.info("监听用户添加完成")
        
        # 初始化所有用户的自动消息计时器
        if ENABLE_AUTO_MESSAGE:
            logger.info("正在加载用户自动消息计时器状态...")
            load_user_timers()  # 替换原来的初始化代码
            logger.info("用户自动消息计时器状态加载完成。")
            
            # 初始化群聊类型缓存
            if IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE:
                logger.info("主动消息群聊忽略功能已启用，正在初始化群聊类型缓存...")
                update_group_chat_cache()
                logger.info("群聊类型缓存初始化完成。")
            else:
                logger.info("主动消息群聊忽略功能已禁用。")
        else:
            logger.info("自动消息功能已禁用，跳过计时器初始化。")

        # --- 启动窗口保活线程 ---
        logger.info("\033[32m启动窗口保活线程...\033[0m")
        listener_thread = threading.Thread(target=keep_alive, name="keep_alive")
        listener_thread.daemon = True
        listener_thread.start()
        logger.info("消息窗口保活已启动。")

        checker_thread = threading.Thread(target=check_inactive_users, name="InactiveUserChecker")
        checker_thread.daemon = True
        checker_thread.start()
        logger.info("非活跃用户检查与消息处理线程已启动。")

         
         # 启动定时重启检查线程 (如果启用)
         # --- 新增：程序启动时加载动态设置 ---
        load_settings()
        global program_start_time, last_received_message_timestamp
        program_start_time = time.time()
        last_received_message_timestamp = time.time()
        if ENABLE_SCHEDULED_RESTART:
            restart_checker_thread = threading.Thread(target=scheduled_restart_checker, name="ScheduledRestartChecker")
            restart_checker_thread.daemon = True # 设置为守护线程，主程序退出时它也会退出
            restart_checker_thread.start()
            logger.info("定时重启检查线程已启动。")


        # 检查重复和长期一次性提醒
        if ENABLE_REMINDERS:
            reminder_checker_thread = threading.Thread(target=recurring_reminder_checker, name="ReminderChecker")
            reminder_checker_thread.daemon = True
            reminder_checker_thread.start()
            logger.info("提醒检查线程（重复和长期一次性）已启动。")

        # 自动消息
        if ENABLE_AUTO_MESSAGE:
            auto_message_thread = threading.Thread(target=check_user_timeouts, name="AutoMessageChecker")
            auto_message_thread.daemon = True
            auto_message_thread.start()
            logger.info("主动消息检查线程已启动。")
        
        # 启动心跳线程
        heartbeat_th = threading.Thread(target=heartbeat_thread_func, name="BotHeartbeatThread", daemon=True)
        heartbeat_th.start()

        logger.info("\033[32mBOT已成功启动并运行中...\033[0m")

        # 启动内存使用监控线程
        monitor_memory_usage_thread = threading.Thread(target=monitor_memory_usage, name="MemoryUsageMonitor")
        monitor_memory_usage_thread.daemon = True
        monitor_memory_usage_thread.start()
        logger.info("内存使用监控线程已启动。")

        # 启动自检线程
        status_check_thread = threading.Thread(target=status_self_check, name="StatusSelfCheck", daemon=True)
        status_check_thread.start()

        wx.KeepRunning()

        while True:
            time.sleep(60)

    except FileNotFoundError as e:
        logger.critical(f"初始化失败: 缺少必要的文件或目录 - {str(e)}")
        logger.error(f"\033[31m错误：{str(e)}\033[0m")
    except Exception as e:
        logger.critical(f"主程序发生严重错误: {str(e)}", exc_info=True)
    finally:
        logger.info("程序准备退出，执行清理操作...")

        # 保存用户计时器状态（如果启用了自动消息）
        if ENABLE_AUTO_MESSAGE:
            logger.info("程序退出前：保存用户计时器状态...")
            save_user_timers()

        # 取消活动的短期一次性提醒定时器
        with timer_lock:
            if active_timers:
                 logger.info(f"正在取消 {len(active_timers)} 个活动的短期一次性提醒定时器...")
                 cancelled_count = 0
                 # 使用 list(active_timers.items()) 创建副本进行迭代
                 for timer_key, timer in list(active_timers.items()):
                     try:
                         timer.cancel()
                         cancelled_count += 1
                     except Exception as cancel_err:
                         logger.warning(f"取消短期定时器 {timer_key} 时出错: {cancel_err}")
                 active_timers.clear()
                 logger.info(f"已取消 {cancelled_count} 个短期一次性定时器。")
            else:
                 logger.info("没有活动的短期一次性提醒定时器需要取消。")

        if 'async_http_handler' in globals() and isinstance(async_http_handler, AsyncHTTPHandler):
            logger.info("正在关闭异步HTTP日志处理器...")
            try:
                 async_http_handler.close()
                 logger.info("异步HTTP日志处理器已关闭。")
            except Exception as log_close_err:
                 logger.error(f"关闭异步日志处理器时出错: {log_close_err}")

        logger.info("执行最终临时文件清理...")
        clean_up_temp_files()
        logger.info("程序退出。")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("接收到用户中断信号 (Ctrl+C)，程序将退出。")
    except Exception as e:
        logger.error(f"程序启动或运行期间发生未捕获的顶层异常: {str(e)}", exc_info=True)
        print(f"FALLBACK LOG: {datetime.now()} - CRITICAL ERROR - {str(e)}")