import os
import sqlite3
from flask import Flask, render_template, request, redirect, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import (
    init_db, get_all_courses, add_course, delete_course,
    get_all_users, get_all_recommendations, get_stats,
    get_user_recommendations
)
from ml_model import recommend_course, stage_aware_recommend

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback-dev-key")

init_db()


# 🔥 AI Explanation Layer
def generate_explanation(course, skills):
    return {
        "why": f"{course} aligns with your interests in {skills} and fits your current career stage.",
        "advantages": [
            "High career demand",
            "Strong growth opportunities",
            "Industry-relevant skills"
        ],
        "disadvantages": [
            "Requires continuous learning",
            "Competitive field",
            "May need specialization"
        ]
    }


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")
    return render_template("dashboard.html")


@app.route("/recommend", methods=["GET", "POST"])
def recommend():
    if "user" not in session:
        return redirect("/login")

    stage = request.form.get("stage", "")
    stream_subjects = request.form.get("stream_subjects", "")
    skills = request.form.get("skills", "")

    input_text = f"{stream_subjects} {skills}".strip()

    # ML
    if stage and input_text:
        results = stage_aware_recommend(stage, input_text)
    else:
        results = recommend_course(input_text or skills)

    # Convert score → percentage
    results["score"] = (results["score"] * 100).round(2)

    # 🔥 Convert into structured data (IMPORTANT)
    courses_data = []
    for _, row in results.iterrows():
        explanation = generate_explanation(row["course"], skills)

        courses_data.append({
            "course": row["course"],
            "score": row["score"],
            "why": explanation["why"],
            "advantages": explanation["advantages"],
            "disadvantages": explanation["disadvantages"]
        })

    return render_template(
        "result.html",
        courses=courses_data,
        stage=stage or "General"
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("students.db")
        c = conn.cursor()
        c.execute("SELECT id, username, password FROM users WHERE username=?", (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            session["user"] = user[1]
            session["user_id"] = user[0]
            return redirect("/dashboard")
        else:
            flash("Invalid login", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")