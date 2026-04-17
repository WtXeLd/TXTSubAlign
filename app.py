from flask import Flask, request, jsonify, send_file, render_template_string
import stable_whisper
import os
import uuid
from pathlib import Path
import threading
import webbrowser
from threading import Timer
from difflib import SequenceMatcher

app = Flask(__name__)

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

# 格式化时间戳为 LRC 格式 [mm:ss.xx]
def format_timestamp_lrc(seconds):
    """将秒数转换为 LRC 时间戳格式"""
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"[{minutes:02d}:{secs:05.2f}]"

# 生成自定义高亮标签
def generate_highlight_tags(color, bold, italic, underline):
    """生成自定义高亮标签"""
    opening_tag = f'<font color="{color}">'
    closing_tag = '</font>'

    # 添加额外样式
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

@app.route('/')
def index():
    with open('index.html', 'r', encoding='utf-8') as f:
        return f.read()

@app.route('/api/align', methods=['POST'])
def align_audio():
    try:
        # 检查文件
        if 'audio' not in request.files or 'text' not in request.files:
            return jsonify({'error': '请上传音频文件和文本文件'}), 400

        audio_file = request.files['audio']
        text_file = request.files['text']

        if audio_file.filename == '' or text_file.filename == '':
            return jsonify({'error': '文件不能为空'}), 400

        # 获取参数
        language = request.form.get('language', 'zh')
        model_size = request.form.get('model_size', 'base')
        output_format = request.form.get('output_format', 'srt')
        batch_id = request.form.get('batch_id', '')  # 批次ID，用于创建独立目录

        # 字幕格式参数
        subtitle_mode = request.form.get('subtitle_mode', 'segment')
        segment_mode = request.form.get('segment_mode', 'auto')  # 'auto' 或 'line'
        highlight_color = request.form.get('highlight_color', '#00ff00')
        style_bold = request.form.get('style_bold', 'false') == 'true'
        style_italic = request.form.get('style_italic', 'false') == 'true'
        style_underline = request.form.get('style_underline', 'false') == 'true'

        # 生成唯一 ID
        task_id = str(uuid.uuid4())

        # 获取原始文件名（不含扩展名）
        audio_basename = os.path.splitext(audio_file.filename)[0]

        # 保存上传的文件
        audio_path = os.path.join(UPLOAD_FOLDER, f"{task_id}_{audio_file.filename}")
        text_path = os.path.join(UPLOAD_FOLDER, f"{task_id}_{text_file.filename}")

        audio_file.save(audio_path)
        text_file.save(text_path)

        # 读取文本（根据 segment_mode 决定如何处理）
        with open(text_path, 'r', encoding='utf-8') as f:
            if segment_mode == 'line':
                # 按行分割，每行作为一个独立的字幕段
                # 使用特殊分隔符连接，后续会用这个分隔符来分段
                text_lines = [line.strip() for line in f.readlines() if line.strip()]
                # 使用换行符作为分隔符（stable-ts 会识别）
                text_content = '\n'.join(text_lines)
                use_line_split = True
            else:
                # AI 自动分段（读取整个文本）
                text_content = f.read().strip()
                use_line_split = False

        if not text_content:
            return jsonify({'error': '文本文件为空'}), 400

        # 初始化任务状态
        tasks[task_id] = {'status': 'processing', 'progress': 0, 'batch_id': batch_id}

        # 在后台处理对齐任务
        def process_alignment():
            try:
                # 加载模型
                tasks[task_id]['progress'] = 10
                m = load_model(model_size)

                # 执行对齐
                tasks[task_id]['progress'] = 30

                print(f"Segment mode: {segment_mode}")
                print(f"Use line split: {use_line_split}")

                if use_line_split:
                    # 按行分段模式：对整个文本对齐，然后按行重新分组
                    print("Using line-by-line mode: align full text, then regroup by lines")

                    # 1. 对整个文本进行对齐，获取 word-level 时间戳
                    result = m.align(audio_path, text_content, language=language)

                    print(f"Alignment completed, segments: {len(result.segments)}")

                    # 2. 提取所有 words
                    all_words = []
                    for seg in result.segments:
                        if hasattr(seg, 'words') and seg.words:
                            all_words.extend(seg.words)

                    print(f"Total words: {len(all_words)}")

                    # 3. 读取用户的文本行
                    text_lines = [line.strip() for line in text_content.split('\n') if line.strip()]
                    print(f"User text lines: {len(text_lines)}")

                    # 4. 将 words 按文本行重新分组
                    # 使用序列匹配算法来精确对齐
                    new_segments = []

                    # 构建所有 words 的文本列表（保留原始顺序）
                    words_chars = []
                    for w in all_words:
                        word_text = w.word.strip().replace(' ', '')
                        words_chars.extend(list(word_text))

                    # 构建用户文本的字符列表
                    user_chars = []
                    line_char_ranges = []  # 记录每一行在 user_chars 中的范围
                    char_idx = 0

                    for line_text in text_lines:
                        line_clean = line_text.replace(' ', '').replace('\n', '')
                        start_idx = char_idx
                        user_chars.extend(list(line_clean))
                        char_idx += len(line_clean)
                        line_char_ranges.append((start_idx, char_idx))

                    print(f"Words chars: {len(words_chars)}, User chars: {len(user_chars)}")

                    # 使用 SequenceMatcher 对齐两个字符序列
                    matcher = SequenceMatcher(None, words_chars, user_chars)
                    matching_blocks = matcher.get_matching_blocks()

                    print(f"Found {len(matching_blocks)} matching blocks")

                    # 为每一行找到对应的 words
                    for line_idx, (line_start, line_end) in enumerate(line_char_ranges):
                        line_text = text_lines[line_idx]

                        # 找到这一行在 words_chars 中的对应范围
                        word_char_start = None
                        word_char_end = None

                        for i, j, size in matching_blocks:
                            # i: words_chars 中的位置
                            # j: user_chars 中的位置
                            # size: 匹配长度

                            # 检查这个匹配块是否与当前行重叠
                            if j < line_end and j + size > line_start:
                                # 有重叠
                                overlap_start = max(j, line_start)
                                overlap_end = min(j + size, line_end)

                                # 计算对应的 words_chars 位置
                                offset_start = overlap_start - j
                                offset_end = overlap_end - j

                                words_start = i + offset_start
                                words_end = i + offset_end

                                if word_char_start is None:
                                    word_char_start = words_start
                                word_char_end = words_end

                        if word_char_start is not None and word_char_end is not None:
                            # 将字符位置转换为 word 索引
                            word_start_idx = 0
                            word_end_idx = 0
                            char_count = 0

                            for w_idx, w in enumerate(all_words):
                                word_len = len(w.word.strip().replace(' ', ''))

                                if char_count <= word_char_start < char_count + word_len:
                                    word_start_idx = w_idx

                                if char_count < word_char_end <= char_count + word_len:
                                    word_end_idx = w_idx + 1

                                char_count += word_len

                                if char_count >= word_char_end:
                                    break

                            # 提取这一行的 words
                            if word_end_idx > word_start_idx:
                                line_words = all_words[word_start_idx:word_end_idx]

                                # 创建新的 segment
                                from stable_whisper.result import Segment

                                new_seg = Segment(
                                    start=line_words[0].start,
                                    end=line_words[-1].end,
                                    text=line_text  # 使用用户原始文本
                                )
                                new_seg.words = line_words
                                new_segments.append(new_seg)

                                if line_idx < 10 or line_idx % 100 == 0:
                                    matched_text = ''.join([w.word.strip().replace(' ', '') for w in line_words])
                                    print(f"Line {line_idx + 1}: '{line_text[:30]}...' -> {len(line_words)} words, {new_seg.start:.2f}s-{new_seg.end:.2f}s")
                                    print(f"  Matched text: '{matched_text[:50]}...'")
                                    print(f"  Target text: '{line_text[:50]}...'")
                            else:
                                print(f"Warning: Line {line_idx + 1} has invalid word range!")
                        else:
                            print(f"Warning: Line {line_idx + 1} has no matching chars!")

                    # 5. 替换结果的 segments
                    result.segments = new_segments
                    print(f"Regrouped into {len(new_segments)} segments (one per line, expected {len(text_lines)})")

                else:
                    # AI 自动分段模式
                    print("Using AI auto-segment mode with align")
                    result = m.align(audio_path, text_content, language=language)

                print(f"Final result segments: {len(result.segments) if hasattr(result, 'segments') else 'N/A'}")

                # 保存结果
                tasks[task_id]['progress'] = 80

                # 创建批次输出目录（如果有batch_id）
                if batch_id:
                    batch_output_folder = os.path.abspath(os.path.join(OUTPUT_FOLDER, batch_id))
                    os.makedirs(batch_output_folder, exist_ok=True)
                else:
                    batch_output_folder = os.path.abspath(OUTPUT_FOLDER)

                # 生成输出文件名（使用原始音频文件名，不添加序号）
                output_filename = f"{audio_basename}.{output_format}"
                output_path = os.path.join(batch_output_folder, output_filename)

                if output_format == 'srt':
                    if use_line_split:
                        # 按行分段模式：手动生成 srt 文件以保持原始分段
                        print("Manually generating SRT file to preserve line segments")
                        with open(output_path, 'w', encoding='utf-8') as f:
                            for idx, seg in enumerate(result.segments, 1):
                                # SRT 格式：
                                # 序号
                                # 开始时间 --> 结束时间
                                # 字幕文本
                                # 空行
                                start_time = format_timestamp_srt(seg.start)
                                end_time = format_timestamp_srt(seg.end)
                                f.write(f"{idx}\n")
                                f.write(f"{start_time} --> {end_time}\n")
                                f.write(f"{seg.text}\n")
                                f.write("\n")
                        print(f"SRT file saved with {len(result.segments)} segments")
                    elif subtitle_mode == 'segment':
                        # 句子级简洁输出（默认）
                        result.to_srt_vtt(output_path, word_level=False, segment_level=True)
                    else:  # word mode
                        # 单词级高亮输出
                        tags = generate_highlight_tags(highlight_color, style_bold, style_italic, style_underline)
                        result.to_srt_vtt(output_path, word_level=True, segment_level=True, tag=tags)
                elif output_format == 'ass':
                    result.to_ass(output_path)
                elif output_format == 'lrc':
                    # 生成 LRC 歌词格式
                    print(f"Generating LRC file with {len(result.segments)} segments")
                    print(f"Output path (abs): {os.path.abspath(output_path)}")
                    try:
                        with open(output_path, 'w', encoding='utf-8') as f:
                            for seg in result.segments:
                                timestamp = format_timestamp_lrc(seg.start)
                                text = seg.text.strip()
                                f.write(f"{timestamp}{text}\n")
                        print(f"LRC file written successfully")
                    except Exception as e:
                        print(f"Error writing LRC file: {e}")
                        raise
                elif output_format == 'json':
                    result.save_as_json(output_path)
                elif output_format == 'tsv':
                    result.to_tsv(output_path)

                print(f"Output file saved to: {output_path}")
                print(f"File exists: {os.path.exists(output_path)}")

                # 保存相对路径（包含batch_id子目录）
                if batch_id:
                    relative_path = f"{batch_id}/{output_filename}"
                else:
                    relative_path = output_filename

                tasks[task_id] = {
                    'status': 'completed',
                    'progress': 100,
                    'output_file': relative_path
                }

                print(f"Task completed: {task_id}")

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

        # 启动后台线程
        thread = threading.Thread(target=process_alignment)
        thread.start()

        return jsonify({'task_id': task_id})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/status/<task_id>', methods=['GET'])
def get_status(task_id):
    if task_id not in tasks:
        return jsonify({'error': '任务不存在'}), 404
    return jsonify(tasks[task_id])

@app.route('/api/download/<path:filename>', methods=['GET'])
def download_file(filename):
    # 支持子目录路径（如 batch_id/file.srt）
    file_path = os.path.abspath(os.path.join(OUTPUT_FOLDER, filename))
    if not os.path.exists(file_path):
        return jsonify({'error': '文件不存在'}), 404
    return send_file(file_path, as_attachment=True)

@app.route('/api/models', methods=['GET'])
def get_models():
    return jsonify({
        'models': ['tiny', 'base', 'small', 'medium', 'large']
    })

def open_browser():
    """延迟1秒后打开浏览器"""
    webbrowser.open('http://localhost:5000')

if __name__ == '__main__':
    print("正在启动服务器...")
    print("请在浏览器中打开: http://localhost:5000")
    print("浏览器将自动打开...")

    # 延迟1秒后自动打开浏览器
    Timer(1, open_browser).start()

    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
