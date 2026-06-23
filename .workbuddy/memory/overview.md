# ThinkVault — 知识馆长 (The Curator) Redesign

## What was done
Product repositioning: ThinkVault is an offline local AI knowledge base, like the Curator/Librarian in Ready Player One. The entire frontend was redesigned around this concept.

## Key decisions
- **No auth gate on homepage** — ThinkVault is offline by default, API token only needed for LAN access
- **API Token in Settings** — non-blocking, user sets it when needed; 401 shows toast pointing to Settings
- **Curator metaphor** — AI is a "知识馆长" who guides users through their knowledge archive
- **Chinese UI** — all labels in Chinese since the target user is Chinese
- **Prompt chips** — 4 scenario-based prompts to reduce cold-start friction
- **Archive card** — shows real-time KB/doc/chunk counts instead of generic feature grid

## Changes (3 frontend files)

### index.html
- Removed entire Auth Modal overlay
- Title: "ThinkVault — 知识馆长"
- Logo: book icon + "知识馆长" tagline (replaced "v2.0")
- Welcome: Curator avatar + "探索你的知识宇宙" + librarian description + 4 prompt chips
- Right side: Archive card with stats (KB count, doc count, chunk count) + 3 features
- Settings: added API Token field with "局域网访问时填写" hint
- All labels in Chinese: 馆藏, 文献, 对话, 设置, 硬件, 后端地址, 连接/断开
- Input placeholder: "向馆长提问，探索知识库..."
- Drag overlay: "拖放文献以上传"

### style.css
- Removed all auth modal styles (~100 lines)
- Added `.curator-avatar`, `.welcome-prompts`, `.prompt-chip` styles
- Added `.archive-card`, `.archive-header`, `.archive-stats`, `.archive-stat`, `.archive-features` styles
- Added `.field-optional`, `.field-input-mono` for settings token field
- Updated `.logo-tagline` replacing `.logo-version`

### app.js
- Removed `initAuth()`, `showAuthModal()`, `hideAuthModal()`, `submitAuth()` — no auth gate
- `bootstrapApp()` called directly on DOMContentLoaded
- 401 handling: Toast "请在侧边栏「设置」中配置 API Token" (non-blocking)
- API Token synced with settings input field via `setToken()`
- Added prompt chip click handlers (fill input with prompt text)
- Added `updateArchiveStats()`, `loadDocCount()` for archive card stats
- All toast messages in Chinese

## Verification
- ✅ Homepage loads without any token (200)
- ✅ API with token returns data
- ✅ API without token returns Chinese 401 message
- ✅ Frontend 401 → Toast pointing to Settings
- ✅ All Chinese labels rendering correctly
