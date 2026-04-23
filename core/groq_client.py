from groq import Groq
import os, json, time

client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
MODEL = "llama3-70b-8192"

def safe_groq(func, *args, retries=2, **kwargs):
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == retries - 1:
                raise Exception(f"Groq API failed after {retries} attempts: {str(e)}")
            time.sleep(1.5)

def analyze_profile(user_data: dict) -> dict:
    prompt = f"""You are a career counselor AI. Analyze this student profile and return ONLY a valid JSON object with no extra text or markdown.

Profile:
- Education Stage: {user_data.get('stage', 'Not specified')}
- Stream/Subjects: {user_data.get('subjects', 'Not specified')}
- Interests: {user_data.get('interests', 'Not specified')}
- Strengths: {user_data.get('strengths', 'Not specified')}
- Career Goal: {user_data.get('goal', 'Not specified')}

Return this exact JSON structure:
{{
  "archetypes": ["archetype1", "archetype2", "archetype3"],
  "skill_gaps": ["gap1", "gap2", "gap3"],
  "hidden_strengths": ["strength1", "strength2"],
  "personality_fit": "one sentence description",
  "market_outlook": "one sentence about market opportunity"
}}"""
    def call():
        r = client.chat.completions.create(model=MODEL, messages=[{"role":"user","content":prompt}], temperature=0.3, max_tokens=600)
        return json.loads(r.choices[0].message.content.strip())
    return safe_groq(call)

def generate_recommendations(profile_analysis: dict, user_data: dict) -> list:
    prompt = f"""You are a career recommendation AI. Generate exactly 5 ranked career paths for this student. Return ONLY a valid JSON array with no extra text or markdown.

Student Profile: {json.dumps(user_data)}
Profile Analysis: {json.dumps(profile_analysis)}

Return a JSON array of exactly 5 objects, each with this structure:
{{
  "rank": 1,
  "path_name": "Full Stack Web Development",
  "match_score": 92,
  "fit_reasons": ["reason one", "reason two", "reason three"],
  "tradeoffs": ["tradeoff one", "tradeoff two"],
  "salary_range": "4L - 18L per year",
  "growth_outlook": "High",
  "top_skills_needed": ["skill1", "skill2", "skill3"],
  "time_to_job_ready": "8-12 months",
  "job_titles": ["Junior Developer", "Frontend Engineer", "Full Stack Developer"]
}}

Sort by match_score descending. Make each path genuinely unique. Base recommendations on the actual profile provided."""
    def call():
        r = client.chat.completions.create(model=MODEL, messages=[{"role":"user","content":prompt}], temperature=0.4, max_tokens=2000)
        text = r.choices[0].message.content.strip()
        start = text.find('[')
        end = text.rfind(']') + 1
        return json.loads(text[start:end])
    return safe_groq(call)

def generate_roadmap(path_name: str, user_data: dict) -> dict:
    prompt = f"""You are a learning roadmap expert. Generate a detailed 12-month roadmap for: {path_name}
Student context: {json.dumps(user_data)}

Return ONLY a valid JSON object with no extra text or markdown:
{{
  "path_name": "{path_name}",
  "total_duration": "12 months",
  "phases": [
    {{
      "phase": 1,
      "title": "Foundations",
      "duration": "Months 1-3",
      "goal": "what this phase achieves",
      "topics": ["topic1", "topic2", "topic3", "topic4"],
      "resources": ["Free resource name 1", "Free resource name 2"],
      "project": "specific mini project idea",
      "milestone": "what you can build/do at end of this phase"
    }},
    {{
      "phase": 2,
      "title": "Core Skills",
      "duration": "Months 4-6",
      "goal": "what this phase achieves",
      "topics": ["topic1", "topic2", "topic3"],
      "resources": ["resource1", "resource2"],
      "project": "intermediate project idea",
      "milestone": "milestone description"
    }},
    {{
      "phase": 3,
      "title": "Build & Portfolio",
      "duration": "Months 7-9",
      "goal": "what this phase achieves",
      "topics": ["topic1", "topic2", "topic3"],
      "resources": ["resource1", "resource2"],
      "project": "portfolio-worthy project",
      "milestone": "milestone description"
    }},
    {{
      "phase": 4,
      "title": "Job Ready",
      "duration": "Months 10-12",
      "goal": "land first job",
      "topics": ["interview prep", "DSA basics", "resume building", "LinkedIn optimization"],
      "resources": ["resource1", "resource2"],
      "project": "final capstone project",
      "milestone": "ready to apply for entry level roles"
    }}
  ],
  "certifications": ["cert1", "cert2"],
  "first_job_titles": ["title1", "title2", "title3"]
}}"""
    def call():
        r = client.chat.completions.create(model=MODEL, messages=[{"role":"user","content":prompt}], temperature=0.4, max_tokens=2500)
        text = r.choices[0].message.content.strip()
        start = text.find('{')
        end = text.rfind('}') + 1
        return json.loads(text[start:end])
    return safe_groq(call)

def ai_chat(messages: list, path_context: str = "") -> str:
    system = f"""You are PathFinder AI, a helpful and concise career advisor for Indian students. You help with course selection, career paths, and learning roadmaps. Be warm, practical, and specific. Use Indian job market salary ranges and company names where relevant.{' Context: Student is exploring ' + path_context if path_context else ''}"""
    def call():
        r = client.chat.completions.create(model=MODEL, messages=[{"role":"system","content":system}] + messages, temperature=0.6, max_tokens=500)
        return r.choices[0].message.content
    return safe_groq(call)
