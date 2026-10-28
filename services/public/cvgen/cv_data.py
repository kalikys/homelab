"""CV content in English and Slovak. Facts come from ../PROFILE.md; change them there first."""

CONTACTS = [
    ("kalikys@outlook.com", "mailto:kalikys@outlook.com"),
    ("Telegram @kalikys", "https://t.me/kalikys"),
    ("LinkedIn", "https://www.linkedin.com/in/devops-kalislav-smirnov/"),
    ("GitHub", "https://github.com/kalikys"),
    ("kalik8s.com", "https://kalik8s.com/?utm_source=cv&utm_medium=pdf"),
]

SKILLS_TAGS = {
    "platform": "Kubernetes, Helm, Docker, Linux, Proxmox, ZFS, disaster recovery",
    "ai": "Claude API, MCP servers, RAG (embeddings + reranker), agent orchestration, Claude Code, Python",
    "iac": "Ansible, Terraform, Python, Bash",
    "cicd": "GitLab CI, GitLab, Jenkins, Nexus, Git",
    "obs": "Prometheus, Grafana, Alertmanager, ELK, Loki, OpenTelemetry",
    "data": "PostgreSQL, ClickHouse, RabbitMQ, Airflow",
    "sec": "SAST, DAST, SCA, Semgrep, Trivy, GPG",
    "eng": "SolidWorks, KOMPAS-3D, ANSYS, MATLAB, Simulink",
}

EN = {
    "lang": "en",
    "stack_label": "Stack",
    "title": "Kalislav Smirnov, CV",
    "role": "DevOps Engineer · Aerospace Engineer",
    "location": "Tbilisi, Georgia (GMT+4) · remote, any country · relocation: US, EU, Cyprus",
    "h": {"summary": "Summary", "exp": "Experience", "agents": "AI agents and automation",
          "aero": "Aerospace engineering", "lab": "Homelab", "skills": "Skills", "lang": "Languages"},
    "summary": [
        "Engineer with two backgrounds. For 4.5 years I have built and run on-prem platforms for banks and government "
        "agencies, including fully air-gapped networks: HA GitLab, Nexus and PostgreSQL clusters automated with Ansible, "
        "Kubernetes across several data centers, 5 end-to-end platform implementations. At a bank I cut edge-device setup "
        "from 10 hours to 20 minutes.",
        "Alongside that work I completed an integrated Master's degree in spacecraft engineering at Bauman Moscow State "
        "Technical University (thesis: a suborbital spaceplane for intercontinental flights).",
        "I am looking for a long-term role, remote with a company in any country or with relocation to the US, the EU or Cyprus: DevOps or platform engineering, "
        "or engineering where software meets physical systems (automotive, manufacturing, space).",
    ],
    "jobs": [
        {
            "role": "DevSecOps Engineer", "company": "Swordfish Security", "type": "Full-time",
            "period": "Feb 2025 – Aug 2026",
            "intro": "Deployed and maintained DevSecOps platforms for enterprise clients in banking, fintech and "
                     "government, including fully air-gapped environments.",
            "points": [
                "Led 5 end-to-end platform implementations for banking and government clients, from architecture design to handover.",
                "Deployed highly available GitLab clusters, plus Nexus and PostgreSQL clusters, fully automated with Ansible, and kept them running.",
                "Built a GPG-signed package delivery service (Python, Kubernetes) for a major bank's air-gapped Nexus repository.",
                "Integrated SAST, DAST and SCA tools (Semgrep, Trivy) into GitLab CI: security scans on 100% of new commits.",
                "Wrote 15+ reusable Ansible roles that standardized deployments across clients (about 30% faster setup of new projects).",
                "Designed and ran multi-datacenter Kubernetes platforms (100+ VMs) with disaster recovery for financial systems.",
                "Ran product demonstrations and acceptance testing (Nexus, GitLab, DevSecOps products).",
            ],
            "stack": "Docker, Kubernetes, Helm, Ansible, GitLab CI, Nexus, PostgreSQL, Python, Bash, Linux, SAST/DAST/SCA",
        },
        {
            "role": "DevOps Engineer", "company": "Sinara Investment Bank", "type": "",
            "period": "Oct 2024 – Feb 2025", "intro": "",
            "points": [
                "Automated edge-device (mini-PC) deployment with Ansible and scripts: from 10 hours to 20 minutes per device.",
                "Led the first migration of a core monolith to 10 containerized microservices on Kubernetes, with a Helm chart for each.",
                "Built monitoring and alerting from scratch with Prometheus, Grafana and ELK.",
            ],
            "stack": "Kubernetes, Helm, GitLab CI, Python, ELK, Airflow, ClickHouse, PostgreSQL, RabbitMQ",
        },
        {
            "role": "DevOps Engineer", "company": "Engineering & Manufacturing Company", "type": "",
            "period": "Apr 2022 – Oct 2024", "intro": "",
            "points": [
                "Rebuilt CI/CD in GitLab CI: release cycle for 20+ microservices from 2 weeks to 3 days.",
                "Automated deployment checklists with Ansible and Bash: from 4+ hours to under 30 minutes per release.",
                "Containerized 20+ legacy Java services with Docker and ran 50+ Linux servers in two data centers.",
            ],
            "stack": "Docker, Terraform, GitLab CI, Python, Linux",
        },
    ],
    "degree": "Integrated Master's degree (Specialist, Engineer)",
    "degree_note": "Bauman Moscow State Technical University · 2020 – 2026 · full-time, 6-year programme, 360 ECTS, "
                   "equivalent to a Bachelor's plus a Master's",
    "field": "Design, Production and Operation of Rockets and Rocket-Space Systems. "
             "Specialization: crewed and uncrewed spacecraft and systems.",
    "aero_points": [
        "Thesis: Suborbital spaceplane for intercontinental commercial flights (graded excellent).",
        "3D models and design drawings of spacecraft structures and assemblies.",
        "Strength, vibration and dynamics calculations for spacecraft structures.",
        "Aerodynamics and gas dynamics, flight theory and ballistics, propulsion systems; modelling of automatic control and stabilization.",
        "Research work and a research-and-production internship, both graded excellent.",
    ],
    "aero_tools": "Tools: SolidWorks, KOMPAS-3D, ANSYS, MATLAB, Simulink",
    "lab": [
        "Proxmox VE on ZFS managed with Terraform: LXC containers, VMs and a Kubernetes cluster for practice.",
        "Hosts my own production projects: a macOS app's API server and a 12-microservice Python platform with "
        "Prometheus, Grafana, Loki, Tempo and OpenTelemetry. My CV site runs on it.",
    ],
    "agents": [
        ("Autonomous “AI employee” in GitLab",
         "Runs Claude Code as a sandboxed worker (bubblewrap and a custom AppArmor profile, shell with no "
         "network access) under a dedicated GitLab service account: it picks up labelled issues, proposes a "
         "plan, works in the repo and writes to the team knowledge base only after human approval. The agent "
         "and the team work through a custom MCP server I built (Python, OAuth) that exposes tasks, threads, "
         "decisions and the knowledge base, two-way-synced with GitLab issues. Per-run time and budget caps; "
         "it calls a human after repeated failures."),
        ("RAG document-automation service",
         "Remote MCP service (Python, FastAPI, OAuth 2.1 over Streamable HTTP) with retrieval over a curated "
         "knowledge base: local BGE-M3 embeddings and a reranker served on my own GPU, a PII-anonymization "
         "stage and an output guard (n-gram and embedding similarity, canary markers, a judge model) so source "
         "material never leaks."),
        ("LLM risk guard over a trading bot",
         "A Claude news-and-risk gate wraps a Freqtrade bot in paper mode: every 30 minutes it reads market "
         "and news feeds and can throttle or stop trading, with a weekly self-review. Research only, no real funds."),
        ("Agent orchestration dashboard",
         "Self-hosted tracker (FastAPI, SQLite, React) where my agents log work, decisions and findings across "
         "sessions, wired in through a CLI and a session-end hook so long-running projects keep context between runs."),
        ("Telegram security bots",
         "Shipped bots with React Mini Apps: CVE alerts from the CISA KEV feed and a Kubernetes “cluster "
         "snapshot” that parses kubectl/helm output and returns affected CVEs with fix commands."),
    ],
    "skills": {
        "platform": "Platform", "ai": "AI and agents", "iac": "Automation and IaC", "cicd": "CI/CD",
        "obs": "Observability", "data": "Data and messaging", "sec": "Security in pipelines",
        "eng": "Engineering (CAD/CAE)",
    },
    "languages": "English B2 · Russian native",
}

SK = {
    "lang": "sk",
    "stack_label": "Technológie",
    "title": "Kalislav Smirnov, životopis",
    "role": "DevOps inžinier · inžinier kozmickej techniky",
    "location": "Tbilisi, Gruzínsko (GMT+4) · na diaľku, akákoľvek krajina · relokácia: USA, EÚ, Cyprus",
    "h": {"summary": "Profil", "exp": "Pracovné skúsenosti", "agents": "AI agenti a automatizácia",
          "aero": "Kozmická technika", "lab": "Homelab", "skills": "Zručnosti", "lang": "Jazyky"},
    "summary": [
        "Inžinier s dvoma odbornosťami. 4,5 roka staviam a prevádzkujem on-prem platformy pre banky a štátne inštitúcie, "
        "vrátane úplne izolovaných sietí: HA klastre GitLab, Nexus a PostgreSQL automatizované cez Ansible, Kubernetes "
        "vo viacerých dátových centrách, 5 kompletných implementácií platforiem. V banke som skrátil nastavenie edge "
        "zariadení z 10 hodín na 20 minút.",
        "Popri práci som dokončil integrovaný inžiniersky titul v odbore kozmická technika na Moskovskej štátnej "
        "technickej univerzite N. E. Baumana (diplomová práca: suborbitálny raketoplán na medzikontinentálne lety).",
        "Hľadám dlhodobú prácu na diaľku pre firmu z akejkoľvek krajiny alebo s relokáciou do USA, EÚ či na Cyprus: DevOps alebo platform engineering, prípadne "
        "inžiniersku pozíciu, kde sa stretáva softvér s fyzickými systémami (automotive, výroba, kozmonautika).",
    ],
    "jobs": [
        {
            "role": "DevSecOps inžinier", "company": "Swordfish Security", "type": "Plný úväzok",
            "period": "02/2025 – 08/2026",
            "intro": "Nasadzovanie a prevádzka DevSecOps platforiem pre firemných klientov z bankovníctva, fintechu "
                     "a štátneho sektora, vrátane úplne izolovaných prostredí.",
            "points": [
                "Viedol som 5 kompletných implementácií platforiem pre banky a štátne inštitúcie, od návrhu architektúry po odovzdanie.",
                "Nasadil som vysoko dostupné klastre GitLab, Nexus a PostgreSQL plne automatizované cez Ansible a staral sa o ich prevádzku.",
                "Postavil som službu na dodávku balíčkov podpísaných cez GPG (Python, Kubernetes) do izolovaného repozitára Nexus veľkej banky.",
                "Integroval som nástroje SAST, DAST a SCA (Semgrep, Trivy) do GitLab CI: kontroluje sa 100 % nových commitov.",
                "Vytvoril som 15+ opakovane použiteľných Ansible rolí, ktoré zjednotili nasadenia u klientov (príprava nových projektov asi o 30 % rýchlejšia).",
                "Navrhoval a prevádzkoval som platformy Kubernetes vo viacerých dátových centrách (100+ VM) s plánom obnovy po havárii pre finančné systémy.",
                "Viedol som produktové ukážky a akceptačné testy (Nexus, GitLab, DevSecOps produkty).",
            ],
            "stack": "Docker, Kubernetes, Helm, Ansible, GitLab CI, Nexus, PostgreSQL, Python, Bash, Linux, SAST/DAST/SCA",
        },
        {
            "role": "DevOps inžinier", "company": "Sinara Investment Bank", "type": "",
            "period": "10/2024 – 02/2025", "intro": "",
            "points": [
                "Automatizoval som nasadenie edge zariadení (mini-PC) cez Ansible a skripty: z 10 hodín na 20 minút na zariadenie.",
                "Viedol som prvú migráciu hlavného monolitu na 10 kontajnerizovaných mikroslužieb v Kubernetes, s Helm chartom pre každú.",
                "Od nuly som postavil monitoring a alerting s Prometheus, Grafana a ELK.",
            ],
            "stack": "Kubernetes, Helm, GitLab CI, Python, ELK, Airflow, ClickHouse, PostgreSQL, RabbitMQ",
        },
        {
            "role": "DevOps inžinier", "company": "Strojárska a výrobná spoločnosť", "type": "",
            "period": "04/2022 – 10/2024", "intro": "",
            "points": [
                "Prerobil som CI/CD v GitLab CI: cyklus vydávania pre 20+ mikroslužieb z 2 týždňov na 3 dni.",
                "Automatizoval som checklisty nasadenia cez Ansible a Bash: z viac ako 4 hodín na menej ako 30 minút na vydanie.",
                "Kontajnerizoval som 20+ starších služieb v Jave cez Docker a spravoval 50+ linuxových serverov v dvoch dátových centrách.",
            ],
            "stack": "Docker, Terraform, GitLab CI, Python, Linux",
        },
    ],
    "degree": "Integrovaný inžiniersky titul (špecialista, inžinier)",
    "degree_note": "Moskovská štátna technická univerzita N. E. Baumana · 2020 – 2026 · denné štúdium, 6-ročný program, "
                   "360 ECTS, zodpovedá bakalárskemu a magisterskému štúdiu spolu",
    "field": "Projektovanie, výroba a prevádzka rakiet a raketovo-kozmických komplexov. "
             "Špecializácia: pilotované a automatické kozmické lode a systémy.",
    "aero_points": [
        "Diplomová práca: Suborbitálny raketoplán na medzikontinentálne komerčné lety (hodnotenie výborne).",
        "3D modely a výkresová dokumentácia konštrukcií a zostáv kozmických lodí.",
        "Výpočty pevnosti, kmitania a dynamiky konštrukcií kozmických lodí.",
        "Aerodynamika a dynamika plynov, teória letu a balistika, pohonné jednotky; modelovanie automatického riadenia a stabilizácie.",
        "Výskumná práca a výskumno-výrobná prax, obe hodnotené výborne.",
    ],
    "aero_tools": "Nástroje: SolidWorks, KOMPAS-3D, ANSYS, MATLAB, Simulink",
    "lab": [
        "Proxmox VE na ZFS spravovaný cez Terraform: LXC kontajnery, VM a klaster Kubernetes na tréning.",
        "Bežia na ňom moje vlastné produkčné projekty: API server pre aplikáciu na macOS a Python platforma "
        "s 12 mikroslužbami a monitoringom (Prometheus, Grafana, Loki, Tempo, OpenTelemetry).",
    ],
    "agents": [
        ("Autonómny „AI zamestnanec“ v GitLabe",
         "Spúšťa Claude Code ako izolovaného workera (bubblewrap a vlastný AppArmor profil) pod vyhradeným "
         "servisným účtom GitLabu: preberá označené úlohy, navrhne plán, pracuje v repozitári a do bázy znalostí "
         "zapíše až po schválení človekom. Agent aj tím pracujú cez vlastný MCP server (Python, OAuth) pre úlohy, "
         "vlákna, rozhodnutia a bázu znalostí, obojsmerne zosynchronizovaný s GitLab issues. Limity času a "
         "rozpočtu, po opakovaných zlyhaniach volá človeka."),
        ("Služba na tvorbu dokumentov s RAG",
         "Remote MCP služba (Python, FastAPI, OAuth 2.1) s vyhľadávaním nad kurovanou bázou znalostí: lokálne "
         "embeddingy BGE-M3 a reranker na mojom GPU, anonymizácia osobných údajov a strážca výstupu (podobnosť "
         "n-gramov a embeddingov, canary značky, model-sudca), aby zdrojové materiály neunikli."),
        ("LLM strážca rizika nad obchodným botom",
         "Novinový a rizikový filter na báze Claude obaľuje bot Freqtrade v paper režime: každých 30 minút číta "
         "trhové a spravodajské zdroje a vie obmedziť či zastaviť obchodovanie. Len výskum, bez reálnych peňazí."),
        ("Dashboard na orchestráciu agentov",
         "Vlastný tracker (FastAPI, SQLite, React), kam moji agenti zapisujú prácu, rozhodnutia a zistenia "
         "naprieč sedeniami cez CLI a session-end hook, aby dlhé projekty udržali kontext."),
        ("Telegram bezpečnostné boty",
         "Boty s React Mini Apps: CVE upozornenia zo zdroja CISA KEV a „cluster snapshot“ pre Kubernetes "
         "(parsuje kubectl/helm a vráti dotknuté CVE s príkazmi na opravu)."),
    ],
    "skills": {
        "platform": "Platforma", "ai": "AI a agenti", "iac": "Automatizácia a IaC", "cicd": "CI/CD",
        "obs": "Monitoring", "data": "Dáta a správy", "sec": "Bezpečnosť v pipeline",
        "eng": "Inžinierstvo (CAD/CAE)",
    },
    "languages": "Angličtina B2 · ruština materinský jazyk",
}

# Engineering variant (2026-10-13): CAD / design / automation roles in Košice. Same facts, degree first.
ENG = {
    **EN,
    "title": "Kalislav Smirnov, CV (engineering)",
    "role": "Aerospace Engineer · Design and Automation",
    "edu_first": True,
    "h": {**EN["h"], "aero": "Education: aerospace engineering", "exp": "Experience: automation and software",
          "agents": "Automation and AI agents"},
    "agents": [
        ("Autonomous AI agents",
         "Built a sandboxed Claude-based worker that picks up tasks in GitLab, plans the work and edits code "
         "under strict guardrails (isolated sandbox, time and budget limits, human approval before anything "
         "is published)."),
        ("Document-automation service (RAG)",
         "A Python and FastAPI backend that retrieves from a knowledge base using local machine-learning models "
         "on a GPU and checks every answer with safety filters before it is returned."),
        ("Orchestration dashboard",
         "A self-hosted dashboard (Python, React) where the agents log their work across sessions, so "
         "long-running projects keep their history."),
    ],
    "summary": [
        "Engineer with an integrated Master's degree in spacecraft engineering from Bauman Moscow State Technical "
        "University (2026). Trained in 3D modelling and design drawings of structures and assemblies, strength, "
        "vibration and dynamics calculations, and modelling of control systems in SolidWorks, KOMPAS-3D, ANSYS, "
        "MATLAB and Simulink. Thesis: a suborbital spaceplane for intercontinental flights, graded excellent.",
        "Alongside my studies I worked 4.5 years in automation: I script equipment set-up and deployments in Python, "
        "Bash and Ansible (edge devices at a bank: from 10 hours to 20 minutes each) and run Linux systems in "
        "production, including 2.5 years at an engineering and manufacturing company.",
        "My family is moving to Košice. I am looking for a junior engineering role with room to grow: mechanical "
        "design and CAD, or industrial automation. I learn new tools fast.",
    ],
    "jobs": [
        {**EN["jobs"][0], "intro": "", "points": [
            "Led 5 end-to-end platform implementations for banks and government agencies, from design to handover and acceptance tests.",
            "Wrote 15+ reusable Ansible roles that standardized deployments across clients (about 30% faster setup of new projects).",
            "Ran product demonstrations and acceptance testing with clients.",
        ]},
        {**EN["jobs"][1], "points": [
            "Automated set-up of edge devices (mini-PCs) with Ansible and scripts: from 10 hours to 20 minutes per device.",
            "Built monitoring and alerting from scratch with Prometheus, Grafana and ELK.",
        ]},
        {**EN["jobs"][2], "points": [
            "Automated deployment checklists with Ansible and Bash: from 4+ hours to under 30 minutes per release.",
            "Ran 50+ Linux servers in two data centers; release cycle for 20+ services cut from 2 weeks to 3 days.",
        ]},
    ],
}

# Role variants served from /cv/ (2026-10-29). Same facts as EN; only the headline, the first summary
# paragraph and the order of the Swordfish bullets change. Indexes into EN["jobs"][0]["points"]:
# 0 platform implementations, 1 HA GitLab/Nexus/PostgreSQL, 2 GPG delivery, 3 SAST/DAST/SCA,
# 4 Ansible roles, 5 multi-datacenter Kubernetes, 6 demos and acceptance testing.
AGENTS_LINE = ("I also build and run AI agents on Claude: a sandboxed Claude Code worker in GitLab, my own MCP "
               "servers and a RAG service (details below).")


def _role(role, summary, order):
    job0 = {**EN["jobs"][0], "points": [EN["jobs"][0]["points"][i] for i in order]}
    return {**EN, "title": f"Kalislav Smirnov, CV ({role})", "role": role,
            "summary": [f"{summary} {AGENTS_LINE}", EN["summary"][2]], "jobs": [job0, *EN["jobs"][1:]]}


ROLE_CVS = {
    "Kalislav-Smirnov-DevOps": _role(
        "DevOps Engineer",
        "DevOps engineer focused on Kubernetes, GitLab CI/CD, Linux and infrastructure automation with Ansible and "
        "Terraform. Cut the release cycle for 20+ microservices from two weeks to three days and automated edge-device "
        "setup from ten hours to 20 minutes. Professional experience since April 2022.",
        [0, 4, 1, 5, 2, 3, 6]),
    "Kalislav-Smirnov-DevSecOps": _role(
        "DevSecOps Engineer",
        "DevSecOps engineer with five end-to-end platform implementations for banking and government clients. Built "
        "GPG-signed package delivery for an air-gapped Nexus repository and integrated SAST, DAST and SCA checks into "
        "GitLab CI. Combines security automation with Kubernetes operations and repeatable Ansible deployments.",
        [3, 2, 0, 4, 1, 5, 6]),
    "Kalislav-Smirnov-Platform-SRE": _role(
        "DevOps Engineer · Platform and SRE",
        "DevOps engineer with experience in platform engineering and site reliability: multi-datacenter Kubernetes "
        "platforms with 100+ VMs, disaster recovery, Helm-based deployments and observability with Prometheus, Grafana "
        "and ELK. Professional experience since April 2022, including financial and air-gapped environments.",
        [5, 1, 0, 4, 2, 3, 6]),
    "Kalislav-Smirnov-Master": _role(
        "DevOps and DevSecOps Engineer",
        "DevOps and DevSecOps engineer with professional experience since April 2022. Built Kubernetes platforms, "
        "GitLab CI/CD pipelines and infrastructure automation for banking, fintech and government environments, "
        "including air-gapped networks. Experience spans platform delivery, observability and security checks in CI/CD.",
        [0, 1, 2, 3, 4, 5, 6]),
}
