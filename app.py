from flask import Flask, request, jsonify, send_file, render_template_string
import stable_whisper
import os
import uuid
from pathlib import Path
import threading
import webbrowser
from threading import Timer

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

        # 读取文本
        with open(text_path, 'r', encoding='utf-8') as f:
            text = f.read().strip()

        if not text:
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
                result = m.align(audio_path, text, language=language)

                # 保存结果
                tasks[task_id]['progress'] = 80

                # 创建批次输出目录（如果有batch_id）
                if batch_id:
                    batch_output_folder = os.path.join(OUTPUT_FOLDER, batch_id)
                    os.makedirs(batch_output_folder, exist_ok=True)
                else:
                    batch_output_folder = OUTPUT_FOLDER

                # 生成输出文件名（使用原始音频文件名，不添加序号）
                output_filename = f"{audio_basename}.{output_format}"
                output_path = os.path.join(batch_output_folder, output_filename)

                if output_format == 'srt':
                    if subtitle_mode == 'segment':
                        # 句子级简洁输出（默认）
                        result.to_srt_vtt(output_path, word_level=False, segment_level=True)
                    else:  # word mode
                        # 单词级高亮输出
                        tags = generate_highlight_tags(highlight_color, style_bold, style_italic, style_underline)
                        result.to_srt_vtt(output_path, word_level=True, segment_level=True, tag=tags)
                elif output_format == 'ass':
                    result.to_ass(output_path)
                elif output_format == 'json':
                    result.save_as_json(output_path)
                elif output_format == 'tsv':
                    result.to_tsv(output_path)

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

                # 清理上传的文件
                os.remove(audio_path)
                os.remove(text_path)

            except Exception as e:
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
    file_path = os.path.join(OUTPUT_FOLDER, filename)
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
