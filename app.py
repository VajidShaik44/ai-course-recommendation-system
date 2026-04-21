import os
import sqlite3
from flask import Flask, render_template, request, redirect, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from database import (
    init_db,
    get_user_recommendations,
    user_exists,
    create_user,
    get_user
)

from ml_model import recommend_course, stage_aware_recommend

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

init_db()


# ---------------- AI EXPLANATION ---------------- #
def generate_explanation(course, skills):
    return {
        "why": f"{course} fits your profile based on your skills ({skills}).",
        "advantages": [
            f"{course} has strong industry demand",
            f"{course} offers good salary growth",
            f"{course} builds future-ready skills"
        ],
        "disadvantages": [
            f"{course} requires continuous learning",
            f"{course} is competitive",
            f"{course} needs specialization"
        ]
    }


# ---------------- ROUTES ---------------- #

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    history = get_user_recommendations(session["user_id"])
    return render_template("dashboard.html", history=history)


# 🔥 FIXED (GET + POST)
@app.route("/recommend", methods=["GET", "POST"])
def recommend():
    if "user" not in session:
        return redirect("/login")

    if request.method == "GET":
        return redirect("/dashboard")

    stage = request.form.get("stage", "")
    subjects = request.form.get("stream_subjects", "")
    skills = request.form.get("skills", "")

    input_text = f"{subjects} {skills}".strip()

    try:
        if stage:
            results = stage_aware_recommend(stage, input_text)
        else:
            results = recommend_course(input_text)

        if results is None or results.empty:
            flash("No recommendations found", "warning")
            return redirect("/dashboard")

    except Exception as e:
        print("ML ERROR:", e)
        flash("Error generating recommendations", "error")
        return redirect("/dashboard")

    # Normalize score
    max_score = results["score"].max()
    if max_score > 0:
        results["score"] = ((results["score"] / max_score) * 100).round(2)
    else:
        results["score"] = 0

    # Filter weak matches
    results = results[results["score"] > 10]

    courses = []

    for _, row in results.iterrows():
        ai = generate_explanation(row["course"], skills)

        courses.append({
            "course": row["course"],
            "score": row["score"],
            "why": ai["why"],
            "advantages": ai["advantages"],
            "disadvantages": ai["disadvantages"]
        })

    return render_template("result.html", courses=courses, stage=stage or "General")


# 🔥 FIXED REGISTER (REAL LOGIC)
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        if not username or not password:
            flash("All fields are required", "error")
            return redirect("/register")

        if user_exists(username):
            flash("Username already taken", "error")
            return redirect("/register")

        try:
            hashed_password = generate_password_hash(password)
            create_user(username, hashed_password)

            flash("Account created successfully", "success")
            return redirect("/login")

        except Exception as e:
            print("REGISTER ERROR:", e)
            flash("Something went wrong. Try again.", "error")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = get_user(username)

        if user and check_password_hash(user["password"], password):
            session["user"] = user["username"]
            session["user_id"] = user["id"]
            return redirect("/dashboard")
        else:
            flash("Invalid credentials", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")