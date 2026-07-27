# 👋 Profile Repo Setup Guide

This is your **GitHub profile README repo**. Follow these 3 steps to make it live:

## 1️⃣ Create the repo on GitHub

Create a **public** repo named exactly **`MezbahUddin21`** (same as your username):
👉 https://github.com/new — name it `MezbahUddin21`, keep it public, **don't** add a README.

## 2️⃣ Push this folder

```bash
cd ~/MezbahUddin21
git init
git add .
git commit -m "✨ Launch profile README"
git branch -M main
git remote add origin https://github.com/MezbahUddin21/MezbahUddin21.git
git push -u origin main
```

## 3️⃣ Enable the snake 🐍

1. Go to the repo → **Settings → Actions → General**
   → under *Workflow permissions* select **Read and write permissions** → Save.
2. Go to **Actions** tab → click **Generate Contribution Snake** → **Run workflow**.
3. Wait ~1 minute. The snake SVGs will appear on the `output` branch and render in your README automatically.

## ✅ That's it!

Visit **https://github.com/MezbahUddin21** — your animated profile is live.
The snake regenerates automatically every 12 hours, and all stats cards
(Codeforces, LeetCode, GitHub stats, streaks, activity graph) update live on their own.

---

### 🔧 Customization tips

- **Colors**: banner gradient is in the `capsule-render` URLs in `README.md` (`8E2DE2 → 4A00E0 → 00C9FF`).
- **Typing lines**: edit the `lines=` param in the typing SVG URL.
- **LinkedIn link**: update the URL in the *Connect* section if your handle differs.
- **Featured projects**: swap the repo names in the `pin` card URLs.



