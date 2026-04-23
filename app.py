from dotenv import load_dotenv
load_dotenv()

import json
import os
import sqlite3
import urllib.parse
import uuid
from datetime import datetime

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

from core.groq_client import analyze_profile, generate_recommendations, generate_roadmap, ai_chat
from database import (
    get_course_id_by_name,
    get_latest_recommendation_session,
    get_peer_goal_stats,
    get_recommendation_session,
    get_saved_roadmap,
    get_saved_roadmap_by_token,
    get_user_profile,
    get_user_recommendations,
    get_user_saved_roadmaps,
    init_db,
    mark_recommendation_selected_path,
    record_goal_choice,
    save_ai_recommendation,
    save_ai_roadmap,
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


def normalize_form_values(form, *field_names):
    values = []

    for field_name in field_names:
        for raw_value in form.getlist(field_name):
            if isinstance(raw_value, list):
                candidates = raw_value
            else:
                candidates = str(raw_value or "").replace("\n", ",").split(",")

            for candidate in candidates:
                value = str(candidate or "").strip()
                if value:
                    values.append(value)

    normalized = []
    seen = set()

    for value in values:
        key = value.lower()
        if key in seen:
            continue

        seen.add(key)
        normalized.append(value)

    return normalized


def values_to_text(value):
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())

    return str(value or "").strip()


def build_user_data_from_form(form):
    skills = normalize_skill_list(form.get("skills"))
    subjects = normalize_form_values(form, "subjects", "stream_subjects")
    specialization = (form.get("specialization") or "").strip()

    if specialization and specialization.lower() not in {subject.lower() for subject in subjects}:
        subjects.append(specialization)

    interests = normalize_form_values(form, "interests")
    strengths = normalize_form_values(form, "strengths")

    if not interests:
        interests = skills[:]

    if not strengths:
        strengths = skills[:]

    return {
        "stage": (form.get("stage") or "").strip(),
        "subjects": subjects,
        "interests": interests,
        "strengths": strengths,
        "goal": (form.get("goal") or form.get("career_goal") or "").strip(),
        "profession": (form.get("profession") or "Student").strip() or "Student",
        "experience": (form.get("experience") or "0").strip() or "0",
        "current_role": (form.get("current_role") or "").strip(),
        "specialization": specialization,
        "skills": skills,
    }


def profile_from_user_data(user_data):
    profile = default_profile()
    skills = user_data.get("skills") or user_data.get("strengths") or user_data.get("interests") or []
    profile.update(
        {
            "stage": user_data.get("stage", ""),
            "profession": user_data.get("profession", "Student") or "Student",
            "experience": user_data.get("experience", "0") or "0",
            "current_role": user_data.get("current_role", ""),
            "specialization": user_data.get("specialization", ""),
            "subjects": values_to_text(user_data.get("subjects")),
            "skills": skills,
        }
    )

    if profile["profession"] == "Student":
        profile["current_role"] = ""

    return profile


def get_session_user_data():
    user_data = session.get("latest_user_data")
    if user_data:
        return user_data

    session_id = session.get("recommendation_session_id")
    if session_id:
        row = get_recommendation_session(session_id, session.get("user_id"))
        if row:
            user_data = json.loads(row["user_input"] or "{}")
            session["latest_user_data"] = user_data
            return user_data

    profile = get_active_profile()
    return {
        "stage": profile.get("stage", ""),
        "subjects": normalize_skill_list(profile.get("subjects", "")),
        "interests": profile.get("skills", []),
        "strengths": profile.get("skills", []),
        "goal": "",
        "profession": profile.get("profession", "Student"),
        "experience": profile.get("experience", "0"),
        "current_role": profile.get("current_role", ""),
        "specialization": profile.get("specialization", ""),
        "skills": profile.get("skills", []),
    }


def course_card_from_ai_recommendation(recommendation):
    score = recommendation.get("match_score", 0)
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0

    advantages = [
        f"Salary range: {recommendation.get('salary_range', 'Not specified')}",
        f"Growth outlook: {recommendation.get('growth_outlook', 'Not specified')}",
        f"Job-ready timeline: {recommendation.get('time_to_job_ready', 'Not specified')}",
    ]

    return {
        "course": recommendation.get("path_name", "Recommended Path"),
        "score": score,
        "why": recommendation.get("fit_reasons", []),
        "advantages": advantages,
        "disadvantages": recommendation.get("tradeoffs", []),
        "jobs": recommendation.get("job_titles", []),
        "upskillReskill": recommendation.get("growth_outlook", "AI recommended"),
        "difficultyRating": "Medium",
        "careerTransition": f"Focus first on {values_to_text(recommendation.get('top_skills_needed', [])) or 'the core skills'} to move toward this path.",
        "summaryTags": (recommendation.get("top_skills_needed", []) or [])[:3],
        "peerChoicePercent": None,
    }


def course_cards_from_ai_recommendations(recommendations):
    return [course_card_from_ai_recommendation(item) for item in recommendations or []]


def get_current_recommendation_row():
    session_id = session.get("recommendation_session_id")
    if session_id:
        row = get_recommendation_session(session_id, session.get("user_id"))
        if row:
            return row

    if session.get("user_id"):
        return get_latest_recommendation_session(session["user_id"])

    return None


def get_match_score_for_path(path_name):
    for recommendation in session.get("recommendations", []):
        if recommendation.get("path_name", "").lower() == path_name.lower():
            return recommendation.get("match_score", 0)

    row = get_current_recommendation_row()
    if not row:
        return 0

    for recommendation in json.loads(row["recommendations"] or "[]"):
        if recommendation.get("path_name", "").lower() == path_name.lower():
            return recommendation.get("match_score", 0)

    return 0


def roadmap_resource_for_template(resource):
    if isinstance(resource, dict):
        return {
            "name": resource.get("name", "Learning resource"),
            "type": resource.get("type", "Free"),
            "url": resource.get("url", "#"),
        }

    return {
        "name": str(resource or "Learning resource"),
        "type": "Free",
        "url": "#",
    }


def adapt_roadmap_for_template(path_name, roadmap_data, user_data):
    roadmap_data = roadmap_data or {}
    profile_analysis = session.get("profile_analysis", {})
    phases = roadmap_data.get("phases") or roadmap_data.get("roadmap") or []
    strengths = user_data.get("strengths") or user_data.get("skills") or []
    skill_gaps = profile_analysis.get("skill_gaps", [])
    hidden_strengths = profile_analysis.get("hidden_strengths", [])
    first_jobs = roadmap_data.get("first_job_titles", [])
    certifications = roadmap_data.get("certifications", [])
    topics = []

    adapted_phases = []
    for index, phase in enumerate(phases):
        phase_topics = phase.get("topics", [])
        topics.extend(phase_topics)
        adapted_phases.append(
            {
                "phase": phase.get("phase", index + 1),
                "title": phase.get("title", f"Phase {index + 1}"),
                "duration": phase.get("duration", ""),
                "topics": phase_topics,
                "resources": [roadmap_resource_for_template(item) for item in phase.get("resources", [])],
                "goal": phase.get("goal", ""),
                "project": phase.get("project", ""),
                "milestone": phase.get("milestone", ""),
            }
        )

    need_to_learn = skill_gaps or topics[:5] or [f"{path_name} foundations"]
    already_have = strengths[:4] or hidden_strengths[:3] or ["Learning intent", "Problem solving"]
    nice_to_have = hidden_strengths[:3] or ["Communication", "Portfolio building", "Interview practice"]
    job_roles = [
        {
            "title": title,
            "avgSalary": "4L - 12LPA",
            "requiredSkills": need_to_learn[:3],
            "hiringPlatforms": ["LinkedIn", "Naukri", "Internshala"],
        }
        for title in first_jobs
    ]
    certification_items = [
        item if isinstance(item, dict) else {"name": item, "platform": "Recommended", "type": "Free/Paid"}
        for item in certifications
    ]

    adapted = dict(roadmap_data)
    adapted.update(
        {
            "goal": path_name,
            "matchScore": get_match_score_for_path(path_name),
            "whyThisFits": profile_analysis.get("personality_fit")
            or f"{path_name} aligns with the profile details from your latest recommendation session.",
            "skillGapAnalysis": {
                "alreadyHave": already_have,
                "needToLearn": need_to_learn,
                "niceToHave": nice_to_have,
            },
            "roadmap": adapted_phases,
            "toolsAndTechnologies": {
                "mustLearn": need_to_learn[:4],
                "recommended": topics[:4] or need_to_learn[:3],
                "advanced": ["Portfolio case studies", "Mock interviews", "Industry networking"],
            },
            "jobRoles": job_roles
            or [
                {
                    "title": f"{path_name} Associate",
                    "avgSalary": "4L - 10LPA",
                    "requiredSkills": need_to_learn[:3],
                    "hiringPlatforms": ["LinkedIn", "Naukri", "Internshala"],
                }
            ],
            "estimatedTimeToJob": roadmap_data.get("total_duration", "12 months"),
            "certifications": certification_items,
            "dailyStudyPlan": {
                "hoursPerDay": 2,
                "weeklyGoal": "Complete one focused topic and one practical exercise each week.",
                "weekendTip": "Turn the week's learning into a small portfolio artifact.",
            },
            "growthMode": {
                "recommendation": "Skill build",
                "difficulty": "Medium",
                "reason": profile_analysis.get("market_outlook", ""),
            },
            "careerTransition": {
                "isTransition": bool(user_data.get("goal")),
                "summary": f"This roadmap moves you toward {path_name} with a project-first learning plan.",
                "bridgeSteps": [
                    "Map your existing strengths to the target role.",
                    "Build one proof-of-work project for the path.",
                    "Update your resume and LinkedIn around measurable outcomes.",
                ],
            },
            "resumeKeywords": list(dict.fromkeys(already_have + need_to_learn + nice_to_have))[:10],
        }
    )
    return adapted


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

    try:
        user_data = build_user_data_from_form(request.form)
        profile = profile_from_user_data(user_data)
        profile_analysis = analyze_profile(user_data)
        recommendations = generate_recommendations(profile_analysis, user_data)
        session_id = str(uuid.uuid4())
        recommendation_id = save_ai_recommendation(
            session["user_id"],
            session_id,
            user_data,
            profile_analysis,
            recommendations,
        )

        session["active_profile"] = profile
        session["latest_user_data"] = user_data
        session["recommendation_session_id"] = session_id
        session["recommendation_id"] = recommendation_id
        session["recommendations"] = recommendations
        session["profile_analysis"] = profile_analysis
        session["recommendation_generated_at"] = datetime.utcnow().isoformat()
        session["cache_session_id"] = uuid.uuid4().hex
        session["tracked_goal_views"] = []
        session["latest_goals"] = [item.get("path_name") for item in recommendations if item.get("path_name")]
        upsert_user_profile(session["user_id"], profile)

        return redirect(url_for("results"))
    except Exception as error:
        print("GROQ RECOMMENDATION ERROR:", error)
        flash("Our AI is temporarily unavailable. Please try again in a moment.", "error")
        return redirect("/dashboard")


@app.route("/results")
def results():
    if "user" not in session:
        return redirect("/login")

    recommendations = session.get("recommendations")
    profile_analysis = session.get("profile_analysis")
    user_data = session.get("latest_user_data")

    if not recommendations:
        row = get_current_recommendation_row()
        if row:
            recommendations = json.loads(row["recommendations"] or "[]")
            profile_analysis = json.loads(row["profile_analysis"] or "{}")
            user_data = json.loads(row["user_input"] or "{}")
            session["recommendations"] = recommendations
            session["profile_analysis"] = profile_analysis
            session["latest_user_data"] = user_data

    if not recommendations:
        flash("No recommendations were generated. Please refine your profile and try again.", "error")
        return redirect("/dashboard")

    profile = profile_from_user_data(user_data or get_session_user_data())
    session["active_profile"] = profile
    courses = course_cards_from_ai_recommendations(recommendations)

    return render_template(
        "result.html",
        courses=courses,
        stage=profile["stage"],
        profile=profile,
        career_analysis_enabled=profile["stage"] == "Degree",
    )


@app.route("/roadmap/<path:course>", methods=["GET", "POST"])
def roadmap(course):
    goal = (request.values.get("path_name") or urllib.parse.unquote(course)).strip()

    try:
        user_data = get_session_user_data()
        profile = profile_from_user_data(user_data)
        roadmap_payload = generate_roadmap(goal, user_data)
        recommendation_row = get_current_recommendation_row()
        recommendation_id = recommendation_row["id"] if recommendation_row else session.get("recommendation_id")

        if session.get("user_id"):
            mark_recommendation_selected_path(recommendation_id, goal)
            save_ai_roadmap(session["user_id"], recommendation_id, goal, roadmap_payload)

        adapted_roadmap = adapt_roadmap_for_template(goal, roadmap_payload, user_data)
        saved = get_saved_roadmap(session["user_id"], goal) if session.get("user_id") else None

        return render_template(
            "roadmap.html",
            course=goal,
            profile=profile,
            saved_roadmap=saved,
            saved_meta=serialize_saved_meta(saved),
            read_only=False,
            shared_view=False,
            initial_roadmap=adapted_roadmap,
            roadmap_data=roadmap_payload,
        )
    except Exception as error:
        print("GROQ ROADMAP ERROR:", error)
        flash("Our AI is temporarily unavailable. Please try again in a moment.", "error")
        return redirect("/dashboard")


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

    try:
        user_data = get_session_user_data()
        roadmap_payload = generate_roadmap(goal, user_data)
        recommendation_row = get_current_recommendation_row()
        recommendation_id = recommendation_row["id"] if recommendation_row else session.get("recommendation_id")

        if session.get("user_id"):
            mark_recommendation_selected_path(recommendation_id, goal)
            save_ai_roadmap(session["user_id"], recommendation_id, goal, roadmap_payload)

        adapted_roadmap = adapt_roadmap_for_template(goal, roadmap_payload, user_data)
        saved = get_saved_roadmap(session["user_id"], goal) if session.get("user_id") else None
        track_goal_choice_once(goal, profile_from_user_data(user_data))
        return jsonify({"roadmap": adapted_roadmap, "saved": serialize_saved_meta(saved)})
    except Exception as error:
        print("GROQ ROADMAP API ERROR:", error)
        return jsonify({"error": "Our AI is temporarily unavailable. Please try again in a moment."}), 503


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
def api_chat():
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or payload.get("question") or "").strip()
    path_context = (payload.get("path_context") or "").strip()

    if not path_context:
        context = payload.get("context") or {}
        if isinstance(context, dict):
            path_context = context.get("goal") or context.get("page") or ""
        else:
            path_context = str(context or "")

    if not message:
        return jsonify({"response": "Please send a message so I can help.", "status": "error"}), 400

    try:
        history = session.get("chat_history", [])
        history = [
            item
            for item in history
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ][-5:]
        messages = history + [{"role": "user", "content": message}]
        response = ai_chat(messages, path_context)
        session["chat_history"] = (messages + [{"role": "assistant", "content": response}])[-6:]
        return jsonify({"response": response, "status": "ok"})
    except Exception as error:
        print("GROQ CHAT ERROR:", error)
        return jsonify(
            {
                "response": "I'm having trouble connecting right now. Please try again.",
                "status": "error",
            }
        ), 503


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.errorhandler(404)
def page_not_found(_error):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=True)
