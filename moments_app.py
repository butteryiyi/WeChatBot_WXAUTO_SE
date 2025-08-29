# moments_app.py (v8.0 - 终极智能交互重构版)

import os
import json
import logging
import re
import requests
import random
import time
import uuid
import threading
import base64
import mimetypes
from openai import OpenAI
from urllib.parse import quote
from flask import Flask, render_template, jsonify, request, send_from_directory, url_for, session, redirect
from flask_cors import CORS
from datetime import datetime
from werkzeug.utils import secure_filename
from setting import settings_bp, parse_config_from_file, load_user_profile, load_avatar_mapping, load_relationships

# --- 全局配置和常量 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app, resources={r"/api/*": {"origins": "*"}})
app.secret_key = os.urandom(24)

CONFIG_FILE = "config.py"
CHAT_CONTEXTS_FILE = "chat_contexts.json"
MOMENTS_DATABASE_FILE = "moments_database.json"
PROCESSING_STATE_FILE = "processing_state.json"
USED_MEDIA_FILE = "used_local_media.json"
PYQ_FOLDER = "pyq"
PROMPTS_FOLDER = "prompts"
USER_UPLOADS_FOLDER = os.path.join(PYQ_FOLDER, "user_uploads")

os.makedirs(USER_UPLOADS_FOLDER, exist_ok=True)
db_lock = threading.Lock()

# --- 辅助函数 (无改动) ---
def _load_json_file(filepath, default_value):
    if not os.path.exists(filepath): return default_value
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content: return default_value
            return json.loads(content)
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"加载 JSON 文件失败 '{filepath}': {e}")
        return default_value

def _save_json_file(filepath, data):
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except IOError as e:
        logging.error(f"写入 JSON 文件失败 '{filepath}': {e}")
        return False

def _filter_sensitive_content(text):
    if not text: return ""
    replacements = {"出生悲惨": "经历坎坷","嫉妒": "羡慕","杀伐果断": "行事果断","会骂人": "性格直接","吊儿郎当": "不拘小节"}
    for old, new in replacements.items(): text = text.replace(old, new)
    return text

# 移除分隔符的清洗器：删除形如 ---、———、***、###、=== 等分隔线
def _sanitize_no_separators(text):
    if not text: return ""
    try:
        # 去除整行的分隔线
        lines = text.split('\n')
        cleaned_lines = []
        sep_line_pattern = re.compile(r'^\s*[-—_*=#~]{3,}\s*$')
        for line in lines:
            if sep_line_pattern.match(line):
                continue
            # 行内的长分隔符片段压缩为一个空格
            line = re.sub(r'[-—_*=#~]{3,}', ' ', line)
            cleaned_lines.append(line)
        cleaned = '\n'.join(cleaned_lines)
        # 清除多余空白
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
        return cleaned
    except Exception:
        return text

def load_used_media(): return _load_json_file(USED_MEDIA_FILE, [])
def save_used_media(used_list): _save_json_file(USED_MEDIA_FILE, used_list)
def get_local_categories():
    if not os.path.isdir(PYQ_FOLDER): return []
    categories = [d for d in os.listdir(PYQ_FOLDER) if os.path.isdir(os.path.join(PYQ_FOLDER, d))]
    # 排除用户上传目录，防止NPC使用主人上传的图片
    return [d for d in categories if d != 'user_uploads']

def get_local_media(category):
    category_path = os.path.join(PYQ_FOLDER, category)
    if not os.path.isdir(category_path): return None
    all_media = [f for f in os.listdir(category_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.mp4'))]
    if not all_media: return None
    used_media = load_used_media()
    # 增加短期冷却：避免短时间重复使用同一图片
    COOLDOWN_MAX = 50  # 记录最近50次使用，避免复用
    # used_media 为列表，后追加最新；仅认为不在最近 COOLDOWN_MAX 次中的为可用
    recent = used_media[-COOLDOWN_MAX:] if len(used_media) > COOLDOWN_MAX else used_media
    available_media = [m for m in all_media if os.path.join(category, m) not in recent]
    if not available_media:
        logging.info(f"分类 '{category}' 在冷却窗口内无可用媒体，放宽到全部媒体中随机选择。")
        available_media = all_media
    chosen_media_name = random.choice(available_media)
    chosen_media_path = os.path.join(category, chosen_media_name).replace('\\', '/')
    # 维护全局最近使用队列
    used_media.append(chosen_media_path)
    if len(used_media) > 500:
        used_media = used_media[-500:]
    save_used_media(used_media)
    with app.app_context():
        return url_for('serve_media', filename=chosen_media_path)

def get_image_from_pexels(keywords, config):
    api_key = config.get('PEXELS_API_KEY')
    if not api_key or '粘贴你' in api_key: return None
    try:
        headers = {"Authorization": api_key}
        # 最强排除：人物及身体相关词汇
        exclusions = [
            '-person','-people','-human','-man','-woman','-boy','-girl','-male','-female',
            '-face','-portrait','-headshot','-selfie','-fashion','-model','-bride','-groom','-wedding',
            '-hand','-hands','-arm','-arms','-shoulder','-shoulders','-leg','-legs','-foot','-feet','-finger','-fingers','-nail','-nails','-skin','-body','-bodies','-closeup','-torso'
        ]
        # 倾向风景/场景/物件类
        scenery_bias = ['scenery','landscape','nature','architecture','interior','cityscape','street','nightscape','mountain','forest','ocean','sky','sunset','sunrise','lake','river','garden','room','desk','object','still life']
        final_keywords = keywords + scenery_bias
        query_with_exclusions = f"{','.join(final_keywords + exclusions)}"
        url = f"https://api.pexels.com/v1/search?query={quote(query_with_exclusions)}&per_page=20"
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            photos = response.json().get('photos', [])
            # 二次过滤：alt 和摄影师名等元数据中如含人/肢体关键词则剔除
            def is_non_human(p):
                alt = (p.get('alt') or '').lower()
                bad_tokens = [
                    'person','people','human','man','woman','boy','girl','male','female','portrait','face','selfie','model','fashion','wedding',
                    'hand','hands','arm','arms','shoulder','leg','legs','foot','feet','finger','fingers','nail','nails','skin','body','bodies','torso'
                ]
                return not any(tok in alt for tok in bad_tokens)
            filtered = [p for p in photos if is_non_human(p)]
            pick = random.choice(filtered or photos) if (filtered or photos) else None
            if pick: return pick['src']['large']
        return None
    except Exception: return None

def get_image_description_from_moonshot(image_path, config):
    api_key, api_url, model = config.get('MOONSHOT_API_KEY'), config.get('MOONSHOT_BASE_URL'), config.get('MOONSHOT_MODEL')
    if api_url and 'chat/completions' not in api_url: api_url = api_url.rstrip('/') + '/chat/completions'
    if not all([api_key, api_url, model]): return "[图片识别配置错误]"
    try:
        with open(image_path, "rb") as image_file: base64_image = base64.b64encode(image_file.read()).decode('utf-8')
    except Exception: return "[图片文件处理失败]"
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type: mime_type = "image/jpeg"
    headers = { "Authorization": f"Bearer {api_key}", "Content-Type": "application/json" }
    payload = { "model": model, "messages": [{"role": "user", "content": [{"type": "text", "text": "请用一句话简要、直接地描述这张图片，不要有任何多余的前缀或解释。"}, {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}]}], "temperature": 0.3 }
    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        return response.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip() or "[图片识别结果为空]"
    except requests.exceptions.RequestException: return "[图片识别API错误]"
    except Exception: return "[图片识别失败]"

def load_persona_prompt(character_name):
    prompt_path = os.path.join(PROMPTS_FOLDER, f"{character_name}.md")
    if not os.path.exists(prompt_path): return ""
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f: return f.read()
    except IOError: return ""

def read_moments_database():
    with db_lock: return _load_json_file(MOMENTS_DATABASE_FILE, [])

def write_moments_database(data):
    with db_lock: _save_json_file(MOMENTS_DATABASE_FILE, data)

# --- 朋友圈生成与更新逻辑 (无改动) ---
def generate_moment_for_character(character_name, conversation_context, config, local_categories, all_relationships):
    api_key, base_url = config.get('DEEPSEEK_API_KEY'), config.get('DEEPSEEK_BASE_URL')
    if not api_key or not base_url: return None
    client = OpenAI(api_key=api_key, base_url=base_url)
    persona_prompt = _filter_sensitive_content(load_persona_prompt(character_name))
    relationships_text = _filter_sensitive_content(all_relationships.get(character_name, ""))
    filtered_conversation = []
    if conversation_context:
        for msg in conversation_context:
            filtered_content = _filter_sensitive_content(msg.get('content', ''))
            filtered_conversation.append(f"{msg.get('role', 'unknown')}: {filtered_content}")
    chat_log = "\n".join(filtered_conversation)

    if relationships_text:
        prompt = f"""你将扮演【{character_name}】生成一条完整的朋友圈动态，包括NPC互动。
# 核心人设
{persona_prompt}
# 人际关系 (你的NPC互动必须基于此)
{relationships_text}
# 参考素材 (如果为空则代表是创意发布)
{chat_log or "无，请自由创作。"}
# 任务
严格按以下JSON格式输出，不要有任何多余文字:
1. `post_text`: 创作朋友圈文案。
2. `media_suggestion`: 提供配图建议。可以使用【本地分类】[{", ".join(local_categories) or "无"}]，或使用【Pexels关键词】（数组），也可以选择不配图（source 设为 "none"）。若使用Pexels，必须仅限风景/场景/物件，严禁出现人物或身体任何部分。
3. `likes`: 从人际关系中挑选2-5个会点赞的NPC名字，并【根据你的性格和文案内容，决定是否也把自己({character_name})加入点赞列表】，最终组成一个包含所有点赞者名字的数组。
4. `npc_comments`: 挑选1-3个NPC发表评论，并可选择性地让【{character_name}】进行回复。
# 约束
禁止使用任何分隔符（例如 ---、——、***、### 等符号线）。
# 配图硬性约束
严禁出现任何人物、肢体或身体部位；优先选择贴合角色的风景/场景/物件。
# 输出格式 (必须严格遵守)
{{
  "post_text": "朋友圈文案...",
  "media_suggestion": {{ "source": "local", "identifier": "分类名" }},
  "likes": ["NPC名字1", "{character_name}", "NPC名字2"],
  "npc_comments": [
    {{ "author": "NPC名字3", "text": "评论内容...", "reply": null }},
    {{ "author": "NPC名字4", "text": "另一条评论...", "reply": "你的回复内容..." }}
  ]
}}
"""
    else:
        prompt = f"""你将扮演【{character_name}】生成一条朋友圈。
# 核心人设
{persona_prompt}
# 参考素材 (如果为空则代表是创意发布)
{chat_log or "无，请自由创作。"}
# 任务
严格按以下JSON格式输出，不要有任何多余文字:
1. `post_text`: 创作朋友圈文案。
2. `media_suggestion`: 提供配图建议。可用本地分类: [{", ".join(local_categories) or "无"}]，或选择不配图（source 设为 "none"）。
# 约束
禁止使用任何分隔符（例如 ---、——、***、### 等符号线）。如果使用Pexels配图，必须仅限风景/场景/物件，严禁出现人物或任何身体部位。
# 输出格式 (必须严格遵守)
{{
  "post_text": "朋友圈文案...",
  "media_suggestion": {{ "source": "pexels", "identifier": ["keyword1", "keyword2"] }}
}}"""
    
    try:
        response = client.chat.completions.create(model=config.get('MODEL', 'deepseek-chat'), messages=[{"role": "user", "content": prompt}], temperature=float(config.get('TEMPERATURE', 0.8)), response_format={"type": "json_object"})
        raw_content = response.choices[0].message.content
        # 先去除可能的代码围栏
        cleaned = raw_content.strip()
        if cleaned.startswith('```'):
            # 兼容 ```json 或 ```
            cleaned = cleaned.split('\n', 1)[-1]
            if cleaned.endswith('```'):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        # 提取第一个大括号JSON片段
        json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if not json_match:
            logging.error(f"角色 '{character_name}' 的AI响应中未找到有效的JSON结构。响应内容: '{raw_content}'")
            return None
        json_string = json_match.group(0)
        try:
            result_json = json.loads(json_string)
        except json.JSONDecodeError:
            # 宽松清洗重试：给未加引号的键加引号，替换单引号为双引号
            tentative = re.sub(r'([\{\s,])(\w+)\s*:', r'\1"\2":', json_string)
            tentative = re.sub(r"'", '"', tentative)
            try:
                result_json = json.loads(tentative)
            except Exception as e2:
                logging.error(f"角色 '{character_name}' JSON解析失败，已尝试清洗仍失败。原始: {json_string} | 错误: {e2}")
                return None
        if not result_json.get("post_text"): return None
        # 清洗文本，移除分隔符
        result_json["post_text"] = _sanitize_no_separators(result_json.get("post_text", ""))
        # 同步清洗评论内容
        if isinstance(result_json.get("npc_comments"), list):
            for item in result_json["npc_comments"]:
                if isinstance(item, dict):
                    if item.get("text"): item["text"] = _sanitize_no_separators(item.get("text", ""))
                    if item.get("reply"): item["reply"] = _sanitize_no_separators(item.get("reply", ""))

        media_suggestion = result_json.get("media_suggestion", {})
        media_url = None
        if media_suggestion.get("source") == "none":
            media_url = None
        elif media_suggestion.get("source") == "local" and media_suggestion.get("identifier") in local_categories:
            media_url = get_local_media(media_suggestion["identifier"])
        elif media_suggestion.get("source") == "pexels" and isinstance(media_suggestion.get("identifier"), list):
            media_url = get_image_from_pexels(media_suggestion["identifier"], config)
        # 兜底：如果未能拿到媒体且存在 PEXELS_API_KEY，则尝试以角色名+风景偏好做二次检索
        if media_suggestion.get("source") != "none" and not media_url and config.get('PEXELS_API_KEY'):
            scenic_fallback = [character_name, 'scenery','landscape','nature','architecture','cityscape']
            media_url = get_image_from_pexels(scenic_fallback, config)
        moment_item = {'id': str(uuid.uuid4()),'author': character_name,'post_text': result_json.get("post_text"),'image_url': media_url,'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),'likes': result_json.get("likes", []), 'comments': []}
        for npc_comment in result_json.get("npc_comments", []):
            if npc_comment.get("author") and npc_comment.get("text"):
                moment_item['comments'].append({"author": npc_comment["author"],"text": npc_comment["text"],"timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
                if npc_comment.get("reply"):
                    moment_item['comments'].append({"author": character_name,"text": npc_comment["reply"],"reply_to": npc_comment["author"],"timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        return moment_item
    except Exception as e:
        logging.error(f"角色 '{character_name}' 朋友圈生成失败: {e}", exc_info=True)
        return None

def update_moments_from_context(is_creative_only=False):
    # ... 此函数代码保持不变 ...
    logging.info(f"开始朋友圈更新，模式: {'创意发布' if is_creative_only else '常规检查'}")
    try:
        current_config = parse_config_from_file(CONFIG_FILE)
        all_contexts = _load_json_file(CHAT_CONTEXTS_FILE, {})
        all_relationships = load_relationships()
    except Exception as e:
        logging.error(f"加载配置文件或数据文件失败: {e}")
        return

    local_categories = get_local_categories()
    newly_generated_moments = []

    if is_creative_only:
        logging.info("强制创意发布模式...")
        all_character_names = [name for group in all_contexts.values() if isinstance(group, dict) for name in group.keys()]
        if all_character_names:
            target_character = random.choice(all_character_names)
            logging.info(f"随机选择角色 '{target_character}' 进行创意发布。")
            moment_item = generate_moment_for_character(target_character, None, current_config, local_categories, all_relationships)
            if moment_item:
                group_name = next((g for g, c in all_contexts.items() if isinstance(c, dict) and target_character in c), "Unknown")
                moment_item['group'] = group_name
                newly_generated_moments.append(moment_item)
                logging.info(f"为角色 '{target_character}' 成功生成一条创意朋友圈。")
        else:
            logging.warning("创意发布失败：无法找到任何角色。")
    else:
        processing_state = _load_json_file(PROCESSING_STATE_FILE, {})
        for group_name, characters in all_contexts.items():
            if not isinstance(characters, dict): continue
            for character_name, conversation in characters.items():
                if not isinstance(conversation, list): continue
                last_processed_count = int(processing_state.get(character_name, 0))
                current_total_count = len(conversation)
                if current_total_count > last_processed_count:
                    logging.info(f"角色 '{character_name}' 发现 {current_total_count - last_processed_count} 条新消息，正在分析...")
                    moment_item = generate_moment_for_character(character_name, conversation[last_processed_count:], current_config, local_categories, all_relationships)
                    if moment_item:
                        moment_item['group'] = group_name
                        newly_generated_moments.append(moment_item)
                    processing_state[character_name] = current_total_count
                elif current_total_count < last_processed_count:
                    processing_state[character_name] = current_total_count
        _save_json_file(PROCESSING_STATE_FILE, processing_state)
    
    if newly_generated_moments:
        moments_database = read_moments_database()
        moments_database.extend(newly_generated_moments)
        moments_database.sort(key=lambda x: x.get('timestamp', '0'), reverse=True)
        write_moments_database(moments_database)
        logging.info(f"成功生成并保存了 {len(newly_generated_moments)} 条新朋友圈。")
    
    logging.info("朋友圈更新检查完成。")

# --- v8.0 CORE REFACTOR: 全新的NPC智能交互逻辑 ---

# -------------------------- v9.0 核心新增模块 --------------------------
def build_derived_persona_and_context(character_to_find, all_relationships):
 
    line_pattern = re.compile(r'^\s*\[?(.+?)\]?\s*[:：]\s*(.*)', re.UNICODE)
    
    for primary_character, relations_text in all_relationships.items():
        if not isinstance(relations_text, str):
            continue
        for line in relations_text.split('\n'):
            match = line_pattern.match(line.strip())
            if match:
                mentioned_npc_name = match.group(1).strip()
                description = match.group(2).strip()
                
                if mentioned_npc_name == character_to_find:
                    # 找到了！返回这个NPC的单句描述，以及定义他的“主导者”的名字
                    return description, primary_character
                    
    return None, None
# -----------------------------------------------------------------------


def decide_and_generate_npc_reply(moment_id, replier_name, trigger_comment, is_primary_reactor, is_commenter_the_user):
    """
    【v9.1 重构】
    集成“主导者人设注入”系统的AI决策核心。
    """
    logging.info(f"AI决策模块 v9.1 启动：角色【{replier_name}】 | 主要: {is_primary_reactor} | 评论者是主人: {is_commenter_the_user}")
    config = parse_config_from_file(CONFIG_FILE)
    api_key, base_url, model = config.get('DEEPSEEK_API_KEY'), config.get('DEEPSEEK_BASE_URL'), config.get('MODEL', 'deepseek-chat')
    if not all([api_key, base_url, model]) or '粘贴你' in api_key:
        logging.error(f"角色 {replier_name} 的AI配置不完整，跳过回复。")
        return None

    all_moments = read_moments_database()
    moment = next((m for m in all_moments if m.get('id') == moment_id), None)
    if not moment: return None

    all_relationships = load_relationships()
    user_profile = load_user_profile()

    # --- v9.1 增强人设获取逻辑 ---
    persona_prompt = _filter_sensitive_content(load_persona_prompt(replier_name))
    relationships_text = _filter_sensitive_content(all_relationships.get(replier_name, ""))
    host_persona_context = "" # 新增：用于存放主导者人设的变量

    # 如果没有专用人设，则启动派生逻辑
    if not persona_prompt:
        logging.info(f"未找到【{replier_name}】的专用人设，尝试派生...")
        derived_description, host_character_name = build_derived_persona_and_context(replier_name, all_relationships)
        
        if derived_description and host_character_name:
            # 1. 构建派生角色的基础人设
            persona_prompt = f"你是【{replier_name}】。你的核心设定是：{derived_description}。"
            logging.info(f"成功派生【{replier_name}】的人设: “{derived_description}”")
            
            # 2. 【核心】加载并注入主导者的人设作为上下文
            host_persona = _filter_sensitive_content(load_persona_prompt(host_character_name))
            if host_persona:
                host_persona_context = f"""
# 重要参考：你的主导者【{host_character_name}】的完整人设 (CRITICAL CONTEXT)
你正在TA的朋友圈下互动。TA的性格和背景是你所有行为的最重要参考基准。
---
{host_persona}
---
"""
                logging.info(f"已成功为【{replier_name}】注入主导者【{host_character_name}】的完整人设。")

            # 3. 使用主导者的关系网作为自己的参考关系网
            relationships_text = _filter_sensitive_content(all_relationships.get(host_character_name, ""))
        else:
            logging.warning(f"无法为【{replier_name}】找到专用或派生人设，跳过回复。")
            return None
    
    if not relationships_text:
        relationships_text = "你目前没有明确的人际关系网。"
    # --- 人设获取逻辑结束 ---
    
    # ... (身份提示 identity_prompt 和 任务指令 task_prompt 的生成逻辑保持不变) ...
    if is_commenter_the_user:
        identity_prompt = f"评论者【{trigger_comment.get('author')}】是你的核心互动对象 “{user_profile.get('nickname', '用户')}”，TA对你来说是特殊的存在。"
    else:
        identity_prompt = f"评论者【{trigger_comment.get('author')}】是一个访客，不是你的核心互动对象“{user_profile.get('nickname', '用户')}”。"
    if is_primary_reactor:
        task_prompt = f"你被指定为主要响应者，**必须**对【最新事件】做出回应。"
    else:
        task_prompt = f"你是一个次要响应者。请严格基于你的人设和上下文，判断是否要插话。若你认为无需插话，就保持沉默。"

    # 【向你确认】这里负责发送所有历史评论
    def format_comment(c):
        return f"{c.get('author','?')} 回复 {c.get('reply_to')}: {c.get('text','')}" if c.get('reply_to') else f"{c.get('author','?')}: {c.get('text','')}"
    comments_history = "\n".join([format_comment(c) for c in moment.get('comments', [])]) or "（暂无评论）"
    
    # 构建最终的、信息极其丰富的Prompt
    prompt = f"""你正在扮演一个在朋友圈下决定如何评论的角色。

# 你的身份 (YOUR IDENTITY)
{persona_prompt}
{host_persona_context}
# 你的人际关系网 (YOUR SOCIAL NETWORK)
{relationships_text}

# 场景背景 (SCENE)
- 朋友圈作者: {moment.get('author')}
- 朋友圈原文: {moment.get('post_text')}
- **当前评论区完整记录:**
---
{comments_history}
---

# 最新事件 (THE TRIGGER)
刚刚，【{trigger_comment.get('author')}】对【{trigger_comment.get('reply_to') or '所有人'}】说: “{trigger_comment.get('text')}”

# 关于评论者的重要情报 (INTEL ON COMMENTER)
{identity_prompt}

# 你的任务 (YOUR TASK)
{task_prompt}
- 你的回复可以针对刚发言的 `{trigger_comment.get('author')}`，也可以针对TA提到的 `{trigger_comment.get('reply_to')}`，或发表无人回复的感叹。
# 写作约束 (CONSTRAINTS)
严禁使用任何分隔符（例如 ---、——、***、### 等）。

# 输出格式 (STRICTLY JSON)
必须严格按照以下 JSON 格式输出你的决策，不要有任何多余的解释或Markdown标记。
{{
  "should_reply": boolean,
  "reply_text": "你的回复内容 (如果 should_reply 为 true，否则为空字符串)",
  "reply_to": "你打算回复的人名 (如果适用，否则为 null)"
}}
"""
    # ... (与AI通信的 try...except... 块保持不变) ...
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], temperature=float(config.get('TEMPERATURE', 0.9)), response_format={"type": "json_object"})
        content = response.choices[0].message.content
        json_string = content.strip()
        if json_string.startswith('```json'):
            json_string = json_string[7:].strip().rstrip('```').strip()
        decision = json.loads(json_string)

        if is_primary_reactor and not decision.get("should_reply"):
            logging.warning(f"主要响应者【{replier_name}】AI返回should_reply=false，但逻辑强制其回复。")
            decision["should_reply"] = True

        if decision.get("should_reply") and decision.get("reply_text"):
            # 清洗回复文本，移除分隔符
            decision["reply_text"] = _sanitize_no_separators(decision.get("reply_text", ""))
            logging.info(f"AI决策结果：角色【{replier_name}】决定回复。")
            return decision
        else:
            logging.info(f"AI决策结果：角色【{replier_name}】决定保持沉默。")
            return None
    except json.JSONDecodeError as e:
        logging.error(f"角色 {replier_name} 的AI决策响应JSON解析失败: {e}. 响应: '{content}'")
        return None
    except Exception as e:
        logging.error(f"角色 {replier_name} 的AI决策时发生异常: {e}", exc_info=True)
        return None

def process_single_npc_reaction(moment_id, replier_name, trigger_comment, is_primary, is_user):
    """
    处理单个NPC反应的线程任务。
    """
    delay = random.uniform(3, 10) if is_primary else random.uniform(8, 20)
    logging.info(f"角色【{replier_name}】将在 {delay:.1f} 秒后做出反应...")
    time.sleep(delay)

    decision = decide_and_generate_npc_reply(moment_id, replier_name, trigger_comment, is_primary, is_user)
    
    if decision:
        ai_comment_obj = {
            "author": replier_name,
            "text": _sanitize_no_separators(decision["reply_text"]),
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        if decision.get("reply_to"):
            ai_comment_obj["reply_to"] = decision["reply_to"]
        
        with db_lock:
            all_moments = _load_json_file(MOMENTS_DATABASE_FILE, [])
            moment_to_update = next((m for m in all_moments if m.get('id') == moment_id), None)
            if moment_to_update:
                moment_to_update.setdefault('comments', []).append(ai_comment_obj)
                _save_json_file(MOMENTS_DATABASE_FILE, all_moments)
                logging.info(f"角色【{replier_name}】的评论已成功添加。")
            else:
                logging.warning(f"在角色【{replier_name}】准备写入评论时，moment_id: {moment_id} 已消失。")

def orchestrate_npc_reactions(moment_id, new_comment):
    """
    v8.2 修复版“智能关联导演”。
    核心修复：正则表达式同时支持中英文冒号 : 和 ：，确保能解析用户输入。
    """
    logging.info("「智能关联导演 v2.2」启动，开始分析评论...")
    all_moments = read_moments_database()
    moment = next((m for m in all_moments if m.get('id') == moment_id), None)
    if not moment:
        logging.warning(f"导演未找到 moment_id: {moment_id}，工作中断。")
        return
    user_profile = load_user_profile()
    all_known_npcs = set()
    all_contexts = _load_json_file(CHAT_CONTEXTS_FILE, {})
    for group in all_contexts.values():
        if isinstance(group, dict):
            all_known_npcs.update(group.keys())

    all_relationships = load_relationships()
    all_known_npcs.update(all_relationships.keys())

    line_pattern = re.compile(r'^\s*\[?(.+?)\]?\s*[:：]\s*', re.UNICODE)
    for rel_text in all_relationships.values():
        if not isinstance(rel_text, str): continue
        for line in rel_text.split('\n'):
            match = line_pattern.match(line.strip())
            if match:
                npc_name = match.group(1).strip()
                all_known_npcs.add(npc_name)
    logging.info(f"导演构建的完整NPC名单: {list(all_known_npcs)}")
    
    commenter_name = new_comment.get('author')
    is_commenter_the_user = (commenter_name == user_profile.get('nickname'))
    logging.info(f"评论者: 【{commenter_name}】 | 是否为主人: {is_commenter_the_user}")

   
    primary_reactor = None
    replied_to_name = new_comment.get('reply_to')
    if replied_to_name and replied_to_name in all_known_npcs:
        primary_reactor = replied_to_name
    elif moment.get('author') in all_known_npcs:
        primary_reactor = moment.get('author')
    
    if primary_reactor:
        logging.info(f"已确定主要响应者: 【{primary_reactor}】")
        thread_primary = threading.Thread(target=process_single_npc_reaction, args=(moment_id, primary_reactor, new_comment, True, is_commenter_the_user))
        thread_primary.start()

    secondary_reactors = set()
    secondary_reactors.add(moment.get('author'))
    for c in moment.get('comments', []): 
        secondary_reactors.add(c.get('author'))
    
    secondary_reactors.discard(commenter_name)
    if primary_reactor:
        secondary_reactors.discard(primary_reactor)
    secondary_reactors = {npc for npc in secondary_reactors if npc in all_known_npcs}
    
    if secondary_reactors:
        logging.info(f"已确定次要响应者: {list(secondary_reactors)}")
        for reactor_name in secondary_reactors:
            thread_secondary = threading.Thread(target=process_single_npc_reaction, args=(moment_id, reactor_name, new_comment, False, is_commenter_the_user))
            thread_secondary.start()
    
    if not primary_reactor and not secondary_reactors:
        logging.info("未找到合适的NPC进行响应，导演工作结束。")

def generate_single_comment_thread(character_name, moment_id, user_nickname, image_description, config):
    """
    这是一个独立的、线程安全的工作函数，负责单个NPC对新帖子的反应。
    [v2.5.2 最终修复] 修复了语法错误并保持了对AI返回JSON的清洗能力。
    """
    with app.app_context():
        response = None
        try:
            time.sleep(random.uniform(5, 15)) 
            
            api_key, base_url = config.get('DEEPSEEK_API_KEY'), config.get('DEEPSEEK_BASE_URL')
            if not api_key or '粘贴你' in api_key or not base_url: 
                logging.warning(f"角色 '{character_name}' 的API配置无效，跳过评论。")
                return

            persona_prompt = load_persona_prompt(character_name)
            if not persona_prompt: 
                logging.info(f"角色 '{character_name}' 没有找到人设文件，不进行互动。")
                return
            
            db_snapshot = read_moments_database()
            target_moment = next((m for m in db_snapshot if m.get('id') == moment_id), None)
            if not target_moment: 
                logging.warning(f"角色 '{character_name}' 准备评论时，帖子 {moment_id} 已不存在。")
                return

            comments_so_far = target_moment.get('comments', [])
            comments_history_text = "\n".join([f"{c.get('author')}: {c.get('text')}" for c in comments_so_far]) or "（暂无评论）"
            
            post_content_parts = []
            if target_moment.get('post_text', ''): post_content_parts.append(f"文案是：“{target_moment.get('post_text')}”")
            if target_moment.get('image_url'): post_content_parts.append(f"配图内容大致是：“{image_description}”" if image_description else "TA还配了一张图片。")
            post_content_prompt = "\n".join(post_content_parts) if post_content_parts else "TA什么都没说。"
            
            identity_prompt = f"你的核心互动对象 “{user_nickname}” 刚刚发了一条新朋友圈。"

            full_prompt = f"""{identity_prompt}
{post_content_prompt}

目前朋友圈下的评论有：
---
{comments_history_text}
---

你的角色人设:
---
{persona_prompt}
---

任务: 你的名字是【{character_name}】。请对“{user_nickname}”的这条朋友圈做出反应。严格按照下面的JSON格式输出你的决策，不要有任何额外文本或Markdown标记：
写作约束：严禁使用任何分隔符（例如 ---、——、***、### 等）。
{{
  "should_comment": boolean,
  "comment_text": "你的评论内容。如果should_comment为false，则此项为空字符串。",
  "should_like": boolean
}}"""
            
            client = OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=config.get('MODEL', 'deepseek-chat'), 
                messages=[{"role": "user", "content": _filter_sensitive_content(full_prompt)}], 
                temperature=float(config.get('TEMPERATURE', 0.8)),
                response_format={"type": "json_object"}
            )
            
            raw_content = response.choices[0].message.content
            json_match = re.search(r'\{.*\}', raw_content, re.DOTALL)
            if not json_match:
                logging.error(f"处理角色 '{character_name}' 评论时，AI响应中未找到有效的JSON结构。AI响应: '{raw_content}'")
                return

            cleaned_json_str = json_match.group(0)
            decision = json.loads(cleaned_json_str)


            should_comment = decision.get("should_comment", False)
            comment_text = _sanitize_no_separators(decision.get("comment_text", "").strip().strip('\"\''))
            should_like = decision.get("should_like", False)

            if not should_comment and not should_like:
                logging.info(f"角色 '{character_name}' 决定对该帖子不进行互动。")
                return

            with db_lock:
                db_after_sleep = _load_json_file(MOMENTS_DATABASE_FILE, [])
                moment_to_update = next((m for m in db_after_sleep if m.get('id') == moment_id), None)
                if moment_to_update:
                    action_taken = False
                    if should_comment and comment_text:
                        new_comment_obj = {"author": character_name, "text": comment_text, "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                        moment_to_update.setdefault('comments', []).append(new_comment_obj)
                        logging.info(f"角色 '{character_name}' 添加了评论: '{comment_text}'")
                        action_taken = True
                    
                    if should_like:
                        likes_list = moment_to_update.setdefault('likes', [])
                        if character_name not in likes_list:
                            likes_list.append(character_name)
                            logging.info(f"角色 '{character_name}' 点了赞。")
                            action_taken = True
                    
                    if action_taken:
                        _save_json_file(MOMENTS_DATABASE_FILE, db_after_sleep)
                        
        except json.JSONDecodeError as e:
            raw_response_for_log = response.choices[0].message.content if response and response.choices else 'N/A'
            logging.error(f"处理角色 '{character_name}' 评论时JSON解析失败: {e}. AI响应: '{raw_response_for_log}'", exc_info=True)
        except Exception as e:
            logging.error(f"处理角色 '{character_name}' 评论时发生严重错误: {e}", exc_info=True)




def trigger_all_characters_comment_on_post(moment_id, user_nickname, image_description=None):
    """
    此函数仅负责调度，为每个角色分配合适的参数并启动一个独立的、健壮的工作线程。
    """
    try:
        current_config = parse_config_from_file(CONFIG_FILE)
        
        with app.app_context():
            all_characters = sorted(list(set([name for group in _load_json_file(CHAT_CONTEXTS_FILE, {}).values() if isinstance(group, dict) for name in group.keys()])))
        
        random.shuffle(all_characters)
        
        logging.info(f"调度中心启动：将为 {len(all_characters)} 个角色分配评论任务...")
        
        for character_name in all_characters:
            thread_args = (character_name, moment_id, user_nickname, image_description, current_config)
            thread = threading.Thread(target=generate_single_comment_thread, args=thread_args)
            thread.start()
            
    except Exception as e:
        logging.error(f"在 'trigger_all_characters_comment_on_post' 调度时发生错误: {e}", exc_info=True)
@app.route('/')
def index():
    user_profile = load_user_profile()
    return render_template('moments.html', user_profile=user_profile)

@app.route('/login', methods=['GET', 'POST'])
def login():
    current_config = parse_config_from_file(CONFIG_FILE)
    if request.method == 'POST':
        expected_password = str(current_config.get('LOGIN_PASSWORD', ''))
        if expected_password and request.form.get('password') == expected_password:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return render_template('logining.html', error="密码错误")
    # GET 一律展示登录页（不再自动登录）
    return render_template('logining.html')

@app.route('/api/auth_status')
def auth_status():
    return jsonify({"is_logged_in": session.get('logged_in', False)})

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

@app.route('/media/<path:filename>')
def serve_media(filename):
    return send_from_directory(PYQ_FOLDER, filename)

@app.route('/api/generate_moments', methods=['GET'])
def get_or_generate_moments():
    is_force_mode = request.args.get('force', 'false').lower() == 'true'
    
    if is_force_mode:
        if not session.get('logged_in', False): 
            return jsonify({"error": "未授权，请先登录后再强制刷新"}), 403
        logging.info("接收到强制更新请求，将执行创意发布...")
        update_moments_from_context(is_creative_only=True)
    
    all_moments = read_moments_database()
    avatar_map = load_avatar_mapping()
    user_profile = load_user_profile()
    for moment in all_moments:
        author = moment.get('author')
        if author == user_profile.get('nickname'): 
            moment['avatar_url'] = url_for('static', filename=user_profile['avatar_url']) if user_profile.get('avatar_url') else None
        else: 
            avatar_file = avatar_map.get(author)
            moment['avatar_url'] = url_for('static', filename=f'avatars/{avatar_file}') if avatar_file else None
    
    return jsonify(all_moments)


@app.route('/api/create_post', methods=['POST'])
def create_user_post():
    if not session.get('logged_in'): return jsonify({"error": "未授权，请登录后再发布"}), 403
    try:
        user_profile = load_user_profile()
        nickname = user_profile.get('nickname')
        
        post_text = request.form.get('post_text', '')
        media_file = request.files.get('post_media')
        
        if not post_text and not media_file: 
            return jsonify({"error": "文本和媒体不能都为空"}), 400
            
        media_url, image_abs_path = None, None
        if media_file:
            filename = secure_filename(f"user_{int(time.time())}_{media_file.filename}")
            save_path = os.path.join(USER_UPLOADS_FOLDER, filename)
            media_file.save(save_path)
            media_url, image_abs_path = url_for('serve_media', filename=f'user_uploads/{filename}'), save_path
            
        moment_id = str(uuid.uuid4())
        new_moment = {'id': moment_id, 'author': nickname, 'post_text': post_text, 'image_url': media_url, 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'likes': [], 'comments': []}
        
        all_moments = read_moments_database()
        all_moments.insert(0, new_moment)
        write_moments_database(all_moments)
        
        image_description = None
        if image_abs_path:
             config = parse_config_from_file(CONFIG_FILE)
             if config.get("MOONSHOT_API_KEY"):
                image_description = get_image_description_from_moonshot(image_abs_path, config)

        threading.Thread(target=trigger_all_characters_comment_on_post, args=(moment_id, nickname, image_description)).start()
        
        new_moment['avatar_url'] = url_for('static', filename=user_profile['avatar_url']) if user_profile.get('avatar_url') else None
        
        return jsonify(success=True, moment=new_moment)
        
    except Exception as e:
        logging.error(f"创建用户帖子失败: {e}", exc_info=True)
        return jsonify(error=str(e)), 500


@app.route('/api/moment/<string:moment_id>/like', methods=['POST'])
def like_moment(moment_id):
    nickname = request.json.get('nickname')
    if not nickname:
        return jsonify(error="需要提供昵称"), 400

    updated_moment = None
    with db_lock:
        all_moments = _load_json_file(MOMENTS_DATABASE_FILE, []) # 直接调用无锁的底层函数
        moment_to_update = next((m for m in all_moments if m.get('id') == moment_id), None)
        
        if not moment_to_update:
            # 在锁外部返回，避免持有锁
            return jsonify(error="未找到该朋友圈"), 404
            
        likes_list = moment_to_update.setdefault('likes', [])
        if nickname in likes_list:
            likes_list.remove(nickname)
        else:
            likes_list.append(nickname)
        
        if not _save_json_file(MOMENTS_DATABASE_FILE, all_moments): # 直接调用无锁的底层函数
             # 在锁外部返回
            return jsonify(error="点赞失败，无法写入数据库"), 500
        
        # 在写入成功后，再准备返回数据
        updated_moment = json.loads(json.dumps(moment_to_update))

    user_profile = load_user_profile()
    avatar_map = load_avatar_mapping()
    author = updated_moment.get('author')
    if author == user_profile.get('nickname'):
        updated_moment['avatar_url'] = url_for('static', filename=user_profile.get('avatar_url')) if user_profile.get('avatar_url') else None
    else:
        avatar_file = avatar_map.get(author)
        updated_moment['avatar_url'] = url_for('static', filename=f'avatars/{avatar_file}') if avatar_file else None

    return jsonify(updated_moment)

@app.route('/api/moment/<string:moment_id>/comment', methods=['POST'])
def comment_on_moment(moment_id):
    data = request.json
    nickname = data.get('nickname')
    text = data.get('text')
    reply_to = data.get('reply_to')

    if not nickname or not text:
        return jsonify(error="昵称和评论内容不能为空"), 400

    new_comment = {
        "author": nickname,
        "text": text,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    if reply_to:
        new_comment['reply_to'] = reply_to
    
    updated_moment = None
    with db_lock:
        all_moments = _load_json_file(MOMENTS_DATABASE_FILE, []) # 直接调用无锁的底层函数
        moment_to_update = next((m for m in all_moments if m.get('id') == moment_id), None)

        if not moment_to_update:
            return jsonify(error="未找到该朋友圈"), 404

        moment_to_update.setdefault('comments', []).append(new_comment)
        
        if not _save_json_file(MOMENTS_DATABASE_FILE, all_moments): # 直接调用无锁的底层函数
            return jsonify(error="评论失败，无法写入数据库"), 500
        
        updated_moment = json.loads(json.dumps(moment_to_update))
            

    thread = threading.Thread(target=orchestrate_npc_reactions, args=(moment_id, new_comment))
    thread.start()
 
    user_profile = load_user_profile()
    avatar_map = load_avatar_mapping()
    author = updated_moment.get('author')
    if author == user_profile.get('nickname'):
        updated_moment['avatar_url'] = url_for('static', filename=user_profile.get('avatar_url')) if user_profile.get('avatar_url') else None
    else:
        avatar_file = avatar_map.get(author)
        updated_moment['avatar_url'] = url_for('static', filename=f'avatars/{avatar_file}') if avatar_file else None
        
    return jsonify(updated_moment)


@app.route('/api/moment/<string:moment_id>/delete', methods=['DELETE'])
def delete_moment(moment_id):
    if not session.get('logged_in'): 
        return jsonify(error="未授权，请先登录"), 403
    
    with db_lock:
        all_moments = _load_json_file(MOMENTS_DATABASE_FILE, []) # 直接调用无锁的底层函数
        original_length = len(all_moments)
        updated_moments = [m for m in all_moments if m.get('id') != moment_id]
        
        if len(updated_moments) < original_length:
            _save_json_file(MOMENTS_DATABASE_FILE, updated_moments) # 直接调用无锁的底层函数
            logging.info(f"朋友圈 {moment_id} 已成功删除。")
            return "", 204
        else:
            return jsonify(error="未找到要删除的朋友圈"), 404



# --- 蓝图和启动 ---
app.register_blueprint(settings_bp)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5002)
