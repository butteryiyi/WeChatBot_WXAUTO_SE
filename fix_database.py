# fix_database.py
import json
import os

DATABASE_FILE = "moments_database.json"

def fix_media_paths():
    """
    读取朋友圈数据库，修复其中不正确的媒体URL路径。
    将 "moments/media/" 替换为 "/media/"。
    """
    if not os.path.exists(DATABASE_FILE):
        print(f"数据库文件 '{DATABASE_FILE}' 不存在，无需修复。")
        return

    try:
        with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            # 如果文件为空，直接返回
            if not content.strip():
                print("数据库文件为空，无需修复。")
                return
            moments = json.loads(content)
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error reading or parsing a {DATABASE_FILE}: {e}")
        return

    changes_made = 0
    
    # 路径修复的核心逻辑
    # 替换两种可能的错误格式
    # 1. 'moments/media/...' -> '/media/...' (相对路径)
    # 2. '/moments/media/...' -> '/media/...' (绝对路径)
    wrong_path_prefix_1 = "moments/media/"
    wrong_path_prefix_2 = "/moments/media/"
    correct_path_prefix = "/media/"

    for moment in moments:
        if 'image_url' in moment and moment['image_url']:
            original_url = moment['image_url']
            
            # 使用 startswith 判断，避免意外替换
            if original_url.startswith(wrong_path_prefix_1):
                moment['image_url'] = correct_path_prefix + original_url[len(wrong_path_prefix_1):]
                print(f"修复路径: {original_url} -> {moment['image_url']}")
                changes_made += 1
            elif original_url.startswith(wrong_path_prefix_2):
                moment['image_url'] = correct_path_prefix + original_url[len(wrong_path_prefix_2):]
                print(f"修复路径: {original_url} -> {moment['image_url']}")
                changes_made += 1

    if changes_made > 0:
        try:
            with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
                json.dump(moments, f, ensure_ascii=False, indent=2)
            print(f"\n成功修复并保存了 {changes_made} 条记录到 '{DATABASE_FILE}'。")
        except IOError as e:
            print(f"写入修复后的数据库文件失败: {e}")
    else:
        print("\n数据库检查完成，未发现需要修复的媒体路径。")

if __name__ == '__main__':
    fix_media_paths()

