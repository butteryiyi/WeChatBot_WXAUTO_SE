# setting.py (v2.0 - with Relationship Management)

import os
import json
import logging
import re
import time
from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for
from werkzeug.utils import secure_filename

settings_bp = Blueprint(
    'settings',
    __name__,
    template_folder='templates',
    static_folder='static'
)

# --- 文件和目录定义 ---
CONFIG_FILE = "config.py"
CHAT_CONTEXTS_FILE = "chat_contexts.json"
USER_PROFILE_FILE = "user_profile.json"
AVATAR_MAPPING_FILE = "avatars.json"
RELATIONSHIPS_FILE = "relationships.json" # 【新增】人际关系数据文件

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
AVATAR_FOLDER = os.path.join('static', 'avatars')
USER_AVATAR_FOLDER = os.path.join('static', 'user')
USER_BACKGROUND_FOLDER = os.path.join('static', 'user_background')

os.makedirs(AVATAR_FOLDER, exist_ok=True)
os.makedirs(USER_AVATAR_FOLDER, exist_ok=True)
os.makedirs(USER_BACKGROUND_FOLDER, exist_ok=True)


# --- 辅助函数 ---

def parse_config_from_file(config_path):
    config = {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            exec(f.read(), {}, config)
        return config
    except Exception as e:
        logging.error(f"解析配置文件 {config_path} 失败: {e}")
        return {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- JSON 文件读写封装 (健壮性) ---
def _load_json_file(filepath, default_value):
    if not os.path.exists(filepath):
        return default_value
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # 防止文件为空时 json.load 报错
            content = f.read()
            if not content:
                return default_value
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

# 用户、头像、人际关系的数据接口
def load_user_profile():
    return _load_json_file(USER_PROFILE_FILE, {'nickname': '鱼', 'avatar_url': None, 'background_url': None})
def save_user_profile(data):
    return _save_json_file(USER_PROFILE_FILE, data)
def load_avatar_mapping():
    return _load_json_file(AVATAR_MAPPING_FILE, {})
def save_avatar_mapping(mapping):
    return _save_json_file(AVATAR_MAPPING_FILE, mapping)
def load_relationships(): # 【新增】
    return _load_json_file(RELATIONSHIPS_FILE, {})
def save_relationships(data): # 【新增】
    return _save_json_file(RELATIONSHIPS_FILE, data)

# ---【新增】人际关系格式服务端验证 ---
def validate_relationships_text(text):
    """
    验证人际关系文本格式。
    允许空字符串（表示删除关系）。
    如果非空，则每行必须是 "名字: 描述" 的格式。
    """
    if not text.strip():
        return True, "格式正确（空）"
    
    # 允许的格式:
    # 名字: 描述
    # 名字 :  描述
    # [名字]: 描述 (支持中括号)
    line_pattern = re.compile(r'^\s*\[?.+?\]?\s*:\s*.+\s*$', re.UNICODE)
    
    lines = text.strip().split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        if not line: # 忽略空行
            continue
        if not line_pattern.match(line):
            error_message = f"第 {i+1} 行格式错误。必须是 '名字: 描述' 的格式。"
            logging.warning(f"人际关系格式验证失败: {error_message} | 内容: '{line}'")
            return False, error_message
    return True, "格式正确"

# --- 视图和 API 路由 ---

@settings_bp.route('/settings')
def settings_page():
    current_config = parse_config_from_file(CONFIG_FILE)
    if current_config.get('ENABLE_LOGIN_PASSWORD', False) and not session.get('logged_in'):
        return redirect(url_for('login'))
    
    try:
        all_contexts = _load_json_file(CHAT_CONTEXTS_FILE, {})
        all_characters = sorted(list(set([name for group in all_contexts.values() if isinstance(group, dict) for name in group.keys()])))
    except Exception as e:
        logging.error(f"加载角色列表失败: {e}")
        all_characters = []
        
    user_profile = load_user_profile()
    avatar_map = load_avatar_mapping()
    # 【修改】不再需要传递 relationships，前端会通过API获取
    return render_template('settings.html', characters=all_characters, avatar_map=avatar_map, user_profile=user_profile)

# 【新增】获取所有人际关系的 API
@settings_bp.route('/api/character_relationships', methods=['GET'])
def get_all_relationships():
    if not session.get('logged_in'):
        return jsonify(error="未授权"), 401
    relationships = load_relationships()
    return jsonify(success=True, data=relationships)

# 【新增】保存/更新单个角色人际关系的 API
@settings_bp.route('/api/character_relationships', methods=['POST'])
def update_character_relationship():
    if not session.get('logged_in'):
        return jsonify(success=False, error="未授权"), 401

    data = request.json
    character_name = data.get('character_name')
    relationships_text = data.get('relationships_text', '')

    if not character_name:
        return jsonify(success=False, error="缺少角色名称"), 400

    # 服务端格式验证
    is_valid, message = validate_relationships_text(relationships_text)
    if not is_valid:
        return jsonify(success=False, error=message), 400

    all_relationships = load_relationships()
    all_relationships[character_name] = relationships_text.strip()
    
    # 如果内容为空，则从字典中移除该角色，保持文件干净
    if not all_relationships[character_name]:
        del all_relationships[character_name]

    if save_relationships(all_relationships):
        return jsonify(success=True, message=f"角色 '{character_name}' 的人际关系已保存。")
    else:
        return jsonify(success=False, error="写入文件失败"), 500


# --- 原有的用户资料和头像上传 API (保持不变) ---
@settings_bp.route('/api/update_user_profile', methods=['POST'])
def update_user_profile():
    # ... 此函数代码保持不变 ...
    if not session.get('logged_in'): return jsonify(success=False, error="未授权"), 401
    try:
        profile = load_user_profile()
        if 'nickname' in request.form and request.form['nickname'].strip():
            profile['nickname'] = request.form['nickname'].strip()
        if 'avatar_file' in request.files:
            file = request.files['avatar_file']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(f"user_avatar_{int(time.time())}.{file.filename.rsplit('.', 1)[1].lower()}")
                save_path = os.path.join(USER_AVATAR_FOLDER, filename)
                file.save(save_path)
                profile['avatar_url'] = os.path.join('user', filename).replace('\\', '/')
        if 'background_file' in request.files:
            file = request.files['background_file']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(f"user_bg_{int(time.time())}.{file.filename.rsplit('.', 1)[1].lower()}")
                save_path = os.path.join(USER_BACKGROUND_FOLDER, filename)
                file.save(save_path)
                profile['background_url'] = os.path.join('user_background', filename).replace('\\', '/')
        save_user_profile(profile)
        return jsonify(success=True, message="用户设置已成功保存！", profile=profile)
    except Exception as e:
        logging.error(f"更新用户资料时出错: {e}", exc_info=True)
        return jsonify(success=False, error=str(e)), 500


@settings_bp.route('/api/upload_avatar', methods=['POST'])
def upload_avatar():
    # ... 此函数代码保持不变 ...
    if not session.get('logged_in'): return jsonify(success=False, error="未授权，请先登录"), 401
    try:
        character_name = request.form.get('character_name')
        file = request.files.get('avatar_file')
        if not character_name or not file or file.filename == '' or not allowed_file(file.filename):
            return jsonify(success=False, error="请求参数无效或文件类型不允许"), 400
        filename = secure_filename(f"{character_name.replace(' ', '_')}_{int(time.time())}.{file.filename.rsplit('.', 1)[1].lower()}")
        save_path = os.path.join(AVATAR_FOLDER, filename)
        file.save(save_path)
        avatar_map = load_avatar_mapping()
        avatar_map[character_name] = filename
        save_avatar_mapping(avatar_map)
        new_avatar_url = url_for('static', filename=os.path.join('avatars', filename).replace('\\', '/'))
        return jsonify(success=True, message="头像上传成功！", avatar_url=new_avatar_url)
    except Exception as e:
        logging.error(f"上传角色头像时出错: {e}", exc_info=True)
        return jsonify(success=False, error=str(e)), 500

