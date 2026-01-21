import time
import random
import math
import streamlit as st
from dataclasses import dataclass

NUM_QUESTIONS = 10
MAX_ABS_ANSWER = 143
MAX_DIV_ANSWER = 12

st.set_page_config(page_title="Speed Math Global", page_icon="🔥", layout="centered")

# ---------- Question gen ----------
@dataclass
class Question:
    text: str
    answer: int

def clamp_ok(ans: int) -> bool:
    return abs(ans) <= MAX_ABS_ANSWER

def make_question(rng: random.Random) -> Question:
    op = rng.choice(["+", "-", "×", "÷"])

    if op == "÷":
        q = rng.randint(0, MAX_DIV_ANSWER)
        b = rng.randint(1, 12)
        a = b * q
        return Question(f"{a} ÷ {b}", q)

    if op == "×":
        while True:
            a = rng.randint(-12, 12)
            b = rng.randint(-12, 12)
            ans = a * b
            if clamp_ok(ans):
                return Question(f"{a} × {b}", ans)

    if op == "+":
        while True:
            a = rng.randint(-99, 99)
            b = rng.randint(-99, 99)
            ans = a + b
            if clamp_ok(ans):
                return Question(f"{a} + {b}", ans)

    # "-"
    while True:
        a = rng.randint(-99, 99)
        b = rng.randint(-99, 99)
        ans = a - b
        if clamp_ok(ans):
            return Question(f"{a} - {b}", ans)

# ---------- Global communal storage (SQLite via Streamlit connection) ----------
# This is persisted on Streamlit Community Cloud and is shared by all users.
@st.cache_resource
def get_conn():
    # Streamlit provides a built-in sqlite connection on Community Cloud
    return st.connection("sqlite", type="sql")

def init_db():
    conn = get_conn()
    conn.query(
        """
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            score REAL NOT NULL,
            accuracy REAL NOT NULL,
            time_taken REAL NOT NULL
        );
        """,
        ttl=0,
    )

def insert_score(score: float, accuracy: float, time_taken: float):
    conn = get_conn()
    # Use parameterized insert
    conn.query(
        """
        INSERT INTO scores (ts, score, accuracy, time_taken)
        VALUES (:ts, :score, :accuracy, :time_taken);
        """,
        params={
            "ts": int(time.time()),
            "score": float(score),
            "accuracy": float(accuracy),
            "time_taken": float(time_taken),
        },
        ttl=0,
    )

def get_global_scores(limit: int | None = None) -> list[float]:
    conn = get_conn()
    q = "SELECT score FROM scores"
    if limit:
        q += " ORDER BY id DESC LIMIT :lim"
        df = conn.query(q, params={"lim": limit}, ttl=0)
    else:
        df = conn.query(q, ttl=0)
    if df is None or df.empty:
        return []
    return [float(x) for x in df["score"].tolist()]

def percentile_rank(user_score: float, history: list[float]) -> float | None:
    # higher percentile = better. lower score is better => count scores worse (greater)
    if not history:
        return None
    worse = sum(1 for s in history if s > user_score)
    return 100.0 * worse / len(history)

# ---------- App state helpers ----------
def reset_all():
    for k in [
        "started", "finished", "start_time", "questions", "idx",
        "user_answers", "seed", "last_run"
    ]:
        st.session_state.pop(k, None)
    st.rerun()

def finish_quiz(show_answers: bool):
    end_time = time.perf_counter()
    time_taken = end_time - st.session_state.start_time

    questions: list[Question] = st.session_state.questions
    user_answers: list[int | None] = st.session_state.user_answers

    correct = 0
    for q, ua in zip(questions, user_answers):
        if ua is not None and ua == q.answer:
            correct += 1

    accuracy = correct / len(questions)
    score = float("inf") if accuracy == 0 else (1.0 / accuracy) * time_taken

    # Get global history BEFORE inserting (so percentile is vs existing attempts)
    history = get_global_scores()
    pct = None if score == float("inf") else percentile_rank(score, history)

    # Save to global DB (skip inf runs so they don't poison the dataset)
    if score != float("inf"):
        insert_score(score, accuracy, time_taken)

    st.session_state.finished = True
    st.session_state.last_run = {
        "time_taken": time_taken,
        "correct": correct,
        "accuracy": accuracy,
        "score": score,
        "percentile": pct,
        "show_answers": show_answers,
    }
    st.rerun()

# ---------- UI ----------
st.title("🔥 Global Speed Math")
st.caption("Communal leaderboard vibes: your percentile is vs *everyone*. Lower score = better 🙏")

init_db()

col1, col2 = st.columns(2)
with col1:
    seed = st.number_input("Random seed (optional)", value=0, step=1)
with col2:
    show_answers = st.checkbox("Show correct answers at end", value=True)

st.divider()

if "started" not in st.session_state:
    st.session_state.started = False
if "finished" not in st.session_state:
    st.session_state.finished = False

if not st.session_state.started:
    st.write("Press **Start**. Then mash Enter like it owes you money 😭")

    if st.button("🚀 Start", type="primary", use_container_width=True):
        rng = random.Random(int(seed) if seed != 0 else None)
        st.session_state.seed = seed
        st.session_state.questions = [make_question(rng) for _ in range(NUM_QUESTIONS)]
        st.session_state.user_answers = [None] * NUM_QUESTIONS
        st.session_state.idx = 0
        st.session_state.start_time = time.perf_counter()
        st.session_state.started = True
        st.session_state.finished = False
        st.rerun()

else:
    if st.session_state.finished:
        r = st.session_state.last_run
        st.success("Done 🔥")

        st.write(f"**Time taken:** {r['time_taken']:.3f} s")
        st.write(f"**Accuracy:** {r['correct']}/{NUM_QUESTIONS} = {r['accuracy']*100:.1f}%")
        st.write(f"**Final score:** {r['score']:.4f}" if r["score"] != float("inf") else "**Final score:** ∞ (accuracy was 0 💀)")

        if r["percentile"] is None:
            st.write("**Percentile:** N/A (not enough global data yet, or score was ∞)")
        else:
            st.write(f"**Percentile:** {r['percentile']:.1f}th (higher = better)")

        # Optional: show total attempts
        global_scores = get_global_scores()
        st.caption(f"Global attempts recorded: **{len(global_scores)}**")

        if r.get("show_answers", True):
            st.divider()
            st.subheader("Review")
            for i, q in enumerate(st.session_state.questions, start=1):
                ua = st.session_state.user_answers[i - 1]
                ok = (ua == q.answer)
                st.write(
                    f"Q{i}. {q.text} = **{q.answer}**  |  you: **{ua if ua is not None else '—'}**  "
                    f"{'✅' if ok else '❌'}"
                )

        st.divider()
        if st.button("🔁 New run", use_container_width=True):
            reset_all()

    else:
        idx = st.session_state.idx
        questions: list[Question] = st.session_state.questions
        q = questions[idx]

        st.info("Timer is running… Enter submits and jumps to the next one 🥷er 💀")
        st.progress(idx / NUM_QUESTIONS)
        st.write(f"**Question {idx+1}/{NUM_QUESTIONS}**")
        st.markdown(f"### {q.text} = ?")

        with st.form("single_q_form", clear_on_submit=True):
            raw = st.text_input("Type answer and press Enter", value="", placeholder="e.g. 42")
            submitted = st.form_submit_button("Next (Enter)")

        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            if st.button("⏭ Skip", use_container_width=True):
                st.session_state.user_answers[idx] = None
                st.session_state.idx += 1
                if st.session_state.idx >= NUM_QUESTIONS:
                    finish_quiz(show_answers)
                st.rerun()

        with c2:
            if st.button("🏁 Finish Quiz", type="primary", use_container_width=True):
                finish_quiz(show_answers)

        with c3:
            if st.button("🔁 Reset", use_container_width=True):
                reset_all()

        if submitted:
            raw = raw.strip()
            try:
                val = int(raw)
            except Exception:
                val = None

            st.session_state.user_answers[idx] = val
            st.session_state.idx += 1

            if st.session_state.idx >= NUM_QUESTIONS:
                finish_quiz(show_answers)
            else:
                st.rerun()
