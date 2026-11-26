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
- Tạo giọng đọc tiếng Việt miễn phí bằng `edge-tts` (`vi-VN-NamMinhNeural` hoặc `vi-VN-HoaiMyNeural`).
- Cắt các đoạn clip theo timestamp và tự co giãn tốc độ hình ảnh khớp với giọng đọc.
- Đóng khung dọc `9:16` (nền mờ + khung hoạt hình 16:9 sắc nét ở giữa, không mất nhân vật hai bên) hoặc giữ `16:9`.
- Burn-in phụ đề `.ass` nổi bật kiểu TikTok / YouTube Shorts.
