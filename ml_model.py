import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def stage_aware_recommend(stage, stream_skills):
    import pandas as pd
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    
    df = pd.read_csv("courses.csv")
    
    # Stage to level filter mapping
    stage_map = {
        '10th': '10th-inter',
        'Intermediate': 'inter-degree',
        'IIIT': 'iiit-job-pg',
        'Degree': 'degree-pg-job'
    }
    
    level_filter = stage_map.get(stage, '')
    filtered_df = df[df['level'].str.contains(level_filter, na=False)] if level_filter else df
    
    if filtered_df.empty:
        filtered_df = df  # fallback
    
    # Enhance query with stage keywords
    query = f"{stream_skills} {stage} career path recommendation"
    
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(filtered_df["skills"])
    
    student_vector = vectorizer.transform([query])
    
    similarity = cosine_similarity(student_vector, tfidf_matrix)
    
    filtered_df.loc[:, "score"] = similarity[0]
    
    recommended = filtered_df.sort_values(by="score", ascending=False).head(5)

    
    return recommended

# Backward compatibility
def recommend_course(student_skills):
    return stage_aware_recommend('general', student_skills)
def recommend_course(student_skills):

    df = pd.read_csv("courses.csv")

    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(df["skills"])

    student_vector = vectorizer.transform([student_skills])

    similarity = cosine_similarity(student_vector, tfidf_matrix)

    df["score"] = similarity[0]

    recommended = df.sort_values(by="score", ascending=False)

    return recommended.head(3)