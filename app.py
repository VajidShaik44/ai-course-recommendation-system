import os
import sqlite3
import urllib.parse
import json
from flask import Flask, render_template, request, redirect, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from groq import Groq

from database import init_db, get_user_recommendations
from ml_model import recommend_course, stage_aware_recommend

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

init_db()

# ---------------- GROQ ---------------- #
client = None
if os.environ.get("GROQ_API_KEY"):
    try:
        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    except:
        client = None

# ---------------- CACHE ---------------- #
ai_cache = {}

# ---------------- AI ENGINE ---------------- #
def generate_ai_content(course, skills):
    cache_key = f"{course}_{skills}"

    # CACHE HIT
    if cache_key in ai_cache:
        print("CACHE HIT:", course)
        return ai_cache[cache_key]

    if client:
        try:
            prompt = f"""
Return STRICT JSON only.

Course: {course}
Skills: {skills}

{{
  "why": ["specific reason"],
  "advantages": ["course specific advantage"],
  "disadvantages": ["course specific disadvantage"],
  "jobs": ["job roles"],
  "roadmap": ["step1", "step2"]
}}
"""

            response = client.chat.completions.create(
                model="llama3-70b-8192",
                messages=[{"role": "user", "content": prompt}]
            )

            text = response.choices[0].message.content.strip()

            # SAFE JSON PARSE
            try:
                start = text.find("{")
                end = text.rfind("}") + 1
                json_str = text[start:end]
                data = json.loads(json_str)
            except Exception as e:
                print("JSON ERROR:", e)
                return fallback_content(course, skills)

            ai_cache[cache_key] = data
            return data

        except Exception as e:
            print("AI ERROR:", e)

    return fallback_content(course, skills)


# ---------------- FALLBACK ---------------- #
def fallback_content(course, skills):
    return {
        "why": [f"{course} aligns with your skills"],
        "advantages": [f"{course} has strong career potential"],
        "disadvantages": [f"{course} requires consistent effort"],
        "jobs": [f"{course} related jobs"],
        "roadmap": [
            f"Learn basics of {course}",
            "Build projects",
            "Gain experience",
            "Apply for jobs"
        ]
    }


# ---------------- ROUTES ---------------- #

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/recommend", methods=["POST"])
def recommend():
    if "user" not in session:
        return redirect("/login")

    stage = request.form.get("stage", "")
    skills = request.form.get("skills", "")
    subjects = request.form.get("stream_subjects", "")

    input_text = f"{subjects} {skills}"

    if stage:
        results = stage_aware_recommend(stage, input_text)
    else:
        results = recommend_course(input_text)

    if results is None or results.empty:
        flash("No results found", "warning")
        return redirect("/dashboard")

    # SAFE NORMALIZATION
    max_score = results["score"].max()
    if max_score == 0:
        results["score"] = 0
    else:
        results["score"] = ((results["score"] / max_score) * 100).round(2)

    # FILTER + FALLBACK
    filtered = results[results["score"] > 20]
    if filtered.empty:
        filtered = results.head(3)

    results = filtered

    courses = []

    for _, row in results.iterrows():
        ai = generate_ai_content(row["course"], skills)

        courses.append({
            "course": row["course"],
            "score": row["score"],
            "why": ai["why"],
            "advantages": ai["advantages"],
            "disadvantages": ai["disadvantages"],
            "jobs": ai["jobs"],
            "roadmap": ai["roadmap"]
        })

    return render_template("result.html", courses=courses, stage=stage)


@app.route("/roadmap/<path:course>")
def roadmap(course):
    course = urllib.parse.unquote(course)

    ai = generate_ai_content(course, "")

    return render_template(
        "roadmap.html",
        course=course,
        steps=ai["roadmap"],
        jobs=ai["jobs"]
    )


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    data = get_user_recommendations(session["user_id"])
    return render_template("dashboard.html", recommendations=data)


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/register")
def register():
    return render_template("register.html")


@app.route("/profile")
def profile():
    return render_template("profile.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")