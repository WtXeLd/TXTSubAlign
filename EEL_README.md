# Eel 桌面版使用说明

## 安装依赖

```bash
pip install eel stable-whisper torch
```

## 启动应用

```bash
python app_eel.py
```

应用会自动打开一个桌面窗口，不需要浏览器。

## 主要改动

### 1. 不再需要 Flask
- 使用 Eel 替代 Flask
- 不占用固定端口
- 独立的桌面应用窗口

### 2. 文件结构
```
app_eel.py          # Eel 启动脚本（新）
index.html          # 原 Flask 版本的前端
index_eel.html      # Eel 版本的前端（需要修改）
app.py              # 原 Flask 版本（保留）
```

### 3. 前端修改要点

原来的 Flask API 调用：
```javascript
const response = await fetch('/api/align', {
    method: 'POST',
    body: formData
});
```

改为 Eel 调用：
```javascript
// 1. 读取文件为 base64 或文本
const audioData = await file.arrayBuffer();
const textData = await textFile.text();

// 2. 调用 Python 函数
const result = await eel.save_files(
    Array.from(new Uint8Array(audioData)),
    file.name,
    textData,
    textFile.name
)();

// 3. 启动对齐任务
await eel.start_alignment(
    result.task_id,
    result.audio_path,
    result.text_path,
    result.audio_basename,
    params
)();
```

## 打包成 .exe（可选）

使用 PyInstaller 打包：

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --add-data "index_eel.html;." app_eel.py
```

生成的 .exe 文件在 `dist/` 目录中。

## 注意事项

1. **文件上传方式不同**：Eel 不支持 HTTP 表单上传，需要在 JavaScript 中读取文件内容后传递给 Python
2. **回调函数**：Python 可以调用 JavaScript 函数来更新进度
3. **路径问题**：打包后需要注意资源文件的路径

## 下一步

由于前端代码修改较多，我建议：
1. 先测试 `app_eel.py` 是否能正常启动
2. 然后我会帮你修改 `index_eel.html` 的 JavaScript 部分
3. 最后测试完整功能

是否继续？
