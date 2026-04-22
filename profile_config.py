PROFESSION_OPTIONS = [
    "Student",
    "Software Developer",
    "Data Analyst",
    "DevOps Engineer",
    "UI/UX Designer",
    "Digital Marketer",
    "Business Analyst",
    "Mechanical Engineer",
    "Civil Engineer",
    "Healthcare Worker",
    "Teacher/Educator",
    "Freelancer",
    "Entrepreneur",
    "Other",
]

EXPERIENCE_OPTIONS = [
    {"value": "0", "label": "0 (Fresher / Student)"},
    {"value": "0-1", "label": "0-1 years"},
    {"value": "1-3", "label": "1-3 years"},
    {"value": "3-5", "label": "3-5 years"},
    {"value": "5+", "label": "5+ years"},
]

STAGE_SPECIALIZATIONS = {
    "10th": [],
    "Intermediate": [
        {"value": "MPC", "label": "MPC"},
        {"value": "BiPC", "label": "BiPC"},
        {"value": "CEC", "label": "CEC"},
        {"value": "Other", "label": "Other"},
    ],
    "Degree": [
        {"value": "CSE/IT", "label": "CSE / IT"},
        {"value": "ECE/EEE", "label": "ECE / EEE"},
        {"value": "MBA", "label": "MBA"},
        {"value": "Commerce", "label": "Commerce"},
        {"value": "Arts/Humanities", "label": "Arts / Humanities"},
        {"value": "Other", "label": "Other"},
    ],
    "IIIT": [
        {"value": "Software", "label": "Software"},
        {"value": "Data/AI", "label": "Data / AI"},
        {"value": "Core Engineering", "label": "Core Engineering"},
        {"value": "Other", "label": "Other"},
    ],
}

STAGE_SKILL_PREFILLS = {
    "10th": {
        "default": [
            "Basic Mathematics",
            "English Communication",
            "Computer Basics",
            "Science Fundamentals",
        ]
    },
    "Intermediate": {
        "MPC": ["Mathematics", "Physics", "Programming Basics", "Problem Solving"],
        "BiPC": ["Biology", "Chemistry", "Data Entry", "Research Skills"],
        "CEC": ["Commerce", "Economics", "Accounting", "MS Excel"],
        "Other": ["Communication", "Foundational Reasoning", "Computer Basics", "MS Office"],
    },
    "Degree": {
        "CSE/IT": ["Python", "Java", "DSA", "HTML/CSS", "SQL", "Git"],
        "ECE/EEE": ["Circuit Design", "MATLAB", "Embedded C", "IoT"],
        "MBA": ["Business Strategy", "MS Excel", "Presentation Skills", "CRM Tools"],
        "Commerce": ["Tally", "Accounting", "MS Excel", "GST Knowledge"],
        "Arts/Humanities": ["Content Writing", "Research", "Communication", "MS Word"],
        "Other": ["Communication", "Presentation Skills", "Problem Solving", "Project Work"],
    },
    "IIIT": {
        "Software": ["JavaScript", "Python", "Git", "Problem Solving", "SQL"],
        "Data/AI": ["Python", "Statistics", "SQL", "Machine Learning", "Data Visualization"],
        "Core Engineering": ["Analytical Thinking", "Technical Communication", "Project Execution", "MS Excel"],
        "Other": ["Communication", "Problem Solving", "Digital Literacy", "Project Work"],
    },
}

PROFESSION_SKILL_PREFILLS = {
    "Student": ["Communication", "Problem Solving", "Learning Agility", "Teamwork"],
    "Software Developer": ["JavaScript", "Python", "Git", "REST APIs", "SQL"],
    "Data Analyst": ["Python", "SQL", "Excel", "Tableau", "Statistics"],
    "DevOps Engineer": ["Linux", "Docker", "Kubernetes", "CI/CD", "AWS", "Terraform"],
    "UI/UX Designer": ["Figma", "Adobe XD", "Wireframing", "User Research", "CSS"],
    "Digital Marketer": ["SEO", "Google Ads", "Social Media", "Analytics", "Canva"],
    "Business Analyst": ["SQL", "Excel", "Power BI", "Requirement Gathering", "JIRA"],
    "Mechanical Engineer": ["AutoCAD", "SolidWorks", "Manufacturing", "Quality Control", "Problem Solving"],
    "Civil Engineer": ["AutoCAD", "Site Planning", "Project Estimation", "Structural Analysis", "MS Excel"],
    "Healthcare Worker": ["Patient Care", "Clinical Documentation", "Communication", "Data Entry", "Compliance"],
    "Teacher/Educator": ["Communication", "Curriculum Design", "Presentation Skills", "Assessment Planning", "MS PowerPoint"],
    "Freelancer": ["Client Communication", "Time Management", "Proposal Writing", "Personal Branding", "Canva"],
    "Entrepreneur": ["Business Strategy", "Sales", "Marketing", "Financial Planning", "Pitching"],
    "Other": ["Communication", "Problem Solving", "Digital Tools", "Adaptability"],
}


def get_profile_form_config():
    return {
        "professionOptions": PROFESSION_OPTIONS,
        "experienceOptions": EXPERIENCE_OPTIONS,
        "stageSpecializations": STAGE_SPECIALIZATIONS,
        "stageSkillPrefills": STAGE_SKILL_PREFILLS,
        "professionSkillPrefills": PROFESSION_SKILL_PREFILLS,
    }


def default_profile():
    return {
        "stage": "",
        "profession": "Student",
        "experience": "0",
        "current_role": "",
        "specialization": "",
        "subjects": "",
        "skills": [],
    }
