# Vietsub Hoạt Hình — Hook-based Recap & Review Pipeline (No-API Mode)

Công cụ dòng lệnh (CLI) giúp bạn tạo video **review / tóm tắt hoạt hình Âu Mỹ theo Hook** (*The Simpsons*, *Family Guy*, *SpongeBob*...) **không cần API key trả phí**.

## Yêu cầu hệ thống
- Python 3.10+
- `ffmpeg` (và `ffprobe`) cài sẵn trên PATH
- Thư viện Python:
  ```bash
  pip install -r requirements.txt
  ```

## Quy trình 3 bước (Không cần API key)

### Bước 1: Chuẩn bị transcript gọn từ video + `.srt`
```bash
python3 -m src.cli prepare --video path/to/episode.mp4 --srt path/to/episode.srt
```
*(Nếu video chưa có `.srt` và bạn đã cài `faster-whisper`, thêm cờ `--whisper` để tách thoại offline).*

Lệnh này tạo ra file `transcript_clean.txt` chứa các dòng `[start -> end] text`.

### Bước 2: Tạo `script.json` qua Antigravity
Gửi file `transcript_clean.txt` (hoặc dán nội dung) vào chat Antigravity kèm yêu cầu theo mẫu tại [`prompts/hook_review_prompt.md`](prompts/hook_review_prompt.md) để nhận file `script.json`.

Kiểm tra nhanh file kịch bản:
```bash
python3 -m src.cli validate --script path/to/script.json
```

### Bước 3: Render video thành phẩm (`.mp4`)
```bash
python3 -m src.cli render \
  --video path/to/episode.mp4 \
  --script path/to/script.json \
  --output output/recap_9x16.mp4
```

Pipeline sẽ tự động:
- Tạo giọng đọc tiếng Việt miễn phí bằng `edge-tts` (`vi-VN-NamMinhNeural` hoặc `vi-VN-HoaiMyNeural`) — hoặc dùng giọng clone **ElevenLabs** của riêng bạn.
- Cắt các đoạn clip theo timestamp và tự co giãn tốc độ hình ảnh khớp với giọng đọc.
- Đóng khung dọc `9:16` (nền mờ + khung hoạt hình 16:9 sắc nét ở giữa, không mất nhân vật hai bên) hoặc giữ `16:9`.
- Burn-in phụ đề `.ass` nổi bật kiểu TikTok / YouTube Shorts.

## Clone giọng của bạn với ElevenLabs

### 1. (Khuyên dùng) Làm sạch & chuẩn hóa file thu âm mẫu
Nếu file ghi âm giọng của bạn còn nhiễu hoặc âm lượng chưa đều, chạy `prepare-voice` để lọc tạp âm, chuẩn hóa âm lượng và tách thành các đoạn sạch:
```bash
python3 -m src.cli prepare-voice \
  --input path/to/my_voice.mp3 \
  --out-dir dataset/my_voice
```

### 2. Upload mẫu giọng lên ElevenLabs để tạo `voice_id`
Đặt biến môi trường `ELEVENLABS_API_KEY` (hoặc truyền `--elevenlabs-key`):
```bash
export ELEVENLABS_API_KEY="sk_..."

python3 -m src.cli clone-voice \
  --name "Giong Cua Toi" \
  --files dataset/my_voice
```
Lệnh sẽ trả về `voice_id` (ví dụ: `abc123xyz`).

### 3. Render video bằng giọng ElevenLabs của bạn
```bash
python3 -m src.cli render \
  --video path/to/episode.mp4 \
  --script path/to/script.json \
  --output output/recap_9x16.mp4 \
  --tts-provider elevenlabs \
  --voice abc123xyz
```
*(Hoặc thêm `"tts_provider": "elevenlabs"` và `"voice": "abc123xyz"` trực tiếp vào `script.json`.)*

