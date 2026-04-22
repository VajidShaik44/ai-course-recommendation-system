import csv
import json
import os
import sqlite3
import uuid

from werkzeug.security import generate_password_hash


def _load_seed_courses():
    seed_courses = []
    csv_path = "courses.csv"

    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                course = (row.get("course") or "").strip()
                level = (row.get("level") or "General").strip() or "General"
                skills = (row.get("skills") or "").strip()

                if not course:
                    continue

                description = f"Recommended learning path for {course}"
                seed_courses.append((course, level, description, skills))

    return seed_courses


def _ensure_columns(cursor, table_name, expected_columns):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = {column[1] for column in cursor.fetchall()}

    for column_name, column_type in expected_columns.items():
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _safe_load_json(value, default_value):
    if not value:
        return default_value

    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default_value


def _serialize_profile(profile):
    return json.dumps(profile or {}, ensure_ascii=True)


def _serialize_skills(skills):
    return json.dumps(skills or [], ensure_ascii=True)


def init_db():
    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            is_admin INTEGER DEFAULT 0
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS courses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course TEXT,
            level TEXT,
            description TEXT,
            skills TEXT
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            skills TEXT,
            stage TEXT DEFAULT 'unknown',
            course_id INTEGER,
            score REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            profession TEXT DEFAULT '',
            experience TEXT DEFAULT '',
            current_role TEXT DEFAULT '',
            specialization TEXT DEFAULT '',
            subjects TEXT DEFAULT '',
            skill_tags TEXT DEFAULT '[]',
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
        """
    )

    _ensure_columns(
        c,
        "recommendations",
        {
            "stage": "TEXT DEFAULT 'unknown'",
            "profession": "TEXT DEFAULT ''",
            "experience": "TEXT DEFAULT ''",
            "current_role": "TEXT DEFAULT ''",
            "specialization": "TEXT DEFAULT ''",
            "subjects": "TEXT DEFAULT ''",
            "skill_tags": "TEXT DEFAULT '[]'",
        },
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            stage TEXT DEFAULT '',
            profession TEXT DEFAULT 'Student',
            experience TEXT DEFAULT '0',
            current_role TEXT DEFAULT '',
            specialization TEXT DEFAULT '',
            subjects TEXT DEFAULT '',
            skill_tags TEXT DEFAULT '[]',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_roadmaps(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            goal TEXT,
            roadmap_json TEXT,
            profile_snapshot TEXT,
            share_token TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, goal),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS roadmap_phase_progress(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            saved_roadmap_id INTEGER,
            phase_number INTEGER,
            completed INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(saved_roadmap_id, phase_number),
            FOREIGN KEY (saved_roadmap_id) REFERENCES saved_roadmaps(id)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS anonymous_choice_stats(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_key TEXT,
            goal TEXT,
            choice_count INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(profile_key, goal)
        )
        """
    )

    c.execute("SELECT * FROM users WHERE username = 'admin'")
    admin_user = c.fetchone()

    if not admin_user:
        c.execute(
            "INSERT INTO users(username, password, is_admin) VALUES(?,?,?)",
            ("admin", generate_password_hash("admin123"), 1),
        )

    c.execute("SELECT course FROM courses")
    existing_courses = {row[0].strip().lower() for row in c.fetchall()}

    seed_courses = _load_seed_courses()
    if not seed_courses:
        seed_courses = [
            ("Python Programming", "Beginner", "Learn Python from scratch", "python programming"),
            ("Advanced Python", "Advanced", "Master advanced Python concepts", "python oops"),
            ("Machine Learning", "Intermediate", "Introduction to ML algorithms", "machine learning python"),
            ("Data Science", "Intermediate", "Data analysis and visualization", "python data analysis"),
            ("Web Development", "Beginner", "Build websites with HTML CSS JS", "html css javascript"),
            ("React JS", "Intermediate", "Modern frontend framework", "javascript react"),
            ("SQL Database", "Beginner", "Learn database management", "sql database"),
            ("Deep Learning", "Advanced", "Neural networks and AI", "deep learning python tensorflow"),
            ("Data Structures", "Intermediate", "Algorithms and data structures", "algorithms data structures"),
            ("Cloud Computing", "Intermediate", "AWS and cloud services", "aws cloud"),
            ("DevOps", "Intermediate", "CI/CD and automation", "devops docker kubernetes"),
            ("Mobile Development", "Intermediate", "Build Android apps", "android java kotlin"),
            ("Blockchain", "Advanced", "Cryptocurrency and smart contracts", "blockchain solidity"),
            ("Cybersecurity", "Intermediate", "Network security fundamentals", "security networking"),
            ("Artificial Intelligence", "Advanced", "AI and cognitive computing", "ai machine learning"),
        ]

    courses_to_insert = [
        course for course in seed_courses
        if course[0].strip().lower() not in existing_courses
    ]

    if courses_to_insert:
        c.executemany(
            "INSERT INTO courses(course, level, description, skills) VALUES(?,?,?,?)",
            courses_to_insert,
        )

    conn.commit()
    conn.close()


def get_db_connection():
    conn = sqlite3.connect("students.db")
    conn.row_factory = sqlite3.Row
    return conn


def get_all_courses():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM courses ORDER BY course ASC")
    courses = c.fetchall()
    conn.close()
    return courses


def add_course(course, level, description, skills):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO courses(course, level, description, skills) VALUES(?,?,?,?)",
        (course, level, description, skills),
    )
    conn.commit()
    conn.close()


def delete_course(course_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM courses WHERE id=?", (course_id,))
    conn.commit()
    conn.close()


def get_all_users():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE is_admin = 0 ORDER BY username ASC")
    users = c.fetchall()
    conn.close()
    return users


def get_all_recommendations():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT r.id, u.username, r.skills, r.stage, c.course, r.score, r.created_at,
               r.profession, r.experience
        FROM recommendations r
        JOIN users u ON r.user_id = u.id
        JOIN courses c ON r.course_id = c.id
        ORDER BY r.created_at DESC
        """
    )
    recommendations = c.fetchall()
    conn.close()
    return recommendations


def save_recommendation(user_id, input_text, course_id, score, profile=None):
    profile = profile or {}
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO recommendations(
            user_id, skills, stage, course_id, score, profession, experience,
            current_role, specialization, subjects, skill_tags
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            user_id,
            input_text,
            profile.get("stage", "unknown"),
            course_id,
            score,
            profile.get("profession", ""),
            profile.get("experience", ""),
            profile.get("current_role", ""),
            profile.get("specialization", ""),
            profile.get("subjects", ""),
            _serialize_skills(profile.get("skills", [])),
        ),
    )
    conn.commit()
    conn.close()


def get_course_id_by_name(course_name):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM courses WHERE lower(course) = lower(?) LIMIT 1", (course_name,))
    row = c.fetchone()
    conn.close()
    return row["id"] if row else None


def get_stats():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM users WHERE is_admin = 0")
    users_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM recommendations")
    rec_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM courses")
    courses_count = c.fetchone()[0]

    conn.close()
    return users_count, rec_count, courses_count


def get_user_recommendations(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT r.id, r.skills, r.stage, c.course, c.level, r.score, r.created_at,
               r.profession, r.experience
        FROM recommendations r
        JOIN courses c ON r.course_id = c.id
        WHERE r.user_id = ?
        ORDER BY r.created_at DESC
        LIMIT 30
        """,
        (user_id,),
    )
    recs = c.fetchall()
    conn.close()
    return recs


def upsert_user_profile(user_id, profile):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO user_profiles(
            user_id, stage, profession, experience, current_role,
            specialization, subjects, skill_tags, updated_at
        )
        VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            stage = excluded.stage,
            profession = excluded.profession,
            experience = excluded.experience,
            current_role = excluded.current_role,
            specialization = excluded.specialization,
            subjects = excluded.subjects,
            skill_tags = excluded.skill_tags,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            user_id,
            profile.get("stage", ""),
            profile.get("profession", "Student"),
            profile.get("experience", "0"),
            profile.get("current_role", ""),
            profile.get("specialization", ""),
            profile.get("subjects", ""),
            _serialize_skills(profile.get("skills", [])),
        ),
    )
    conn.commit()
    conn.close()


def get_user_profile(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "stage": row["stage"] or "",
        "profession": row["profession"] or "Student",
        "experience": row["experience"] or "0",
        "current_role": row["current_role"] or "",
        "specialization": row["specialization"] or "",
        "subjects": row["subjects"] or "",
        "skills": _safe_load_json(row["skill_tags"], []),
        "updated_at": row["updated_at"],
    }


def record_goal_choice(profile_key, goal):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO anonymous_choice_stats(profile_key, goal, choice_count, updated_at)
        VALUES(?,?,1,CURRENT_TIMESTAMP)
        ON CONFLICT(profile_key, goal) DO UPDATE SET
            choice_count = anonymous_choice_stats.choice_count + 1,
            updated_at = CURRENT_TIMESTAMP
        """,
        (profile_key, goal),
    )
    conn.commit()
    conn.close()


def get_peer_goal_stats(profile_key, goals):
    if not profile_key or not goals:
        return {}

    placeholders = ",".join("?" for _ in goals)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        f"""
        SELECT goal, choice_count
        FROM anonymous_choice_stats
        WHERE profile_key = ? AND goal IN ({placeholders})
        """,
        [profile_key, *goals],
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        return {}

    total = sum(row["choice_count"] for row in rows)
    if total == 0:
        return {}

    return {
        row["goal"]: round((row["choice_count"] / total) * 100)
        for row in rows
    }


def _get_completed_phase_map(cursor, saved_roadmap_id):
    cursor.execute(
        """
        SELECT phase_number, completed
        FROM roadmap_phase_progress
        WHERE saved_roadmap_id = ?
        """,
        (saved_roadmap_id,),
    )
    return {row["phase_number"]: bool(row["completed"]) for row in cursor.fetchall()}


def _hydrate_saved_roadmap(row, cursor):
    if not row:
        return None

    roadmap_data = _safe_load_json(row["roadmap_json"], {})
    profile_snapshot = _safe_load_json(row["profile_snapshot"], {})
    completed_map = _get_completed_phase_map(cursor, row["id"])
    roadmap_phases = roadmap_data.get("roadmap", [])

    completed_phases = [
        phase.get("phase", index + 1)
        for index, phase in enumerate(roadmap_phases)
        if completed_map.get(phase.get("phase", index + 1))
    ]
    total_phases = len(roadmap_phases)
    progress_percent = round((len(completed_phases) / total_phases) * 100) if total_phases else 0

    return {
        "id": row["id"],
        "goal": row["goal"],
        "roadmap": roadmap_data,
        "profile_snapshot": profile_snapshot,
        "share_token": row["share_token"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_phases": completed_phases,
        "progress_percent": progress_percent,
    }


def get_saved_roadmap(user_id, goal):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT *
        FROM saved_roadmaps
        WHERE user_id = ? AND goal = ?
        LIMIT 1
        """,
        (user_id, goal),
    )
    row = c.fetchone()
    roadmap = _hydrate_saved_roadmap(row, c)
    conn.close()
    return roadmap


def get_saved_roadmap_by_token(token):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT *
        FROM saved_roadmaps
        WHERE share_token = ?
        LIMIT 1
        """,
        (token,),
    )
    row = c.fetchone()
    roadmap = _hydrate_saved_roadmap(row, c)
    conn.close()
    return roadmap


def upsert_saved_roadmap(user_id, goal, roadmap_data, profile_snapshot):
    existing = get_saved_roadmap(user_id, goal)
    share_token = existing["share_token"] if existing else uuid.uuid4().hex[:12]

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO saved_roadmaps(
            user_id, goal, roadmap_json, profile_snapshot, share_token, updated_at
        )
        VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, goal) DO UPDATE SET
            roadmap_json = excluded.roadmap_json,
            profile_snapshot = excluded.profile_snapshot,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            user_id,
            goal,
            json.dumps(roadmap_data, ensure_ascii=True),
            _serialize_profile(profile_snapshot),
            share_token,
        ),
    )
    conn.commit()
    conn.close()

    return get_saved_roadmap(user_id, goal)


def set_phase_completion(saved_roadmap_id, phase_number, completed):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO roadmap_phase_progress(
            saved_roadmap_id, phase_number, completed, updated_at
        )
        VALUES(?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(saved_roadmap_id, phase_number) DO UPDATE SET
            completed = excluded.completed,
            updated_at = CURRENT_TIMESTAMP
        """,
        (saved_roadmap_id, phase_number, 1 if completed else 0),
    )
    conn.commit()
    conn.close()


def get_user_saved_roadmaps(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT *
        FROM saved_roadmaps
        WHERE user_id = ?
        ORDER BY updated_at DESC
        """,
        (user_id,),
    )
    rows = c.fetchall()
    saved = [_hydrate_saved_roadmap(row, c) for row in rows]
    conn.close()
    return saved
