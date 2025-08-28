# 程序指令中心

import re
import os
import sys
import shutil
import threading
import logging

logger = logging.getLogger(__name__)


def _update_config_boolean(key: str, value: bool) -> bool:
    """在 config.py 中更新布尔配置。"""
    try:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(root_dir, 'config.py')
        if not os.path.exists(config_path):
            logger.error(f"配置文件不存在: {config_path}")
            return False
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        pattern = rf"^{re.escape(key)}\s*=\s*(True|False|.+)$"
        replacement = f"{key} = {str(bool(value))}"
        new_content, count = re.subn(pattern, replacement, content, flags=re.M)
        if count == 0:
            new_content = content.rstrip("\n") + f"\n\n{replacement}\n"
        tmp_path = config_path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        shutil.move(tmp_path, config_path)
        return True
    except Exception as e:
        logger.error(f"更新配置 {key} 失败: {e}")
        return False

def _schedule_restart(reason: str = "指令触发"):
    """延迟1.5秒执行重启。"""
    def _do_restart():
        try:
            logger.info(f"正在执行重启 (原因: {reason}) ...")
            os.execv(sys.executable, ['python'] + [os.path.join(os.path.dirname(__file__), 'bot.py')])
        except Exception as e:
            logger.error(f"执行重启失败: {e}", exc_info=True)
    threading.Timer(1.5, _do_restart).start()

# --- 指令中心的主处理函数 ---

def process_command(original_content: str, user_id: str, clear_context_func, clear_memory_func):
    """
    处理收到的指令。
    如果内容是指令，则执行相应动作并返回要回复的【文本】。
    如果不是指令或未匹配，则返回 None。
    """
    text = original_content.strip()

    # 优化指令提取逻辑，只匹配消息开头的指令
    match = re.match(r'^\s*(/\S+)', text)
    if not match:
        return None  # 不是以 / 开头的指令，直接返回

    command_block = match.group(1)
    # 去掉可能存在的@xxx部分
    at_index = command_block.find('@')
    if at_index != -1:
        command_part = command_block[:at_index]
    else:
        command_part = command_block
        
    normalized = command_part.strip()
    
    reply_text = None

    # 根据指令执行动作并准备回复文本
    if normalized == '/重启' or normalized == '/re':
        _schedule_restart('用户指令重启')
        reply_text = '✅ 指令已收到，程序正在重启...'
        
    elif normalized == '/关闭主动消息' or normalized == '/da':
        ok = _update_config_boolean('ENABLE_AUTO_MESSAGE', False)
        reply_text = '🚫 已关闭主动消息功能。' if ok else '❌ 关闭失败，请检查日志。'
        
    elif normalized == '/开启主动消息' or normalized == '/ea':
        ok = _update_config_boolean('ENABLE_AUTO_MESSAGE', True)
        reply_text = '✅ 已开启主动消息功能。' if ok else '❌ 开启失败，请检查日志。'
        
    elif normalized == '/清除临时记忆' or normalized == '/cl':
        try:
            clear_context_func(user_id)
            clear_memory_func(user_id)
            reply_text = '🧹 已清除当前聊天的临时上下文与临时记忆日志。'
        except Exception as e:
            logger.error(f"清除临时记忆失败: {e}")
            reply_text = '❌ 清除失败，请检查日志。'
            
    elif normalized == '/允许语音通话' or normalized == '/ev':
        ok = _update_config_boolean('USE_VOICE_CALL_FOR_REMINDERS', True)
        reply_text = '📞 已允许使用语音通话进行提醒。' if ok else '❌ 操作失败，请检查日志。'
        
    elif normalized == '/禁止语音通话' or normalized == '/dv':
        ok = _update_config_boolean('USE_VOICE_CALL_FOR_REMINDERS', False)
        reply_text = '🔕 已禁止使用语音通话进行提醒。' if ok else '❌ 操作失败，请检查日志。'
        
    elif normalized == '/帮助' or normalized == '/help':
        reply_text = """📖 可用指令列表 📖
-------------
/重启 (/re)

/关闭主动消息 (/da)

/开启主动消息 (/ea)

/清除临时记忆 (/cl)
  » 清除当前聊天的短期记忆和上下文（包括memory_temp文件），开始新的对话。

/允许语音通话 (/ev)

/禁止语音通话 (/dv)

/帮助 (/help)
--------------
"""
    # 函数最后返回 reply_text (如果匹配到指令就是文本，否则是 None)
    return reply_text