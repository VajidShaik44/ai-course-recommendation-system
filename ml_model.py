import pandas as pd
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# ---------------- TEXT CLEANING ---------------- #
def clean_text(text):
    if pd.isna(text):
        return ""
    text = text.lower()
    text = re.sub(r'[^a-zA-Z0-9\s]', '', text)
    return text


# ---------------- PREPARE DATA ---------------- #
def prepare_dataframe(df):
    # Combine all useful columns (IMPORTANT)
    df["combined"] = (
        df["course"].fillna('') + " " +
        df["skills"].fillna('') + " " +
        df["level"].fillna('')
    )

    df["combined"] = df["combined"].apply(clean_text)
    return df


# ---------------- VECTOR SIMILARITY ---------------- #
def compute_similarity(df, query):
    vectorizer = TfidfVectorizer(
        stop_words='english',
        ngram_range=(1, 2),   # improves matching
        min_df=1
    )

    tfidf_matrix = vectorizer.fit_transform(df["combined"])
    query_vector = vectorizer.transform([clean_text(query)])

    similarity = cosine_similarity(query_vector, tfidf_matrix)[0]

    df["score"] = similarity

    return df


# ---------------- STAGE-AWARE MODEL ---------------- #
def stage_aware_recommend(stage, stream_skills):
    df = pd.read_csv("courses.csv")

    # Stage filtering logic
    stage_map = {
        '10th': '10th-inter',
        'Intermediate': 'inter-degree',
        'IIIT': 'iiit-job-pg',
        'Degree': 'degree-pg-job'
    }

    level_filter = stage_map.get(stage, '')

    if level_filter:
        filtered_df = df[df['level'].str.contains(level_filter, na=False)]
    else:
        filtered_df = df

    if filtered_df.empty:
        filtered_df = df  # fallback if filter fails

    # Better query enrichment
    query = f"{stream_skills} {stage} career jobs skills technology development"

    # Prepare + compute similarity
    filtered_df = prepare_dataframe(filtered_df)
    filtered_df = compute_similarity(filtered_df, query)

    # 🔥 FIX: if all scores are zero
    if filtered_df["score"].sum() == 0:
        # instead of fake equal scores → random slight ranking
        import random
        filtered_df["score"] = [round(random.uniform(0.05, 0.15), 3) for _ in range(len(filtered_df))]

    # Return top results
    return filtered_df.sort_values(by="score", ascending=False).head(5)


# ---------------- GENERAL MODEL ---------------- #
def recommend_course(student_skills):
    df = pd.read_csv("courses.csv")

    query = f"{student_skills} career jobs skills technology"

    df = prepare_dataframe(df)
    df = compute_similarity(df, query)

    # 🔥 FIX zero scores
    if df["score"].sum() == 0:
        import random
        df["score"] = [round(random.uniform(0.05, 0.15), 3) for _ in range(len(df))]

    return df.sort_values(by="score", ascending=False).head(5)