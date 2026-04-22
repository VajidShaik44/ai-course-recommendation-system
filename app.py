import json
import os
import sqlite3
import urllib.parse
import uuid

from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    stream_with_context,
    url_for,
)
from groq import Groq
from werkzeug.security import check_password_hash, generate_password_hash

from database import (
    get_course_id_by_name,
    get_peer_goal_stats,
    get_saved_roadmap,
    get_saved_roadmap_by_token,
    get_user_profile,
    get_user_recommendations,
    get_user_saved_roadmaps,
    init_db,
    record_goal_choice,
    save_recommendation,
    set_phase_completion,
    upsert_saved_roadmap,
    upsert_user_profile,
)
from ml_model import recommend_course, stage_aware_recommend
from profile_config import default_profile, get_profile_form_config

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

init_db()

GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama3-70b-8192")
client = None

if os.environ.get("GROQ_API_KEY"):
    try:
        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    except Exception:
        client = None

course_ai_cache = {}
roadmap_cache = {}
career_fit_cache = {}


def ensure_session_cache_key():
    if "cache_session_id" not in session:
        session["cache_session_id"] = uuid.uuid4().hex

    return session["cache_session_id"]


def normalize_skill_list(raw_skills):
    if isinstance(raw_skills, list):
        values = raw_skills
    else:
        values = str(raw_skills or "").replace("\n", ",").split(",")

    normalized = []
    seen = set()

    for value in values:
        skill = value.strip()
        if not skill:
            continue

        key = skill.lower()
        if key in seen:
            continue

        seen.add(key)
        normalized.append(skill)

    return normalized


def build_profile_from_form(form):
    profile = default_profile()
    profile.update(
        {
            "stage": (form.get("stage") or "").strip(),
            "profession": (form.get("profession") or "Student").strip() or "Student",
            "experience": (form.get("experience") or "0").strip() or "0",
            "current_role": (form.get("current_role") or "").strip(),
            "specialization": (form.get("specialization") or "").strip(),
            "subjects": (form.get("stream_subjects") or "").strip(),
            "skills": normalize_skill_list(form.get("skills")),
        }
    )

    if profile["profession"] == "Student":
        profile["current_role"] = ""

    return profile


def build_query_text(profile):
    return " ".join(
        part
        for part in [
            profile.get("stage"),
            profile.get("profession"),
            profile.get("experience"),
            profile.get("current_role"),
            profile.get("specialization"),
            profile.get("subjects"),
            " ".join(profile.get("skills", [])),
        ]
        if part
    ).strip()


def build_profile_summary(profile):
    skills = profile.get("skills", [])
    return "\n".join(
        [
            f"Education stage: {profile.get('stage') or 'Not provided'}",
            f"Profession: {profile.get('profession') or 'Not provided'}",
            f"Experience: {profile.get('experience') or 'Not provided'}",
            f"Current role: {profile.get('current_role') or 'Not provided'}",
            f"Specialization: {profile.get('specialization') or 'Not provided'}",
            f"Subjects: {profile.get('subjects') or 'Not provided'}",
            f"Skills: {', '.join(skills) if skills else 'Not provided'}",
        ]
    )


def build_profile_key(profile):
    return "|".join(
        [
            (profile.get("stage") or "unknown").strip().lower(),
            (profile.get("profession") or "unknown").strip().lower(),
            (profile.get("experience") or "unknown").strip().lower(),
        ]
    )


def is_experienced(profile):
    return (profile.get("experience") or "0") not in {"", "0", "0-1"}


def infer_upskill_mode(profile, goal):
    profession = (profile.get("profession") or "").lower()
    goal_name = (goal or "").lower()

    if not profession or profession == "student":
        return ("Skill build", "Medium")

    if profession in goal_name or any(token in goal_name for token in profession.split()):
        return ("Upskill", "Medium")

    if is_experienced(profile):
        return ("Reskill", "High")

    return ("Upskill", "Medium")


def infer_transition_note(profile, goal):
    profession = profile.get("profession") or ""
    current_role = profile.get("current_role") or profession

    if not profession or profession == "Student":
        return ""

    goal_name = (goal or "").lower()
    role_text = current_role.lower()

    if role_text and role_text not in goal_name:
        return f"This path can work as a transition from {current_role} into {goal}, with focused bridge projects and domain-specific practice."

    return f"This path builds naturally from your {current_role} background and leans more toward upskilling than a full reset."


def extract_json_object(text):
    start = text.find("{")
    end = text.rfind("}") + 1

    if start == -1 or end <= start:
        raise ValueError("No JSON object found")

    return json.loads(text[start:end])


def call_groq_json(system_prompt, user_prompt, fallback_data):
    if not client:
        return fallback_data

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = response.choices[0].message.content.strip()
        return extract_json_object(text)
    except Exception as error:
        print("GROQ JSON ERROR:", error)
        return fallback_data


def fallback_course_content(course, profile):
    mode, difficulty = infer_upskill_mode(profile, course)
    skills = profile.get("skills", [])

    return {
        "why": [
            f"{course} aligns with your current profile and helps strengthen relevant market-ready skills.",
            f"Your background in {profile.get('profession') or 'your current path'} gives you a useful base for this goal.",
            f"Focusing on {course} can create a clearer path from learning to job opportunities.",
        ],
        "advantages": [
            f"{course} is useful for both project work and employability.",
            "It supports visible portfolio building and clearer specialization.",
            "The roadmap can be tailored around your current experience level.",
        ],
        "disadvantages": [
            "You may need to invest steady practice time before the results feel immediate.",
            "Some tools in this path can feel broad without a focused project strategy.",
        ],
        "jobs": [f"Junior {course}", f"{course} Specialist", f"{course} Associate"],
        "upskillReskill": mode,
        "difficultyRating": difficulty,
        "careerTransition": infer_transition_note(profile, course),
        "summaryTags": skills[:3] or ["Guided roadmap", "Project work", "Career clarity"],
    }


def generate_ai_content(course, profile):
    cache_key = json.dumps({"course": course, "profile": profile}, sort_keys=True)

    if cache_key in course_ai_cache:
        return course_ai_cache[cache_key]

    fallback = fallback_course_content(course, profile)
    system_prompt = (
        "You are PathFinder AI, an expert Indian career advisor. "
        "Return strict JSON only with short, actionable guidance."
    )
    user_prompt = f"""
User profile:
{build_profile_summary(profile)}

Target course or career path: {course}

Return a JSON object with this exact shape:
{{
  "why": ["reason", "reason", "reason"],
  "advantages": ["advantage", "advantage", "advantage"],
  "disadvantages": ["risk", "risk"],
  "jobs": ["job role", "job role", "job role"],
  "upskillReskill": "Upskill or Reskill or Skill build",
  "difficultyRating": "Low or Medium or High",
  "careerTransition": "One personalized sentence about transition or progression",
  "summaryTags": ["short tag", "short tag", "short tag"]
}}

Rules:
- Keep all list items concise and specific.
- If the user has 1+ years of experience, avoid beginner framing.
- If the user's current profession differs from the goal, mention transition guidance.
- Use Indian job-market language.
"""
    data = call_groq_json(system_prompt, user_prompt, fallback)
    course_ai_cache[cache_key] = data
    return data


def build_default_resources(goal):
    query = urllib.parse.quote_plus(goal)
    return [
        {"name": "roadmap.sh", "type": "Free", "url": f"https://roadmap.sh/search?query={query}"},
        {"name": "freeCodeCamp", "type": "Free", "url": "https://www.freecodecamp.org/"},
        {"name": "Coursera", "type": "Paid", "url": "https://www.coursera.org/"},
    ]


def fallback_roadmap(goal, profile):
    mode, difficulty = infer_upskill_mode(profile, goal)
    user_skills = profile.get("skills", [])
    already_have = user_skills[:4]
    need_to_learn = [
        f"{goal} foundations",
        f"{goal} projects",
        f"{goal} interview skills",
        "Portfolio building",
    ]
    nice_to_have = ["Communication", "Documentation", "Industry tools"]

    if is_experienced(profile):
        need_to_learn = [
            f"Advanced {goal} tooling",
            "System design or architecture",
            "Leadership-ready delivery",
            "Portfolio case studies",
        ]
        nice_to_have = ["Mentoring", "Cross-functional collaboration", "Cloud deployment"]

    return {
        "goal": goal,
        "matchScore": 78,
        "whyThisFits": f"{goal} aligns with your {profile.get('profession') or 'current'} background and can be shaped around your existing skills in {', '.join(user_skills[:3]) if user_skills else 'practical execution'}.",
        "skillGapAnalysis": {
            "alreadyHave": already_have or ["Learning intent", "Problem solving"],
            "needToLearn": need_to_learn,
            "niceToHave": nice_to_have,
        },
        "roadmap": [
            {
                "phase": 1,
                "title": "Core foundation",
                "duration": "3-4 weeks",
                "topics": [f"{goal} basics", "Terminology", "Hands-on practice", "Tool setup"],
                "resources": build_default_resources(goal),
            },
            {
                "phase": 2,
                "title": "Applied build phase",
                "duration": "4-6 weeks",
                "topics": ["Projects", "Workflows", "Debugging", "Best practices"],
                "resources": build_default_resources(f"{goal} projects"),
            },
            {
                "phase": 3,
                "title": "Portfolio and positioning",
                "duration": "3-5 weeks",
                "topics": ["Case studies", "Resume updates", "Interview prep", "LinkedIn optimization"],
                "resources": build_default_resources(f"{goal} interview"),
            },
            {
                "phase": 4,
                "title": "Job execution",
                "duration": "2-4 weeks",
                "topics": ["Applications", "Mock interviews", "Networking", "Target companies"],
                "resources": build_default_resources(f"{goal} jobs"),
            },
        ],
        "toolsAndTechnologies": {
            "mustLearn": need_to_learn[:3],
            "recommended": ["Projects", "Version control", "Problem solving"],
            "advanced": ["Leadership communication", "Architecture thinking", "Automation"],
        },
        "jobRoles": [
            {
                "title": f"{goal} Associate",
                "avgSalary": "Rs 4-8 LPA",
                "requiredSkills": already_have[:2] + need_to_learn[:2],
                "hiringPlatforms": ["LinkedIn", "Naukri", "Indeed"],
            },
            {
                "title": f"{goal} Specialist",
                "avgSalary": "Rs 7-14 LPA",
                "requiredSkills": need_to_learn[:3],
                "hiringPlatforms": ["LinkedIn", "Wellfound", "Instahyre"],
            },
        ],
        "estimatedTimeToJob": "4-8 months",
        "certifications": [
            {"name": f"{goal} fundamentals", "platform": "Coursera", "type": "Paid"},
            {"name": f"{goal} practical roadmap", "platform": "roadmap.sh", "type": "Free"},
        ],
        "dailyStudyPlan": {
            "hoursPerDay": 2 if not is_experienced(profile) else 1.5,
            "weeklyGoal": "Finish one focused topic block and one practical exercise each week.",
            "weekendTip": "Turn the week's learning into a small proof-of-work or case study.",
        },
        "growthMode": {
            "recommendation": mode,
            "difficulty": difficulty,
            "reason": infer_transition_note(profile, goal),
        },
        "careerTransition": {
            "isTransition": mode == "Reskill",
            "summary": infer_transition_note(profile, goal),
            "bridgeSteps": [
                "Map your current transferable strengths to the target role.",
                "Build one transition-focused project that proves the new skill set.",
                "Update resume and LinkedIn around measurable outcomes, not only tools.",
            ],
        },
        "resumeKeywords": list(dict.fromkeys((already_have + need_to_learn + nice_to_have)[:10])),
    }


def generate_goal_roadmap(goal, profile):
    fallback = fallback_roadmap(goal, profile)
    system_prompt = (
        "You are PathFinder AI, an expert Indian career strategist. "
        "Return strict JSON only. Personalize the roadmap to the user's education, profession, experience, "
        "and current skill set. Avoid beginner content for users with 1+ years of experience."
    )
    user_prompt = f"""
User profile:
{build_profile_summary(profile)}

Target goal: {goal}

Return a JSON object with this exact shape:
{{
  "goal": "{goal}",
  "matchScore": 92,
  "whyThisFits": "2-3 sentences personalized to the user profile",
  "skillGapAnalysis": {{
    "alreadyHave": ["skill"],
    "needToLearn": ["skill"],
    "niceToHave": ["skill"]
  }},
  "roadmap": [
    {{
      "phase": 1,
      "title": "Phase title",
      "duration": "4-6 weeks",
      "topics": ["topic"],
      "resources": [
        {{"name": "resource", "type": "Free or Paid", "url": "https://..."}}
      ]
    }}
  ],
  "toolsAndTechnologies": {{
    "mustLearn": ["tool"],
    "recommended": ["tool"],
    "advanced": ["tool"]
  }},
  "jobRoles": [
    {{
      "title": "Role title",
      "avgSalary": "Rs 6-14 LPA",
      "requiredSkills": ["skill"],
      "hiringPlatforms": ["LinkedIn", "Naukri"]
    }}
  ],
  "estimatedTimeToJob": "6-9 months",
  "certifications": [
    {{"name": "certificate", "platform": "platform", "type": "Free or Paid"}}
  ],
  "dailyStudyPlan": {{
    "hoursPerDay": 2,
    "weeklyGoal": "goal",
    "weekendTip": "tip"
  }},
  "growthMode": {{
    "recommendation": "Upskill or Reskill or Skill build",
    "difficulty": "Low or Medium or High",
    "reason": "one sentence"
  }},
  "careerTransition": {{
    "isTransition": true,
    "summary": "personalized summary",
    "bridgeSteps": ["step", "step", "step"]
  }},
  "resumeKeywords": ["keyword"]
}}

Rules:
- Keep 4 roadmap phases unless the goal truly needs 5.
- If the user has 1+ years of experience, skip beginner-only steps and include advanced certifications, architecture thinking, and leadership-aware growth where relevant.
- If the user's profession differs from the target, include a meaningful career transition note.
- Use India-specific salary ranges and hiring platforms.
- Make resource URLs real-looking and clickable.
"""
    return call_groq_json(system_prompt, user_prompt, fallback)


def fallback_career_fit_analysis(goals, profile):
    ready_now = []
    almost_there = []
    growth_path = []
    matrix = []

    for goal in goals:
        goal_name = goal.get("course", "Recommended Role")
        match_percent = int(round(float(goal.get("score", 0))))
        item = {
            "role": goal_name,
            "matchPercent": match_percent,
            "matchingSkills": profile.get("skills", [])[:4] or ["Communication", "Problem solving"],
            "missingSkills": [f"{goal_name} projects", f"{goal_name} portfolio", "Interview prep"],
        }
        matrix.append(item)

        role_card = {
            "role": goal_name,
            "matchPercent": match_percent,
            "avgSalary": "Rs 5-12 LPA",
            "topCompanies": ["TCS", "Infosys", "Accenture"],
            "resumeKeywords": item["matchingSkills"] + item["missingSkills"][:2],
            "why": f"{goal_name} is a practical fit based on your current skills and education level.",
            "bridgePlan": [
                "Strengthen the missing tools with one focused learning sprint.",
                "Build a project that proves the target role's workflow.",
                "Update your resume around measurable results and keywords.",
            ],
        }

        if match_percent >= 80:
            ready_now.append(role_card)
        elif match_percent >= 50:
            almost_there.append(role_card)
        else:
            growth_path.append(role_card)

    return {
        "summary": "These role clusters help you see where you can apply now, where you are close, and where deliberate upskilling is still needed.",
        "skillMatchMatrix": matrix,
        "readyNow": ready_now,
        "almostThere": almost_there,
        "growthPath": growth_path,
    }


def generate_career_fit_analysis(goals, profile):
    fallback = fallback_career_fit_analysis(goals, profile)
    system_prompt = (
        "You are PathFinder AI, an expert Indian career analyst. "
        "Return strict JSON only. Analyze role readiness for a degree-level learner based on profile and recommended goals."
    )
    user_prompt = f"""
User profile:
{build_profile_summary(profile)}

Recommended goals:
{json.dumps(goals, ensure_ascii=True)}

Return a JSON object with this exact shape:
{{
  "summary": "short summary",
  "skillMatchMatrix": [
    {{
      "role": "Role name",
      "matchPercent": 82,
      "matchingSkills": ["skill"],
      "missingSkills": ["skill"]
    }}
  ],
  "readyNow": [
    {{
      "role": "Role name",
      "matchPercent": 85,
      "avgSalary": "Rs 6-12 LPA",
      "topCompanies": ["company"],
      "resumeKeywords": ["keyword"],
      "why": "short explanation"
    }}
  ],
  "almostThere": [
    {{
      "role": "Role name",
      "matchPercent": 65,
      "avgSalary": "Rs 5-10 LPA",
      "topCompanies": ["company"],
      "resumeKeywords": ["keyword"],
      "why": "short explanation"
    }}
  ],
  "growthPath": [
    {{
      "role": "Role name",
      "matchPercent": 40,
      "avgSalary": "Rs 4-9 LPA",
      "topCompanies": ["company"],
      "resumeKeywords": ["keyword"],
      "why": "short explanation",
      "bridgePlan": ["step", "step", "step"]
    }}
  ]
}}

Rules:
- Group roles by readiness: Ready Now (80+), Almost There (50-79), Growth Path (below 50).
- Use India-specific salary ranges and recognizable hiring companies.
- Add sample JD keywords that would strengthen a resume.
- Keep the analysis short, useful, and personalized.
"""
    return call_groq_json(system_prompt, user_prompt, fallback)


def get_active_profile():
    if session.get("user_id"):
        db_profile = get_user_profile(session["user_id"])
        if db_profile:
            session["active_profile"] = db_profile
            return db_profile

    return session.get("active_profile") or default_profile()


def serialize_saved_meta(saved):
    if not saved:
        return None

    return {
        "id": saved["id"],
        "progressPercent": saved["progress_percent"],
        "completedPhases": saved["completed_phases"],
        "shareUrl": url_for("shared_roadmap", token=saved["share_token"], _external=True),
    }


def track_goal_choice_once(goal, profile):
    tracked_goals = set(session.get("tracked_goal_views", []))
    tracked_key = goal.lower()

    if tracked_key in tracked_goals:
        return

    record_goal_choice(build_profile_key(profile), goal)
    tracked_goals.add(tracked_key)
    session["tracked_goal_views"] = sorted(tracked_goals)


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("students.db")
        c = conn.cursor()

        try:
            hashed = generate_password_hash(password)
            c.execute("INSERT INTO users(username,password) VALUES(?,?)", (username, hashed))
            conn.commit()
            flash("Account created successfully. Please sign in.", "success")
            return redirect("/login")
        except Exception:
            flash("User already exists", "error")
        finally:
            conn.close()

    return render_template("register.html")


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
            session["tracked_goal_views"] = []
            ensure_session_cache_key()
            return redirect("/dashboard")

        flash("Invalid login", "error")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    profile = get_active_profile()
    recommendations = get_user_recommendations(session["user_id"])
    return render_template(
        "dashboard.html",
        recommendations=recommendations,
        profile=profile,
        form_config=get_profile_form_config(),
    )


@app.route("/profile")
def profile():
    if "user" not in session:
        return redirect("/login")

    recommendations = get_user_recommendations(session["user_id"])
    saved_roadmaps = get_user_saved_roadmaps(session["user_id"])
    active_profile = get_active_profile()
    return render_template(
        "profile.html",
        recommendations=recommendations,
        saved_roadmaps=saved_roadmaps,
        profile=active_profile,
    )


@app.route("/recommend", methods=["GET", "POST"])
def recommend():
    if request.method == "GET":
        return redirect("/dashboard")

    if "user" not in session:
        return redirect("/login")

    profile = build_profile_from_form(request.form)
    input_text = build_query_text(profile)

    session["active_profile"] = profile
    session["cache_session_id"] = uuid.uuid4().hex
    session["tracked_goal_views"] = []
    upsert_user_profile(session["user_id"], profile)

    if profile["stage"]:
        results = stage_aware_recommend(profile["stage"], input_text)
    else:
        results = recommend_course(input_text)

    if results is None or results.empty:
        flash("No recommendations were generated. Please refine your profile and try again.", "error")
        return redirect("/dashboard")

    if is_experienced(profile):
        non_beginner = results[~results["level"].fillna("").str.contains("beginner", case=False)]
        if not non_beginner.empty:
            results = non_beginner

    max_score = results["score"].max()
    if max_score == 0:
        results["score"] = 0
    else:
        results["score"] = ((results["score"] / max_score) * 100).round(2)

    filtered = results[results["score"] > 18]
    if filtered.empty:
        filtered = results.head(4)

    filtered = filtered.head(4)
    course_names = filtered["course"].tolist()
    peer_stats = get_peer_goal_stats(build_profile_key(profile), course_names)
    courses = []

    for _, row in filtered.iterrows():
        course_name = row["course"]
        score_percent = float(row["score"])
        course_id = get_course_id_by_name(course_name)
        ai = generate_ai_content(course_name, profile)

        if course_id is not None:
            save_recommendation(
                session["user_id"],
                input_text,
                course_id,
                round(score_percent / 100, 4),
                profile=profile,
            )

        courses.append(
            {
                "course": course_name,
                "score": score_percent,
                "why": ai.get("why", []),
                "advantages": ai.get("advantages", []),
                "disadvantages": ai.get("disadvantages", []),
                "jobs": ai.get("jobs", []),
                "upskillReskill": ai.get("upskillReskill", "Skill build"),
                "difficultyRating": ai.get("difficultyRating", "Medium"),
                "careerTransition": ai.get("careerTransition", ""),
                "summaryTags": ai.get("summaryTags", []),
                "peerChoicePercent": peer_stats.get(course_name),
            }
        )

    session["latest_goals"] = [course["course"] for course in courses]

    return render_template(
        "result.html",
        courses=courses,
        stage=profile["stage"],
        profile=profile,
        career_analysis_enabled=profile["stage"] == "Degree",
    )


@app.route("/roadmap/<path:course>")
def roadmap(course):
    goal = urllib.parse.unquote(course)
    profile = get_active_profile()
    saved = get_saved_roadmap(session["user_id"], goal) if session.get("user_id") else None

    return render_template(
        "roadmap.html",
        course=goal,
        profile=profile,
        saved_roadmap=saved,
        saved_meta=serialize_saved_meta(saved),
        read_only=False,
        shared_view=False,
        initial_roadmap=None,
    )


@app.route("/roadmap/share/<token>")
def shared_roadmap(token):
    saved = get_saved_roadmap_by_token(token)

    if not saved:
        return render_template("404.html"), 404

    return render_template(
        "roadmap.html",
        course=saved["goal"],
        profile=saved["profile_snapshot"],
        saved_roadmap=saved,
        saved_meta=serialize_saved_meta(saved),
        read_only=True,
        shared_view=True,
        initial_roadmap=saved["roadmap"],
    )


@app.route("/api/roadmap/<path:course>")
def roadmap_data(course):
    goal = urllib.parse.unquote(course)
    profile = get_active_profile()
    user_scope = session.get("user_id", "guest")
    cache_key = (user_scope, ensure_session_cache_key(), goal.lower())

    if cache_key not in roadmap_cache:
        roadmap_cache[cache_key] = generate_goal_roadmap(goal, profile)

    track_goal_choice_once(goal, profile)
    saved = get_saved_roadmap(session["user_id"], goal) if session.get("user_id") else None
    return jsonify({"roadmap": roadmap_cache[cache_key], "saved": serialize_saved_meta(saved)})


@app.route("/api/career-fit-analysis", methods=["POST"])
def career_fit_analysis():
    if "user" not in session:
        return jsonify({"error": "Login required"}), 401

    payload = request.get_json(silent=True) or {}
    goals = payload.get("goals", [])
    profile = get_active_profile()

    if profile.get("stage") != "Degree":
        return jsonify({"error": "Career fit analysis is available for degree profiles only."}), 400

    cache_key = (
        session["user_id"],
        ensure_session_cache_key(),
        json.dumps(goals, sort_keys=True),
    )

    if cache_key not in career_fit_cache:
        career_fit_cache[cache_key] = generate_career_fit_analysis(goals, profile)

    return jsonify({"analysis": career_fit_cache[cache_key]})


@app.route("/api/roadmap/save", methods=["POST"])
def save_roadmap():
    if "user" not in session:
        return jsonify({"error": "Login required"}), 401

    payload = request.get_json(silent=True) or {}
    goal = (payload.get("goal") or "").strip()
    roadmap = payload.get("roadmap")

    if not goal or not isinstance(roadmap, dict):
        return jsonify({"error": "Goal and roadmap payload are required."}), 400

    saved = upsert_saved_roadmap(session["user_id"], goal, roadmap, get_active_profile())
    return jsonify({"saved": serialize_saved_meta(saved)})


@app.route("/api/roadmap/progress", methods=["POST"])
def update_roadmap_progress():
    if "user" not in session:
        return jsonify({"error": "Login required"}), 401

    payload = request.get_json(silent=True) or {}
    goal = (payload.get("goal") or "").strip()
    phase_number = int(payload.get("phaseNumber") or 0)
    completed = bool(payload.get("completed"))

    if not goal or not phase_number:
        return jsonify({"error": "Goal and phase number are required."}), 400

    saved = get_saved_roadmap(session["user_id"], goal)
    if not saved:
        return jsonify({"error": "Save the roadmap before tracking progress."}), 400

    set_phase_completion(saved["id"], phase_number, completed)
    updated = get_saved_roadmap(session["user_id"], goal)
    return jsonify({"saved": serialize_saved_meta(updated)})


@app.route("/api/chat", methods=["POST"])
def ai_chat():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    page_context = payload.get("context") or {}

    if not question:
        return Response("Please ask a question so I can help.", mimetype="text/plain")

    profile = get_active_profile()
    recommendations = payload.get("recommendations") or session.get("latest_goals", [])
    goal = page_context.get("goal") or ""

    system_prompt = (
        "You are the PathFinder AI assistant. Answer in a concise, high-value way. "
        "Use the user profile, recommendations, and roadmap context when relevant. "
        "Do not invent that you have live salary or location data unless it is provided in context."
    )
    user_prompt = f"""
User profile:
{build_profile_summary(profile)}

Current page context:
{json.dumps(page_context, ensure_ascii=True)}

Recommended goals in session:
{json.dumps(recommendations, ensure_ascii=True)}

Active goal:
{goal or 'None'}

User question:
{question}
"""

    if not client:
        return Response(
            "The AI assistant is temporarily unavailable. Please try again later.",
            mimetype="text/plain",
        )

    try:
        stream = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=True,
        )

        def generate():
            for chunk in stream:
                delta = ""
                if chunk.choices and getattr(chunk.choices[0], "delta", None):
                    delta = chunk.choices[0].delta.content or ""

                if delta:
                    yield delta

        return Response(stream_with_context(generate()), mimetype="text/plain")
    except Exception as error:
        print("GROQ CHAT ERROR:", error)
        return Response(
            "I could not complete the chat request right now. Please try again in a moment.",
            mimetype="text/plain",
        )


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.errorhandler(404)
def page_not_found(_error):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=True)
