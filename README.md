# 🗣️ Bollo English

An interactive English practice dashboard built with Streamlit.

## Features
- **Gamification:** XP, levels, daily streaks, and badges
- **Conversational coaching:** chat with Bollo, get gentle corrections and a follow-up question
- **Voice I/O:** speak your answers (speech-to-text) and hear Bollo's replies (text-to-speech)
- **Weak-points tracker:** see which mistake categories you repeat most, plus recent corrections to re-practice
- **Daily challenge:** a new speaking/writing prompt every day

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```
Works free out of the box with a built-in rule-based checker.

### Optional: smarter AI coach
```bash
export ANTHROPIC_API_KEY=your_key   # Windows: set ANTHROPIC_API_KEY=your_key
streamlit run app.py
```

## Deploy free
Push to GitHub, then deploy on [Streamlit Community Cloud](https://streamlit.io/cloud) (set `ANTHROPIC_API_KEY` under Secrets if you want the AI coach).

> Note: progress is saved to `data/progress.json`, which is local per deployment.
