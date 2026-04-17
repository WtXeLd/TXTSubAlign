# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TXTSubAlign is a web-based audio-text subtitle alignment tool built on stable-ts. It aligns existing TXT text with audio files to generate SRT/ASS subtitle files. The application uses OpenAI's Whisper model for audio processing.

**Tech Stack:**
- Backend: Flask + stable-ts (Whisper-based alignment)
- Frontend: Vanilla HTML/CSS/JavaScript (no framework)
- AI Model: OpenAI Whisper (multiple sizes: tiny, base, small, medium, large)

## Development Commands

### Start the server
```bash
python app.py
```
Server runs on `http://localhost:5000` and automatically opens in browser.

### Install dependencies
```bash
pip install -r requirements.txt
```

**Requirements:**
- Python 3.8+
- Flask 2.3.0+
- stable-ts 2.13.0+
- torch 2.0.0+

### Windows quick start
```bash
start.bat
```

## Architecture

### Backend (app.py)

**Core Components:**
- **Model Management**: Global model instance with thread-safe loading (`model_lock`)
- **Task Queue**: In-memory task tracking (`tasks` dict) with status polling
- **File Processing**: Async alignment processing in background threads

**Key Endpoints:**
- `POST /api/align` - Initiates alignment task, returns task_id
- `GET /api/status/<task_id>` - Polls task progress (0-100%)
- `GET /api/download/<path:filename>` - Downloads generated subtitle files
- `GET /api/models` - Lists available Whisper models

**Alignment Flow:**
1. Upload audio + text files → saved with UUID prefix
2. Background thread loads model → aligns audio with text
3. Task status updated (processing → completed/error)
4. Output saved to `outputs/<batch_id>/<filename>.<format>`
5. Temporary upload files cleaned up

**Subtitle Modes:**
- **Segment mode** (default): Sentence-level timestamps, clean output
- **Word mode**: Word-level timestamps with customizable highlighting (color, bold, italic, underline)

### Frontend (index.html)

**Single-page application with sections:**
- File upload (drag-drop + click, auto-categorizes audio/text)
- File lists (separate audio/text columns, sortable, paired by index)
- Configuration (language, model size, output format, subtitle mode)
- Progress tracking (overall + per-task progress bars)
- Results (batch download, individual file downloads)

**State Management:**
- `audioFiles[]` / `textFiles[]` - Uploaded file arrays
- `processingTasks[]` - Current batch processing state
- `completedFiles[]` - Finished tasks for download
- LocalStorage persistence for history and preferences

**Key Features:**
- Duplicate file filtering
- Automatic filename sorting
- Batch processing with sequential task execution
- Real-time progress polling (500ms intervals)
- History restoration on page refresh

## File Structure

```
uploads/          # Temporary upload storage (auto-created, files deleted after processing)
outputs/          # Generated subtitle files
  └── YYYY-MM-DD_HH-MM-SS/  # Batch-specific directories (timestamp-based)
      ├── file1.srt
      └── file2.srt
```

## Important Notes

### Model Behavior
- First run downloads Whisper model files (can be slow)
- Models are cached locally for subsequent runs
- Model loading is thread-safe but blocks during initial load
- Larger models (medium/large) require significant memory

### File Pairing
- Audio and text files are paired by list index (1st audio → 1st text)
- File counts must match exactly to start processing
- Use sort buttons to reorder lists before processing

### Batch Processing
- Each batch creates a timestamped output directory
- Tasks process sequentially (not parallel) to manage memory
- Failed tasks don't stop the batch
- History persists in localStorage across sessions

### Language Support
Supported languages: Chinese (zh), English (en), Japanese (ja), Korean (ko), Spanish (es), French (fr). See [Whisper language list](https://github.com/openai/whisper#available-models-and-languages) for full list.

### Output Formats
- **SRT**: Most compatible, widely supported
- **ASS**: Advanced styling support
- **JSON**: Full metadata with timestamps
- **TSV**: Tabular format for analysis
