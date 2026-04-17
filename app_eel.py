import eel
import stable_whisper
import os
import uuid
import threading
from pathlib import Path
from difflib import SequenceMatcher

# 配置
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# 全局变量存储模型和任务状态
model = None
model_lock = threading.Lock()
tasks = {}

# 加载模型
def load_model(model_size='base'):
    global model
    with model_lock:
        if model is None:
            print(f"正在加载 {model_size} 模型...")
            model = stable_whisper.load_model(model_size)
            print("模型加载完成")
        return model

# 格式化时间戳为 SRT 格式 (HH:MM:SS,mmm)
def format_timestamp_srt(seconds):
    """将秒数转换为 SRT 时间戳格式"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

# 生成自定义高亮标签
def generate_highlight_tags(color, bold, italic, underline):
    """生成自定义高亮标签"""
    opening_tag = f'<font color="{color}">'
    closing_tag = '</font>'

    if bold:
        opening_tag = '<b>' + opening_tag
        closing_tag = closing_tag + '</b>'
    if italic:
        opening_tag = '<i>' + opening_tag
        closing_tag = closing_tag + '</i>'
    if underline:
        opening_tag = '<u>' + opening_tag
        closing_tag = closing_tag + '</u>'

    return (opening_tag, closing_tag)

@eel.expose
def save_files(audio_data, audio_filename, text_data, text_filename):
    """保存上传的文件并返回任务ID"""
    task_id = str(uuid.uuid4())

    # 保存文件路径
    audio_path = os.path.join(UPLOAD_FOLDER, f"{task_id}_{audio_filename}")
    text_path = os.path.join(UPLOAD_FOLDER, f"{task_id}_{text_filename}")

    # 保存文件
    with open(audio_path, 'wb') as f:
        f.write(audio_data)
    with open(text_path, 'w', encoding='utf-8') as f:
        f.write(text_data)

    return {
        'task_id': task_id,
        'audio_path': audio_path,
        'text_path': text_path,
        'audio_basename': os.path.splitext(audio_filename)[0]
    }

@eel.expose
def start_alignment(task_id, audio_path, text_path, audio_basename, params):
    """启动对齐任务"""
    # 提取参数
    language = params.get('language', 'zh')
    model_size = params.get('model_size', 'base')
    output_format = params.get('output_format', 'srt')
    batch_id = params.get('batch_id', '')
    subtitle_mode = params.get('subtitle_mode', 'segment')
    segment_mode = params.get('segment_mode', 'auto')
    highlight_color = params.get('highlight_color', '#00ff00')
    style_bold = params.get('style_bold', False)
    style_italic = params.get('style_italic', False)
    style_underline = params.get('style_underline', False)

    # 读取文本
    with open(text_path, 'r', encoding='utf-8') as f:
        if segment_mode == 'line':
            text_lines = [line.strip() for line in f.readlines() if line.strip()]
            text_content = '\n'.join(text_lines)
            use_line_split = True
        else:
            text_content = f.read().strip()
            use_line_split = False

    if not text_content:
        return {'error': '文本文件为空'}

    # 初始化任务状态
    tasks[task_id] = {'status': 'processing', 'progress': 0, 'batch_id': batch_id}

    # 在后台处理对齐任务
    def process_alignment():
        try:
            # 加载模型
            tasks[task_id]['progress'] = 10
            eel.update_task_progress(task_id, 10)()
            m = load_model(model_size)

            # 执行对齐
            tasks[task_id]['progress'] = 30
            eel.update_task_progress(task_id, 30)()

            print(f"Segment mode: {segment_mode}")
            print(f"Use line split: {use_line_split}")

            if use_line_split:
                # 按行分段模式
                print("Using line-by-line mode: align full text, then regroup by lines")

                result = m.align(audio_path, text_content, language=language)
                print(f"Alignment completed, segments: {len(result.segments)}")

                # 提取所有 words
                all_words = []
                for seg in result.segments:
                    if hasattr(seg, 'words') and seg.words:
                        all_words.extend(seg.words)

                print(f"Total words: {len(all_words)}")

                # 读取用户的文本行
                text_lines = [line.strip() for line in text_content.split('\n') if line.strip()]
                print(f"User text lines: {len(text_lines)}")

                # 将 words 按文本行重新分组（使用序列匹配）
                new_segments = []

                # 构建字符序列
                words_chars = []
                for w in all_words:
                    word_text = w.word.strip().replace(' ', '')
                    words_chars.extend(list(word_text))

                user_chars = []
                line_char_ranges = []
                char_idx = 0

                for line_text in text_lines:
                    line_clean = line_text.replace(' ', '').replace('\n', '')
                    start_idx = char_idx
                    user_chars.extend(list(line_clean))
                    char_idx += len(line_clean)
                    line_char_ranges.append((start_idx, char_idx))

                print(f"Words chars: {len(words_chars)}, User chars: {len(user_chars)}")

                # 使用序列匹配对齐
                matcher = SequenceMatcher(None, words_chars, user_chars)
                matching_blocks = matcher.get_matching_blocks()

                # 为每一行找到对应的 words
                word_char_index = 0
                for line_idx, (line_start, line_end) in enumerate(line_char_ranges):
                    line_text = text_lines[line_idx]
                    line_words = []

                    # 简化匹配：按字符数量分配 words
                    line_char_count = line_end - line_start
                    accumulated_chars = 0

                    while word_char_index < len(all_words) and accumulated_chars < line_char_count:
                        word = all_words[word_char_index]
                        line_words.append(word)
                        word_text = word.word.strip().replace(' ', '')
                        accumulated_chars += len(word_text)
                        word_char_index += 1

                    if line_words:
                        from stable_whisper.result import Segment
                        new_seg = Segment(
                            start=line_words[0].start,
                            end=line_words[-1].end,
                            text=line_text,
                            words=line_words
                        )
                        new_segments.append(new_seg)

                result.segments = new_segments
                print(f"Regrouped into {len(new_segments)} segments")

            else:
                # AI 自动分段模式
                print("Using AI auto-segment mode with align")
                result = m.align(audio_path, text_content, language=language)

            print(f"Final result segments: {len(result.segments)}")

            # 保存结果
            tasks[task_id]['progress'] = 80
            eel.update_task_progress(task_id, 80)()

            # 创建输出目录
            if batch_id:
                batch_output_folder = os.path.join(OUTPUT_FOLDER, batch_id)
                os.makedirs(batch_output_folder, exist_ok=True)
            else:
                batch_output_folder = OUTPUT_FOLDER

            output_filename = f"{audio_basename}.{output_format}"
            output_path = os.path.join(batch_output_folder, output_filename)

            # 保存文件
            if output_format == 'srt':
                if use_line_split:
                    # 手动生成 SRT
                    print("Manually generating SRT file to preserve line segments")
                    with open(output_path, 'w', encoding='utf-8') as f:
                        for idx, seg in enumerate(result.segments, 1):
                            start_time = format_timestamp_srt(seg.start)
                            end_time = format_timestamp_srt(seg.end)
                            f.write(f"{idx}\n")
                            f.write(f"{start_time} --> {end_time}\n")
                            f.write(f"{seg.text}\n")
                            f.write("\n")
                    print(f"SRT file saved with {len(result.segments)} segments")
                elif subtitle_mode == 'segment':
                    result.to_srt_vtt(output_path, word_level=False, segment_level=True)
                else:
                    tags = generate_highlight_tags(highlight_color, style_bold, style_italic, style_underline)
                    result.to_srt_vtt(output_path, word_level=True, segment_level=True, tag=tags)
            elif output_format == 'ass':
                result.to_ass(output_path)
            elif output_format == 'json':
                result.save_as_json(output_path)
            elif output_format == 'tsv':
                result.to_tsv(output_path)

            # 保存相对路径
            if batch_id:
                relative_path = f"{batch_id}/{output_filename}"
            else:
                relative_path = output_filename

            tasks[task_id] = {
                'status': 'completed',
                'progress': 100,
                'output_file': relative_path
            }

            # 通知前端任务完成
            eel.task_completed(task_id, relative_path)()

            # 清理上传的文件
            os.remove(audio_path)
            os.remove(text_path)

        except Exception as e:
            print(f"Error in task {task_id}: {str(e)}")
            import traceback
            traceback.print_exc()
            tasks[task_id] = {
                'status': 'error',
                'error': str(e)
            }
            eel.task_error(task_id, str(e))()

    # 启动后台线程
    thread = threading.Thread(target=process_alignment)
    thread.daemon = True
    thread.start()

    return {'success': True}

@eel.expose
def get_task_status(task_id):
    """获取任务状态"""
    if task_id not in tasks:
        return {'error': '任务不存在'}
    return tasks[task_id]

@eel.expose
def get_output_path(filename):
    """获取输出文件的绝对路径"""
    file_path = os.path.join(OUTPUT_FOLDER, filename)
    return os.path.abspath(file_path) if os.path.exists(file_path) else None

@eel.expose
def get_models():
    """获取可用的模型列表"""
    return ['tiny', 'base', 'small', 'medium', 'large']

# 初始化 Eel
eel.init('.')

# 启动应用
if __name__ == '__main__':
    print("正在启动 TXTSubAlign 桌面应用...")
    eel.start('index.html', size=(1200, 800), port=0)
