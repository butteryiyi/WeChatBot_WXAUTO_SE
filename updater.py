# -*- coding: utf-8 -*-

# ***********************************************************************
# Modified based on the KouriChat project
# Copyright of this modification: Copyright (C) 2025, iwyxdxl
# Licensed under GNU GPL-3.0 or higher, see the LICENSE file for details.
# 
# This file is part of WeChatBot, which includes modifications to the KouriChat project.
# The original KouriChat project's copyright and license information are preserved in the LICENSE file.
# For any further details regarding the license, please refer to the LICENSE file.
# ***********************************************************************

"""
自动更新模块
提供程序自动更新功能，包括:
- GitHub版本检查
- 更新包下载（增加下载进度指示）
- 文件更新
- 备份和恢复
- 更新回滚
- 对 config.py 进行更新时合并用户原有的配置选项（保留原有注释和格式，仅追加新增项）
"""

import os
import re
import ast
import requests
import zipfile
import shutil
import json
import logging
from typing import Tuple, Optional
import sys
import datetime
import time

logger = logging.getLogger(__name__)

class Updater:
    # GitHub仓库信息
    REPO_OWNER = "butteryiyi"
    REPO_NAME = "WeChatBot_WXAUTO_SE"
    REPO_BRANCH = "main"
    GITHUB_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
    
    # 需要跳过的文件和文件夹（不会被更新）
    SKIP_FILES = [
        "prompts",      # 聊天提示词
        "Memory_Temp",  # 临时记忆文件
        "emojis",      # 表情包
        "recurring_reminders.json",  # 定时提醒
        "config.py",    # 配置文件(单独处理)
        "数据备份",  # 数据备份
    ]

    # GitHub代理列表
    PROXY_SERVERS = [
        "https://ghfast.top/",
        "https://github.moeyy.xyz/", 
        "https://git.886.be/",
        "",  # 空字符串表示直接使用原始GitHub地址
    ]

    def __init__(self):
        self.root_dir = os.path.dirname(os.path.abspath(__file__))
        self.temp_dir = os.path.join(self.root_dir, 'temp_update')
        self.version_file = os.path.join(self.root_dir, 'version.json')
        self.current_proxy_index = 0  # 当前使用的代理索引

    def get_proxy_url(self, original_url: str) -> str:
        """获取当前代理URL"""
        if self.current_proxy_index >= len(self.PROXY_SERVERS):
            return original_url
        proxy = self.PROXY_SERVERS[self.current_proxy_index]
        return f"{proxy}{original_url}" if proxy else original_url

    def try_next_proxy(self) -> bool:
        """尝试切换到下一个代理"""
        self.current_proxy_index += 1
        return self.current_proxy_index < len(self.PROXY_SERVERS)

    def get_current_version(self) -> str:
        """获取当前版本号"""
        try:
            if os.path.exists(self.version_file):
                with open(self.version_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('version', '0.0.0')
        except Exception as e:
            logger.error(f"读取版本文件失败: {str(e)}")
        return '0.0.0'

    def format_version_info(self, current_version: str, update_info: Optional[dict] = None) -> str:
        """格式化版本信息输出"""
        output = f'\n{"=" * 50}\n'
        output += f"当前版本: {current_version}\n"
        
        if update_info:
            output += (
                f"最新版本: {update_info['version']}\n\n"
                f"更新时间: {update_info.get('last_update', '未知')}\n\n"
                "更新内容:\n"
                f"  {update_info.get('description', '无更新说明')}\n"
                f'{"=" * 50}\n\n'
            )
        else:
            output += (
                "检查结果: 当前已是最新版本\n"
                f'{"=" * 50}\n'
            )
            
        return output

    def format_update_progress(self, step: str, success: bool = True, details: str = "") -> str:
        """格式化更新进度输出"""
        status = "✓" if success else "✗"
        output = f"[{status}] {step}"
        if details:
            output += f": {details}"
        return output

    def check_for_updates(self) -> dict:
        """检查更新"""
        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': f'{self.REPO_NAME}-UpdateChecker'
        }
        
        while True:
            try:
                version_url = f"https://raw.githubusercontent.com/{self.REPO_OWNER}/{self.REPO_NAME}/{self.REPO_BRANCH}/version.json?t={int(time.time())}"
                proxied_url = self.get_proxy_url(str(version_url))
                
                logger.info(f"正在尝试从 {proxied_url} 获取版本信息...")
                response = requests.get(
                    proxied_url,
                    headers=headers,
                    timeout=30,
                    verify=True
                )
                response.raise_for_status()
                
                remote_version_info = response.json()
                current_version = self.get_current_version()
                latest_version = remote_version_info.get('version', '0.0.0')
                
                def parse_version(version: str) -> tuple:
                    version = version.lower().strip('v')
                    try:
                        parts = version.split('.')
                        while len(parts) < 3:
                            parts.append('0')
                        return tuple(map(int, parts[:3]))
                    except (ValueError, AttributeError):
                        return (0, 0, 0)

                current_ver_tuple = parse_version(current_version)
                latest_ver_tuple = parse_version(latest_version)

                if latest_ver_tuple > current_ver_tuple:
                    release_url_str = f"{self.GITHUB_API}/releases/latest"
                    release_url = self.get_proxy_url(str(release_url_str))
                    response = requests.get(
                        release_url,
                        headers=headers,
                        timeout=30
                    )
                    
                    if response.status_code == 404:
                        download_url = f"{self.GITHUB_API}/zipball/{self.REPO_BRANCH}"
                    else:
                        release_info = response.json()
                        download_url = release_info['zipball_url']
                    
                    # 返回原始下载URL（关键修改点）
                    return {
                        'has_update': True,
                        'version': latest_version,
                        'download_url': download_url,  # 直接返回GitHub原始URL
                        'description': remote_version_info.get('description', '无更新说明'),
                        'last_update': remote_version_info.get('last_update', ''),
                        'output': self.format_version_info(current_version, remote_version_info)
                    }
                
                return {
                    'has_update': False,
                    'output': self.format_version_info(current_version)
                }
                
            except (requests.RequestException, json.JSONDecodeError) as e:
                if self.try_next_proxy():
                    logger.info("正在切换到下一个代理服务器检查更新，请稍候...")
                    continue
                else:
                    logger.error("所有代理服务器均已尝试失败，将跳过更新直接启动程序")
                    return {
                        'has_update': False,
                        'error': "检查更新失败：无法连接到更新服务器",
                        'output': "检查更新失败：无法连接到更新服务器"
                    }

    def backup_important_files(self) -> bool:
        """在更新前备份重要文件和文件夹到数据备份/{时间}目录"""
        try:
            # 创建带时间戳的备份目录
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = os.path.join(self.root_dir, '数据备份', timestamp)
            os.makedirs(backup_dir, exist_ok=True)
            
            # 需要备份的文件和文件夹
            files_to_backup = [
                "config.py",
                "recurring_reminders.json"
            ]
            
            folders_to_backup = [
                "prompts",
                "emojis"
            ]
            
            # 备份单个文件
            for file in files_to_backup:
                src_file = os.path.join(self.root_dir, file)
                if os.path.exists(src_file):
                    dst_file = os.path.join(backup_dir, file)
                    os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                    shutil.copy2(src_file, dst_file)
                    logger.info(f"已备份文件: {file}")
            
            # 备份文件夹
            for folder in folders_to_backup:
                src_folder = os.path.join(self.root_dir, folder)
                if os.path.exists(src_folder):
                    dst_folder = os.path.join(backup_dir, folder)
                    shutil.copytree(src_folder, dst_folder)
                    logger.info(f"已备份文件夹: {folder}")
            
            logger.info(f"重要文件已备份到: {backup_dir}")
            return True
        except Exception as e:
            logger.error(f"备份重要文件失败: {str(e)}")
            return False

    def should_skip_file(self, file_path: str) -> bool:
        """检查是否应该跳过更新某个文件"""
        return any(skip_file in file_path for skip_file in self.SKIP_FILES)

    def backup_current_version(self) -> bool:
        """备份当前版本"""
        try:
            backup_dir = os.path.join(self.root_dir, 'backup')
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)
            shutil.copytree(self.root_dir, backup_dir, ignore=shutil.ignore_patterns(*self.SKIP_FILES))
            return True
        except Exception as e:
            logger.error(f"备份失败: {str(e)}")
            return False

    def restore_from_backup(self) -> bool:
        """从备份恢复"""
        try:
            backup_dir = os.path.join(self.root_dir, 'backup')
            if not os.path.exists(backup_dir):
                logger.error("备份目录不存在")
                return False
                
            for root, dirs, files in os.walk(backup_dir):
                relative_path = os.path.relpath(root, backup_dir)
                target_dir = os.path.join(self.root_dir, relative_path)
                
                for file in files:
                    if not self.should_skip_file(file):
                        src_file = os.path.join(root, file)
                        dst_file = os.path.join(target_dir, file)
                        os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                        shutil.copy2(src_file, dst_file)
            return True
        except Exception as e:
            logger.error(f"恢复失败: {str(e)}")
            return False

    def apply_update(self) -> Tuple[bool, str]:
        """
        应用更新，并返回 (成功标志, 更新包顶层目录名称)
        """
        try:
            zip_path = os.path.join(self.temp_dir, 'update.zip')
            extract_dir = os.path.join(self.temp_dir, 'extracted')
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            extracted_dirs = [d for d in os.listdir(extract_dir) 
                            if os.path.isdir(os.path.join(extract_dir, d))]
            if not extracted_dirs:
                raise Exception("无效的更新包结构")
            
            new_dir = extracted_dirs[0]
            source_root = os.path.join(extract_dir, new_dir)
            
            for root, dirs, files in os.walk(source_root):
                relative_path = os.path.relpath(root, source_root)
                target_dir = os.path.join(self.root_dir, relative_path)
                os.makedirs(target_dir, exist_ok=True)
                for file in files:
                    if not self.should_skip_file(file):
                        src_file = os.path.join(root, file)
                        dst_file = os.path.join(target_dir, file)
                        if os.path.exists(dst_file):
                            os.remove(dst_file)
                        shutil.copy2(src_file, dst_file)
                        
                        # 特殊处理version.json，确保它被正确复制
                        if file == 'version.json':
                            logger.info(f"已更新版本文件: {dst_file}")
            return True, new_dir
        except Exception as e:
            logger.error(f"更新失败: {str(e)}")
            return False, ""

    def cleanup(self):
        """清理临时文件"""
        try:
            if os.path.exists(self.temp_dir):
                logger.info(f"正在删除临时目录: {self.temp_dir}")
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            backup_dir = os.path.join(self.root_dir, 'backup')
            if os.path.exists(backup_dir):
                logger.info(f"正在删除备份目录: {backup_dir}")
                shutil.rmtree(backup_dir, ignore_errors=True)
            extract_dir = os.path.join(self.temp_dir, 'extracted')
            if os.path.exists(extract_dir):
                logger.info(f"正在删除解压目录: {extract_dir}")
                shutil.rmtree(extract_dir, ignore_errors=True)
            temp_zip = os.path.join(self.root_dir, 'update.zip')
            if os.path.exists(temp_zip):
                logger.info(f"正在删除残留zip文件: {temp_zip}")
                os.remove(temp_zip)
        except Exception as e:
            logger.error(f"清理失败: {str(e)}")
            if os.name == 'nt':
                try:
                    os.system(f'rmdir /s /q "{self.temp_dir}" 2>nul')
                    os.system(f'rmdir /s /q "{backup_dir}" 2>nul')
                except:
                    pass

    def prompt_update(self, update_info: dict) -> bool:
        """提示用户是否更新"""
        print(self.format_version_info(self.get_current_version(), update_info))
        
        while True:
            choice = input("\n是否现在更新?\n输入'y'更新 / 输入'n'取消更新并继续启动: ").lower().strip()
            if choice in ('y', 'yes'):
                print("\n正在更新,这可能需要一些时间,请耐心等待...")
                return True
            elif choice in ('n', 'no'):
                return False
            print("请输入 y 或 n")

    def download_update(self, download_url: str, callback=None) -> bool:
        """下载更新包，并在下载过程中通过 callback 输出进度指示"""
        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': f'{self.REPO_NAME}-UpdateChecker'
        }
        
        while True:
            try:
            # --- 这是我们新加的代码 ---
                timestamp = int(time.time())
            # 判断原始链接是否已有参数，来决定是用 ? 还是 &
                separator = '&' if '?' in download_url else '?'
                unique_download_url = f"{download_url}{separator}_cache_bust={timestamp}"
            # --- 新加代码结束 ---
                proxied_url = self.get_proxy_url(download_url)
                logger.info(f"正在从 {proxied_url} 下载更新...")
                # 为了方便确认，我们加一句打印
                print(f"正在下载防缓存链接: {proxied_url}")
                
                response = requests.get(
                    proxied_url,
                    headers=headers,
                    timeout=30,
                    stream=True
                )
                response.raise_for_status()
                
                os.makedirs(self.temp_dir, exist_ok=True)
                zip_path = os.path.join(self.temp_dir, 'update.zip')
                
                total_length = response.headers.get("Content-Length")
                if total_length is not None:
                    total_length = int(total_length)
                downloaded = 0
            
                with open(zip_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_length:
                                percent = downloaded / total_length * 100
                                # 添加进度条显示
                                bar_length = 30
                                filled = int(bar_length * downloaded // total_length)
                                bar = '█' * filled + ' ' * (bar_length - filled)
                                sys.stdout.write(f"\r下载进度 |{bar}| {percent:.1f}% ({downloaded/1024/1024:.1f}MB/{total_length/1024/1024:.1f}MB)")
                            else:
                                sys.stdout.write(f"\r已下载: {downloaded/1024/1024:.1f} MB")
                            sys.stdout.flush()
                print("\n下载完成")  # 换行确保后续输出不混乱
                
                return True
                    
            except requests.RequestException as e:
                logger.warning(f"使用当前代理下载更新失败: {str(e)}")
                if self.try_next_proxy():
                    logger.info("正在切换到下一个代理服务器...")
                    continue
                else:
                    logger.error("所有代理服务器均已尝试失败")
                    return False

    def update(self, callback=None) -> dict:
        """执行更新"""
        try:
            progress = []
            def log_progress(step, success=True, details=""):
                msg = self.format_update_progress(step, success, details)
                progress.append(msg)
                if callback:
                    callback(msg)

            log_progress("开始检查GitHub更新...")
            update_info = self.check_for_updates()
            if not update_info['has_update']:
                log_progress("检查更新完成", True, "当前已是最新版本")
                print("\n当前已是最新版本，无需更新")
                return {'success': True, 'output': '\n'.join(progress)}
            
            if not self.prompt_update(update_info):
                log_progress("提示用户是否更新", True, "用户取消更新")
                print("\n已取消更新")
                return {'success': True, 'output': '\n'.join(progress)}
                    
            log_progress(f"开始更新到版本: {update_info['version']}")
            
            # 添加重要文件备份步骤
            log_progress("开始备份重要文件...")
            if not self.backup_important_files():
                log_progress("备份重要文件", False, "备份失败")
                if not self.prompt_continue_update():
                    return {'success': False, 'output': '\n'.join(progress)}
            else:
                log_progress("备份重要文件", True, "备份完成")
            
            log_progress("开始下载更新...")
            if not self.download_update(update_info['download_url'], callback=log_progress):
                log_progress("下载更新", False, "下载失败")
                return {'success': False, 'output': '\n'.join(progress)}
            log_progress("下载更新", True, "下载完成")
                
            log_progress("开始备份当前版本...")
            if not self.backup_current_version():
                log_progress("备份当前版本", False, "备份失败")
                return {'success': False, 'output': '\n'.join(progress)}
            log_progress("备份当前版本", True, "备份完成")
                
            log_progress("开始应用更新...")
            success, new_dir = self.apply_update()
            if not success:
                log_progress("应用更新", False, "更新失败")
                log_progress("正在恢复之前的版本...")
                if not self.restore_from_backup():
                    log_progress("恢复备份", False, "恢复失败！请手动处理")
                return {'success': False, 'output': '\n'.join(progress)}
            log_progress("应用更新", True, "更新成功")
            
            # 合并配置文件：保留旧config.py所有原始内容，仅追加新版本中新增的配置项
            current_config = os.path.join(self.root_dir, "config.py")
            new_config = os.path.join(self.temp_dir, "extracted", new_dir, "config.py")
            if os.path.exists(current_config) and os.path.exists(new_config):
                log_progress("开始合并配置文件...")
                Updater.merge_config(current_config, new_config, current_config)
                log_progress("合并配置文件", True, "配置合并完成")
            else:
                log_progress("合并配置文件", False, "配置文件不存在，无法合并")
                if not os.path.exists(current_config) and os.path.exists(new_config):
                    shutil.copy2(new_config, current_config)
                    log_progress("复制新配置文件", True, "已复制新的配置文件")
            
            # 确保更新version.json文件 (添加明确的日志记录)
            log_progress("更新版本信息文件...")
            try:
                with open(self.version_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        'version': update_info['version'],
                        'last_update': update_info.get('last_update', ''),
                        'description': update_info.get('description', '')
                    }, f, indent=4, ensure_ascii=False)
                log_progress("更新版本信息文件", True, f"成功更新到版本 {update_info['version']}")
            except Exception as e:
                log_progress("更新版本信息文件", False, f"无法写入版本文件: {str(e)}")
                logger.error(f"写入版本文件失败: {str(e)}")
            
            # 验证版本文件是否已更新
            log_progress("验证版本文件...")
            try:
                if os.path.exists(self.version_file):
                    with open(self.version_file, 'r', encoding='utf-8') as f:
                        version_data = json.load(f)
                        if version_data.get('version') == update_info['version']:
                            log_progress("验证版本文件", True, "版本文件已正确更新")
                        else:
                            log_progress("验证版本文件", False, "版本文件内容不正确，重新写入")
                            # 重新写入版本文件
                            with open(self.version_file, 'w', encoding='utf-8') as f:
                                json.dump({
                                    'version': update_info['version'],
                                    'last_update': update_info.get('last_update', ''),
                                    'description': update_info.get('description', '')
                                }, f, indent=4, ensure_ascii=False)
                else:
                    log_progress("验证版本文件", False, "版本文件不存在，创建新文件")
                    # 创建版本文件
                    with open(self.version_file, 'w', encoding='utf-8') as f:
                        json.dump({
                            'version': update_info['version'],
                            'last_update': update_info.get('last_update', ''),
                            'description': update_info.get('description', '')
                        }, f, indent=4, ensure_ascii=False)
            except Exception as e:
                log_progress("验证版本文件", False, f"验证失败: {str(e)}")
                
            self.cleanup()
            log_progress("清理临时文件", True)
            log_progress("更新完成", True, "请重启程序以应用更新")

            if success:
                print("\n" + "="*50)
                print("\033[32m\n更新成功!请关闭此窗口并重新运行Run.bat以应用更新。\n\033[0m")

                print("="*50 + "\n")
                # 使用while循环阻止程序退出,直到用户手动关闭窗口
                while True:
                    try:
                        time.sleep(1)
                    except KeyboardInterrupt:
                        continue

            return {'success': True, 'output': '\n'.join(progress)}

        except Exception as e:
            logger.error(f"更新失败: {str(e)}")
            return {'success': False, 'error': str(e), 'output': f"更新失败: {str(e)}"}

    def prompt_continue_update(self) -> bool:
        """当备份失败时，询问用户是否继续更新"""
        print("\n\033[31m警告：备份重要文件失败！\033[0m")
        while True:
            choice = input("是否仍要继续更新?\n输入'y'继续更新 / 输入'n'取消更新: ").lower().strip()
            if choice in ('y', 'yes'):
                print("\n继续更新...")
                return True
            elif choice in ('n', 'no'):
                print("\n已取消更新")
                return False
            print("请输入 y 或 n")

    @staticmethod
    def parse_config_file(path):
        """
        解析配置文件，返回字典和原始行列表
        """
        config = {}
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        assign_pattern = re.compile(r'^(\w+)\s*=\s*(.+)$')
        for line in lines:
            line_strip = line.strip()
            if not line_strip or line_strip.startswith("#"):
                continue
            match = assign_pattern.match(line_strip)
            if match:
                key = match.group(1)
                value_str = match.group(2)
                try:
                    value = ast.literal_eval(value_str)
                except Exception:
                    value = value_str
                config[key] = value
        return config, lines

    @staticmethod
    def merge_config(old_path, new_path, output_path):
        """
        合并 old_path 与 new_path 两个配置文件：
        1. 保留旧文件的所有原始内容（包括注释和格式）。
        2. 对于新文件中出现而旧文件中不存在的配置项，将其原始赋值行追加到文件末尾。
        """
        # 读取旧文件原始内容
        with open(old_path, 'r', encoding='utf-8') as f:
            old_lines = f.readlines()

        # 提取旧文件中已存在的配置键
        assign_pattern = re.compile(r'^(\w+)\s*=\s*(.+)$')
        old_keys = set()
        for line in old_lines:
            m = assign_pattern.match(line.strip())
            if m:
                old_keys.add(m.group(1))

        # 读取新文件的所有行
        with open(new_path, 'r', encoding='utf-8') as f:
            new_lines = f.readlines()

        # 收集新文件中新增的配置项的原始行
        added_lines = []
        for line in new_lines:
            m = assign_pattern.match(line.strip())
            if m:
                key = m.group(1)
                if key not in old_keys:
                    added_lines.append(line)

        if added_lines:
            old_lines.append("\n# 以下为新增配置项\n")
            old_lines.extend(added_lines)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(old_lines)


def check_and_update():
    """检查并执行更新"""
    logger.info("开始检查GitHub更新...")
    updater = Updater()
    return updater.update()


if __name__ == "__main__":
    try:
        result = check_and_update()
        if not result['success']:
            print("\n更新失败，请查看日志")
        else:
            print(result['output'])
    except KeyboardInterrupt:
        print("\n用户取消更新")
    except Exception as e:
        print(f"\n发生错误: {str(e)}")
