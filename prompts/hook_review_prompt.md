# Hướng dẫn tạo `script.json` cho Review/Recap Hoạt hình theo Hook

Khi gửi file `transcript_clean.txt` cho Antigravity (hoặc bất kỳ AI nào), hãy dùng mẫu yêu cầu sau:

> Đọc file `transcript_clean.txt` đính kèm và viết kịch bản review/tóm tắt tập phim theo đúng định dạng `script.json`:
> 1. **Mở đầu (Hook 3–5 giây):** Chọn chi tiết gây tò mò, vô lý hoặc hài hước nhất tập. `type: "hook"`.
> 2. **Thân bài (4–8 đoạn / mỗi phần):** Tóm tắt mạch truyện chính bằng **ngôn ngữ trẻ trung, hiện đại, tự nhiên kiểu Gen Z / TikTok / YouTube Shorts** (tránh văn phong dịch sát chữ hay cứng nhắc kiểu sách giáo khoa). **Lồng ghép khéo 2–3 câu đùa / meme mạng xã hội Việt Nam** đúng tình huống (ví dụ: *bật max nhân phẩm, chiến thần lý sự, work from home, bất ngờ chưa bà già, vũ trụ gửi tín hiệu, nghiệp quật tốc độ bàn thờ, đứng hình mất 5 giây, hết cứu, quay xe...*) sao cho tự nhiên, không gượng ép. Dịch thoát ý các câu đùa/slang tiếng Anh sang cách nói dí dỏm của người Việt.
> 3. **Điểm nhấn:** Có thể giữ lại 1–2 đoạn thoại/tiếng cười gốc (`"keep_original_audio": true, "narration": ""`) ở các cảnh punchline để tránh cảm giác đọc AI đều đều.
> 4. **Thời lượng & chia phần:** Mỗi đoạn từ 3–8 giây. Nếu làm video dài ~3 phút chia 2 phần, gắn `"part": 1` và `"part": 2` (mỗi phần đều có `hook` mở đầu riêng) để render bằng `--split-parts`.

## Schema JSON chuẩn

```json
{
  "title": "Tên tập phim",
  "aspect_ratio": "9:16",
  "voice": "vi-VN-NamMinhNeural",
  "voice_rate": "+10%",
  "segments": [
    {
      "id": 1,
      "type": "hook",
      "start": "00:04:12.000",
      "end": "00:04:17.500",
      "narration": "Câu hook mở đầu thật cuốn bằng tiếng Việt.",
      "keep_original_audio": false
    },
    {
      "id": 2,
      "type": "body",
      "start": "00:00:30.000",
      "end": "00:00:36.000",
      "narration": "Diễn biến tiếp theo của câu chuyện...",
      "keep_original_audio": false
    },
    {
      "id": 3,
      "type": "punchline",
      "start": "00:08:10.000",
      "end": "00:08:13.000",
      "narration": "",
      "keep_original_audio": true
    }
  ]
}
```
