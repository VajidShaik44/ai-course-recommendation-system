# PathFinder AI

PathFinder AI is a Flask-based course and career recommendation platform that blends rule-aware shortlisting with Groq-powered AI guidance. It now supports richer profile collection, smarter skill suggestions, dynamic goal roadmaps, degree-level career-fit analysis, roadmap saving and progress tracking, anonymous peer insights, and a floating AI chat assistant.

## Core stack

- Backend: Flask
- Frontend: Jinja templates, vanilla JavaScript, shared CSS design system
- Database: SQLite
- Recommendation engine: Pandas + scikit-learn TF-IDF similarity
- AI provider: Groq `llama3-70b-8192` by default

## What is included now

- User authentication with login and registration
- Expanded profile form with:
  - education stage
  - profession
  - years of experience
  - current role / job title
  - specialization / stream
  - additional subjects
  - manual and suggested skill tags
- Dynamic skill prefills based on education stage and profession
- Personalized recommendation cards with:
  - why it fits
  - advantages
  - watch-outs
  - likely roles
  - upskill vs reskill guidance
  - transition note for experienced users
  - anonymous peer-comparison stats
- Dynamic AI roadmap page per goal with:
  - fresh Groq roadmap generation
  - session-scoped caching per user and goal
  - skill-gap analysis
  - phased roadmap cards
  - tools and technologies groups
  - job-role cards
  - certifications
  - daily study plan
  - resume keyword suggestions
  - copy roadmap and print-to-PDF actions
- Degree-only Career Fit Analysis section after recommendations
- Floating AI chat assistant with streaming responses
- Saved roadmaps with:
  - shareable read-only links
  - phase completion tracking
  - progress percentages on the profile page

## Database notes

The app currently uses SQLite through `students.db`. The schema now includes:

- `users`
- `courses`
- `recommendations`
- `user_profiles`
- `saved_roadmaps`
- `roadmap_phase_progress`
- `anonymous_choice_stats`

No PostgreSQL or MongoDB setup is required for local use because the existing app is built around SQLite.

## Environment variables

Set these before running the app:

```bash
SECRET_KEY=your-secret-key
GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=llama3-70b-8192
```

`GROQ_MODEL` is optional. If omitted, the app uses `llama3-70b-8192`.

## Local setup

```bash
git clone https://github.com/VajidShaik44/ai-course-recommendation-system.git
cd ai-course-recommendation-system
pip install -r requirements.txt
python app.py
```

If you prefer the existing batch launcher on Windows:

```bat
run.bat
```

## Main routes

- `/` - landing page
- `/login` - login
- `/register` - register
- `/dashboard` - recommendation workspace
- `/recommend` - profile submission and recommendation generation
- `/roadmap/<goal>` - personalized roadmap shell
- `/roadmap/share/<token>` - read-only shared roadmap
- `/profile` - recommendation history and saved roadmaps

### JSON and streaming routes

- `/api/roadmap/<goal>` - fetch roadmap JSON
- `/api/career-fit-analysis` - degree-level analysis
- `/api/roadmap/save` - save roadmap to profile
- `/api/roadmap/progress` - update phase completion
- `/api/chat` - streaming AI assistant response

## AI behavior

- Recommendation cards and roadmap generation use Groq with system + user prompts.
- Roadmaps are personalized with education stage, profession, experience, current role, specialization, subjects, and selected skills.
- Degree-level career-fit analysis is generated separately from the roadmap.
- If Groq is unavailable, the app falls back to structured non-breaking default content so the UI still works.

## Mobile and UI

- The UI uses a shared premium design system across landing, dashboard, results, roadmap, profile, auth, and admin templates.
- New AI sections include loading skeletons and responsive layouts tuned for small screens.

## Project files

```text
app.py
database.py
ml_model.py
profile_config.py
courses.csv
jobs.csv
static/
templates/
```

## Deployment

This app can be deployed on Render, Railway, or any Python hosting platform that supports Flask and SQLite-backed storage.
