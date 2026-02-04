# main.py
# Streamlit Speed Math: 10 random questions (+, -, ×, ÷)
# - Enter advances to next question (one-at-a-time form)
# - Global/communal percentile via Supabase table: speed_math_scores

import os
import time
import uuid
import random
from dataclasses import dataclass
from typing import Optional, List, Tuple

import streamlit as st

# Supabase is optional; app still runs without it (no global percentile)
try:
    from supabase import create_client, Client
except Exception:
    create_client = None
    Client = None


# ----------------- Config -----------------
NUM_QUESTIONS = 10
MAX_ABS_ANSWER = 143          # all answers under 144 in magnitude
MAX_DIV_ANSWER = 12           # division highest answer (quotient)
SCORE_EPS = 0.01              # prevents inf scores when accuracy=0

SCORES_TABLE = "speed_math_scores"

st.set_page_config(
    page_title="Speed Math Global",
    page_icon="🧮",
    layout="centered",
)


# ----------------- Data models -----------------
@dataclass(frozen=True)
class Question:
    text: str
    answer: int


# ----------------- Supabase helpers -----------------
def _get_supabase_client() -> Optional["Client"]:
    """
    Returns a Supabase client if configured + library installed, else None.
    Uses Streamlit secrets first, then environment variables.
    """
    if create_client is None:
        return None

    url = None
    key = None

    # Streamlit Secrets
    try:
        url = st.secrets.get("SUPABASE_URL")
        key = st.secrets.get("SUPABASE_KEY")
    except Exception:
        pass

    # Env fallback
    url = url or os.getenv("SUPABASE_URL")
    key = key or os.getenv("SUPABASE_KEY")

    if not url or not key:
        return None

    try:
        return create_client(url, key)
    except Exception:
        return None


@st.cache_resource
def supabase_client() -> Optional["Client"]:
    # One shared client per server process
    return _get_supabase_client()


def supabase_available() -> bool:
    return supabase_client() is not None


def insert_score_supabase(
    score: float,
    accuracy: float,
    time_taken: float,
    correct: int,
    num_questions: int,
) -> None:
    sb = supabase_client()
    if sb is None:
        return

    payload = {
        "id": str(uuid.uuid4()),
        "score": float(score),
        "accuracy": float(accuracy),
        "time_taken": float(time_taken),
        "num_questions": int(num_questions),
        "correct": int(correct),
    }

    # Don’t let a failed insert crash the run
    try:
        sb.table(SCORES_TABLE).insert(payload).execute()
    except Exception:
        # silently fail (or you can st.warning if you want noisy mode)
        pass


def get_global_scores_supabase(limit: int = 5000) -> Tuple[List[float], Optional[int]]:
    """
    Returns (scores_list, total_count_if_available).
    We fetch up to `limit` scores to compute percentile client-side.
    """
    sb = supabase_client()
    if sb is None:
        return [], None

    try:
        # Get total count (exact) + scores sample
        res = (
            sb.table(SCORES_TABLE)
            .select("score", count="exact")
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )

        scores = [float(row["score"]) for row in (res.data or [])]
        total = getattr(res, "count", None)
        return scores, total
    except Exception:
        return [], None


# ----------------- Question generation -----------------
def clamp_ok(ans: int) -> bool:
    return abs(ans) <= MAX_ABS_ANSWER


def make_question(rng: random.Random) -> Question:
    """
    Generates +, -, ×, ÷ questions with constraints:
    - abs(answer) <= 143
    - division quotient <= 12
    """
    op = rng.choice(["+", "-", "×", "÷"])

    if op == "÷":
        # Ensure integer division, quotient <= 12
        q = rng.randint(0, MAX_DIV_ANSWER)  # keep 0 if you want; change to 1..12 if you hate freebies
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
            a = rng.randint(-12, 12)
            b = rng.randint(-12, 12)
            ans = a + b
            if clamp_ok(ans):
                return Question(f"{a} + {b}", ans)

    # op == "-"
    while True:
        a = rng.randint(-12, 12)
        b = rng.randint(-12, 12)
        ans = a - b
        if clamp_ok(ans):
            return Question(f"{a} - {b}", ans)


def percentile_rank(user_score: float, history: List[float]) -> Optional[float]:
    """
    Higher percentile = better.
    Lower score is better, so percentile counts how many past scores are worse (greater).
    """
    if not history:
        return None
    worse = sum(1 for s in history if s > user_score)
    return 100.0 * worse / len(history)


# ----------------- Session helpers -----------------
def reset_all() -> None:
    for k in [
        "started",
        "finished",
        "start_time",
        "questions",
        "idx",
        "user_answers",
        "seed",
        "last_run",
    ]:
        st.session_state.pop(k, None)
    st.rerun()


def finish_quiz(show_answers: bool) -> None:
    end_time = time.perf_counter()
    time_taken = float(end_time - st.session_state.start_time)

    questions: List[Question] = st.session_state.questions
    user_answers: List[Optional[int]] = st.session_state.user_answers

    correct = 0
    for q, ua in zip(questions, user_answers):
        if ua is not None and ua == q.answer:
            correct += 1

    accuracy = correct / len(questions)

    # Finite, always:
    # score = (1/accuracy)*time would explode; we clamp accuracy to EPS to avoid inf.
    effective_acc = max(accuracy, SCORE_EPS)
    score = (1.0 / effective_acc) * time_taken

    # Percentile vs GLOBAL history BEFORE inserting this run
    history, total_count = get_global_scores_supabase()
    pct = percentile_rank(score, history)

    # Save run to Supabase (best effort)
    insert_score_supabase(
        score=score,
        accuracy=accuracy,
        time_taken=time_taken,
        correct=correct,
        num_questions=len(questions),
    )

    st.session_state.finished = True
    st.session_state.last_run = {
        "time_taken": time_taken,
        "correct": correct,
        "accuracy": accuracy,
        "score": score,
        "percentile": pct,
        "global_count": total_count if total_count is not None else len(history),
        "show_answers": show_answers,
    }
    st.rerun()


# ----------------- UI -----------------
st.title("Global Speed Math")
st.caption("Score = (1/accuracy) × time_taken_seconds  •  lower is better   •  Percentile is vs everyone")

# Settings row
col1, col2 = st.columns(2)
with col1:
    seed = st.number_input("Random seed (0 = random)", value=0, step=1)
with col2:
    show_answers = st.checkbox("Show correct answers at end", value=True)

# Supabase status
if not supabase_available():
    st.warning(
        "Supabase not configured — runs will still work, but **global percentile + global attempts** are disabled. 🙏"
    )

st.divider()

# Init session flags
if "started" not in st.session_state:
    st.session_state.started = False
if "finished" not in st.session_state:
    st.session_state.finished = False

# Start screen
if not st.session_state.started:
    st.write("Press **Start**. Then continue until finished (10 questions).")

    if st.button("Start", type="primary", use_container_width=True):
        rng = random.Random(int(seed)) if int(seed) != 0 else random.Random()
        st.session_state.seed = int(seed)
        st.session_state.questions = [make_question(rng) for _ in range(NUM_QUESTIONS)]
        st.session_state.user_answers = [None] * NUM_QUESTIONS
        st.session_state.idx = 0
        st.session_state.start_time = time.perf_counter()
        st.session_state.started = True
        st.session_state.finished = False
        st.rerun()

# Running / finished
else:
    # Finished screen
    if st.session_state.finished:
        r = st.session_state.last_run
        st.success("Done 🔥")

        st.write(f"**Time taken:** {r['time_taken']:.3f} s")
        st.write(f"**Accuracy:** {r['correct']}/{NUM_QUESTIONS} = {r['accuracy']*100:.1f}%")
        st.write(f"**Final score:** {r['score']:.4f}")

        if r["percentile"] is None or not supabase_available():
            st.write("**Percentile:** N/A (no global data available)")
        else:
            st.write(f"**Percentile:** {r['percentile']:.1f}th (higher = better)")

        if supabase_available():
            st.caption(f"Global attempts recorded: **{r.get('global_count', '—')}**")
        else:
            st.caption("Global attempts recorded: **—**")

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
        c1, c2 = st.columns(2)
        with c1:
            if st.button("New run", use_container_width=True):
                reset_all()
        with c2:
            if st.button("Reset (local session only)", use_container_width=True):
                reset_all()

    # In-progress screen
    else:
        idx = st.session_state.idx
        questions: List[Question] = st.session_state.questions
        q = questions[idx]

        st.info("Timer is running… Enter submits and jumps to the next one")
        st.progress(idx / NUM_QUESTIONS)
        st.write(f"**Question {idx+1}/{NUM_QUESTIONS}**")
        st.markdown(f"### {q.text} = ?")

        # Form makes Enter submit
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
            if st.button("Finish Quiz", type="primary", use_container_width=True):
                finish_quiz(show_answers)

        with c3:
            if st.button("Reset", use_container_width=True):
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
