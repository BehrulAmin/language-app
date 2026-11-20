"""Bollo English - interactive English practice dashboard (Streamlit).

Features: gamification (XP, levels, streaks, badges), conversational coaching,
voice input/output, and a weak-points tracker.

Works fully free with the built-in rule-based checker. If ANTHROPIC_API_KEY is
set, the coach uses Claude for much smarter corrections and replies.
"""
import io
import json
import os
import random
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Bollo English", page_icon="🗣️", layout="wide")

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
PROGRESS_FILE = DATA_DIR / "progress.json"

# ----------------------------------------------------------------- storage
DEFAULT_PROGRESS = {
    "xp": 0,
    "streak": 0,
    "last_day": None,
    "messages": 0,
    "clean": 0,
    "mistakes": {},      # {category: count}
    "recent": [],        # [{wrong, fix, type, tip}]
}


def load_progress():
    if PROGRESS_FILE.exists():
        try:
            return {**DEFAULT_PROGRESS, **json.loads(PROGRESS_FILE.read_text())}
        except Exception:
            pass
    return dict(DEFAULT_PROGRESS)


def save_progress():
    PROGRESS_FILE.write_text(json.dumps(st.session_state.progress, indent=2))


if "progress" not in st.session_state:
    st.session_state.progress = load_progress()
if "chat" not in st.session_state:
    st.session_state.chat = [
        {"role": "assistant",
         "content": "Hi! I'm Bollo 👋 Tell me about your day, and I'll gently help you with your English."}
    ]
if "last_audio" not in st.session_state:
    st.session_state.last_audio = None

P = st.session_state.progress

# ------------------------------------------------------------- gamification
def level_of(xp):
    return xp // 100 + 1


def touch_streak():
    today = date.today()
    last = date.fromisoformat(P["last_day"]) if P["last_day"] else None
    if last == today:
        return
    P["streak"] = P["streak"] + 1 if last == today - timedelta(days=1) else 1
    P["last_day"] = today.isoformat()


def award(points):
    touch_streak()
    P["xp"] += points


BADGES = [
    ("🌱 First Step", lambda p: p["messages"] >= 1),
    ("🔥 On Fire (3-day streak)", lambda p: p["streak"] >= 3),
    ("✨ Clean Speaker (5 flawless)", lambda p: p["clean"] >= 5),
    ("🚀 Level 3", lambda p: level_of(p["xp"]) >= 3),
    ("💬 Chatterbox (25 messages)", lambda p: p["messages"] >= 25),
]

# ---------------------------------------------------------- rule-based coach
RULES = [
    (r"\bi\b(?!')", "Capital I", "Always write 'I' in capitals.", lambda m: "I"),
    (r"\b(he|she|it) (go|do|have|don't|want|like|need|play|work)\b", "Subject-verb agreement",
     "With he/she/it, the verb takes -s (he goes, she has, it doesn't).",
     lambda m: m.group(1) + " " + {"go": "goes", "do": "does", "have": "has", "don't": "doesn't"}.get(
         m.group(2), m.group(2) + "s")),
    (r"\bdidn't (went|came|saw|ate|took|got|did)\b", "Past tense after didn't",
     "After 'didn't', use the base verb (didn't go, not didn't went).",
     lambda m: "didn't " + {"went": "go", "came": "come", "saw": "see", "ate": "eat",
                            "took": "take", "got": "get", "did": "do"}[m.group(1)]),
    (r"\bmore (better|easier|faster|bigger)\b", "Double comparative",
     "Use either 'more' or '-er', never both.", lambda m: m.group(1)),
    (r"\bi am agree\b", "Verb 'agree'", "'Agree' is a verb: say 'I agree'.", lambda m: "I agree"),
    (r"\bdiscuss about\b", "Unneeded preposition", "'Discuss' needs no 'about'.", lambda m: "discuss"),
    (r"\bmarried with\b", "Preposition", "We say 'married to'.", lambda m: "married to"),
    (r"\b(a) ((?!one\b|once\b|eu)[aeio]\w+)", "a / an", "Use 'an' before a vowel sound.", lambda m: "an " + m.group(2)),
    (r"\bmany informations\b|\binformations\b", "Uncountable noun",
     "'Information' has no plural.", lambda m: "information"),
    (r"\bi have \d+ years?\b", "Age expression", "In English we say 'I am 20 years old'.",
     lambda m: "I am" + m.group(0)[6:] + " old"),
]

FOLLOW_UPS = [
    "That's interesting! Can you tell me more?",
    "Nice! What was the best part?",
    "Got it. How did that make you feel?",
    "Great effort! What will you do next?",
    "Tell me about it in more detail, I'm listening.",
]


def rule_based(text):
    fixed, mistakes = text, []
    for pat, kind, tip, repl in RULES:
        for m in list(re.finditer(pat, fixed, flags=re.I if kind != "Capital I" else 0)):
            if kind == "Capital I" and m.group(0) == "I":
                continue
            new = repl(m)
            if new != m.group(0):
                mistakes.append({"type": kind, "wrong": m.group(0), "fix": new, "tip": tip})
        fixed = re.sub(pat, repl, fixed, flags=re.I if kind != "Capital I" else 0)
    if fixed and fixed[0].islower():
        fixed = fixed[0].upper() + fixed[1:]
        mistakes.append({"type": "Capitalisation", "wrong": text.split()[0],
                         "fix": fixed.split()[0], "tip": "Start a sentence with a capital letter."})
    return {"corrected": fixed, "mistakes": mistakes, "reply": random.choice(FOLLOW_UPS)}


# ------------------------------------------------------------------ LLM coach
SYSTEM_PROMPT = """You are Bollo, a warm, encouraging English speaking coach for learners
(often Pakistani students). Never shame the learner. Reply with ONLY JSON:
{"corrected": "<natural corrected version of the learner's message>",
 "mistakes": [{"type": "<short category e.g. Verb tense>", "wrong": "...", "fix": "...",
               "tip": "<one short, simple sentence>"}],
 "reply": "<1-2 friendly sentences continuing the conversation, ending with a question>"}
If there are no mistakes, return an empty list."""


def llm_coach(text, history):
    import anthropic
    client = anthropic.Anthropic()
    msgs = [{"role": m["role"], "content": m["content"]} for m in history[-6:] if m["content"]]
    msgs.append({"role": "user", "content": text})
    # the first message must be from the user
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    resp = client.messages.create(
        model=os.getenv("BOLLO_MODEL", "claude-haiku-4-5"),
        max_tokens=600, system=SYSTEM_PROMPT, messages=msgs)
    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw).strip()
    return json.loads(raw)


def analyze(text):
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return llm_coach(text, st.session_state.chat)
        except Exception as e:
            st.toast(f"AI coach unavailable, using basic checker ({e.__class__.__name__})")
    return rule_based(text)


def record(result, points_base=10):
    P["messages"] += 1
    ms = result.get("mistakes", [])
    if not ms:
        P["clean"] += 1
        award(points_base + 5)
    else:
        award(points_base)
        counts = Counter(P["mistakes"])
        for m in ms:
            counts[m["type"]] += 1
        P["mistakes"] = dict(counts)
        P["recent"] = (ms + P["recent"])[:50]
    save_progress()


# ------------------------------------------------------------------- voice
def transcribe(audio_file):
    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        with sr.AudioFile(audio_file) as src:
            audio = r.record(src)
        return r.recognize_google(audio)
    except Exception as e:
        st.warning(f"Couldn't understand the audio ({e.__class__.__name__}). Try again.")
        return None


def speak(text):
    try:
        from gtts import gTTS
        buf = io.BytesIO()
        gTTS(text=text, lang="en").write_to_fp(buf)
        st.audio(buf.getvalue(), format="audio/mp3")
    except Exception:
        st.caption("🔇 Voice playback needs an internet connection (gTTS).")


# ----------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🗣️ Bollo English")
    lvl = level_of(P["xp"])
    st.metric("Level", lvl)
    st.progress((P["xp"] % 100) / 100, text=f"{P['xp'] % 100}/100 XP to level {lvl + 1}")
    c1, c2 = st.columns(2)
    c1.metric("🔥 Streak", f"{P['streak']}d")
    c2.metric("XP", P["xp"])
    st.subheader("Badges")
    earned = [b for b, ok in BADGES if ok(P)]
    for b in earned or ["Keep practicing to earn badges!"]:
        st.write(b)
    voice_on = st.toggle("🔊 Bollo speaks replies", value=False)
    if st.button("Reset progress"):
        st.session_state.progress = dict(DEFAULT_PROGRESS)
        save_progress()
        st.rerun()

tab_chat, tab_daily, tab_weak = st.tabs(["💬 Coach", "🎯 Daily challenge", "📉 Weak points"])

# ---------------------------------------------------------------- coach tab
def handle_user_text(text):
    st.session_state.chat.append({"role": "user", "content": text})
    result = analyze(text)
    record(result)
    lines = []
    if result["mistakes"]:
        lines.append(f"✅ **Better:** {result['corrected']}")
        for m in result["mistakes"]:
            lines.append(f"- ~~{m['wrong']}~~ → **{m['fix']}** ({m['type']}): {m['tip']}")
        lines.append("\n🔁 *Say the corrected sentence out loud once. Repeating builds memory muscle.*")
    else:
        lines.append("🌟 Perfect, no mistakes!")
    lines.append("\n" + result["reply"])
    st.session_state.chat.append({"role": "assistant", "content": "\n".join(lines),
                                  "speech": result["reply"]})


with tab_chat:
    for m in st.session_state.chat:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
    audio = st.audio_input("🎙️ Or speak your answer")
    if audio is not None:
        data = audio.getvalue()
        if data and hash(data) != st.session_state.last_audio:
            st.session_state.last_audio = hash(data)
            text = transcribe(io.BytesIO(data))
            if text:
                handle_user_text(text)
                st.rerun()
    typed = st.chat_input("Type in English...")
    if typed:
        handle_user_text(typed)
        st.rerun()
    if voice_on and st.session_state.chat[-1].get("speech"):
        speak(st.session_state.chat[-1]["speech"])

# ------------------------------------------------------------ daily challenge
CHALLENGES = [
    "Describe your day in 5 sentences.",
    "Introduce yourself as if you're at a job interview.",
    "What would you do if you won 1 million rupees?",
    "Should students be allowed to use phones in class? Give your opinion.",
    "You meet your old teacher on the road. What do you say?",
    "Describe your best friend and why you like them.",
    "Explain your favorite food to someone who has never tried it.",
]

with tab_daily:
    idx = date.today().toordinal() % len(CHALLENGES)
    st.subheader("Today's challenge")
    st.info(CHALLENGES[idx])
    answer = st.text_area("Your answer", height=160, key="daily_answer")
    if st.button("Submit (+20 XP)") and answer.strip():
        res = analyze(answer)
        record(res, points_base=20)
        st.success("Submitted!")
        st.markdown(f"**Corrected version:** {res['corrected']}")
        for m in res["mistakes"]:
            st.markdown(f"- ~~{m['wrong']}~~ → **{m['fix']}**: {m['tip']}")
        if not res["mistakes"]:
            st.balloons()

# --------------------------------------------------------------- weak points
with tab_weak:
    st.subheader("Your weak points")
    if not P["mistakes"]:
        st.write("No mistakes tracked yet. Start chatting with Bollo!")
    else:
        st.bar_chart(P["mistakes"])
        top = sorted(P["mistakes"].items(), key=lambda kv: -kv[1])[:3]
        st.write("**Focus on:** " + ", ".join(f"{k} ({v})" for k, v in top))
        st.subheader("Recent corrections: retype them to practice")
        for m in P["recent"][:8]:
            st.markdown(f"- ~~{m['wrong']}~~ → **{m['fix']}** · *{m['type']}*")
